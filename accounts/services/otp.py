"""OTP send rate-limit helpers."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from accounts.models import OTPLog


def otp_send_cooldown_seconds(phone: str) -> int:
    """
    Seconds until another OTP may be sent for *phone*.

    Enforces a 60-second gap after the most recent OTP and respects the
    hourly cap enforced by ``OTPLog.can_send``.
    """
    now = timezone.now()
    latest = (
        OTPLog.objects.filter(phone=phone)
        .order_by("-created_at")
        .first()
    )
    if latest:
        elapsed = (now - latest.created_at).total_seconds()
        if elapsed < 60:
            return int(60 - elapsed)

    if not OTPLog.can_send(phone):
        one_hour_ago = now - timedelta(hours=1)
        oldest = (
            OTPLog.objects.filter(
                phone=phone,
                created_at__gte=one_hour_ago,
                is_verified=False,
            )
            .order_by("created_at")
            .first()
        )
        if oldest:
            unlock = oldest.created_at + timedelta(hours=1)
            return max(0, int((unlock - now).total_seconds()))
        return 3600

    return 0
