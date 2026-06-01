"""Properties application models.

Owns room types and individual rooms within branches.  Separated from
branches to keep room inventory management independent of branch metadata.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from core.models import (
    AllObjectsManager,
    SoftDeleteManager,
    SoftDeleteModel,
    TimeStampedModel,
)


OPERATIONAL_STATUS_CHOICES = [
    ("available", "Available"),
    ("blocked", "Blocked"),
    ("maintenance", "Maintenance"),
]


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
        choices=OPERATIONAL_STATUS_CHOICES,
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
        upload_to="properties.media_paths.room_image_upload_to",
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


# ---------------------------------------------------------------------------
# Function hall inventory (one active hall per branch)
# ---------------------------------------------------------------------------


class FunctionHall(SoftDeleteModel):
    """A bookable function hall tied to exactly one branch.

    Each branch may have at most one non-deleted function hall at a time
    (enforced by a partial unique constraint on ``branch``).
    """

    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.CASCADE,
        related_name="function_halls",
        help_text="The branch this function hall belongs to.",
    )
    name = models.CharField(max_length=255)
    capacity = models.PositiveIntegerField(
        help_text="Maximum guest capacity.",
        validators=[MinValueValidator(1), MaxValueValidator(500)],
    )
    base_price_per_day = models.PositiveIntegerField(
        help_text="Amount in paise (₹1 = 100 paise).",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive halls are hidden from availability searches.",
    )
    operational_status = models.CharField(
        max_length=20,
        choices=OPERATIONAL_STATUS_CHOICES,
        default="available",
        help_text="Staff-managed availability (separate from booking occupancy).",
    )
    description = models.TextField(blank=True, default="")
    amenities = models.JSONField(default=list, blank=True)

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        verbose_name = "function hall"
        verbose_name_plural = "function halls"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch"],
                condition=Q(is_deleted=False),
                name="uq_one_active_hall_per_branch",
            ),
        ]
        indexes = [
            models.Index(
                fields=["is_deleted", "is_active", "operational_status"],
                name="idx_hall_availability",
            ),
            models.Index(
                fields=["branch"],
                name="idx_hall_branch",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} — {self.branch.name}"

    @property
    def is_available_for_booking(self) -> bool:
        """True when the hall can accept new bookings."""
        return (
            self.is_active
            and not self.is_deleted
            and self.operational_status == "available"
        )

    def clean(self) -> None:
        super().clean()
        if self.capacity is not None and self.capacity <= 0:
            raise ValidationError({"capacity": "Capacity must be greater than zero."})
        if self.base_price_per_day is not None and self.base_price_per_day < 0:
            raise ValidationError(
                {"base_price_per_day": "Price cannot be negative."}
            )


class FunctionHallImage(TimeStampedModel):
    """Photo attached to a function hall for staff and guest-facing listings."""

    function_hall = models.ForeignKey(
        FunctionHall,
        on_delete=models.CASCADE,
        related_name="images",
    )
    image = models.ImageField(
        upload_to="properties.media_paths.function_hall_image_upload_to",
        help_text="Hall photo (JPEG, PNG, or WebP).",
    )
    caption = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_primary = models.BooleanField(default=False)

    class Meta:
        verbose_name = "function hall image"
        verbose_name_plural = "function hall images"
        ordering = ["sort_order", "created_at"]

    def __str__(self) -> str:
        return f"Image for {self.function_hall.name}"
