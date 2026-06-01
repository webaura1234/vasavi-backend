"""Shared booking availability helpers for rooms and function halls."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import models

from bookings.models import Booking

if TYPE_CHECKING:
    from properties.models import FunctionHall, Room

BLOCKING_STATUSES = [
    Booking.Status.PENDING,
    Booking.Status.CONFIRMED,
    Booking.Status.CHECKED_IN,
]


def get_blocking_statuses() -> list[str]:
    """Return booking statuses that block new reservations."""
    return list(BLOCKING_STATUSES)


def _resource_filter(resource: Room | FunctionHall) -> dict:
    """Build ORM filter kwargs for the given bookable resource."""
    from properties.models import FunctionHall, Room

    if isinstance(resource, Room):
        return {"room": resource}
    if isinstance(resource, FunctionHall):
        return {"function_hall": resource}
    raise ValueError(
        "resource must be a Room or FunctionHall instance, "
        f"got {type(resource).__name__}"
    )


def resource_is_available(
    resource: Room | FunctionHall,
    check_in_date: date,
    check_out_date: date,
    *,
    exclude_booking_id: UUID | None = None,
) -> bool:
    """Return True when *resource* has no overlapping blocking bookings."""
    qs = Booking.objects.filter(
        **_resource_filter(resource),
        status__in=BLOCKING_STATUSES,
        check_in_date__lt=check_out_date,
        check_out_date__gt=check_in_date,
        is_deleted=False,
    )
    if exclude_booking_id is not None:
        qs = qs.exclude(pk=exclude_booking_id)
    return not qs.exists()


def lock_resource(resource: Room | FunctionHall) -> None:
    """Row-lock *resource* with ``select_for_update()`` inside ``atomic()``."""
    from properties.models import FunctionHall, Room

    if isinstance(resource, Room):
        Room.objects.select_for_update().get(pk=resource.pk)
        return
    if isinstance(resource, FunctionHall):
        FunctionHall.objects.select_for_update().get(pk=resource.pk)
        return
    raise ValueError(
        "resource must be a Room or FunctionHall instance, "
        f"got {type(resource).__name__}"
    )


def check_availability_with_lock(
    resource: Room | FunctionHall,
    check_in_date: date,
    check_out_date: date,
    *,
    exclude_booking_id: UUID | None = None,
) -> bool:
    """Lock *resource* then test availability. Caller must use ``atomic()``."""
    lock_resource(resource)
    return resource_is_available(
        resource,
        check_in_date,
        check_out_date,
        exclude_booking_id=exclude_booking_id,
    )


def get_booked_resource_ids(
    resource_model: type[models.Model],
    branch,
    check_in_date: date,
    check_out_date: date,
) -> set[UUID]:
    """Return IDs of *resource_model* instances booked in the date range."""
    from properties.models import FunctionHall, Room

    if resource_model is Room:
        fk_field = "room_id"
        resource_qs = Room.objects.filter(
            branch=branch,
            is_deleted=False,
            is_active=True,
        )
    elif resource_model is FunctionHall:
        fk_field = "function_hall_id"
        resource_qs = FunctionHall.objects.filter(
            branch=branch,
            is_deleted=False,
            is_active=True,
        )
    else:
        raise ValueError(
            "resource_model must be Room or FunctionHall, "
            f"got {resource_model.__name__}"
        )

    booked_ids = Booking.objects.filter(
        status__in=BLOCKING_STATUSES,
        check_in_date__lt=check_out_date,
        check_out_date__gt=check_in_date,
        is_deleted=False,
        **{f"{fk_field}__in": resource_qs.values_list("pk", flat=True)},
    ).values_list(fk_field, flat=True)

    return {pk for pk in booked_ids if pk is not None}
