"""Branch API views."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework import generics, status

from accounts.branch_scope import staff_branch_id
from accounts.models import AdminBranch, User
from branches.models import Branch
from branches.serializers import (
    AdminBranchSerializer,
    AssignAdminSerializer,
    BranchCreateSerializer,
    BranchSerializer,
    RevokeAdminSerializer,
)
from permissions import IsAdminOrAbove, IsPublic, IsSuperAdmin
from utils.responses import error_response, paginated_response, success_response


class BranchListCreateView(generics.ListCreateAPIView):
    lookup_field = "pk"

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsSuperAdmin()]
        return [IsPublic()]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return BranchCreateSerializer
        return BranchSerializer

    def get_queryset(self):
        qs = Branch.objects.filter(is_deleted=False)
        user = self.request.user
        if user.is_authenticated and user.role == "admin":
            branch_id = staff_branch_id(user)
            if not branch_id:
                return qs.none()
            return qs.filter(pk=branch_id).order_by("city", "name")
        if user.is_authenticated and user.role == "super_admin":
            return qs.order_by("city", "name")
        return qs.filter(is_active=True).order_by("city", "name")

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        return paginated_response(queryset, request, BranchSerializer)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        branch = serializer.save()
        return success_response(
            BranchSerializer(branch).data,
            status=201,
            message="Branch created.",
        )


class BranchDetailView(generics.RetrieveUpdateDestroyAPIView):
    lookup_field = "pk"
    permission_classes = [IsAdminOrAbove]
    queryset = Branch.objects.filter(is_deleted=False)

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return BranchCreateSerializer
        return BranchSerializer

    def retrieve(self, request, *args, **kwargs):
        branch = self.get_object()
        return success_response(BranchSerializer(branch).data)

    def partial_update(self, request, *args, **kwargs):
        if request.user.role != "super_admin":
            return error_response(
                "PERMISSION_DENIED",
                "Only super admins may update branches.",
                status=403,
            )
        branch = self.get_object()
        serializer = BranchCreateSerializer(branch, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(BranchSerializer(branch).data)

    def patch(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if request.user.role != "super_admin":
            return error_response(
                "PERMISSION_DENIED",
                "Only super admins may deactivate branches.",
                status=403,
            )
        branch = self.get_object()
        branch.is_active = False
        branch.soft_delete()
        return success_response(message="Branch deactivated.")


class AssignAdminToBranchView(generics.GenericAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = AssignAdminSerializer

    def post(self, request, pk, *args, **kwargs):
        payload = {**request.data, "branch_id": str(pk)}
        serializer = self.get_serializer(data=payload)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        branch = serializer.validated_data["branch"]

        assignment, _ = AdminBranch.objects.update_or_create(
            user=user,
            defaults={
                "branch": branch,
                "assigned_by": request.user,
                "assigned_at": timezone.now(),
            },
        )

        return success_response(
            AdminBranchSerializer(assignment).data,
            message="Branch admin assigned.",
        )


def _blacklist_user_refresh_tokens(user: User) -> None:
    """Invalidate outstanding JWT refresh tokens so revoked staff cannot stay signed in."""
    try:
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )
    except ImportError:
        return

    for outstanding in OutstandingToken.objects.filter(user_id=user.pk):
        BlacklistedToken.objects.get_or_create(token=outstanding)


class RevokeAdminFromBranchView(generics.GenericAPIView):
    """Remove a branch admin's assignment and deactivate their staff portal access."""

    permission_classes = [IsSuperAdmin]
    serializer_class = RevokeAdminSerializer

    def post(self, request, pk, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user_id"]

        try:
            branch = Branch.objects.get(pk=pk, is_deleted=False)
        except Branch.DoesNotExist:
            return error_response("NOT_FOUND", "Branch not found.", status=404)

        try:
            assignment = AdminBranch.objects.select_related("user", "branch").get(
                user=user, branch=branch
            )
        except AdminBranch.DoesNotExist:
            return error_response(
                "NOT_FOUND",
                "This admin is not assigned to this branch.",
                status=404,
            )

        with transaction.atomic():
            assignment.delete()
            user.is_active = False
            user.save(update_fields=["is_active", "updated_at"])
            _blacklist_user_refresh_tokens(user)

        return success_response(
            message=f"Branch access revoked for {user.name or user.phone}.",
            status=status.HTTP_200_OK,
        )
