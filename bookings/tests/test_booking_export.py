"""Tests for Bookings Export System with role-based restrictions."""

import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
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
        response = client.post(
            "/api/v1/staff/bookings/export/",
            payload,
            format="json",
            HTTP_X_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
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
        response = client.post(
            "/api/v1/staff/bookings/export/",
            payload,
            format="json",
            HTTP_X_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
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

    def test_export_download_requires_ready_file(self):
        export = BookingExport.objects.create(
            requested_by=self.admin_a,
            branch=self.branch_a,
            status=BookingExport.Status.PENDING,
            filters_applied={},
        )
        client = self._get_authenticated_client(self.admin_a)
        response = client.get(f"/api/v1/staff/bookings/export/{export.pk}/download/")
        self.assertEqual(response.status_code, 409)

    def test_export_download_streams_ready_file(self):
        from bookings.services.export import booking_export_download_api_path

        export_dir = Path(settings.BOOKING_EXPORT_DIR)
        export_dir.mkdir(parents=True, exist_ok=True)
        file_path = export_dir / f"bookings_export_{uuid.uuid4().hex[:8]}_test.xlsx"
        file_path.write_bytes(b"PK\x03\x04test")

        export = BookingExport.objects.create(
            requested_by=self.admin_a,
            branch=self.branch_a,
            status=BookingExport.Status.READY,
            filters_applied={},
            file_path=str(file_path),
            download_url=booking_export_download_api_path(str(uuid.uuid4())),
            record_count=1,
            expires_at=timezone.now() + timedelta(days=7),
        )

        client = self._get_authenticated_client(self.admin_a)
        response = client.get(f"/api/v1/staff/bookings/export/{export.pk}/download/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            response["Content-Type"],
        )
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(b"".join(response.streaming_content), b"PK\x03\x04test")

        file_path.unlink(missing_ok=True)

    def test_export_status_returns_api_download_url_when_ready(self):
        from bookings.services.export import booking_export_download_api_path

        export_dir = Path(settings.BOOKING_EXPORT_DIR)
        export_dir.mkdir(parents=True, exist_ok=True)
        file_path = export_dir / f"bookings_export_{uuid.uuid4().hex[:8]}_status.xlsx"
        file_path.write_bytes(b"ready")

        export = BookingExport.objects.create(
            requested_by=self.super_admin,
            branch=None,
            status=BookingExport.Status.READY,
            filters_applied={},
            file_path=str(file_path),
            download_url="/media/exports/bookings/old-path.xlsx",
            record_count=20,
            expires_at=timezone.now() + timedelta(days=7),
        )

        client = self._get_authenticated_client(self.super_admin)
        response = client.get(f"/api/v1/staff/bookings/export/{export.pk}/")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "ready")
        self.assertEqual(
            data["download_url"],
            booking_export_download_api_path(str(export.pk)),
        )

        file_path.unlink(missing_ok=True)

    def test_export_list_endpoint(self):
        export_dir = Path(settings.BOOKING_EXPORT_DIR)
        export_dir.mkdir(parents=True, exist_ok=True)
        file_path = export_dir / f"bookings_export_{uuid.uuid4().hex[:8]}_list.xlsx"
        file_path.write_bytes(b"list")

        BookingExport.objects.create(
            requested_by=self.admin_a,
            branch=self.branch_a,
            status=BookingExport.Status.READY,
            filters_applied={"status": "confirmed"},
            file_path=str(file_path),
            record_count=3,
            estimated_count=3,
            progress_percent=100,
            expires_at=timezone.now() + timedelta(days=7),
        )

        client = self._get_authenticated_client(self.admin_a)
        response = client.get("/api/v1/staff/bookings/export/")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertGreaterEqual(data["count"], 1)
        self.assertTrue(data["results"])
        self.assertIn("progress_percent", data["results"][0])
        self.assertIn("download_url", data["results"][0])

        file_path.unlink(missing_ok=True)
