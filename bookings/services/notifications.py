"""Booking confirmation and status-change notifications."""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

from bookings.models import Booking

logger = logging.getLogger("vasavi.bookings.notifications")


def _recipient_for_booking(booking: Booking) -> tuple[str, str]:
    """Return (email, phone) for the guest."""
    email = booking.user.email or ""
    phone = booking.guest_phone or booking.user.phone
    return email, phone


def send_booking_confirmation(booking_id: int) -> dict[str, str | bool]:
    """
    Notify the guest that their booking is confirmed.

    Uses email when configured; logs SMS intent when ``SMS_PROVIDER_ENABLED``.
    """
    booking = (
        Booking.objects.select_related("user", "room", "branch")
        .filter(pk=booking_id, is_deleted=False)
        .first()
    )
    if booking is None:
        raise ValueError(f"Booking {booking_id} not found.")

    email, phone = _recipient_for_booking(booking)
    subject = f"Booking confirmed — {booking.booking_reference}"
    amount_line = (
        f"Amount paid: ₹{booking.final_amount / 100:,.2f}"
        if booking.payment_status == Booking.PaymentStatus.PAID
        else f"Amount due at property: ₹{booking.final_amount / 100:,.2f}"
    )
    message = (
        f"Dear {booking.guest_name or booking.user.name or 'Guest'},\n\n"
        f"Your stay at {booking.branch.name} is confirmed.\n"
        f"Reference: {booking.booking_reference}\n"
        f"Check-in: {booking.check_in_date}\n"
        f"Check-out: {booking.check_out_date}\n"
        f"Room: {booking.room.room_number}\n"
        f"{amount_line}\n\n"
        f"Thank you,\nVasavi Clubs International"
    )

    email_sent = False
    if email:
        try:
            send_mail(
                subject,
                message,
                settings.BOOKING_NOTIFICATION_EMAIL,
                [email],
                fail_silently=False,
            )
            email_sent = True
        except Exception:
            logger.exception("Failed to send booking confirmation email to %s", email)

    sms_sent = False
    if settings.SMS_PROVIDER_ENABLED and phone:
        # Integrate MSG91 / Twilio / etc. here
        logger.info(
            "SMS booking confirmation queued for %s ref=%s",
            phone,
            booking.booking_reference,
        )
        sms_sent = True

    logger.info(
        "Booking confirmation %s email=%s sms=%s",
        booking.booking_reference,
        email_sent,
        sms_sent,
    )
    return {
        "booking_reference": booking.booking_reference,
        "email_sent": email_sent,
        "sms_sent": sms_sent,
    }


def send_booking_status_notification(
    booking_id: int,
    from_status: str,
    to_status: str,
    *,
    reason: str = "",
) -> dict[str, str | bool]:
    """Notify the guest when booking status changes."""
    booking = (
        Booking.objects.select_related("user", "room", "branch")
        .filter(pk=booking_id, is_deleted=False)
        .first()
    )
    if booking is None:
        raise ValueError(f"Booking {booking_id} not found.")

    email, phone = _recipient_for_booking(booking)
    subject = f"Booking update — {booking.booking_reference}"
    message = (
        f"Your booking {booking.booking_reference} status changed:\n"
        f"  {from_status} → {to_status}\n"
    )
    if reason:
        message += f"\nNote: {reason}\n"

    email_sent = False
    if email:
        try:
            send_mail(
                subject,
                message,
                settings.BOOKING_NOTIFICATION_EMAIL,
                [email],
                fail_silently=False,
            )
            email_sent = True
        except Exception:
            logger.exception("Failed to send status notification to %s", email)

    sms_sent = False
    if settings.SMS_PROVIDER_ENABLED and phone:
        logger.info(
            "SMS status notification %s→%s for %s",
            from_status,
            to_status,
            phone,
        )
        sms_sent = True

    return {
        "booking_reference": booking.booking_reference,
        "from_status": from_status,
        "to_status": to_status,
        "email_sent": email_sent,
        "sms_sent": sms_sent,
    }
