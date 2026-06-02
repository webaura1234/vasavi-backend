"""Staff donor coupon list API tests."""

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import AdminBranch, ProfileConfirmation, User
from branches.models import Branch
from coupons.models import Coupon, CouponBatch
from donors.models import Donation, DonationPurpose, DonorProfile, MembershipTier


class StaffDonorCouponListTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Main",
            city="Hyderabad",
            address="1 Road",
            phone="9999999999",
        )
        self.other_branch = Branch.objects.create(
            name="Other",
            city="Warangal",
            address="2 Road",
            phone="8888888888",
        )
        self.super_admin = User.objects.create_user(
            phone="9000000010",
            name="Super",
            role="super_admin",
        )
        ProfileConfirmation.objects.create(user=self.super_admin, is_confirmed=True)

        self.admin = User.objects.create_user(
            phone="9000000011",
            name="Admin",
            role="admin",
        )
        ProfileConfirmation.objects.create(user=self.admin, is_confirmed=True)
        AdminBranch.objects.create(
            user=self.admin,
            branch=self.branch,
            assigned_by=self.super_admin,
        )

        self.tier = MembershipTier.objects.create(name="Gold")
        self.purpose = DonationPurpose.objects.create(name="General")
        self.donor_user = User.objects.create_user(
            phone="9000000012",
            name="Donor",
            role="donor",
        )
        ProfileConfirmation.objects.create(user=self.donor_user, is_confirmed=True)
        self.profile = DonorProfile.objects.create(
            user=self.donor_user,
            donor_id="VCI-2026-00099",
            membership_tier=self.tier,
            for_place=self.branch,
        )
        self.other_profile = DonorProfile.objects.create(
            user=User.objects.create_user(
                phone="9000000013",
                name="Other Donor",
                role="donor",
            ),
            donor_id="VCI-2026-00100",
            membership_tier=self.tier,
            for_place=self.other_branch,
        )
        ProfileConfirmation.objects.create(
            user=self.other_profile.user,
            is_confirmed=True,
        )
        donation = Donation.objects.create(
            donor=self.profile,
            amount=50_000,
            purpose=self.purpose,
            created_by=self.super_admin,
        )
        batch = CouponBatch.objects.create(
            donation=donation,
            coupon_type=CouponBatch.CouponType.FREE,
            serial_start=1,
            serial_end=2,
            count=2,
        )
        batch.coupons.update(status=Coupon.Status.DISPATCHED)

        self.client = APIClient()
        token = str(RefreshToken.for_user(self.admin).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_branch_admin_lists_donors_for_assigned_branch_only(self):
        response = self.client.get("/api/v1/staff/donors/coupons/")
        self.assertEqual(response.status_code, 200)
        results = response.json()["data"]["results"]
        donor_ids = {row["donor_id"] for row in results}
        self.assertIn(self.profile.donor_id, donor_ids)
        self.assertNotIn(self.other_profile.donor_id, donor_ids)

    def test_super_admin_blocked_from_branch_coupon_tracking(self):
        token = str(RefreshToken.for_user(self.super_admin).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = self.client.get("/api/v1/staff/donors/coupons/")
        self.assertEqual(response.status_code, 403)
