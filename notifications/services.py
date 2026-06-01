"""Notification creation helpers — all emitters call into this module."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib.auth import get_user_model
from django.db.models import QuerySet
from django.utils import timezone

from notifications.models import Notification

if TYPE_CHECKING:
    from accounts.models import User
    from bookings.models import Booking
    from coupons.models import Coupon
    from donors.models import Donation

UserModel = get_user_model()


def create_notification(
    recipient: UserModel,
    *,
    category: str,
    type: str,
    title: str,
    message: str,
    metadata: dict[str, Any] | None = None,
    related_entity_type: str = "",
    related_entity_id=None,
) -> Notification:
    return Notification.objects.create(
        recipient=recipient,
        category=category,
        type=type,
        title=title,
        message=message,
        metadata=metadata or {},
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
    )


def _coupon_code(coupon: Coupon) -> str:
    return str(coupon.serial_number)


def _display_name(user: UserModel | None) -> str:
    if not user:
        return "Someone"
    return user.name or user.phone or "Someone"


def _coupon_donor_recipients(coupon: Coupon) -> QuerySet:
    assigned = coupon.assigned_donors.all()
    if assigned.exists():
        return assigned
    donation = coupon.batch.donation
    return UserModel.objects.filter(pk=donation.donor.user_id)


def notify_coupon_redeemed(
    coupon: Coupon,
    *,
    redeemed_by_user: UserModel | None,
    booking: Booking,
) -> list[Notification]:
    """Notify assigned / owning donors when their coupon is redeemed."""
    from coupons.models import Coupon as CouponModel

    coupon = (
        CouponModel.objects.select_related("batch__donation__donor__user")
        .prefetch_related("assigned_donors")
        .get(pk=coupon.pk)
    )

    redeemed_at = coupon.redeemed_on or timezone.now()
    redeemer_name = _display_name(redeemed_by_user)
    coupon_code = _coupon_code(coupon)

    donation = coupon.batch.donation
    donor_profile = donation.donor
    donor_name = donor_profile.donor_id or _display_name(donor_profile.user)

    metadata = {
        "coupon_code": coupon_code,
        "donor_name": donor_name,
        "user_name": redeemer_name,
        "redeemed_at": redeemed_at.isoformat(),
        "coupon_id": str(coupon.pk),
        "booking_id": str(booking.pk),
    }

    created: list[Notification] = []
    for recipient in _coupon_donor_recipients(coupon):
        if redeemed_by_user and recipient.pk == redeemed_by_user.pk:
            continue
        created.append(
            create_notification(
                recipient,
                category=Notification.Category.COUPON,
                type=Notification.Type.COUPON_REDEEMED,
                title="Coupon Used Successfully",
                message=(
                    f"Your coupon code {coupon_code} was used by {redeemer_name} "
                    f"on {redeemed_at.strftime('%d-%b-%Y')}."
                ),
                metadata=metadata,
                related_entity_type="booking",
                related_entity_id=booking.pk,
            )
        )
    return created


def notify_account_approved(user: UserModel) -> Notification:
    return create_notification(
        user,
        category=Notification.Category.USER,
        type=Notification.Type.ACCOUNT_APPROVED,
        title="Account Approved",
        message="Your profile was confirmed successfully. Welcome to Vasavi Spiritual Stays.",
        metadata={},
        related_entity_type="user",
        related_entity_id=user.pk,
    )


def notify_profile_updated(user: UserModel) -> Notification:
    return create_notification(
        user,
        category=Notification.Category.USER,
        type=Notification.Type.PROFILE_UPDATED,
        title="Profile Updated",
        message="Your profile was updated successfully.",
        metadata={},
        related_entity_type="user",
        related_entity_id=user.pk,
    )


def notify_donation_received(donation: Donation) -> Notification | None:
    donor_user = donation.donor.user
    amount_rupees = donation.amount / 100
    return create_notification(
        donor_user,
        category=Notification.Category.DONATION,
        type=Notification.Type.DONATION_RECEIVED,
        title="New Donation Recorded",
        message=(
            f"A donation of ₹{amount_rupees:,.2f} for {donation.purpose.name} "
            f"has been recorded on your account."
        ),
        metadata={
            "donation_id": str(donation.pk),
            "amount_paise": donation.amount,
            "purpose": donation.purpose.name,
        },
        related_entity_type="donation",
        related_entity_id=donation.pk,
    )
