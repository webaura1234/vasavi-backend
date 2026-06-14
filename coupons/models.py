"""Owns coupon batches and individual coupons.

Coupons are issued by super admin against donations and can be redeemed
by donors at checkout for room bookings.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from core.models import AllObjectsManager, SoftDeleteManager, SoftDeleteModel, TimeStampedModel


# ---------------------------------------------------------------------------
# CouponBatch
# ---------------------------------------------------------------------------


class CouponBatch(TimeStampedModel):
    """A contiguous range of coupons generated against a single donation.

    When a batch is created its ``save()`` method automatically bulk-creates
    one :class:`Coupon` row per serial number in the range
    ``[serial_start, serial_end]``.

    Database-level constraints guarantee that ``serial_end >= serial_start``
    and ``count > 0``.  The ``clean()`` method additionally validates that
    ``count`` equals the actual range size and that no serial-number overlap
    exists with any other batch.
    """

    # -- choices (shared with Coupon) ----------------------------------------
    class CouponType(models.TextChoices):
        CONCESSION = "concession", "Concession"
        FREE = "free", "Free"

    # -- fields --------------------------------------------------------------
    donation = models.ForeignKey(
        "donors.Donation",
        on_delete=models.CASCADE,
        related_name="coupon_batches",
    )
    coupon_type = models.CharField(
        max_length=20,
        choices=CouponType.choices,
    )
    serial_start = models.PositiveIntegerField()
    serial_end = models.PositiveIntegerField()
    count = models.PositiveIntegerField(
        help_text="Number of coupons in this batch. Must equal serial_end - serial_start + 1.",
    )
    extra_benefit = models.TextField(
        blank=True,
        help_text="e.g. 50% Concession in Hall Booking for 1 Day.",
    )

    # -- meta ----------------------------------------------------------------
    class Meta:
        verbose_name = "coupon batch"
        verbose_name_plural = "coupon batches"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["donation"], name="idx_couponbatch_donation"),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(serial_end__gte=F("serial_start")),
                name="batch_serial_end_gte_start",
            ),
            models.CheckConstraint(
                check=Q(count__gt=0),
                name="batch_count_positive",
            ),
        ]

    # -- str -----------------------------------------------------------------
    def __str__(self) -> str:
        return (
            f"Batch {self.serial_start}\u2013{self.serial_end} "
            f"({self.get_coupon_type_display()})"
        )

    # -- validation ----------------------------------------------------------
    def clean(self) -> None:
        """Validate serial range consistency and check for overlaps."""
        super().clean()

        # 1. serial_end must be >= serial_start
        if self.serial_end is not None and self.serial_start is not None:
            if self.serial_end < self.serial_start:
                raise ValidationError(
                    {"serial_end": "serial_end must be >= serial_start."}
                )

            # 2. count must match the range
            expected = self.serial_end - self.serial_start + 1
            if self.count is not None and self.count != expected:
                raise ValidationError(
                    {
                        "count": (
                            f"count must equal serial_end - serial_start + 1 "
                            f"(expected {expected}, got {self.count})."
                        )
                    }
                )

            # 3. No serial-number overlap with existing batches
            overlap_qs = CouponBatch.objects.filter(
                serial_start__lte=self.serial_end,
                serial_end__gte=self.serial_start,
            )
            if self.pk:
                overlap_qs = overlap_qs.exclude(pk=self.pk)

            if overlap_qs.exists():
                raise ValidationError(
                    "Serial number range overlaps with an existing batch."
                )

    # -- save ----------------------------------------------------------------
    def save(self, *args, **kwargs) -> None:
        """Validate, persist, and auto-generate individual coupons on create."""
        is_new = self._state.adding
        self.full_clean()
        super().save(*args, **kwargs)

        if is_new:
            Coupon.objects.bulk_create(
                [
                    Coupon(
                        batch=self,
                        serial_number=sn,
                        coupon_type=self.coupon_type,
                        status=Coupon.Status.ISSUED,
                    )
                    for sn in range(self.serial_start, self.serial_end + 1)
                ]
            )


# ---------------------------------------------------------------------------
# Coupon
# ---------------------------------------------------------------------------


class Coupon(SoftDeleteModel):
    """An individual coupon that can be dispatched to donors and redeemed.

    Lifecycle: **Issued → Dispatched → Redeemed**

    * *Issued* – generated automatically when a :class:`CouponBatch` is
      created.
    * *Dispatched* – assigned / sent to one or more donors.
    * *Redeemed* – used by a donor at checkout for a room booking.

    The ``clean()`` method enforces valid status transitions and ensures
    redemption metadata is present only when the coupon is in the
    ``REDEEMED`` state.
    """

    # -- choices -------------------------------------------------------------
    class CouponType(models.TextChoices):
        # Backend types → Frontend mapping (in vasavi-main-site/lib/api/mappers.ts):
        #   "concession" → "percentage_discount"
        #   "free"       → "free_booking"
        CONCESSION = "concession", "Concession"
        FREE = "free", "Free"

    class Status(models.TextChoices):
        ISSUED = "issued", "Issued"
        DISPATCHED = "dispatched", "Dispatched"
        REDEEMED = "redeemed", "Redeemed"

    # -- valid transitions ---------------------------------------------------
    _VALID_TRANSITIONS: dict[str, set[str]] = {
        Status.ISSUED: {Status.DISPATCHED},
        Status.DISPATCHED: {Status.REDEEMED},
        Status.REDEEMED: set(),  # terminal state
    }

    # -- fields --------------------------------------------------------------
    batch = models.ForeignKey(
        CouponBatch,
        on_delete=models.CASCADE,
        related_name="coupons",
    )
    serial_number = models.PositiveIntegerField(unique=True, db_index=True)
    coupon_type = models.CharField(
        max_length=20,
        choices=CouponType.choices,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ISSUED,
        db_index=True,
    )

    # -- assignment / redemption ---------------------------------------------
    assigned_donors = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="assigned_coupons",
        help_text=(
            "If empty, coupon is available to all donors. "
            "If populated, only listed donors may use it."
        ),
    )
    redeemed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="redeemed_coupons",
    )
    redeemed_at_branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="redeemed_coupons",
    )
    redeemed_at_booking = models.ForeignKey(
        "bookings.Booking",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="redeemed_coupons",
    )
    redeemed_on = models.DateTimeField(null=True, blank=True)

    # -- managers ------------------------------------------------------------
    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    # -- meta ----------------------------------------------------------------
    class Meta:
        verbose_name = "coupon"
        verbose_name_plural = "coupons"
        ordering = ["serial_number"]
        indexes = [
            models.Index(fields=["status"], name="idx_coupon_status"),
            # Speeds up batch dispatch queries (batch.coupons.filter(status=...))
            models.Index(fields=["batch", "status"], name="idx_coupon_batch_status"),
        ]

    # -- str -----------------------------------------------------------------
    def __str__(self) -> str:
        return f"Coupon #{self.serial_number} ({self.get_status_display()})"

    # -- validation ----------------------------------------------------------
    def clean(self) -> None:
        """Enforce valid status transitions and redemption-field consistency."""
        super().clean()

        # --- status transition validation (only for existing rows) ----------
        if self.pk:
            try:
                old = Coupon.objects.get(pk=self.pk)
            except Coupon.DoesNotExist:
                old = None

            if old is not None and old.status != self.status:
                allowed = self._VALID_TRANSITIONS.get(old.status, set())
                if self.status not in allowed:
                    raise ValidationError(
                        {
                            "status": (
                                f"Invalid transition from "
                                f"'{old.get_status_display()}' to "
                                f"'{self.get_status_display()}'."
                            )
                        }
                    )

        # --- redemption-field consistency -----------------------------------
        redemption_fields = {
            "redeemed_by": self.redeemed_by,
            "redeemed_at_branch": self.redeemed_at_branch,
            "redeemed_at_booking": self.redeemed_at_booking,
            "redeemed_on": self.redeemed_on,
        }

        if self.status == self.Status.REDEEMED:
            missing = [k for k, v in redemption_fields.items() if v is None]
            if missing:
                raise ValidationError(
                    {
                        f: "This field is required when status is 'Redeemed'."
                        for f in missing
                    }
                )
        else:
            set_fields = [k for k, v in redemption_fields.items() if v is not None]
            if set_fields:
                raise ValidationError(
                    {
                        f: "This field must be empty when status is not 'Redeemed'."
                        for f in set_fields
                    }
                )

    # -- save ----------------------------------------------------------------
    def save(self, *args, **kwargs) -> None:
        """Validate and persist."""
        self.full_clean()
        super().save(*args, **kwargs)
