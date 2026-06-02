"""Coupon counting helpers for donor profiles and wallets."""

from __future__ import annotations

from django.db.models import Count, Q, QuerySet

from coupons.models import Coupon
from donors.models import DonorProfile


def coupons_for_donor_profile(donor_profile: DonorProfile) -> QuerySet[Coupon]:
    """All non-deleted coupons linked to a donor (via donation or assignment)."""
    return (
        Coupon.objects.filter(is_deleted=False)
        .filter(
            Q(batch__donation__donor_id=donor_profile.pk)
            | Q(assigned_donors__donor_profile__pk=donor_profile.pk)
        )
        .distinct()
    )


def coupons_redeemable_for_user(user) -> QuerySet[Coupon]:
    """Dispatched coupons the user may redeem at checkout."""
    return (
        Coupon.objects.filter(is_deleted=False, status=Coupon.Status.DISPATCHED)
        .annotate(assigned_count=Count("assigned_donors"))
        .filter(Q(assigned_count=0) | Q(assigned_donors=user))
        .distinct()
    )


def compute_coupon_stats(
    *,
    donor_profile: DonorProfile | None = None,
    user=None,
) -> dict[str, int]:
    """Return total / issued / dispatched / available / used counts.

    * **total** — coupons on the donor's donations or explicitly assigned.
    * **issued** — created but not yet dispatched.
    * **dispatched** — dispatched and not yet redeemed (includes redeemable pool).
    * **available** — dispatched coupons the user can redeem (wallet-ready).
    * **used** — redeemed by this donor's user account.
    """
    if donor_profile is None:
        if user is None:
            return _empty_stats()
        try:
            donor_profile = user.donor_profile
        except DonorProfile.DoesNotExist:
            return _empty_stats()

    base = coupons_for_donor_profile(donor_profile)
    redeem_user = user or donor_profile.user

    issued = base.filter(status=Coupon.Status.ISSUED).count()
    dispatched = base.filter(status=Coupon.Status.DISPATCHED).count()
    used = base.filter(
        status=Coupon.Status.REDEEMED,
        redeemed_by=redeem_user,
    ).count()
    available = coupons_redeemable_for_user(redeem_user).filter(
        pk__in=base.values("pk")
    ).count()

    total = base.count()
    return {
        "total": total,
        "issued": issued,
        "dispatched": dispatched,
        "available": available,
        "used": used,
    }


def _empty_stats() -> dict[str, int]:
    return {
        "total": 0,
        "issued": 0,
        "dispatched": 0,
        "available": 0,
        "used": 0,
    }


def build_coupon_tracking_stats(*, branch_id: str | None = None) -> dict[str, int]:
    """Platform- or branch-scoped coupon lifecycle counts for staff dashboards."""
    base = Coupon.objects.filter(is_deleted=False)
    issued = base.filter(status=Coupon.Status.ISSUED).count()
    dispatched = base.filter(status=Coupon.Status.DISPATCHED).count()
    used_qs = base.filter(status=Coupon.Status.REDEEMED)
    if branch_id:
        used = used_qs.filter(redeemed_at_branch_id=branch_id).count()
    else:
        used = used_qs.count()
    return {
        "total": base.count(),
        "issued": issued,
        "dispatched": dispatched,
        "available": dispatched,
        "used": used,
    }
