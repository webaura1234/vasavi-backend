"""Tests for coupon stats service."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import ProfileConfirmation, User
from branches.models import Branch
from coupons.models import Coupon, CouponBatch
from coupons.services.stats import (
    build_coupon_tracking_stats,
    compute_coupon_stats,
    coupons_for_donor_profile,
)
from donors.models import Donation, DonationPurpose, DonorProfile, MembershipTier


class CouponStatsTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Test Branch",
            city="Hyderabad",
            address="1 Main St",
            phone="9999999999",
        )
        self.tier = MembershipTier.objects.create(name="Gold")
        self.purpose = DonationPurpose.objects.create(name="General")
        self.super_admin = User.objects.create_user(
            phone="9000000001",
            name="Super Admin",
            role="super_admin",
        )
        self.donor_user = User.objects.create_user(
            phone="9000000002",
            name="Donor One",
            role="donor",
        )
        ProfileConfirmation.objects.create(user=self.donor_user, is_confirmed=True)
        self.profile = DonorProfile.objects.create(
            user=self.donor_user,
            donor_id="VCI-2026-00001",
            membership_tier=self.tier,
            for_place=self.branch,
        )
        self.donation = Donation.objects.create(
            donor=self.profile,
            amount=100_000,
            purpose=self.purpose,
            created_by=self.super_admin,
        )

    def _create_batch(self, start: int, end: int, dispatch: bool = False):
        batch = CouponBatch.objects.create(
            donation=self.donation,
            coupon_type=CouponBatch.CouponType.FREE,
            serial_start=start,
            serial_end=end,
            count=end - start + 1,
        )
        if dispatch:
            batch.coupons.update(status=Coupon.Status.DISPATCHED)
        return batch

    def test_stats_empty_donor(self):
        stats = compute_coupon_stats(donor_profile=self.profile, user=self.donor_user)
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["available"], 0)

    def test_stats_issued_and_dispatched(self):
        self._create_batch(1001, 1002, dispatch=False)
        self._create_batch(2001, 2001, dispatch=True)

        stats = compute_coupon_stats(donor_profile=self.profile, user=self.donor_user)
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["issued"], 2)
        self.assertEqual(stats["dispatched"], 1)
        self.assertEqual(stats["available"], 1)
        self.assertEqual(stats["used"], 0)

    def test_coupons_for_donor_profile_includes_donation_batches(self):
        self._create_batch(3001, 3003)
        qs = coupons_for_donor_profile(self.profile)
        self.assertEqual(qs.count(), 3)

    def test_build_coupon_tracking_stats_platform_wide(self):
        self._create_batch(4001, 4002, dispatch=False)
        self._create_batch(5001, 5001, dispatch=True)

        stats = build_coupon_tracking_stats()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["issued"], 2)
        self.assertEqual(stats["dispatched"], 1)
        self.assertEqual(stats["available"], 1)
        self.assertEqual(stats["used"], 0)

    def test_build_coupon_tracking_stats_branch_scoped_used(self):
        from bookings.models import Booking
        from properties.models import Room, RoomType

        room_type = RoomType.objects.create(name="Deluxe", description="")
        room = Room.objects.create(
            branch=self.branch,
            room_type=room_type,
            room_number="201",
            capacity=2,
            base_price_per_night=100_00,
        )
        check_in = timezone.localdate()
        booking = Booking.objects.create(
            user=self.donor_user,
            room=room,
            branch=self.branch,
            check_in_date=check_in,
            check_out_date=check_in + timedelta(days=1),
            nights=1,
            base_amount=100_00,
            discount_amount=0,
            final_amount=100_00,
        )
        batch = self._create_batch(6001, 6001, dispatch=True)
        coupon = batch.coupons.get()
        coupon.status = Coupon.Status.REDEEMED
        coupon.redeemed_at_branch = self.branch
        coupon.redeemed_by = self.donor_user
        coupon.redeemed_at_booking = booking
        coupon.redeemed_on = timezone.now()
        coupon.save(
            update_fields=[
                "status",
                "redeemed_at_branch",
                "redeemed_by",
                "redeemed_at_booking",
                "redeemed_on",
            ]
        )

        other_branch = Branch.objects.create(
            name="Other",
            city="City",
            address="Addr",
            phone="8888888888",
        )
        stats_here = build_coupon_tracking_stats(branch_id=str(self.branch.pk))
        stats_other = build_coupon_tracking_stats(branch_id=str(other_branch.pk))

        self.assertEqual(stats_here["used"], 1)
        self.assertEqual(stats_other["used"], 0)
