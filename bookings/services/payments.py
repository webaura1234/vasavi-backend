"""Booking payment confirmation helpers (cash, complimentary, etc.)."""

from __future__ import annotations

import logging
import secrets
import string

from django.db import transaction
from django.utils import timezone

from bookings.models import Booking, BookingStatusLog
from bookings.services.notifications import send_booking_confirmation

logger = logging.getLogger("vasavi.bookings.payments")


def _cash_reference() -> str:
    suffix = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
    return f"CASH-{suffix}"


def _notify_booking_confirmation(booking: Booking) -> None:
    """Queue confirmation email/SMS; fall back to sync when Celery is unavailable."""
    booking_id = str(booking.pk)
    try:
        from bookings.tasks import send_booking_confirmation_task

        send_booking_confirmation_task.delay(booking_id)
        return
    except Exception:
        logger.debug(
            "Celery unavailable for booking %s — sending confirmation synchronously",
            booking.booking_reference,
            exc_info=True,
        )

    try:
        send_booking_confirmation(booking_id)
    except Exception:
        logger.exception(
            "Could not send booking confirmation for %s", booking.booking_reference
        )


def confirm_booking_payment(
    booking: Booking,
    *,
    gateway: str,
    payment_reference: str,
    changed_by,
    reason: str,
    amount_paise: int | None = None,
) -> Booking:
    """Mark booking paid and confirmed; idempotent if already paid."""
    if booking.payment_status == Booking.PaymentStatus.PAID:
        return booking

    if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED):
        raise ValueError("Booking cannot be paid in its current status.")

    if amount_paise is not None and amount_paise != booking.final_amount:
        raise ValueError("Payment amount does not match booking total.")

    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if booking.payment_status == Booking.PaymentStatus.PAID:
            return booking

        old_status = booking.status
        now = timezone.now()
        booking.payment_status = Booking.PaymentStatus.PAID
        booking.payment_gateway = gateway
        booking.payment_reference = payment_reference
        booking.payment_paid_at = now
        if booking.status == Booking.Status.PENDING:
            booking.status = Booking.Status.CONFIRMED
        booking.save(
            update_fields=[
                "payment_status",
                "payment_gateway",
                "payment_reference",
                "payment_paid_at",
                "status",
                "updated_at",
            ]
        )
        BookingStatusLog.objects.create(
            booking=booking,
            from_status=old_status,
            to_status=booking.status,
            changed_by=changed_by,
            reason=reason,
        )

    _notify_booking_confirmation(booking)
    return booking


def confirm_cash_payment(booking: Booking, *, changed_by, notes: str = "") -> Booking:
    """Record an in-person / pay-at-desk cash payment."""
    reason = "Cash payment recorded"
    if notes.strip():
        reason = f"{reason}: {notes.strip()}"
    return confirm_booking_payment(
        booking,
        gateway=Booking.PaymentGateway.CASH,
        payment_reference=_cash_reference(),
        changed_by=changed_by,
        reason=reason,
    )
