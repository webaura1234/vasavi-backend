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
