"""Properties application models.

Owns room types and individual rooms within branches.  Separated from
branches to keep room inventory management independent of branch metadata.
"""

from __future__ import annotations

from django.db import models

from core.models import (
    AllObjectsManager,
    SoftDeleteManager,
    SoftDeleteModel,
    TimeStampedModel,
)


# ---------------------------------------------------------------------------
# Lookup tables (super-admin managed)
# ---------------------------------------------------------------------------


class RoomType(TimeStampedModel):
    """Super-admin–managed lookup table for room categories.

    Examples: Standard, Deluxe, Suite, Conference Hall, Banquet Hall.
    """

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Room category label, e.g. Standard, Deluxe, Suite.",
    )
    description = models.TextField(
        blank=True,
        help_text="Optional description of the room type.",
    )

    class Meta:
        verbose_name = "room type"
        verbose_name_plural = "room types"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# Room inventory
# ---------------------------------------------------------------------------


class Room(SoftDeleteModel):
    """A bookable room (or hall) within a branch.

    Tracks capacity, nightly pricing (in paise), and whether the room is
    restricted to donors only.
    """

    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.CASCADE,
        related_name="rooms",
        help_text="The branch this room belongs to.",
    )
    room_number = models.CharField(
        max_length=50,
        help_text="Room number or name.",
    )
    room_type = models.ForeignKey(
        RoomType,
        on_delete=models.PROTECT,
        related_name="rooms",
        help_text="Category of this room.",
    )
    capacity = models.PositiveIntegerField(
        help_text="Max guest capacity.",
    )
    base_price_per_night = models.BigIntegerField(
        help_text="Amount in paise (₹1 = 100 paise).",
    )
    is_donor_exclusive = models.BooleanField(
        default=False,
        help_text="If True, only donors can book this room.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive rooms are hidden from availability searches.",
    )
    operational_status = models.CharField(
        max_length=20,
        choices=[
            ("available", "Available"),
            ("blocked", "Blocked"),
            ("maintenance", "Maintenance"),
        ],
        default="available",
        help_text="Staff-managed availability (separate from booking occupancy).",
    )
    description = models.TextField(
        blank=True,
        help_text="Optional notes shown to staff (amenities, view, etc.).",
    )

    # -- managers ----------------------------------------------------------
    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        verbose_name = "room"
        verbose_name_plural = "rooms"
        ordering = ["branch", "room_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "room_number"],
                name="uq_branch_room_number",
            ),
            models.CheckConstraint(
                check=models.Q(capacity__gt=0),
                name="room_capacity_positive",
            ),
            models.CheckConstraint(
                check=models.Q(base_price_per_night__gte=0),
                name="room_price_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.room_number} ({self.room_type.name}) "
            f"@ {self.branch.name}"
        )


class RoomImage(TimeStampedModel):
    """Photo attached to a room for staff and guest-facing listings."""

    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name="images",
    )
    image = models.ImageField(
        upload_to="rooms/%Y/%m/",
        help_text="Room photo (JPEG, PNG, or WebP).",
    )
    caption = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_primary = models.BooleanField(default=False)

    class Meta:
        verbose_name = "room image"
        verbose_name_plural = "room images"
        ordering = ["sort_order", "created_at"]

    def __str__(self) -> str:
        return f"Image for {self.room.room_number}"
