"""Phone normalization for Indian mobile numbers."""

from __future__ import annotations

import re

_INDIAN_MOBILE = re.compile(r"^[6-9]\d{9}$")


def normalize_indian_phone(raw: str) -> str:
    """Strip formatting and return 10-digit Indian mobile or raise ValueError."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    if not _INDIAN_MOBILE.fullmatch(digits):
        raise ValueError("invalid_phone")
    return digits


def is_valid_indian_phone(raw: str) -> bool:
    try:
        normalize_indian_phone(raw)
        return True
    except ValueError:
        return False
