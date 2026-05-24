"""Analytics revenue attribution tests."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from bookings.models import Booking
from bookings.services.analytics import (
    _build_revenue_chart,
    _collected_bookings_qs,
    build_dashboard_analytics,
)
from bookings.views import _booking_queryset_for_user


class AnalyticsRevenueTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.user = User.objects.create_user(
            phone="9999999999",
            name="Guest",
            role="user",
        )
        self.admin = User.objects.create_user(
            phone="8888888888",
            name="Super",
            role="super_admin",
        )

    def _make_booking(self, **kwargs):
        from branches.models import Branch
        from properties.models import Room, RoomType

        branch = Branch.objects.first()
        if not branch:
            branch = Branch.objects.create(
                name="Test Branch",
                city="Test City",
                address="Addr",
                phone="1111111111",
            )
        room_type = RoomType.objects.filter(name="Standard").first()
        if not room_type:
            room_type = RoomType.objects.create(
                name="Standard",
                description="",
            )
        room = Room.objects.filter(branch=branch).first()
        if not room:
            room = Room.objects.create(
                branch=branch,
                room_type=room_type,
                room_number="101",
                capacity=2,
                base_price_per_night=100_00,
            )

        defaults = {
            "user": self.user,
            "room": room,
            "branch": branch,
            "check_in_date": self.today,
            "check_out_date": self.today + timedelta(days=1),
            "nights": 1,
            "base_amount": 100_00,
            "discount_amount": 0,
            "final_amount": 100_00,
            "payment_status": Booking.PaymentStatus.PAID,
            "status": Booking.Status.CONFIRMED,
        }
        defaults.update(kwargs)
        # Booking.full_clean() requires final_amount == base_amount - discount_amount.
        discount = int(defaults.get("discount_amount") or 0)
        final = int(defaults["final_amount"])
        defaults["base_amount"] = final + discount
        defaults["final_amount"] = final
        return Booking.objects.create(**defaults)

    def test_collected_excludes_cancelled_and_unpaid(self):
        self._make_booking(
            payment_status=Booking.PaymentStatus.UNPAID,
            final_amount=50_00,
        )
        self._make_booking(
            status=Booking.Status.CANCELLED,
            payment_status=Booking.PaymentStatus.PAID,
            final_amount=75_00,
        )
        paid = self._make_booking(final_amount=200_00)
        qs = _booking_queryset_for_user(self.admin)
        collected = _collected_bookings_qs(qs)
        total = sum(b.final_amount for b in collected)
        self.assertEqual(total, paid.final_amount)

    def test_chart_does_not_double_count_same_booking(self):
        now = timezone.now()
        self._make_booking(
            check_in_date=self.today,
            payment_paid_at=now,
            final_amount=100_00,
        )
        qs = _booking_queryset_for_user(self.admin)
        chart = _build_revenue_chart(qs, days=7)
        today_point = next(p for p in chart if p["date"] == self.today.isoformat())
        self.assertEqual(today_point["revenue_paise"], 100_00)
        self.assertEqual(today_point["bookings"], 1)

    def test_today_revenue_uses_payment_day_not_future_checkin(self):
        future = self.today + timedelta(days=10)
        self._make_booking(
            check_in_date=future,
            check_out_date=future + timedelta(days=1),
            payment_paid_at=timezone.now(),
            final_amount=300_00,
        )
        data = build_dashboard_analytics(self.admin)
        self.assertEqual(data["stats"]["today_revenue_paise"], 300_00)

    def test_seven_day_total_matches_chart_sum(self):
        for i in range(3):
            day = timezone.now() - timedelta(days=i)
            self._make_booking(
                payment_paid_at=day,
                final_amount=(i + 1) * 100_00,
            )
        qs = _booking_queryset_for_user(self.admin)
        data = build_dashboard_analytics(self.admin)
        chart_sum = sum(p["revenue_paise"] for p in data["revenue_chart"])
        self.assertEqual(data["stats"]["revenue_7d_paise"], chart_sum)
