"""Money display helpers (amounts stored in paise)."""

from __future__ import annotations


def paise_to_rupees_display(paise: int) -> str:
    """Format paise as a rupee string, e.g. ₹1,234.56."""
    rupees = paise / 100
    return f"₹{rupees:,.2f}"
