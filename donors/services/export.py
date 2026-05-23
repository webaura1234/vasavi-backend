"""Generate donor data exports (CSV) for admin download."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone

from donors.models import DonorProfile


def build_donors_export(
    *,
    branch_id: int | None = None,
    membership_tier_id: int | None = None,
    include_deleted: bool = False,
) -> dict[str, Any]:
    """
    Write a CSV of donor profiles to ``media/exports/donors/``.

    Returns metadata including absolute path and relative path for download URLs.
    """
    export_dir = Path(settings.DONOR_EXPORT_DIR)
    export_dir.mkdir(parents=True, exist_ok=True)

    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    filename = f"donors_export_{timestamp}.csv"
    file_path = export_dir / filename

    manager = DonorProfile.all_objects if include_deleted else DonorProfile.objects
    qs = (
        manager.select_related("user", "membership_tier", "for_place")
        .annotate(
            donation_count=Count("donations"),
            total_donated_paise=Sum("donations__amount"),
        )
        .order_by("donor_id")
    )

    if branch_id is not None:
        qs = qs.filter(for_place_id=branch_id)
    if membership_tier_id is not None:
        qs = qs.filter(membership_tier_id=membership_tier_id)

    headers = [
        "donor_id",
        "name",
        "phone",
        "email",
        "membership_tier",
        "district_code",
        "club_name",
        "for_place_branch",
        "donation_count",
        "total_donated_inr",
        "is_deleted",
        "created_at",
    ]

    row_count = 0
    with file_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        for profile in qs.iterator(chunk_size=500):
            total_paise = profile.total_donated_paise or 0
            writer.writerow(
                [
                    profile.donor_id,
                    profile.user.name,
                    profile.user.phone,
                    profile.user.email or "",
                    profile.membership_tier.name,
                    profile.district_code,
                    profile.club_name,
                    profile.for_place.name if profile.for_place_id else "",
                    profile.donation_count,
                    f"{total_paise / 100:.2f}",
                    profile.is_deleted,
                    profile.created_at.isoformat() if profile.created_at else "",
                ]
            )
            row_count += 1

    relative = file_path.relative_to(settings.MEDIA_ROOT)
    return {
        "filename": filename,
        "file_path": str(file_path),
        "relative_path": str(relative).replace("\\", "/"),
        "download_url": f"{settings.MEDIA_URL}{relative.as_posix()}",
        "row_count": row_count,
        "generated_at": datetime.now().isoformat(),
        "filters": {
            "branch_id": branch_id,
            "membership_tier_id": membership_tier_id,
            "include_deleted": include_deleted,
        },
    }
