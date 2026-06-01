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

# Staff/guest booking lists include future reservations (function halls are often booked ahead).
LIST_PERIOD_LOOKAHEAD_DAYS = 365


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


def resolve_list_date_range(params: Any) -> tuple[date | None, date | None]:
    """
    Date window for booking list/export queries.

    Presets keep a backward-looking start (same as analytics) but extend the end
    date into the future so upcoming room and function-hall reservations appear.
    Custom ``date_from`` / ``date_to`` are respected as-is.
    """
    date_from, date_to = resolve_date_range(params)
    period = (params.get("period") or "").strip().lower()
    if period in PERIOD_DAYS:
        today = timezone.localdate()
        lookahead_end = today + timedelta(days=LIST_PERIOD_LOOKAHEAD_DAYS)
        if date_to is None or date_to < lookahead_end:
            date_to = lookahead_end
    return date_from, date_to


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

    date_from, date_to = resolve_list_date_range(params)
    # Stays overlapping [date_from, date_to]: check-in on/before end, check-out on/after start.
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
            | Q(function_hall__name__icontains=q)
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

    booking_kind = (params.get("booking_kind") or "").strip().lower()
    if booking_kind in ("room", "function_hall"):
        qs = qs.filter(booking_kind=booking_kind)

    return qs


def apply_booking_export_filters(qs: QuerySet, params: Any) -> QuerySet:
    """Apply all export-specific filters on top of role-scoped queryset.

    Extends ``apply_booking_list_filters`` with additional filter params
    available in the export modal (room_type_id, room_number, payment_gateway,
    standalone guest_name).  Branch/city scoping is handled by the caller
    (``build_booking_export_queryset``) before this function is invoked.

    All lookups use the already-joined ``select_related`` tables, so no
    additional queries are generated per row.
    """
    # --- reuse common filters ------------------------------------------------
    qs = apply_booking_list_filters(qs, params)

    # --- room type (exact FK match) ------------------------------------------
    room_type_id = (params.get("room_type_id") or "").strip()
    if room_type_id:
        qs = qs.filter(room__room_type_id=room_type_id)

    # --- room number (partial match) -----------------------------------------
    room_number = (params.get("room_number") or "").strip()
    if room_number:
        qs = qs.filter(room__room_number__icontains=room_number)

    # --- payment method / gateway (exact) ------------------------------------
    payment_gateway = (params.get("payment_gateway") or "").strip()
    if payment_gateway:
        qs = qs.filter(payment_gateway=payment_gateway)

    # --- standalone guest name (icontains) -----------------------------------
    # Note: the shared ``q`` param already searches guest_name, phone,
    # reference, room.  This param allows filtering by guest name alone.
    guest_name = (params.get("guest_name") or "").strip()
    if guest_name:
        qs = qs.filter(guest_name__icontains=guest_name)

    booking_kind = (params.get("booking_kind") or "").strip().lower()
    if booking_kind in ("room", "function_hall"):
        qs = qs.filter(booking_kind=booking_kind)

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
        hall_name = b.function_hall.name if b.function_hall_id else ""
        resource_label = room_no or hall_name
        amount_rupees = round((b.final_amount or 0) / 100)
        rows.append(
            [
                b.booking_reference,
                b.guest_name or "",
                b.guest_phone or "",
                resource_label,
                b.check_in_date.isoformat(),
                b.check_out_date.isoformat(),
                b.status,
                b.payment_status,
                str(amount_rupees),
            ]
        )
    return rows
