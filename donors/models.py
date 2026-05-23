"""Donors application models.

Owns donor profiles, membership tiers, donations, receipt numbers, and
donation purposes.  Donors are users with role='donor' who have additional
membership and contribution data.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.core.exceptions import ValidationError
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


class MembershipTier(TimeStampedModel):
    """Super-admin–managed lookup table for donor membership tiers.

    Examples: Silver, Golden, Diamond, Crown, Couple Silver, Late Silver,
    Vanitha, Progressive, 2-Star, 3-Star, 5-Star.
    """

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Membership tier label, e.g. Silver, Golden, Diamond.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive tiers are hidden from new registrations.",
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "membership tier"
        verbose_name_plural = "membership tiers"

    def __str__(self) -> str:
        return self.name


class DonationPurpose(TimeStampedModel):
    """Super-admin–managed lookup table for donation purposes.

    Examples: Hall Renovation, AC Purpose, Room Purpose, Board Room Purpose,
    Lift, Conference Hall.
    """

    name = models.CharField(
        max_length=200,
        unique=True,
        help_text="Purpose label, e.g. Hall Renovation, AC Purpose.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive purposes are hidden from new donations.",
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "donation purpose"
        verbose_name_plural = "donation purposes"

    def __str__(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# Donor profile
# ---------------------------------------------------------------------------


class DonorProfile(SoftDeleteModel):
    """One-to-one extension of User for donor-specific data.

    Carries membership tier, club affiliation, and the branch the donor
    primarily contributes to.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="donor_profile",
        limit_choices_to={"role": "donor"},
        help_text="The user account linked to this donor profile.",
    )
    donor_id = models.CharField(
        max_length=30,
        unique=True,
        db_index=True,
        help_text="Unique donor identifier, e.g. DH-2024-8842.",
    )
    membership_tier = models.ForeignKey(
        MembershipTier,
        on_delete=models.PROTECT,
        related_name="donors",
        help_text="Donor's current membership tier.",
    )
    district_code = models.CharField(
        max_length=20,
        blank=True,
        help_text="Normalized district code, e.g. V101A, V203A.",
    )
    club_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Club name, e.g. KCGF Warangal.",
    )
    for_place = models.ForeignKey(
        "branches.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="donors_for_place",
        help_text="Branch where the donor sent their donation.",
    )

    # -- managers ----------------------------------------------------------
    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        verbose_name = "donor profile"
        verbose_name_plural = "donor profiles"
        ordering = ["donor_id"]

    def __str__(self) -> str:
        display = self.user.name or self.user.phone  # type: ignore[union-attr]
        return f"{self.donor_id} — {display}"

    # -- validation --------------------------------------------------------

    def clean(self) -> None:
        """Validate business rules before saving.

        1. The linked user must have role='donor'.
        2. ``district_code`` is normalized: whitespace stripped, uppercased.
        """
        super().clean()

        # 1. Role check
        if self.user_id and self.user.role != "donor":  # type: ignore[union-attr]
            raise ValidationError(
                {
                    "user": (
                        "The linked user must have role='donor'. "
                        f"Current role is '{self.user.role}'."  # type: ignore[union-attr]
                    )
                }
            )

        # 2. Normalize district_code (strip spaces, uppercase)
        if self.district_code:
            self.district_code = re.sub(r"\s+", "", self.district_code).upper()

    def save(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        """Run full validation then persist."""
        self.full_clean()
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Donations
# ---------------------------------------------------------------------------


class Donation(TimeStampedModel):
    """A single donation recorded *manually* by a super-admin.

    There is no online donation flow — all records are entered by staff.
    """

    donor = models.ForeignKey(
        DonorProfile,
        on_delete=models.PROTECT,
        related_name="donations",
        help_text="The donor who made this contribution.",
    )
    amount = models.BigIntegerField(
        help_text="Amount in paise (₹1 = 100 paise).",
    )
    purpose = models.ForeignKey(
        DonationPurpose,
        on_delete=models.PROTECT,
        related_name="donations",
        help_text="What the donation is earmarked for.",
    )
    dispatch_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date when coupons were physically dispatched.",
    )
    dispatch_method = models.CharField(
        max_length=20,
        choices=[
            ("courier", "Courier"),
            ("by_hand", "By Hand"),
            ("other", "Other"),
        ],
        blank=True,
        help_text="How coupons were dispatched.",
    )
    dispatch_notes = models.TextField(
        blank=True,
        help_text="Free-text dispatch notes.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="donations_created",
        limit_choices_to={"role": "super_admin"},
        help_text="Must be a super_admin.",
    )

    class Meta:
        verbose_name = "donation"
        verbose_name_plural = "donations"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["donor"], name="idx_donation_donor"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gt=0),
                name="donation_amount_positive",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Donation {self.pk} — ₹{self.amount / 100:,.2f} "
            f"by {self.donor.donor_id}"
        )

    # -- validation --------------------------------------------------------

    def clean(self) -> None:
        """Ensure amount is positive and creator is a super-admin."""
        super().clean()

        if self.amount is not None and self.amount <= 0:
            raise ValidationError(
                {"amount": "Donation amount must be greater than zero."}
            )

        if self.created_by_id:
            # Access role through the FK; avoids an extra query when the
            # related object is already loaded.
            creator = self.created_by
            if creator.role != "super_admin":  # type: ignore[union-attr]
                raise ValidationError(
                    {
                        "created_by": (
                            "Only users with role='super_admin' may record "
                            f"donations. Got '{creator.role}'."  # type: ignore[union-attr]
                        )
                    }
                )


# ---------------------------------------------------------------------------
# Receipt numbers
# ---------------------------------------------------------------------------


class ReceiptNumber(TimeStampedModel):
    """Individual receipt number tied to a donation.

    One donation can have multiple receipt numbers, e.g.
    "6804/2020 & 2461/2021" would be stored as two ``ReceiptNumber`` rows.
    """

    donation = models.ForeignKey(
        Donation,
        on_delete=models.CASCADE,
        related_name="receipt_numbers",
        help_text="The donation this receipt belongs to.",
    )
    receipt_number = models.CharField(
        max_length=50,
        help_text="Individual receipt number, e.g. 6804/2020.",
    )

    class Meta:
        verbose_name = "receipt number"
        verbose_name_plural = "receipt numbers"
        ordering = ["receipt_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["donation", "receipt_number"],
                name="uq_donation_receipt",
            ),
        ]

    def __str__(self) -> str:
        return f"Receipt {self.receipt_number} (Donation #{self.donation_id})"
