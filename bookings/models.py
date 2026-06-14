"""Bookings application models.

Owns bookings and booking status audit logs.  Handles room reservations,
payment tracking, coupon redemption linkage, and full status-change history.
"""

from __future__ import annotations

import secrets
import string
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
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
        REFUND_PENDING = "refund_pending", "Refund Pending"
        REFUNDED = "refunded", "Refunded"
        PARTIALLY_REFUNDED = "partially_refunded", "Partially Refunded"

    class PaymentGateway(models.TextChoices):
        RAZORPAY = "razorpay", "Razorpay"
        CASH = "cash", "Cash"
        OTHER = "other", "Other"

    class CancelRole(models.TextChoices):
        USER = "user", "User"
        DONOR = "donor", "Donor"
        ADMIN = "admin", "Admin"
        SUPER_ADMIN = "super_admin", "Super Admin"
        SYSTEM = "system", "System (auto-expired)"

    class BookingKind(models.TextChoices):
        ROOM = "room", "Room"
        FUNCTION_HALL = "function_hall", "Function Hall"

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
        null=True,
        blank=True,
        related_name="bookings",
        help_text="The room being booked. Mutually exclusive with function_hall.",
    )
    function_hall = models.ForeignKey(
        "properties.FunctionHall",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bookings",
        help_text="The function hall being booked. Mutually exclusive with room.",
    )
    booking_kind = models.CharField(
        max_length=20,
        choices=BookingKind.choices,
        default=BookingKind.ROOM,
        db_index=True,
        help_text="Discriminator: whether this booking is for a room or function hall.",
    )
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
        related_name="bookings",
        help_text="Denormalised from room or function_hall for query performance.",
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
        default=Status.CONFIRMED,
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
        help_text="Cash receipt number or other payment reference.",
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

    # -- razorpay (dormant — activated when RAZORPAY_ENABLED=True) ----------

    razorpay_order_id = models.CharField(
        max_length=200,
        blank=True,
        help_text="Razorpay order ID (separate from payment ID).",
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
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cancelled_bookings",
        help_text="The user who triggered the cancellation.",
    )
    cancel_initiated_by_role = models.CharField(
        max_length=20,
        choices=CancelRole.choices,
        blank=True,
        help_text="Role of the actor who cancelled (user/admin/super_admin/system).",
    )

    # -- refund tracking (cash refunds — Razorpay deferred) -----------------

    refund_amount = models.BigIntegerField(
        default=0,
        help_text="Amount refunded in paise. 0 = no refund yet.",
    )
    refund_reference = models.CharField(
        max_length=200,
        blank=True,
        help_text="Cash receipt/reference for the refund.",
    )
    refund_processed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the refund was processed.",
    )
    refund_reason = models.TextField(
        blank=True,
        help_text="Reason provided when processing the refund.",
    )
    refund_requested_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the guest submitted the refund request.",
    )
    refund_requested_reason = models.TextField(
        blank=True,
        help_text="Guest's stated reason for requesting a refund.",
    )

    # -- TTL for PENDING bookings -------------------------------------------

    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Auto-cancel PENDING+UNPAID booking if still unresolved after this time.",
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
            models.Index(
                fields=["status", "expires_at"],
                name="idx_booking_status_expires",
            ),
            models.Index(
                fields=["payment_status"],
                name="idx_booking_payment_status",
            ),
            models.Index(
                fields=["function_hall", "check_in_date", "check_out_date"],
                name="idx_booking_hall_dates",
            ),
            # Composite index for room availability checks — hit on every
            # booking creation and room search (check_availability_with_lock).
            models.Index(
                fields=["room", "check_in_date", "check_out_date"],
                name="idx_booking_room_dates",
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
            models.CheckConstraint(
                check=Q(refund_amount__gte=0),
                name="booking_refund_amount_non_negative",
            ),
            models.CheckConstraint(
                check=(
                    Q(room__isnull=False, function_hall__isnull=True)
                    | Q(room__isnull=True, function_hall__isnull=False)
                ),
                name="chk_booking_exactly_one_resource",
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

    # -- helpers -------------------------------------------------------------

    @property
    def is_cancellable_by_guest(self) -> bool:
        """Guest can cancel only if not yet checked in and still active."""
        return self.status in (self.Status.CONFIRMED, self.Status.PENDING) and (
            self.check_in_date > timezone.localdate()
        )

    @property
    def needs_refund_approval(self) -> bool:
        """True if a guest refund request is awaiting staff action."""
        return (
            self.payment_status == self.PaymentStatus.REFUND_PENDING
            and self.refund_requested_at is not None
        )

    @property
    def bookable_resource(self):
        """The room or function hall this booking reserves."""
        return self.room or self.function_hall

    # -- validation ----------------------------------------------------------

    def clean(self) -> None:
        """Validate booking business rules."""
        super().clean()

        has_room = self.room_id is not None
        has_hall = self.function_hall_id is not None
        if has_room == has_hall:
            raise ValidationError(
                "Exactly one of room or function_hall must be set."
            )
        if self.booking_kind == self.BookingKind.ROOM and has_hall:
            raise ValidationError(
                {"booking_kind": "Room bookings cannot reference a function hall."}
            )
        if self.booking_kind == self.BookingKind.FUNCTION_HALL and has_room:
            raise ValidationError(
                {"booking_kind": "Function hall bookings cannot reference a room."}
            )

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

        Must be called **after** M2M is saved.
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
        """Auto-generate reference, denormalise branch, compute nights, set TTL, then persist."""

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

        # Denormalise branch from bookable resource
        if self.room_id:
            self.branch_id = self.room.branch_id
        elif self.function_hall_id:
            self.branch_id = self.function_hall.branch_id

        # Compute nights
        if self.check_in_date and self.check_out_date:
            self.nights = (self.check_out_date - self.check_in_date).days

        # Set TTL for PENDING bookings on first create (UUID pk is set before insert).
        if self._state.adding and self.status == Booking.Status.PENDING and not self.expires_at:
            expiry_minutes = getattr(settings, "BOOKING_PENDING_EXPIRY_MINUTES", 15)
            self.expires_at = timezone.now() + timedelta(minutes=expiry_minutes)

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


# ---------------------------------------------------------------------------
# Booking Export (async xlsx export job tracker)
# ---------------------------------------------------------------------------


class BookingExport(TimeStampedModel):
    """Tracks an asynchronous xlsx booking export job.

    Lifecycle: PENDING → PROCESSING → READY (file ready for download)
                                    → FAILED (error, can retry)

    The ``filters_applied`` JSON field is an immutable audit snapshot of
    every filter and the requesting user's role at export time.

    Files are stored in ``BOOKING_EXPORT_DIR`` and auto-deleted after
    ``BOOKING_EXPORT_RETENTION_DAYS`` days via the Celery Beat cleanup task.
    """

    class Status(models.TextChoices):
        PENDING    = "pending",    "Pending"
        PROCESSING = "processing", "Processing"
        READY      = "ready",      "Ready"
        FAILED     = "failed",     "Failed"

    # -- who and scope --------------------------------------------------------

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="booking_exports",
        help_text="Staff user who triggered this export.",
    )
    branch = models.ForeignKey(
        "branches.Branch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Branch scope at export time. NULL = all branches (super_admin).",
    )

    # -- job state ------------------------------------------------------------

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    # -- audit snapshot (immutable once written) ------------------------------

    filters_applied = models.JSONField(
        default=dict,
        help_text=(
            "Snapshot of all filters + requesting user role at export time. "
            "Serves as the audit log — never mutated after creation."
        ),
    )

    # -- result ---------------------------------------------------------------

    file_path    = models.CharField(max_length=500, blank=True, help_text="Absolute path on disk.")
    download_url = models.CharField(max_length=500, blank=True, help_text="Relative MEDIA_URL path.")
    record_count = models.PositiveIntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    # -- TTL ------------------------------------------------------------------

    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="File is deleted and status set to FAILED after this timestamp.",
    )

    # -- timing ---------------------------------------------------------------

    export_started_at  = models.DateTimeField(null=True, blank=True)
    export_finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "booking export"
        verbose_name_plural = "booking exports"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["requested_by", "status"],
                name="idx_bkgexport_user_status",
            ),
            models.Index(
                fields=["status", "expires_at"],
                name="idx_bkgexport_status_expires",
            ),
        ]

    def __str__(self) -> str:
        return f"BookingExport {self.pk} ({self.get_status_display()})"
