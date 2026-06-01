"""Booking list date filters include upcoming reservations."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from bookings.models import Booking
from bookings.query_filters import apply_booking_list_filters
from branches.models import Branch
from properties.models import FunctionHall


class BookingListDateFilterTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.branch = Branch.objects.create(
            name="Filter Branch",
            city="City",
            address="Addr",
            phone="1111111111",
        )
        self.hall = FunctionHall.objects.create(
            branch=self.branch,
            name="Future Hall",
            capacity=100,
            base_price_per_day=10_000_00,
            operational_status="available",
        )
        self.user = User.objects.create_user(
            phone="9888888888",
            name="Guest",
            role="user",
        )

    def test_future_function_hall_booking_in_30d_preset(self):
        check_in = self.today + timedelta(days=20)
        check_out = check_in + timedelta(days=2)
        Booking.objects.create(
            user=self.user,
            function_hall=self.hall,
            branch=self.branch,
            booking_kind=Booking.BookingKind.FUNCTION_HALL,
            check_in_date=check_in,
            check_out_date=check_out,
            nights=2,
            base_amount=20_000_00,
            discount_amount=0,
            final_amount=20_000_00,
            status=Booking.Status.CONFIRMED,
            payment_status=Booking.PaymentStatus.UNPAID,
        )

        qs = Booking.objects.filter(is_deleted=False)
        filtered = apply_booking_list_filters(
            qs,
            {"period": "30d"},
        )
        self.assertEqual(filtered.count(), 1)
