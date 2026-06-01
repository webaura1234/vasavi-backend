"""Tests for Bookings Export System with role-based restrictions."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import AdminBranch, User
from bookings.models import Booking, BookingExport
from branches.models import Branch
from properties.models import Room, RoomType


class BookingExportTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        
        # Create Branches
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
        
        # Create RoomType & Rooms
        self.room_type = RoomType.objects.create(name="Standard", description="")
        self.room_a = Room.objects.create(
            branch=self.branch_a,
            room_type=self.room_type,
            room_number="101",
            capacity=2,
            base_price_per_night=1000_00,
        )
        self.room_b = Room.objects.create(
            branch=self.branch_b,
            room_type=self.room_type,
            room_number="201",
            capacity=2,
            base_price_per_night=2000_00,
        )
        
        # Create Users
        self.guest = User.objects.create_user(
            phone="9000000001",
            name="Guest",
            role="user",
        )
        self.super_admin = User.objects.create_user(
            phone="9000000000",
            name="Super Admin",
            role="super_admin",
        )
        self.admin_a = User.objects.create_user(
            phone="9000000002",
            name="Admin A",
            role="admin",
        )
        
        # Assign Branch A to Admin A
        AdminBranch.objects.create(
            user=self.admin_a,
            branch=self.branch_a,
            assigned_by=self.super_admin,
        )
        
        # Create Bookings
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
            base_amount=1000_00,
            discount_amount=0,
            final_amount=1000_00,
            status=Booking.Status.CONFIRMED,
            payment_status=Booking.PaymentStatus.UNPAID,
        )

    def _get_authenticated_client(self, user: User) -> APIClient:
        token = RefreshToken.for_user(user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        return client

    def test_export_count_endpoint(self):
        # 1. Super Admin sees all (2 bookings)
        client = self._get_authenticated_client(self.super_admin)
        response = client.get("/api/v1/staff/bookings/export/count/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["count"], 2)

        # 2. Branch Admin only sees Branch A (1 booking)
        client = self._get_authenticated_client(self.admin_a)
        response = client.get("/api/v1/staff/bookings/export/count/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["count"], 1)

    @patch("bookings.tasks.generate_booking_export.apply_async")
    def test_branch_admin_export_request_ignores_spoofed_branch(self, mock_apply_async):
        client = self._get_authenticated_client(self.admin_a)
        # Attempt to export data for Branch B
        payload = {"branch_id": str(self.branch_b.pk)}
        response = client.post("/api/v1/staff/bookings/export/", payload, format="json")
        self.assertEqual(response.status_code, 202)
        
        # Verify the database entry has branch set to self.branch_a, NOT branch_b
        export_id = response.json()["data"]["export_id"]
        export = BookingExport.objects.get(pk=export_id)
        self.assertEqual(export.branch, self.branch_a)
        self.assertEqual(export.requested_by, self.admin_a)
        self.assertEqual(export.status, BookingExport.Status.PENDING)
        
        # Celery task should be enqueued
        mock_apply_async.assert_called_once()

    @patch("bookings.tasks.generate_booking_export.apply_async")
    def test_super_admin_can_export_any_branch(self, mock_apply_async):
        client = self._get_authenticated_client(self.super_admin)
        # Super Admin explicitly filters to Branch B
        payload = {"branch_id": str(self.branch_b.pk)}
        response = client.post("/api/v1/staff/bookings/export/", payload, format="json")
        self.assertEqual(response.status_code, 202)
        
        export_id = response.json()["data"]["export_id"]
        export = BookingExport.objects.get(pk=export_id)
        self.assertEqual(export.branch, self.branch_b)
        self.assertEqual(export.requested_by, self.super_admin)
        
        mock_apply_async.assert_called_once()

    def test_export_status_endpoint_security(self):
        # Create an export request for Admin A
        export = BookingExport.objects.create(
            requested_by=self.admin_a,
            branch=self.branch_a,
            status=BookingExport.Status.PENDING,
            filters_applied={},
        )
        
        # Admin A should be able to view their own export status
        client_a = self._get_authenticated_client(self.admin_a)
        response = client_a.get(f"/api/v1/staff/bookings/export/{export.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "pending")
        
        # Super Admin should be able to view Admin A's export status
        client_super = self._get_authenticated_client(self.super_admin)
        response_super = client_super.get(f"/api/v1/staff/bookings/export/{export.pk}/")
        self.assertEqual(response_super.status_code, 200)
        
        # Another standard user or admin should NOT be able to view Admin A's export status
        other_admin = User.objects.create_user(
            phone="9000000003",
            name="Other Admin",
            role="admin",
        )
        client_other = self._get_authenticated_client(other_admin)
        response_other = client_other.get(f"/api/v1/staff/bookings/export/{export.pk}/")
        self.assertEqual(response_other.status_code, 403)
