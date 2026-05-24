"""Guest reservation confirmation (pending → confirmed, pay at property)."""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from bookings.models import Booking, BookingStatusLog
from bookings.services.notifications import send_booking_confirmation
from bookings.services.pricing import compute_coupon_discount
from coupons.models import Coupon

logger = logging.getLogger("vasavi.bookings.guest_confirm")


def _notify_confirmation(booking: Booking) -> None:
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


def _revert_booking_coupons(booking: Booking) -> None:
    """Revert redeemed coupons on a booking back to dispatched."""
    coupon_ids = list(booking.coupons_applied.values_list("pk", flat=True))
    if not coupon_ids:
        return
    Coupon.objects.filter(pk__in=coupon_ids).update(
        status=Coupon.Status.DISPATCHED,
        redeemed_by=None,
        redeemed_at_booking=None,
        redeemed_at_branch=None,
        redeemed_on=None,
    )
    booking.coupons_applied.clear()


def redeem_coupons_on_booking(
    booking: Booking,
    coupons: list[Coupon],
    *,
    changed_by,
) -> None:
    """Attach coupons and mark them redeemed."""
    if booking.coupons_applied.exists():
        _revert_booking_coupons(booking)

    if not coupons:
        return

    now = timezone.now()
    locked_coupons = []
    for coupon in coupons:
        locked = Coupon.objects.select_for_update().get(pk=coupon.pk)
        if locked.status != Coupon.Status.DISPATCHED:
            raise ValueError(f"Coupon {locked.serial_number} is no longer available.")
        locked_coupons.append(locked)

    booking.coupons_applied.set(locked_coupons)
    booking.validate_coupons()
    for locked in locked_coupons:
        locked.status = Coupon.Status.REDEEMED
        locked.redeemed_by = changed_by
        locked.redeemed_at_booking = booking
        locked.redeemed_at_branch = booking.branch
        locked.redeemed_on = now
        locked.save()


def confirm_guest_reservation(
    booking: Booking,
    *,
    coupons: list[Coupon],
    changed_by,
    notes: str = "",
) -> Booking:
    """
    Finalize a guest's pending hold: apply coupons, set amounts, confirm (unpaid).

    Payment remains UNPAID — guest pays cash at the property desk.
    """
    if booking.status != Booking.Status.PENDING:
        raise ValueError("Only pending bookings can be confirmed.")
    if booking.payment_status != Booking.PaymentStatus.UNPAID:
        raise ValueError("Booking payment is not in an unpaid state.")

    with transaction.atomic():
        booking = (
            Booking.objects.select_for_update()
            .select_related("room", "branch")
            .get(pk=booking.pk)
        )
        if booking.status != Booking.Status.PENDING:
            raise ValueError("Only pending bookings can be confirmed.")

        base_amount = booking.room.base_price_per_night * booking.nights
        discount_amount, final_amount = compute_coupon_discount(base_amount, coupons)

        redeem_coupons_on_booking(booking, coupons, changed_by=changed_by)

        old_status = booking.status
        booking.base_amount = base_amount
        booking.discount_amount = discount_amount
        booking.final_amount = final_amount
        if notes.strip():
            booking.notes = notes.strip()
        booking.status = Booking.Status.CONFIRMED
        booking.save(
            update_fields=[
                "base_amount",
                "discount_amount",
                "final_amount",
                "notes",
                "status",
                "updated_at",
            ]
        )
        BookingStatusLog.objects.create(
            booking=booking,
            from_status=old_status,
            to_status=Booking.Status.CONFIRMED,
            changed_by=changed_by,
            reason="Guest confirmed reservation (pay at property)",
        )

    _notify_confirmation(booking)
    return booking
