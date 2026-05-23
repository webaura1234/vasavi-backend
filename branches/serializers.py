"""Branch serializers."""

from __future__ import annotations

import re

from rest_framework import serializers

from accounts.models import AdminBranch, User
from accounts.serializers import UserProfileSerializer
from branches.models import Branch


class BranchSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Branch
        fields = (
            "id",
            "name",
            "city",
            "address",
            "phone",
            "is_active",
            "created_at",
        )
        read_only_fields = ("id", "created_at")


class BranchCreateSerializer(BranchSerializer):
    class Meta(BranchSerializer.Meta):
        read_only_fields = ("id", "created_at")

    def validate_phone(self, value: str) -> str:
        digits = re.sub(r"\D", "", value or "")
        if value and len(digits) != 10:
            raise serializers.ValidationError("Phone must be 10 digits.")
        return digits or ""


class AdminBranchSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    user = UserProfileSerializer(read_only=True)
    branch = BranchSerializer(read_only=True)
    assigned_by = UserProfileSerializer(read_only=True)

    class Meta:
        model = AdminBranch
        fields = (
            "id",
            "user",
            "branch",
            "assigned_by",
            "assigned_at",
        )
        read_only_fields = fields


class AssignAdminSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    branch_id = serializers.UUIDField()

    def validate(self, attrs):
        try:
            user = User.objects.get(pk=attrs["user_id"], is_deleted=False)
        except User.DoesNotExist as exc:
            raise serializers.ValidationError({"user_id": "User not found."}) from exc

        if user.role != "admin":
            raise serializers.ValidationError(
                {"user_id": "User must have the admin role."}
            )

        try:
            branch = Branch.objects.get(pk=attrs["branch_id"], is_deleted=False)
        except Branch.DoesNotExist as exc:
            raise serializers.ValidationError({"branch_id": "Branch not found."}) from exc

        if not branch.is_active:
            raise serializers.ValidationError({"branch_id": "Branch is not active."})

        if AdminBranch.objects.filter(user=user).exclude(branch=branch).exists():
            raise serializers.ValidationError(
                {"user_id": "Admin is already assigned to another branch."}
            )

        attrs["user"] = user
        attrs["branch"] = branch
        return attrs
