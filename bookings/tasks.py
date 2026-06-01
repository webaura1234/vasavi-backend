"""Celery tasks for the bookings app."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("vasavi.bookings.tasks")


@shared_task(
    name="bookings.tasks.expire_pending_bookings",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def expire_pending_bookings(self) -> dict:
    """
    Auto-cancel PENDING+UNPAID bookings that have passed their ``expires_at``
    timestamp.  Reverts coupons and creates an audit log entry.

    Runs every 5 minutes via Celery Beat (``expire-pending-bookings-every-5min``).
    Uses ``select_for_update(skip_locked=True)`` so parallel Beat workers
    never process the same row twice.
    """
    from django.db import transaction
    from django.utils import timezone

    from accounts.models import User
    from bookings.models import Booking, BookingStatusLog
    from coupons.models import Coupon

    now = timezone.now()

    # Find the system user for audit logs (first super_admin, or any admin)
    system_user = (
        User.objects.filter(role="super_admin").order_by("created_at").first()
        or User.objects.filter(role="admin").order_by("created_at").first()
    )
    if not system_user:
        logger.warning("No admin user found for booking expiry audit logs — skipping.")
        return {"expired_bookings_cancelled": 0, "error": "no_system_user"}

    expired_ids = list(
        Booking.objects.filter(
            status=Booking.Status.PENDING,
            payment_status=Booking.PaymentStatus.UNPAID,
            expires_at__lte=now,
            is_deleted=False,
        ).values_list("pk", flat=True)
    )

    if not expired_ids:
        return {"expired_bookings_cancelled": 0}

    cancelled_count = 0
    for booking_pk in expired_ids:
        try:
            with transaction.atomic():
                # Lock individually to prevent race conditions with concurrent tasks.
                booking = (
                    Booking.objects.select_for_update(skip_locked=True)
                    .filter(
                        pk=booking_pk,
                        status=Booking.Status.PENDING,
                        payment_status=Booking.PaymentStatus.UNPAID,
                        is_deleted=False,
                    )
                    .first()
                )
                if booking is None:
                    # Already processed by a concurrent task or status changed.
                    continue

                old_status = booking.status

                # Revert coupons before status change.
                coupon_ids = list(
                    booking.coupons_applied.values_list("pk", flat=True)
                )
                if coupon_ids:
                    Coupon.objects.filter(pk__in=coupon_ids).update(
                        status=Coupon.Status.DISPATCHED,
                        redeemed_by=None,
                        redeemed_at_booking=None,
                        redeemed_at_branch=None,
                        redeemed_on=None,
                    )
                    booking.coupons_applied.clear()

                booking.status = Booking.Status.CANCELLED
                booking.cancelled_at = now
                booking.cancellation_reason = (
                    "Auto-cancelled: booking expired without payment within the allowed window."
                )
                booking.cancel_initiated_by_role = Booking.CancelRole.SYSTEM
                booking.save(
                    update_fields=[
                        "status",
                        "cancelled_at",
                        "cancellation_reason",
                        "cancel_initiated_by_role",
                        "updated_at",
                    ]
                )

                BookingStatusLog.objects.create(
                    booking=booking,
                    from_status=old_status,
                    to_status=Booking.Status.CANCELLED,
                    changed_by=system_user,
                    reason="Auto-expired by system: no payment received within TTL.",
                )

                cancelled_count += 1
                logger.info(
                    "Auto-cancelled expired booking %s", booking.booking_reference
                )
        except Exception as exc:
            logger.exception(
                "Error auto-cancelling booking pk=%s: %s", booking_pk, exc
            )
            # Don't let one failure abort the whole batch.
            continue

    logger.info("Expiry task complete: cancelled %d bookings.", cancelled_count)
    return {"expired_bookings_cancelled": cancelled_count}


@shared_task(name="bookings.tasks.send_booking_confirmation_task", bind=True, max_retries=3)
def send_booking_confirmation_task(self, booking_id: str) -> dict:
    """Queue a booking confirmation email/SMS asynchronously."""
    from bookings.services.notifications import send_booking_confirmation

    try:
        return send_booking_confirmation(booking_id)
    except Exception as exc:
        logger.exception("Failed to send confirmation for booking %s", booking_id)
        raise self.retry(exc=exc, countdown=60)


@shared_task(name="bookings.tasks.booking_status_notification", bind=True, max_retries=3)
def booking_status_notification(
    self,
    booking_id: str,
    from_status: str,
    to_status: str,
    reason: str = "",
) -> dict:
    """Notify guest when booking status changes."""
    from bookings.services.notifications import send_booking_status_notification

    try:
        return send_booking_status_notification(
            booking_id, from_status, to_status, reason=reason
        )
    except Exception as exc:
        logger.exception(
            "Failed to send status notification for booking %s", booking_id
        )
        raise self.retry(exc=exc, countdown=60)


@shared_task(
    name="bookings.tasks.generate_booking_export",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    time_limit=900,       # 15 min hard limit — enough for 100 k rows
    soft_time_limit=840,  # 14 min soft limit — allows graceful wrap-up
)
def generate_booking_export(self, *, export_id: str) -> dict:
    """Build an xlsx booking export in the background.

    Loaded by ``StaffBookingExportRequestView`` which creates the
    ``BookingExport`` record (status=PENDING) then enqueues this task.

    Status flow
    -----------
    PENDING  → PROCESSING (this task starts)
             → READY      (file written successfully)
             → FAILED     (exception — sets error_message, re-raises for retry)

    All related data is fetched in a single SQL JOIN via ``select_related``
    inside ``build_booking_export_queryset`` — no N+1 queries.
    Rows are streamed via ``QuerySet.iterator(chunk_size=1000)``.
    """
    from bookings.services.export import run_booking_export

    try:
        return run_booking_export(
            export_id=export_id,
            requesting_user_id=None,  # resolved inside run_booking_export
        )
    except Exception as exc:
        logger.exception("generate_booking_export failed for export_id=%s", export_id)
        raise self.retry(exc=exc, countdown=30)


@shared_task(
    name="bookings.tasks.cleanup_expired_booking_exports",
    bind=True,
    max_retries=1,
    default_retry_delay=120,
    time_limit=300,
)
def cleanup_expired_booking_exports(self) -> dict:
    """Delete expired export files from disk and mark records as FAILED.

    Runs hourly via Celery Beat (``cleanup-booking-exports-hourly``).
    Only processes ``READY`` records past their ``expires_at`` timestamp
    to avoid accidentally removing still-processing jobs.
    """
    import os

    from django.utils import timezone

    from bookings.models import BookingExport

    now     = timezone.now()
    expired = BookingExport.objects.filter(
        status=BookingExport.Status.READY,
        expires_at__lte=now,
    )

    deleted_files  = 0
    updated_records = 0

    for export in expired:
        if export.file_path and os.path.exists(export.file_path):
            try:
                os.remove(export.file_path)
                deleted_files += 1
            except OSError:
                logger.warning(
                    "Could not delete export file: %s", export.file_path
                )

        export.status        = BookingExport.Status.FAILED
        export.error_message = "Export expired — file deleted automatically."
        export.file_path     = ""
        export.download_url  = ""
        export.save(update_fields=[
            "status", "error_message", "file_path", "download_url", "updated_at",
        ])
        updated_records += 1

    logger.info(
        "Booking export cleanup: deleted=%d records_updated=%d",
        deleted_files,
        updated_records,
    )
    return {"deleted_files": deleted_files, "updated_records": updated_records}
