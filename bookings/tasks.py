"""Celery tasks for bookings — payments and notifications."""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

from bookings.services.notifications import (
    send_booking_confirmation,
    send_booking_status_notification,
)
from bookings.services.razorpay import (
    RazorpayError,
    create_order_for_booking,
    verify_and_process_webhook,
)

logger = logging.getLogger("vasavi.bookings.tasks")


@shared_task(
    name="bookings.tasks.razorpay_create_order",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(RazorpayError,),
    retry_backoff=True,
)
def razorpay_create_order(self, booking_id: int) -> dict[str, Any]:
    """
    Create a Razorpay order for *booking_id* and store the order id on the booking.

    Call from the payment API after the booking row exists and amounts are final.
    """
    result = create_order_for_booking(booking_id)
    logger.info("Razorpay order created for booking %s: %s", booking_id, result["order_id"])
    return result


@shared_task(
    name="bookings.tasks.razorpay_verify_payment_webhook",
    bind=True,
    max_retries=5,
    default_retry_delay=60,
)
def razorpay_verify_payment_webhook(
    self,
    raw_body: str,
    signature: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Verify Razorpay webhook signature and update booking payment state.

    The HTTP view should read the raw body, pass it here with the
    ``X-Razorpay-Signature`` header value, and return 200 immediately.
    """
    try:
        body_bytes = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
        result = verify_and_process_webhook(body_bytes, signature, payload)

        if result.get("status") == "paid":
            booking_id = result.get("booking_id")
            if booking_id:
                send_booking_confirmation_task.delay(booking_id)
                send_booking_status_notification.delay(
                    booking_id,
                    "pending",
                    "confirmed",
                    reason="Payment captured",
                )

        return result
    except RazorpayError as exc:
        logger.exception("razorpay_verify_payment_webhook failed")
        raise self.retry(exc=exc) from exc


@shared_task(
    name="bookings.tasks.send_booking_confirmation",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
)
def send_booking_confirmation_task(self, booking_id: int) -> dict[str, str | bool]:
    """Email/SMS confirmation after a successful booking payment."""
    try:
        return send_booking_confirmation(booking_id)
    except Exception as exc:
        logger.exception("send_booking_confirmation failed for booking %s", booking_id)
        raise self.retry(exc=exc) from exc


@shared_task(
    name="bookings.tasks.booking_status_notification",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
)
def booking_status_notification(
    self,
    booking_id: int,
    from_status: str,
    to_status: str,
    reason: str = "",
) -> dict[str, str | bool]:
    """
    Notify the guest when booking status changes.

    Enqueue from admin actions or when ``BookingStatusLog`` is created.
    """
    try:
        return send_booking_status_notification(
            booking_id,
            from_status,
            to_status,
            reason=reason,
        )
    except Exception as exc:
        logger.exception(
            "booking_status_notification failed booking=%s %s→%s",
            booking_id,
            from_status,
            to_status,
        )
        raise self.retry(exc=exc) from exc
