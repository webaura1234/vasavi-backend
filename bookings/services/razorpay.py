"""Razorpay order creation and webhook verification."""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from bookings.models import Booking, BookingStatusLog

logger = logging.getLogger("vasavi.bookings.razorpay")


class RazorpayError(Exception):
    """Raised when Razorpay API or webhook handling fails."""


def _get_client():
    """Return an authenticated Razorpay client."""
    key_id = settings.RAZORPAY_KEY_ID
    key_secret = settings.RAZORPAY_KEY_SECRET
    if not key_id or not key_secret:
        raise RazorpayError("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set.")

    import razorpay

    return razorpay.Client(auth=(key_id, key_secret))


def create_order_for_booking(booking_id: int) -> dict[str, Any]:
    """
    Create a Razorpay order for the booking's ``final_amount`` (paise).

    Persists the order id on ``Booking.payment_reference`` and sets gateway to razorpay.
    """
    booking = (
        Booking.objects.select_related("user", "room", "branch")
        .filter(pk=booking_id, is_deleted=False)
        .first()
    )
    if booking is None:
        raise RazorpayError(f"Booking {booking_id} not found.")

    if booking.final_amount <= 0:
        raise RazorpayError("Booking has zero payable amount; no Razorpay order needed.")

    if booking.payment_status == Booking.PaymentStatus.PAID:
        raise RazorpayError("Booking is already paid.")

    client = _get_client()
    receipt = booking.booking_reference
    amount_paise = int(booking.final_amount)

    order = client.order.create(
        {
            "amount": amount_paise,
            "currency": settings.RAZORPAY_CURRENCY,
            "receipt": receipt,
            "notes": {
                "booking_id": str(booking.pk),
                "booking_reference": booking.booking_reference,
                "user_phone": booking.user.phone,
            },
        }
    )

    order_id = order["id"]
    booking.payment_reference = order_id
    booking.payment_gateway = Booking.PaymentGateway.RAZORPAY
    booking.save(update_fields=["payment_reference", "payment_gateway", "updated_at"])

    return {
        "order_id": order_id,
        "amount": amount_paise,
        "currency": order.get("currency", settings.RAZORPAY_CURRENCY),
        "key_id": settings.RAZORPAY_KEY_ID,
        "booking_id": booking.pk,
        "booking_reference": booking.booking_reference,
    }


def verify_and_process_webhook(
    raw_body: bytes,
    signature: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Verify Razorpay webhook signature and update booking payment state.

    Handles ``payment.captured`` and ``payment.failed`` events.
    """
    secret = settings.RAZORPAY_WEBHOOK_SECRET
    if not secret:
        raise RazorpayError("RAZORPAY_WEBHOOK_SECRET is not configured.")

    client = _get_client()
    body_str = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else raw_body

    try:
        client.utility.verify_webhook_signature(body_str, signature, secret)
    except Exception as exc:
        raise RazorpayError(f"Invalid webhook signature: {exc}") from exc

    if payload is None:
        payload = json.loads(body_str)

    event = payload.get("event", "")
    entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    if not entity and "payment" in payload:
        entity = payload.get("payment", {})

    order_id = entity.get("order_id") or entity.get("notes", {}).get("order_id")
    payment_id = entity.get("id")
    status = entity.get("status")

    if not order_id:
        notes = entity.get("notes") or {}
        booking_id = notes.get("booking_id")
        if booking_id:
            booking = Booking.objects.filter(pk=int(booking_id), is_deleted=False).first()
        else:
            booking = None
    else:
        booking = Booking.objects.filter(
            payment_reference=order_id,
            is_deleted=False,
        ).first()

    if booking is None:
        logger.warning("Webhook for unknown order: %s", order_id)
        return {"status": "ignored", "reason": "booking_not_found", "order_id": order_id}

    with transaction.atomic():
        if event == "payment.captured" or status == "captured":
            previous_status = booking.status
            booking.payment_status = Booking.PaymentStatus.PAID
            booking.payment_paid_at = timezone.now()
            if payment_id:
                booking.payment_reference = payment_id
            if booking.status == Booking.Status.PENDING:
                booking.status = Booking.Status.CONFIRMED
            booking.save(
                update_fields=[
                    "payment_status",
                    "payment_paid_at",
                    "payment_reference",
                    "status",
                    "updated_at",
                ]
            )
            if booking.user_id and previous_status != booking.status:
                BookingStatusLog.objects.create(
                    booking=booking,
                    from_status=previous_status,
                    to_status=booking.status,
                    changed_by=booking.user,
                    reason="Payment captured via Razorpay webhook",
                )
            return {
                "status": "paid",
                "booking_id": booking.pk,
                "booking_reference": booking.booking_reference,
                "payment_id": payment_id,
            }

        if event == "payment.failed" or status == "failed":
            booking.notes = (
                f"{booking.notes}\n[Razorpay] Payment failed: {payment_id}".strip()
            )
            booking.save(update_fields=["notes", "updated_at"])
            return {
                "status": "failed",
                "booking_id": booking.pk,
                "payment_id": payment_id,
            }

    return {"status": "ignored", "event": event}
