"""Staff room operational status API tests."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import AdminBranch, User
from bookings.models import Booking
from branches.models import Branch
from properties.models import Room, RoomType


class StaffRoomOperationalStatusTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Test Branch",
            city="City",
            address="Addr",
            phone="1111111111",
        )
        self.room_type = RoomType.objects.create(name="Deluxe", description="")
        self.room = Room.objects.create(
            branch=self.branch,
            room_type=self.room_type,
            room_number="D05",
            capacity=2,
            base_price_per_night=4_200_00,
            operational_status="available",
        )
        self.super_admin = User.objects.create_user(
            phone="9000000000",
            name="Super",
            role="super_admin",
        )
        self.admin = User.objects.create_user(
            phone="9111111111",
            name="Branch Admin",
            role="admin",
        )
        AdminBranch.objects.create(
            user=self.admin,
            branch=self.branch,
            assigned_by=self.super_admin,
        )
        token = RefreshToken.for_user(self.admin)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    def test_patch_operational_status_blocked(self):
        response = self.client.patch(
            f"/api/v1/staff/rooms/{self.room.pk}/operational-status/",
            {"operational_status": "blocked"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.room.refresh_from_db()
        self.assertEqual(self.room.operational_status, "blocked")

    def test_cannot_block_while_checked_in(self):
        guest = User.objects.create_user(phone="9222222222", name="Guest", role="user")
        today = timezone.localdate()
        Booking.objects.create(
            user=guest,
            room=self.room,
            branch=self.branch,
            check_in_date=today,
            check_out_date=today + timedelta(days=2),
            nights=2,
            base_amount=8_400_00,
            discount_amount=0,
            final_amount=8_400_00,
            status=Booking.Status.CHECKED_IN,
            payment_status=Booking.PaymentStatus.PAID,
        )
        response = self.client.patch(
            f"/api/v1/staff/rooms/{self.room.pk}/operational-status/",
            {"operational_status": "maintenance"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.room.refresh_from_db()
        self.assertEqual(self.room.operational_status, "available")
