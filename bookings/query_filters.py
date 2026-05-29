"""Shared booking list / analytics date and status filters."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from django.db.models import Count, Q, QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_date

from bookings.models import Booking

# period token -> chart / aggregation day count (inclusive)
PERIOD_DAYS: dict[str, int] = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
}


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    parsed = parse_date(value.strip())
    return parsed


def resolve_date_range(params: Any) -> tuple[date | None, date | None]:
    """
    Resolve an inclusive calendar date range from query params.

    Priority: explicit ``date_from`` + ``date_to``, then ``period`` preset,
    otherwise no date bound (all time).
    """
    date_from = _parse_iso_date(params.get("date_from"))
    date_to = _parse_iso_date(params.get("date_to"))
    if date_from and date_to:
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        return date_from, date_to

    period = (params.get("period") or "").strip().lower()
    if period in PERIOD_DAYS:
        days = PERIOD_DAYS[period]
        today = timezone.localdate()
        return today - timedelta(days=days - 1), today

    return None, None


def resolve_chart_days(params: Any, *, default: int = 7) -> int:
    """Number of days for revenue chart buckets."""
    period = (params.get("period") or "").strip().lower()
    if period in PERIOD_DAYS:
        return PERIOD_DAYS[period]
    date_from, date_to = resolve_date_range(params)
    if date_from and date_to:
        return max(1, (date_to - date_from).days + 1)
    return default


def apply_booking_list_filters(qs: QuerySet, params: Any) -> QuerySet:
    """Apply staff/guest list filters. Caller must already scope by role/branch."""
    status_param = (params.get("status") or "").strip().lower()
    in_house = (params.get("in_house") or "").strip().lower()

    if in_house == "true" or status_param == "in_house":
        qs = qs.filter(notes__icontains="[In-house")
    elif status_param and status_param not in ("", "all"):
        qs = qs.filter(status=status_param)

    date_from, date_to = resolve_date_range(params)
    if date_from:
        qs = qs.filter(check_out_date__gte=date_from)
    if date_to:
        qs = qs.filter(check_in_date__lte=date_to)

    q = (params.get("q") or params.get("search") or "").strip()
    if q:
        qs = qs.filter(
            Q(guest_name__icontains=q)
            | Q(guest_phone__icontains=q)
            | Q(booking_reference__icontains=q)
            | Q(room__room_number__icontains=q)
        )

    payment_status = (params.get("payment_status") or "").strip()
    if payment_status:
        qs = qs.filter(payment_status=payment_status)

    check_in = params.get("check_in_date")
    if check_in:
        parsed = _parse_iso_date(check_in)
        if parsed:
            qs = qs.filter(check_in_date=parsed)

    booking_reference = (params.get("booking_reference") or "").strip()
    if booking_reference:
        qs = qs.filter(booking_reference__iexact=booking_reference)

    return qs


def compute_booking_list_summary(qs: QuerySet) -> dict[str, int]:
    """Aggregate counts for the current filtered queryset (one query)."""
    agg = qs.aggregate(
        total=Count("id"),
        in_house=Count("id", filter=Q(notes__icontains="[In-house")),
        pending=Count("id", filter=Q(status=Booking.Status.PENDING)),
        confirmed=Count("id", filter=Q(status=Booking.Status.CONFIRMED)),
        checked_in=Count("id", filter=Q(status=Booking.Status.CHECKED_IN)),
        checked_out=Count("id", filter=Q(status=Booking.Status.CHECKED_OUT)),
    )
    return {k: int(v or 0) for k, v in agg.items()}


def bookings_to_csv_rows(bookings: list[Booking]) -> list[list[str]]:
    """Build CSV rows for export."""
    header = [
        "Reference",
        "Guest",
        "Phone",
        "Room",
        "Check-in",
        "Check-out",
        "Status",
        "Payment",
        "Amount (INR)",
    ]
    rows: list[list[str]] = [header]
    for b in bookings:
        room_no = b.room.room_number if b.room_id else ""
        amount_rupees = round((b.final_amount or 0) / 100)
        rows.append(
            [
                b.booking_reference,
                b.guest_name or "",
                b.guest_phone or "",
                room_no,
                b.check_in_date.isoformat(),
                b.check_out_date.isoformat(),
                b.status,
                b.payment_status,
                str(amount_rupees),
            ]
        )
    return rows
