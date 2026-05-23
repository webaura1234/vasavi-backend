"""Celery tasks for donor management."""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

from donors.services.export import build_donors_export

logger = logging.getLogger("vasavi.donors.tasks")


@shared_task(
    name="donors.tasks.export_donors_data",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    time_limit=600,
    soft_time_limit=540,
)
def export_donors_data(
    self,
    *,
    requested_by_user_id: int | None = None,
    branch_id: int | None = None,
    membership_tier_id: int | None = None,
    include_deleted: bool = False,
) -> dict[str, Any]:
    """
    Build a CSV export of donor profiles for admin download.

    Poll the Celery result or store ``download_url`` from the return value.
    """
    try:
        result = build_donors_export(
            branch_id=branch_id,
            membership_tier_id=membership_tier_id,
            include_deleted=include_deleted,
        )
        result["requested_by_user_id"] = requested_by_user_id
        logger.info(
            "Donor export ready: %s rows=%s user=%s",
            result["filename"],
            result["row_count"],
            requested_by_user_id,
        )
        return result
    except Exception as exc:
        logger.exception("export_donors_data failed")
        raise self.retry(exc=exc) from exc
