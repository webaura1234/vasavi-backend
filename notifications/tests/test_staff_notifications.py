"""Staff portal booking notifications."""

from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import AdminBranch, User
from bookings.models import Booking
from branches.models import Branch
from notifications.models import Notification
from notifications.services.staff import notify_staff_new_booking
from properties.models import Room, RoomType


class StaffBookingNotificationTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Test Branch",
            city="Hyderabad",
            address="Addr",
            phone="1333333333",
        )
        self.super_admin = User.objects.create_user(
            phone="9000000001",
            name="Super",
            role="super_admin",
        )
        self.branch_admin = User.objects.create_user(
            phone="9000000002",
            name="Branch Admin",
            role="admin",
        )
        AdminBranch.objects.create(
            user=self.branch_admin,
            branch=self.branch,
            assigned_by=self.super_admin,
        )
        self.guest = User.objects.create_user(
            phone="9000000003",
            name="Guest User",
            role="donor",
        )
        room_type = RoomType.objects.create(name="Standard", description="")
        self.room = Room.objects.create(
            branch=self.branch,
            room_type=room_type,
            room_number="101",
            capacity=2,
            base_price_per_night=250000,
            operational_status="available",
        )
        check_in = date.today() + timedelta(days=2)
        check_out = check_in + timedelta(days=1)
        self.booking = Booking.objects.create(
            user=self.guest,
            room=self.room,
            branch=self.branch,
            booking_kind=Booking.BookingKind.ROOM,
            check_in_date=check_in,
            check_out_date=check_out,
            nights=1,
            guest_count=2,
            guest_name="Rama",
            guest_phone="9876543210",
            status=Booking.Status.CONFIRMED,
            base_amount=250000,
            discount_amount=0,
            final_amount=250000,
            payment_status=Booking.PaymentStatus.UNPAID,
        )

    def test_notify_staff_new_booking_creates_for_admin_and_super(self):
        notify_staff_new_booking(self.booking.pk)
        admin_notes = Notification.objects.filter(recipient=self.branch_admin)
        super_notes = Notification.objects.filter(recipient=self.super_admin)
        self.assertEqual(admin_notes.count(), 2)
        self.assertEqual(super_notes.count(), 2)
        types = set(admin_notes.values_list("type", flat=True))
        self.assertIn(Notification.Type.NEW_BOOKING, types)
        self.assertIn(Notification.Type.PAYMENT_PENDING, types)
        note = admin_notes.filter(type=Notification.Type.NEW_BOOKING).first()
        self.assertEqual(note.related_entity_type, "booking")
        self.assertEqual(note.related_entity_id, self.booking.pk)

    def test_staff_can_list_own_notifications(self):
        notify_staff_new_booking(self.booking.pk)
        client = APIClient()
        client.force_authenticate(user=self.branch_admin)
        response = client.get("/api/v1/notifications/recent/?limit=5")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertGreaterEqual(len(data), 1)
