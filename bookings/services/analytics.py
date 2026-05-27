"""Booking and operations analytics for the staff portal.

Revenue rules (collections basis):
- Count only ``payment_status=paid`` bookings that are not cancelled.
- Attribute revenue to the calendar day of ``payment_paid_at``; if missing, ``created_at``.
- Charts aggregate by that same day so totals match the sum of daily bars.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Count, DateField, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from accounts.branch_scope import staff_branch_id
from bookings.models import Booking
from bookings.views import _booking_queryset_for_user
from properties.models import Room
from utils.money import paise_to_rupees_display

# Statuses that represent money successfully collected (not refunded / pending).
_COLLECTED_PAYMENT = Booking.PaymentStatus.PAID
_EXCLUDED_BOOKING_STATUSES = (
    Booking.Status.CANCELLED,
    Booking.Status.NO_SHOW,
)


def _resolve_branch_id(user, branch_id_param: str | None) -> str | None:
    assigned = staff_branch_id(user)
    if assigned:
        return assigned
    if user.role == "super_admin" and branch_id_param:
        return branch_id_param
    return None


def _bookings_qs(user, branch_id_param: str | None = None):
    qs = _booking_queryset_for_user(user)
    branch_id = _resolve_branch_id(user, branch_id_param)
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    return qs


def _rooms_qs(user, branch_id_param: str | None = None):
    qs = Room.objects.filter(is_deleted=False, is_active=True)
    branch_id = _resolve_branch_id(user, branch_id_param)
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    return qs


def _collected_bookings_qs(bookings_qs):
    """Paid, non-cancelled bookings used for all revenue metrics."""
    return bookings_qs.filter(payment_status=_COLLECTED_PAYMENT).exclude(
        status__in=_EXCLUDED_BOOKING_STATUSES
    )


def _with_revenue_day(qs):
    """Annotate the calendar day revenue is recognized (payment time, else created)."""
    return qs.annotate(
        revenue_day=TruncDate(
            Coalesce("payment_paid_at", "created_at"),
            output_field=DateField(),
        )
    )


def _day_point_label(day: date) -> str:
    return day.strftime("%a")


def _chart_point(day: date, revenue_paise: int, savings_paise: int, bookings: int) -> dict:
    return {
        "date": day.isoformat(),
        "label": _day_point_label(day),
        "revenue_paise": revenue_paise,
        "revenue_rupees": round(revenue_paise / 100),
        "donor_savings_paise": savings_paise,
        "donor_savings_rupees": round(savings_paise / 100),
        "bookings": bookings,
    }


def _build_revenue_chart(bookings_qs, days: int = 7) -> list[dict]:
    """One grouped query; fill missing days with zeros (no OR double-count)."""
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)

    collected = _with_revenue_day(_collected_bookings_qs(bookings_qs))
    rows = (
        collected.filter(revenue_day__gte=start, revenue_day__lte=today)
        .values("revenue_day")
        .annotate(
            revenue_paise=Sum("final_amount"),
            donor_savings_paise=Sum("discount_amount"),
            bookings=Count("id"),
        )
        .order_by("revenue_day")
    )
    by_day = {
        row["revenue_day"]: {
            "revenue_paise": int(row["revenue_paise"] or 0),
            "donor_savings_paise": int(row["donor_savings_paise"] or 0),
            "bookings": int(row["bookings"] or 0),
        }
        for row in rows
    }

    chart: list[dict] = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        bucket = by_day.get(
            day,
            {"revenue_paise": 0, "donor_savings_paise": 0, "bookings": 0},
        )
        chart.append(
            _chart_point(
                day,
                bucket["revenue_paise"],
                bucket["donor_savings_paise"],
                bucket["bookings"],
            )
        )
    return chart


def _occupancy_stats(bookings_qs, rooms_qs) -> dict:
    total_rooms = rooms_qs.count()
    occupied_rooms = (
        bookings_qs.filter(status=Booking.Status.CHECKED_IN)
        .values("room_id")
        .distinct()
        .count()
    )
    available_rooms = max(0, total_rooms - occupied_rooms)
    occupancy_percent = (
        round((occupied_rooms / total_rooms) * 100) if total_rooms else 0
    )
    return {
        "total_rooms": total_rooms,
        "occupied_rooms": occupied_rooms,
        "available_rooms": available_rooms,
        "occupancy_percent": occupancy_percent,
    }


def build_dashboard_analytics(user, branch_id_param: str | None = None) -> dict:
    today = timezone.localdate()
    bookings_qs = _bookings_qs(user, branch_id_param)
    rooms_qs = _rooms_qs(user, branch_id_param)

    collected = _with_revenue_day(_collected_bookings_qs(bookings_qs))
    period_start = today - timedelta(days=6)

    period_agg = collected.filter(
        revenue_day__gte=period_start,
        revenue_day__lte=today,
    ).aggregate(
        revenue_7d_paise=Sum("final_amount"),
        savings_7d_paise=Sum("discount_amount"),
    )

    today_agg = collected.filter(revenue_day=today).aggregate(
        today_revenue_paise=Sum("final_amount"),
        today_bookings=Count("id"),
    )

    today_revenue_paise = int(today_agg["today_revenue_paise"] or 0)
    revenue_7d_paise = int(period_agg["revenue_7d_paise"] or 0)
    donor_savings_7d_paise = int(period_agg["savings_7d_paise"] or 0)

    active_bookings = (
        bookings_qs.exclude(
            status__in=[Booking.Status.CANCELLED, Booking.Status.CHECKED_OUT]
        ).count()
    )

    check_ins_today = (
        bookings_qs.filter(check_in_date=today)
        .exclude(status__in=_EXCLUDED_BOOKING_STATUSES)
        .count()
    )

    vip_arrivals = (
        bookings_qs.filter(
            check_in_date=today,
            user__role="donor",
        )
        .exclude(status__in=_EXCLUDED_BOOKING_STATUSES)
        .count()
    )

    revenue_chart = _build_revenue_chart(bookings_qs)
    occupancy = _occupancy_stats(bookings_qs, rooms_qs)

    return {
        "stats": {
            "today_revenue_paise": today_revenue_paise,
            "today_revenue_display": paise_to_rupees_display(today_revenue_paise),
            "today_collected_bookings": int(today_agg["today_bookings"] or 0),
            "revenue_7d_paise": revenue_7d_paise,
            "revenue_7d_display": paise_to_rupees_display(revenue_7d_paise),
            "active_bookings": active_bookings,
            "check_ins_today": check_ins_today,
            "donor_savings_paise": donor_savings_7d_paise,
            "donor_savings_display": paise_to_rupees_display(donor_savings_7d_paise),
            "vip_arrivals": vip_arrivals,
            **occupancy,
        },
        "revenue_chart": revenue_chart,
    }


def build_reports_analytics(user, branch_id_param: str | None = None) -> dict:
    bookings_qs = _bookings_qs(user, branch_id_param)

    coupon_redemptions = Booking.coupons_applied.through.objects.filter(
        booking_id__in=bookings_qs.values("pk")
    ).count()

    free_stays = (
        bookings_qs.filter(final_amount=0)
        .exclude(status=Booking.Status.CANCELLED)
        .count()
    )

    today = timezone.localdate()
    period_start = today - timedelta(days=6)
    collected = _with_revenue_day(_collected_bookings_qs(bookings_qs))
    period_discount = collected.filter(
        revenue_day__gte=period_start,
        revenue_day__lte=today,
    ).aggregate(total=Sum("discount_amount"))
    total_discount_paise = int(period_discount["total"] or 0)

    return {
        "coupon_redemptions": coupon_redemptions,
        "free_stays": free_stays,
        "total_discount_paise": total_discount_paise,
        "total_discount_display": paise_to_rupees_display(total_discount_paise),
        "revenue_chart": _build_revenue_chart(bookings_qs),
    }


def build_finance_analytics(user, branch_id_param: str | None = None) -> dict:
    bookings_qs = _bookings_qs(user, branch_id_param)

    paid_qs = _collected_bookings_qs(bookings_qs)
    finance_agg = paid_qs.aggregate(
        collected_paise=Sum("final_amount"),
        paid_bookings=Count("id"),
    )

    unpaid_qs = bookings_qs.filter(
        payment_status=Booking.PaymentStatus.UNPAID
    ).exclude(status=Booking.Status.CANCELLED)
    pending_agg = unpaid_qs.aggregate(
        pending_paise=Sum("final_amount"),
        unpaid_bookings=Count("id"),
    )

    refunds_queue = bookings_qs.filter(
        payment_status=Booking.PaymentStatus.REFUND_PENDING
    ).count()

    collected_paise = int(finance_agg["collected_paise"] or 0)
    pending_paise = int(pending_agg["pending_paise"] or 0)

    return {
        "collected_paise": collected_paise,
        "collected_display": paise_to_rupees_display(collected_paise),
        "paid_bookings": int(finance_agg["paid_bookings"] or 0),
        "pending_paise": pending_paise,
        "pending_display": paise_to_rupees_display(pending_paise),
        "unpaid_bookings": int(pending_agg["unpaid_bookings"] or 0),
        "refunds_queue": refunds_queue,
    }
