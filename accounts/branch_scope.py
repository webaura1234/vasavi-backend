"""Branch scoping helpers for staff portal users."""

from __future__ import annotations

from typing import TYPE_CHECKING

from accounts.models import AdminBranch

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from accounts.models import User


def staff_branch_id(user: User) -> str | None:
    """
    Return the assigned branch UUID for a branch admin.

    Returns ``None`` for super admins, guests, or admins without an
    :class:`~accounts.models.AdminBranch` assignment.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return None
    if user.role != "admin":
        return None
    try:
        return str(user.admin_branch.branch_id)
    except AdminBranch.DoesNotExist:
        return None


def require_staff_branch_id(user: User) -> str | None:
    """Like :func:`staff_branch_id` but returns ``None`` only for non-admin roles."""
    if user.role != "admin":
        return None
    return staff_branch_id(user)


def filter_queryset_by_staff_branch(
    queryset: QuerySet,
    user: User,
    *,
    field: str = "branch_id",
) -> QuerySet:
    """Restrict *queryset* to the admin's branch; no-op for super admins."""
    branch_id = staff_branch_id(user)
    if branch_id is None and user.role == "admin":
        return queryset.none()
    if branch_id:
        return queryset.filter(**{field: branch_id})
    return queryset


def filter_staff_room_queryset(
    queryset: QuerySet,
    user: User,
    branch_id_param: str | None = None,
) -> QuerySet:
    """
    Staff room list scope.

    - Branch admin: always their assigned branch (ignores spoofed params).
    - Super admin: optional ``branch_id`` query param; otherwise all branches.
    """
    assigned = staff_branch_id(user)
    if user.role == "admin":
        if not assigned:
            return queryset.none()
        return queryset.filter(branch_id=assigned)
    if branch_id_param:
        return queryset.filter(branch_id=branch_id_param)
    return queryset


def filter_staff_function_hall_queryset(
    queryset: QuerySet,
    user: User,
    branch_id_param: str | None = None,
) -> QuerySet:
    """
    Staff function hall list scope.

    - Branch admin: always their assigned branch (ignores spoofed params).
    - Super admin: optional ``branch_id`` query param; otherwise all branches.
    """
    assigned = staff_branch_id(user)
    if user.role == "admin":
        if not assigned:
            return queryset.none()
        return queryset.filter(branch_id=assigned)
    if branch_id_param:
        return queryset.filter(branch_id=branch_id_param)
    return queryset
