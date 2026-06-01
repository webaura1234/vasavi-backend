"""DRF permission classes for Vasavi role-based access control."""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from accounts.models import AdminBranch


class IsPublic(BasePermission):
    """Explicitly allow unauthenticated access."""

    def has_permission(self, request, view) -> bool:
        return True


class IsDonorOrAbove(BasePermission):
    """Authenticated users with donor, admin, or super_admin role."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return user.role in ("donor", "admin", "super_admin")


class IsAdminOrAbove(BasePermission):
    """Branch admin or super admin."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return user.role in ("admin", "super_admin")


class IsSuperAdmin(BasePermission):
    """Platform super admin only."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return user.role == "super_admin"


class IsBranchAdmin(BasePermission):
    """Branch admin with an assigned branch."""  # UNUSED — scoping uses branch_scope helpers

    # UNUSED — branch scoping is handled via queryset helpers instead.

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated or user.role != "admin":
            return False
        return AdminBranch.objects.filter(user=user).exists()

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if user.role == "super_admin":
            return True
        if user.role != "admin":
            return False
        try:
            admin_branch = user.admin_branch
        except AdminBranch.DoesNotExist:
            return False
        branch = getattr(obj, "branch", None)
        if branch is None and hasattr(obj, "branch_id"):
            return obj.branch_id == admin_branch.branch_id
        return branch is not None and branch.pk == admin_branch.branch.pk


class IsOwnerOrAdminAbove(BasePermission):
    """Object belongs to the request user, or caller is admin/super_admin."""  # UNUSED

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.role in ("admin", "super_admin"):
            return True
        owner = getattr(obj, "user", None)
        return owner is not None and owner.pk == user.pk
