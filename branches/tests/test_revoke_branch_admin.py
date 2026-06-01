"""Super admin can revoke branch staff admin assignments."""

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import AdminBranch, User
from branches.models import Branch


class RevokeBranchAdminTests(TestCase):
    def setUp(self):
        self.super_admin = User.objects.create_user(
            phone="9111111111",
            name="Super",
            role="super_admin",
        )
        self.branch = Branch.objects.create(
            name="Revoke Test Branch",
            city="City",
            address="Addr",
            phone="1222222222",
        )
        self.admin = User.objects.create_user(
            phone="9222222222",
            name="Branch Admin",
            role="admin",
            is_active=True,
        )
        AdminBranch.objects.create(
            user=self.admin,
            branch=self.branch,
            assigned_by=self.super_admin,
        )
        self.client = APIClient()
        token = RefreshToken.for_user(self.super_admin)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    def test_super_admin_revokes_branch_admin(self):
        response = self.client.post(
            f"/api/v1/branches/{self.branch.pk}/revoke-admin/",
            {"user_id": str(self.admin.pk)},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_active)
        self.assertFalse(
            AdminBranch.objects.filter(user=self.admin, branch=self.branch).exists()
        )

    def test_branch_admin_cannot_revoke(self):
        other_admin = User.objects.create_user(
            phone="9333333333",
            name="Other",
            role="admin",
        )
        token = RefreshToken.for_user(other_admin)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        response = client.post(
            f"/api/v1/branches/{self.branch.pk}/revoke-admin/",
            {"user_id": str(self.admin.pk)},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
