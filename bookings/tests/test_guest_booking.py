"""Guest pending booking and confirm flow."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from bookings.models import Booking
from branches.models import Branch
from properties.models import Room, RoomType


class GuestBookingFlowTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.user = User.objects.create_user(
            phone="9777777777",
            name="Guest Test",
            role="user",
        )
        token = RefreshToken.for_user(self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

        self.branch = Branch.objects.create(
            name="Flow Branch",
            city="City",
            address="Addr",
            phone="1222222222",
        )
        self.room_type = RoomType.objects.create(name="Deluxe", description="")
        self.room = Room.objects.create(
            branch=self.branch,
            room_type=self.room_type,
            room_number="201",
            capacity=2,
            base_price_per_night=5_000_00,
            operational_status="available",
        )

    def test_create_pending_and_guest_confirm(self):
        create = self.client.post(
            "/api/v1/bookings/",
            {
                "room_id": str(self.room.pk),
                "check_in_date": (self.today + timedelta(days=2)).isoformat(),
                "check_out_date": (self.today + timedelta(days=4)).isoformat(),
                "guest_count": 2,
            },
            format="json",
            HTTP_X_IDEMPOTENCY_KEY="test-create-1",
        )
        self.assertEqual(create.status_code, 201)
        data = create.json()["data"]
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["payment_status"], "unpaid")
        self.assertIsNotNone(data["expires_at"])

        booking_id = data["id"]
        confirm = self.client.post(
            f"/api/v1/bookings/{booking_id}/confirm/",
            {},
            format="json",
            HTTP_X_IDEMPOTENCY_KEY="test-confirm-1",
        )
        self.assertEqual(confirm.status_code, 200)
        confirmed = confirm.json()["data"]
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(confirmed["payment_status"], "unpaid")

        booking = Booking.objects.get(pk=booking_id)
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(booking.payment_status, Booking.PaymentStatus.UNPAID)

    def test_list_pending_filter(self):
        Booking.objects.create(
            user=self.user,
            room=self.room,
            branch=self.branch,
            check_in_date=self.today + timedelta(days=5),
            check_out_date=self.today + timedelta(days=6),
            nights=1,
            base_amount=5_000_00,
            discount_amount=0,
            final_amount=5_000_00,
            status=Booking.Status.PENDING,
            payment_status=Booking.PaymentStatus.UNPAID,
        )
        Booking.objects.create(
            user=self.user,
            room=self.room,
            branch=self.branch,
            check_in_date=self.today + timedelta(days=10),
            check_out_date=self.today + timedelta(days=11),
            nights=1,
            base_amount=5_000_00,
            discount_amount=0,
            final_amount=5_000_00,
            status=Booking.Status.CONFIRMED,
            payment_status=Booking.PaymentStatus.PAID,
        )

        response = self.client.get(
            "/api/v1/bookings/?status=pending&payment_status=unpaid"
        )
        self.assertEqual(response.status_code, 200)
        results = response.json()["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "pending")
