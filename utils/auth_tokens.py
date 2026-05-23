"""Short-lived registration tokens (not SimpleJWT user tokens)."""

from __future__ import annotations

from datetime import timedelta

import jwt
from django.conf import settings
from django.utils import timezone


class RegistrationTokenError(Exception):
    """Invalid or expired registration token."""


def issue_registration_token(phone: str) -> str:
    """Sign a 10-minute registration token for a verified phone."""
    now = timezone.now()
    payload = {
        "phone": phone,
        "purpose": "registration",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=10)).timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def verify_registration_token(token: str) -> str:
    """Validate token and return normalized phone."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"],
        )
    except jwt.PyJWTError as exc:
        raise RegistrationTokenError("Invalid or expired registration token.") from exc

    if payload.get("purpose") != "registration":
        raise RegistrationTokenError("Invalid registration token purpose.")

    phone = payload.get("phone")
    if not phone:
        raise RegistrationTokenError("Registration token missing phone.")

    return str(phone)
