"""Tests for in-app notifications."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from bookings.models import Booking
from bookings.services.guest_confirm import redeem_coupons_on_booking
from branches.models import Branch
from coupons.models import Coupon, CouponBatch
from donors.models import Donation, DonationPurpose, DonorProfile, MembershipTier
from notifications.models import Notification
from notifications.services import notify_coupon_redeemed, create_notification
from properties.models import Room, RoomType


class NotificationServiceTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Notify Branch",
            city="City",
            address="Addr",
            phone="1333333333",
        )
        self.tier = MembershipTier.objects.create(name="Silver")
        self.purpose = DonationPurpose.objects.create(name="Hall Renovation")

        self.donor_user = User.objects.create_user(
            phone="9888888881",
            name="Donor Owner",
            role="donor",
        )
        self.donor_profile = DonorProfile.objects.create(
            user=self.donor_user,
            donor_id="DH-TEST-001",
            membership_tier=self.tier,
            for_place=self.branch,
        )

        self.redeemer = User.objects.create_user(
            phone="9888888882",
            name="John Doe",
            role="user",
        )

        self.super_admin = User.objects.create_user(
            phone="9888888883",
            name="Super Admin",
            role="super_admin",
        )

        self.donation = Donation.objects.create(
            donor=self.donor_profile,
            amount=100_000_00,
            purpose=self.purpose,
            created_by=self.super_admin,
        )

        self.batch = CouponBatch.objects.create(
            donation=self.donation,
            coupon_type=CouponBatch.CouponType.CONCESSION,
            serial_start=1001,
            serial_end=1001,
            count=1,
        )
        self.coupon = Coupon.objects.get(batch=self.batch, serial_number=1001)
        self.coupon.status = Coupon.Status.DISPATCHED
        self.coupon.save(update_fields=["status", "updated_at"])

        self.room_type = RoomType.objects.create(name="Standard", description="")
        self.room = Room.objects.create(
            branch=self.branch,
            room_type=self.room_type,
            room_number="101",
            capacity=2,
            base_price_per_night=5_000_00,
            operational_status="available",
        )

        self.today = timezone.localdate()
        self.booking = Booking.objects.create(
            user=self.redeemer,
            room=self.room,
            branch=self.branch,
            check_in_date=self.today + timedelta(days=3),
            check_out_date=self.today + timedelta(days=5),
            nights=2,
            base_amount=10_000_00,
            discount_amount=0,
            final_amount=10_000_00,
            status=Booking.Status.PENDING,
            payment_status=Booking.PaymentStatus.UNPAID,
        )

    def test_notify_coupon_redeemed_notifies_donation_owner(self):
        redeem_coupons_on_booking(
            self.booking,
            [self.coupon],
            changed_by=self.redeemer,
        )

        notifications = Notification.objects.filter(recipient=self.donor_user)
        self.assertEqual(notifications.count(), 1)
        note = notifications.first()
        self.assertEqual(note.type, Notification.Type.COUPON_REDEEMED)
        self.assertEqual(note.category, Notification.Category.COUPON)
        self.assertIn("1001", note.message)
        self.assertIn("John Doe", note.message)
        self.assertEqual(note.metadata["coupon_code"], "1001")
        self.assertIsNone(note.read_at)

    def test_notify_coupon_redeemed_skips_redeemer_when_assigned(self):
        assigned_donor = User.objects.create_user(
            phone="9888888884",
            name="Assigned Donor",
            role="donor",
        )
        DonorProfile.objects.create(
            user=assigned_donor,
            donor_id="DH-TEST-002",
            membership_tier=self.tier,
            for_place=self.branch,
        )
        self.coupon.assigned_donors.add(assigned_donor)
        self.booking.user = assigned_donor
        self.booking.save(update_fields=["user", "updated_at"])

        redeem_coupons_on_booking(
            self.booking,
            [self.coupon],
            changed_by=assigned_donor,
        )

        self.assertFalse(
            Notification.objects.filter(recipient=assigned_donor).exists()
        )

    def test_notify_coupon_redeemed_notifies_assigned_donors(self):
        assigned_donor = User.objects.create_user(
            phone="9888888885",
            name="Assigned Donor Two",
            role="donor",
        )
        DonorProfile.objects.create(
            user=assigned_donor,
            donor_id="DH-TEST-003",
            membership_tier=self.tier,
            for_place=self.branch,
        )
        self.coupon.assigned_donors.add(assigned_donor)

        notify_coupon_redeemed(
            self.coupon,
            redeemed_by_user=self.redeemer,
            booking=self.booking,
        )

        self.assertTrue(
            Notification.objects.filter(recipient=assigned_donor).exists()
        )
        self.assertFalse(
            Notification.objects.filter(recipient=self.donor_user).exists()
        )


class NotificationApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            phone="9777777778",
            name="Notify User",
            role="user",
        )
        self.other = User.objects.create_user(
            phone="9777777779",
            name="Other User",
            role="user",
        )
        token = RefreshToken.for_user(self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

        self.unread = create_notification(
            self.user,
            category=Notification.Category.COUPON,
            type=Notification.Type.COUPON_REDEEMED,
            title="Coupon Used",
            message="Your coupon was used.",
        )
        self.read = create_notification(
            self.user,
            category=Notification.Category.USER,
            type=Notification.Type.PROFILE_UPDATED,
            title="Profile Updated",
            message="Your profile was updated.",
        )
        self.read.read_at = timezone.now()
        self.read.save(update_fields=["read_at", "updated_at"])

        create_notification(
            self.other,
            category=Notification.Category.SYSTEM,
            type=Notification.Type.SYSTEM_ALERT,
            title="Other alert",
            message="Not for this user.",
        )

    def test_unread_count(self):
        response = self.client.get("/api/v1/notifications/unread-count/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["count"], 1)

    def test_list_filter_unread(self):
        response = self.client.get("/api/v1/notifications/?status=unread")
        self.assertEqual(response.status_code, 200)
        results = response.json()["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(self.unread.pk))

    def test_list_search(self):
        response = self.client.get("/api/v1/notifications/?search=Profile")
        self.assertEqual(response.status_code, 200)
        results = response.json()["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Profile Updated")

    def test_mark_read(self):
        response = self.client.patch(f"/api/v1/notifications/{self.unread.pk}/read/")
        self.assertEqual(response.status_code, 200)
        self.unread.refresh_from_db()
        self.assertIsNotNone(self.unread.read_at)

    def test_mark_all_read(self):
        response = self.client.post("/api/v1/notifications/mark-all-read/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Notification.objects.filter(recipient=self.user, read_at__isnull=True).count(),
            0,
        )

    def test_recent_returns_limited_results(self):
        for i in range(6):
            create_notification(
                self.user,
                category=Notification.Category.SYSTEM,
                type=Notification.Type.SYSTEM_ALERT,
                title=f"Alert {i}",
                message=f"Message {i}",
            )

        response = self.client.get("/api/v1/notifications/recent/?limit=5")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 5)

    def test_cannot_mark_other_users_notification(self):
        response = self.client.patch(
            f"/api/v1/notifications/{Notification.objects.filter(recipient=self.other).first().pk}/read/"
        )
        self.assertEqual(response.status_code, 404)
