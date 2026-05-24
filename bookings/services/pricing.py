"""Booking amount and coupon helpers."""

from __future__ import annotations

import re

from coupons.models import Coupon


def parse_concession_percent(extra_benefit: str) -> int:
    match = re.search(r"(\d+)\s*%", extra_benefit or "")
    if match:
        return min(100, max(0, int(match.group(1))))
    return 50


def compute_coupon_discount(
    base_amount: int,
    coupons: list[Coupon],
) -> tuple[int, int]:
    """Return (discount_amount, final_amount) in paise."""
    if not coupons:
        return 0, base_amount

    has_free = any(c.coupon_type == Coupon.CouponType.FREE for c in coupons)
    concession = next(
        (c for c in coupons if c.coupon_type == Coupon.CouponType.CONCESSION),
        None,
    )

    if has_free:
        return base_amount, 0
    if concession:
        percent = parse_concession_percent(concession.batch.extra_benefit)
        discount = (base_amount * percent) // 100
        return discount, base_amount - discount
    return 0, base_amount
