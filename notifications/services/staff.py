"""In-app notifications for branch admins and super admins (staff portal)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db.models import QuerySet

from notifications.models import Notification
from . import create_notification

if TYPE_CHECKING:
    from bookings.models import Booking

logger = logging.getLogger(__name__)
UserModel = get_user_model()


def staff_recipients_for_branch(branch_id: UUID) -> QuerySet:
    """Branch admins assigned to the property plus all active super admins."""
    branch_admins = UserModel.objects.filter(
        role="admin",
        is_active=True,
        admin_branch__branch_id=branch_id,
    )
    super_admins = UserModel.objects.filter(role="super_admin", is_active=True)
    return (branch_admins | super_admins).distinct()


def _booking_resource_label(booking: Booking) -> str:
    if booking.booking_kind == booking.BookingKind.FUNCTION_HALL:
        hall = booking.function_hall
        return hall.name if hall else "Function hall"
    room = booking.room
    if room:
        return f"Room {room.room_number}"
    return "Room"


def _booking_metadata(booking: Booking) -> dict:
    branch_id = booking.branch_id
    return {
        "booking_id": str(booking.pk),
        "booking_reference": booking.booking_reference,
        "branch_id": str(branch_id) if branch_id else None,
        "guest_name": booking.guest_name or "",
        "payment_status": booking.payment_status,
        "status": booking.status,
    }


def _notify_branch_staff(
    booking: Booking,
    *,
    type: str,
    title: str,
    message: str,
    exclude_user_id: UUID | None = None,
) -> list[Notification]:
    branch_id = booking.branch_id
    if not branch_id:
        logger.warning("Skipping staff notification: booking %s has no branch", booking.pk)
        return []

    recipients = staff_recipients_for_branch(branch_id)
    if exclude_user_id:
        recipients = recipients.exclude(pk=exclude_user_id)

    metadata = _booking_metadata(booking)
    created: list[Notification] = []
    for recipient in recipients:
        created.append(
            create_notification(
                recipient,
                category=Notification.Category.BOOKING,
                type=type,
                title=title,
                message=message,
                metadata=metadata,
                related_entity_type="booking",
                related_entity_id=booking.pk,
            )
        )
    return created


def notify_staff_new_booking(booking_id: UUID, *, exclude_user_id: UUID | None = None) -> None:
    from bookings.models import Booking

    try:
        booking = Booking.objects.select_related("room", "function_hall", "branch").get(
            pk=booking_id
        )
    except Booking.DoesNotExist:
        return

    resource = _booking_resource_label(booking)
    guest = booking.guest_name or "Guest"
    title = "New booking"
    message = (
        f"{guest} — {resource}, {booking.nights} night(s). "
        f"Ref {booking.booking_reference}."
    )
    _notify_branch_staff(
        booking,
        type=Notification.Type.NEW_BOOKING,
        title=title,
        message=message,
        exclude_user_id=exclude_user_id,
    )

    if booking.payment_status == booking.PaymentStatus.UNPAID and booking.final_amount > 0:
        _notify_branch_staff(
            booking,
            type=Notification.Type.PAYMENT_PENDING,
            title="Payment pending",
            message=(
                f"{guest} — {resource}. Ref {booking.booking_reference} "
                "awaiting payment."
            ),
            exclude_user_id=exclude_user_id,
        )


def notify_staff_stay_extended(
    booking_id: UUID,
    *,
    old_check_out,
    changed_by_id: UUID | None = None,
) -> None:
    from bookings.models import Booking

    try:
        booking = Booking.objects.select_related("room", "function_hall", "branch").get(
            pk=booking_id
        )
    except Booking.DoesNotExist:
        return

    guest = booking.guest_name or "Guest"
    resource = _booking_resource_label(booking)
    _notify_branch_staff(
        booking,
        type=Notification.Type.STAY_EXTENDED,
        title="Stay extended",
        message=(
            f"{guest} ({booking.booking_reference}) — {resource} checkout "
            f"updated from {old_check_out} to {booking.check_out_date}."
        ),
        exclude_user_id=changed_by_id,
    )


def schedule_staff_new_booking_notification(
    booking_id: UUID, *, exclude_user_id: UUID | None = None
) -> None:
    """Run after DB commit so rolled-back bookings do not notify."""
    from django.db import transaction

    transaction.on_commit(
        lambda: notify_staff_new_booking(
            booking_id, exclude_user_id=exclude_user_id
        )
    )


def schedule_staff_stay_extended_notification(
    booking_id: UUID,
    *,
    old_check_out,
    changed_by_id: UUID | None = None,
) -> None:
    from django.db import transaction

    transaction.on_commit(
        lambda: notify_staff_stay_extended(
            booking_id,
            old_check_out=old_check_out,
            changed_by_id=changed_by_id,
        )
    )
