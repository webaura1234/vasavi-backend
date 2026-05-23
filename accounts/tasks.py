"""Celery tasks for accounts (OTP maintenance)."""

from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings

from accounts.services.otp_cleanup import cleanup_expired_otps

logger = logging.getLogger("vasavi.accounts.tasks")


@shared_task(
    name="accounts.tasks.cleanup_expired_otps",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def cleanup_expired_otps_task(self, retention_days: int | None = None) -> dict[str, int]:
    """
  Periodic job: purge old OTP log entries.

  Scheduled hourly via ``CELERY_BEAT_SCHEDULE``.
  """
    days = retention_days or getattr(settings, "OTP_LOG_RETENTION_DAYS", 30)
    try:
        result = cleanup_expired_otps(retention_days=days)
        logger.info("cleanup_expired_otps: %s", result)
        return result
    except Exception as exc:
        logger.exception("cleanup_expired_otps failed")
        raise self.retry(exc=exc) from exc
