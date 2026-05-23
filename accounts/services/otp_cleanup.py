"""OTP log maintenance — used by Celery periodic task."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from accounts.models import OTPLog


def cleanup_expired_otps(*, retention_days: int = 30) -> dict[str, int]:
    """
    Delete OTP rows that are no longer needed for audit or verification.

    Removes records where:
    - ``expires_at`` is older than *retention_days*, or
    - ``is_verified`` is True and created more than *retention_days* ago.

    Returns counts for logging/monitoring.
    """
    cutoff = timezone.now() - timedelta(days=retention_days)

    expired_qs = OTPLog.objects.filter(expires_at__lt=cutoff)
    verified_old_qs = OTPLog.objects.filter(
        is_verified=True,
        created_at__lt=cutoff,
    )

    expired_count, _ = expired_qs.delete()
    verified_count, _ = verified_old_qs.delete()

    return {
        "expired_deleted": expired_count,
        "verified_old_deleted": verified_count,
        "total_deleted": expired_count + verified_count,
    }
