"""Staff portal guest lookup and coupon validation helpers."""

from __future__ import annotations

from accounts.models import User
from coupons.models import Coupon
from coupons.serializers import CouponSerializer
from coupons.services.stats import compute_coupon_stats, coupons_for_donor_profile, coupons_redeemable_for_user
from donors.models import DonorProfile
from rest_framework import serializers


def lookup_guest_by_phone(phone: str) -> dict:
    """Resolve a guest by phone for manual booking (no user creation)."""
    user = (
        User.objects.filter(phone=phone, is_deleted=False)
        .select_related("donor_profile", "donor_profile__membership_tier")
        .first()
    )
    if not user:
        return {"found": False, "phone": phone}

    if user.role in ("admin", "super_admin"):
        return {
            "found": True,
            "phone": phone,
            "is_staff": True,
            "role": user.role,
            "name": user.name,
            "user_id": str(user.pk),
        }

    payload: dict = {
        "found": True,
        "phone": phone,
        "is_staff": False,
        "role": user.role,
        "name": user.name or "",
        "user_id": str(user.pk),
        "is_donor": user.role == "donor",
    }

    if user.role != "donor":
        return payload

    try:
        profile = user.donor_profile
    except DonorProfile.DoesNotExist:
        payload["is_donor"] = False
        return payload

    profile_qs = coupons_for_donor_profile(profile).select_related("batch")
    redeemable_ids = set(coupons_redeemable_for_user(user).values_list("pk", flat=True))
    available = profile_qs.filter(
        status=Coupon.Status.DISPATCHED,
        pk__in=redeemable_ids,
    )
    stats = compute_coupon_stats(donor_profile=profile, user=user)

    payload.update(
        {
            "donor_profile_id": str(profile.pk),
            "donor_id": profile.donor_id,
            "tier": profile.membership_tier.name if profile.membership_tier_id else "",
            "coupon_stats": stats,
            "available_coupons": CouponSerializer(
                available, many=True, context={}
            ).data,
        }
    )
    return payload


def validate_coupons_for_guest(
    coupon_ids: list,
    guest_user: User,
    *,
    room_booking: bool,
) -> list[Coupon]:
    if not coupon_ids:
        return []
    if not room_booking:
        raise serializers.ValidationError(
            {"coupon_ids": "Coupons can only be applied to room bookings."}
        )
    if guest_user.role != "donor":
        raise serializers.ValidationError(
            {"coupon_ids": "Coupons require a registered donor for this phone number."}
        )
    if len(coupon_ids) > 2:
        raise serializers.ValidationError(
            {"coupon_ids": "Maximum two coupons allowed per booking."}
        )

    coupons: list[Coupon] = []
    types_seen: set[str] = set()
    for coupon_id in coupon_ids:
        try:
            coupon = Coupon.objects.select_related("batch").get(pk=coupon_id)
        except Coupon.DoesNotExist as exc:
            raise serializers.ValidationError(
                {"coupon_ids": f"Coupon {coupon_id} not found."}
            ) from exc
        if coupon.status != Coupon.Status.DISPATCHED:
            raise serializers.ValidationError(
                {
                    "coupon_ids": (
                        f"Coupon #{coupon.serial_number} is not available "
                        f"(status: {coupon.get_status_display()})."
                    )
                }
            )
        if coupon.assigned_donors.exists() and not coupon.assigned_donors.filter(
            pk=guest_user.pk
        ).exists():
            raise serializers.ValidationError(
                {
                    "coupon_ids": (
                        f"Coupon #{coupon.serial_number} is not assigned to this donor."
                    )
                }
            )
        if coupon.coupon_type in types_seen:
            raise serializers.ValidationError(
                {"coupon_ids": "Cannot apply two coupons of the same type."}
            )
        types_seen.add(coupon.coupon_type)
        coupons.append(coupon)

    return coupons
