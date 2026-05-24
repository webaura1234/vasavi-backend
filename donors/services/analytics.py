"""Donor analytics for the staff portal (super admin)."""

from __future__ import annotations

from django.db.models import Count, Sum

from accounts.models import ProfileConfirmation
from donors.models import Donation, DonorProfile
from utils.money import paise_to_rupees_display


def build_donor_analytics() -> dict:
    donors_qs = DonorProfile.objects.filter(is_deleted=False).select_related(
        "user", "membership_tier"
    )

    total_donors = donors_qs.count()
    active_donors = donors_qs.filter(user__is_active=True).count()

    pending_approval = ProfileConfirmation.objects.filter(
        is_confirmed=False,
        user__role="donor",
    ).count()

    total_contributions_paise = int(
        Donation.objects.aggregate(total=Sum("amount"))["total"] or 0
    )

    by_tier = (
        donors_qs.values("membership_tier__name")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    tier_chart = [
        {
            "tier": row["membership_tier__name"] or "Other",
            "count": row["count"],
        }
        for row in by_tier
    ]

    top_rows = (
        donors_qs.annotate(total_paise=Sum("donations__amount"))
        .order_by("-total_paise")[:5]
    )
    top_contributors = [
        {
            "donor_id": str(row.id),
            "name": row.user.name,
            "amount_paise": int(row.total_paise or 0),
            "amount_rupees": round(int(row.total_paise or 0) / 100),
            "amount_display": paise_to_rupees_display(int(row.total_paise or 0)),
        }
        for row in top_rows
    ]

    return {
        "total_donors": total_donors,
        "active_donors": active_donors,
        "pending_approval": pending_approval,
        "total_contributions_paise": total_contributions_paise,
        "total_contributions_display": paise_to_rupees_display(
            total_contributions_paise
        ),
        "tier_chart": tier_chart,
        "top_contributors": top_contributors,
    }
