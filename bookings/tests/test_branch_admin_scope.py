"""Branch admin must only see bookings for their assigned property."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import AdminBranch, User
from bookings.models import Booking
from bookings.views import _booking_queryset_for_user
from branches.models import Branch
from properties.models import Room, RoomType


class BranchAdminBookingScopeTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.branch_a = Branch.objects.create(
            name="Branch A",
            city="City A",
            address="A",
            phone="1111111111",
        )
        self.branch_b = Branch.objects.create(
            name="Branch B",
            city="City B",
            address="B",
            phone="2222222222",
        )
        self.room_type = RoomType.objects.create(name="Standard", description="")
        self.room_a = Room.objects.create(
            branch=self.branch_a,
            room_type=self.room_type,
            room_number="101",
            capacity=2,
            base_price_per_night=1_000_00,
        )
        self.room_b = Room.objects.create(
            branch=self.branch_b,
            room_type=self.room_type,
            room_number="201",
            capacity=2,
            base_price_per_night=2_000_00,
        )
        self.guest = User.objects.create_user(
            phone="9000000001",
            name="Guest",
            role="user",
        )
        self.admin_a = User.objects.create_user(
            phone="9000000002",
            name="Admin A",
            role="admin",
        )
        AdminBranch.objects.create(
            user=self.admin_a,
            branch=self.branch_a,
            assigned_by=User.objects.create_user(
                phone="9000000099",
                name="Super",
                role="super_admin",
            ),
        )
        self.booking_a = self._create_booking(self.branch_a, self.room_a)
        self.booking_b = self._create_booking(self.branch_b, self.room_b)

    def _create_booking(self, branch: Branch, room: Room) -> Booking:
        return Booking.objects.create(
            user=self.guest,
            room=room,
            branch=branch,
            check_in_date=self.today,
            check_out_date=self.today + timedelta(days=1),
            nights=1,
            base_amount=1_000_00,
            discount_amount=0,
            final_amount=1_000_00,
            status=Booking.Status.CONFIRMED,
            payment_status=Booking.PaymentStatus.UNPAID,
        )

    def test_queryset_only_includes_assigned_branch(self):
        qs = _booking_queryset_for_user(self.admin_a)
        ids = set(qs.values_list("pk", flat=True))
        self.assertEqual(ids, {self.booking_a.pk})
        self.assertNotIn(self.booking_b.pk, ids)

    def test_admin_without_branch_assignment_sees_nothing(self):
        orphan = User.objects.create_user(
            phone="9000000003",
            name="Orphan Admin",
            role="admin",
        )
        self.assertEqual(_booking_queryset_for_user(orphan).count(), 0)

    def test_list_api_ignores_spoofed_branch_id_param(self):
        token = RefreshToken.for_user(self.admin_a)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

        response = client.get(
            f"/api/v1/bookings/?branch_id={self.branch_b.pk}"
        )
        self.assertEqual(response.status_code, 200)
        results = response.json()["data"]["results"]
        result_ids = {row["id"] for row in results}
        self.assertEqual(result_ids, {str(self.booking_a.pk)})

    def test_detail_other_branch_returns_404(self):
        token = RefreshToken.for_user(self.admin_a)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

        response = client.get(f"/api/v1/bookings/{self.booking_b.pk}/")
        self.assertEqual(response.status_code, 404)
