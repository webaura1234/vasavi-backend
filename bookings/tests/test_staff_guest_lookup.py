"""Staff guest lookup for manual booking."""

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import AdminBranch, ProfileConfirmation, User
from branches.models import Branch
from coupons.models import Coupon, CouponBatch
from donors.models import Donation, DonationPurpose, DonorProfile, MembershipTier


class StaffGuestLookupTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Main",
            city="Hyderabad",
            address="1 Road",
            phone="9999999999",
        )
        self.admin = User.objects.create_user(
            phone="9000000020",
            name="Admin",
            role="admin",
        )
        ProfileConfirmation.objects.create(user=self.admin, is_confirmed=True)
        super_user = User.objects.create_user(
            phone="9000000021",
            name="Super",
            role="super_admin",
        )
        AdminBranch.objects.create(
            user=self.admin,
            branch=self.branch,
            assigned_by=super_user,
        )

        self.tier = MembershipTier.objects.create(name="Gold")
        self.purpose = DonationPurpose.objects.create(name="General")
        self.donor_user = User.objects.create_user(
            phone="9000000022",
            name="Donor Guest",
            role="donor",
        )
        ProfileConfirmation.objects.create(user=self.donor_user, is_confirmed=True)
        self.profile = DonorProfile.objects.create(
            user=self.donor_user,
            donor_id="VCI-2026-00222",
            membership_tier=self.tier,
            for_place=self.branch,
        )
        donation = Donation.objects.create(
            donor=self.profile,
            amount=100_000,
            purpose=self.purpose,
            created_by=super_user,
        )
        batch = CouponBatch.objects.create(
            donation=donation,
            coupon_type=CouponBatch.CouponType.FREE,
            serial_start=9001,
            serial_end=9001,
            count=1,
        )
        batch.coupons.update(status=Coupon.Status.DISPATCHED)

        token = str(RefreshToken.for_user(self.admin).access_token)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_lookup_donor_returns_available_coupons(self):
        response = self.client.get(
            "/api/v1/staff/guests/lookup/",
            {"phone": "9000000022"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertTrue(data["found"])
        self.assertTrue(data["is_donor"])
        self.assertEqual(data["donor_id"], "VCI-2026-00222")
        self.assertEqual(len(data["available_coupons"]), 1)

    def test_lookup_unknown_guest(self):
        response = self.client.get(
            "/api/v1/staff/guests/lookup/",
            {"phone": "9000000099"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["data"]["found"])
