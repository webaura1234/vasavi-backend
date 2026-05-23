"""Bookings application models.

Owns bookings and booking status audit logs.  Handles room reservations,
payment tracking, coupon redemption linkage, and full status-change history.
"""

from __future__ import annotations

import secrets
import string

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.models import (
    AllObjectsManager,
    SoftDeleteManager,
    SoftDeleteModel,
    TimeStampedModel,
)


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------


class Booking(SoftDeleteModel):
    """A room reservation made by a user or donor.

    The ``booking_reference`` is auto-generated on first save in the
    format ``VCI-{YEAR}-{RANDOM5}``.  The ``branch`` field is
    denormalised from ``room.branch`` on every save for efficient
    branch-scoped queries by branch admins.

    All monetary amounts are stored in **paise** (₹1 = 100 paise).
    """

    # -- enum choices --------------------------------------------------------

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        CHECKED_IN = "checked_in", "Checked In"
        CHECKED_OUT = "checked_out", "Checked Out"
        CANCELLED = "cancelled", "Cancelled"
        NO_SHOW = "no_show", "No Show"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID = "paid", "Paid"
        REFUNDED = "refunded", "Refunded"
        PARTIALLY_REFUNDED = "partially_refunded", "Partially Refunded"

    class PaymentGateway(models.TextChoices):
        RAZORPAY = "razorpay", "Razorpay"
        CASH = "cash", "Cash"
        OTHER = "other", "Other"

    # -- fields --------------------------------------------------------------

    booking_reference = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        editable=False,
        help_text="Auto-generated reference, e.g. VCI-2026-A3X7Q.",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="bookings",
        help_text="The user who made this booking.",
    )
    room = models.ForeignKey(
        "properties.Room",
        on_delete=models.PROTECT,
        related_name="bookings",
        help_text="The room being booked.",
    )
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="bookings",
        help_text="Denormalised from room.branch for query performance.",
    )

    # -- dates ---------------------------------------------------------------

    check_in_date = models.DateField(db_index=True)
    check_out_date = models.DateField(db_index=True)
    nights = models.PositiveIntegerField(
        help_text="Computed: (check_out_date - check_in_date).days.",
    )

    # -- guests --------------------------------------------------------------

    guest_count = models.PositiveIntegerField(
        default=1,
        help_text="Number of guests for this booking.",
    )
    guest_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Name of the guest (if different from the booking user).",
    )
    guest_phone = models.CharField(
        max_length=15,
        blank=True,
        help_text="Phone number of the guest.",
    )

    # -- status & payment ----------------------------------------------------

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    base_amount = models.BigIntegerField(
        default=0,
        help_text="Amount in paise (₹1 = 100 paise) before coupon.",
    )
    discount_amount = models.BigIntegerField(
        default=0,
        help_text="Discount from coupon, in paise.",
    )
    final_amount = models.BigIntegerField(
        default=0,
        help_text="Charged amount in paise. Must equal base_amount - discount_amount.",
    )
    payment_status = models.CharField(
        max_length=30,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
    )
    payment_reference = models.CharField(
        max_length=200,
        blank=True,
        help_text="Razorpay or other gateway order/payment ID.",
    )
    payment_gateway = models.CharField(
        max_length=20,
        choices=PaymentGateway.choices,
        blank=True,
    )
    payment_paid_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when payment was confirmed.",
    )

    # -- coupons & notes -----------------------------------------------------

    coupons_applied = models.ManyToManyField(
        "coupons.Coupon",
        blank=True,
        related_name="bookings_applied",
        help_text="Coupons redeemed against this booking.",
    )
    notes = models.TextField(
        blank=True,
        help_text="Internal notes about this booking.",
    )

    # -- cancellation --------------------------------------------------------

    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    cancellation_reason = models.TextField(
        blank=True,
    )

    # -- managers ------------------------------------------------------------

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    # -- meta ----------------------------------------------------------------

    class Meta:
        verbose_name = "booking"
        verbose_name_plural = "bookings"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["user", "status"],
                name="idx_booking_user_status",
            ),
            models.Index(
                fields=["branch", "status"],
                name="idx_booking_branch_status",
            ),
            models.Index(
                fields=["check_in_date", "check_out_date"],
                name="idx_booking_dates",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(nights__gt=0),
                name="booking_nights_positive",
            ),
            models.CheckConstraint(
                check=Q(base_amount__gte=0),
                name="booking_base_amount_non_negative",
            ),
            models.CheckConstraint(
                check=Q(discount_amount__gte=0),
                name="booking_discount_non_negative",
            ),
            models.CheckConstraint(
                check=Q(final_amount__gte=0),
                name="booking_final_amount_non_negative",
            ),
        ]

    # -- str -----------------------------------------------------------------

    def __str__(self) -> str:
        return f"{self.booking_reference} — {self.user.phone}"

    # -- reference generation ------------------------------------------------

    @staticmethod
    def _generate_reference() -> str:
        """Generate a booking reference like ``VCI-2026-A3X7Q``."""
        year = timezone.now().year
        charset = string.ascii_uppercase + string.digits
        random_part = "".join(secrets.choice(charset) for _ in range(5))
        return f"VCI-{year}-{random_part}"

    # -- validation ----------------------------------------------------------

    def clean(self) -> None:
        """Validate booking business rules.

        * ``check_out_date`` must be after ``check_in_date``.
        * ``nights`` must be positive.
        * ``final_amount`` must equal ``base_amount - discount_amount``.

        .. note::
           M2M coupon validation (coupon status, assigned-donor checks)
           cannot be performed in ``clean()`` because the M2M relationship
           is saved *after* the model instance.  Use :meth:`validate_coupons`
           explicitly after saving the M2M.
        """
        super().clean()

        # Date sanity
        if self.check_in_date and self.check_out_date:
            if self.check_out_date <= self.check_in_date:
                raise ValidationError(
                    {
                        "check_out_date": (
                            "Check-out date must be strictly after check-in date."
                        )
                    }
                )

            computed_nights = (self.check_out_date - self.check_in_date).days
            if computed_nights <= 0:
                raise ValidationError(
                    {"nights": "Number of nights must be greater than zero."}
                )

        # Financial consistency
        if (
            self.base_amount is not None
            and self.discount_amount is not None
            and self.final_amount is not None
        ):
            expected = self.base_amount - self.discount_amount
            if self.final_amount != expected:
                raise ValidationError(
                    {
                        "final_amount": (
                            f"final_amount must equal base_amount - discount_amount "
                            f"(expected {expected}, got {self.final_amount})."
                        )
                    }
                )

    def validate_coupons(self) -> None:
        """Validate all coupons in ``coupons_applied``.

        This method must be called **after** the M2M relationship has been
        saved (i.e. after ``booking.coupons_applied.set(...)``).

        Checks:
        1. Each coupon must be in ``dispatched`` status.
        2. If a coupon has ``assigned_donors``, the booking user must be
           in that list.

        Raises
        ------
        ValidationError
            If any coupon fails validation.
        """
        errors = []
        for coupon in self.coupons_applied.all():
            if coupon.status != "dispatched":
                errors.append(
                    f"Coupon #{coupon.serial_number} has status "
                    f"'{coupon.get_status_display()}' — must be 'Dispatched'."
                )

            if (
                coupon.assigned_donors.exists()
                and not coupon.assigned_donors.filter(pk=self.user_id).exists()
            ):
                errors.append(
                    f"Coupon #{coupon.serial_number} is not assigned to "
                    f"user {self.user.phone}."
                )

        if errors:
            raise ValidationError({"coupons_applied": errors})

    # -- save ----------------------------------------------------------------

    def save(self, *args, **kwargs) -> None:
        """Auto-generate reference, denormalise branch, compute nights, then persist."""

        # Auto-generate booking reference (retry on collision)
        if not self.booking_reference:
            for _ in range(10):
                ref = self._generate_reference()
                if not Booking.all_objects.filter(booking_reference=ref).exists():
                    self.booking_reference = ref
                    break
            else:
                raise RuntimeError(
                    "Could not generate a unique booking reference after 10 attempts."
                )

        # Denormalise branch from room
        if self.room_id:
            self.branch_id = self.room.branch_id

        # Compute nights
        if self.check_in_date and self.check_out_date:
            self.nights = (self.check_out_date - self.check_in_date).days

        self.full_clean()
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Booking Status Log (audit trail)
# ---------------------------------------------------------------------------


class BookingStatusLog(TimeStampedModel):
    """Immutable audit log entry for every booking status change.

    One row is created each time a booking transitions from one status to
    another (e.g. ``pending → confirmed``).  The ``changed_by`` FK tracks
    *who* made the change (user, admin, or super admin).
    """

    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name="status_logs",
    )
    from_status = models.CharField(
        max_length=20,
        choices=Booking.Status.choices,
        help_text="Status before the transition.",
    )
    to_status = models.CharField(
        max_length=20,
        choices=Booking.Status.choices,
        help_text="Status after the transition.",
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="booking_status_changes",
        help_text="The user who triggered this status change.",
    )
    reason = models.TextField(
        blank=True,
        help_text="Optional reason or note for the status change.",
    )

    class Meta:
        verbose_name = "booking status log"
        verbose_name_plural = "booking status logs"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return (
            f"{self.booking.booking_reference}: "
            f"{self.from_status} → {self.to_status}"
        )
