"""Serializers for accounts / authentication API."""

from __future__ import annotations

from rest_framework import serializers

from accounts.models import User
from utils.phone import is_valid_indian_phone, normalize_indian_phone


class OTPSendSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=15)

    def validate_phone(self, value: str) -> str:
        if not is_valid_indian_phone(value):
            raise serializers.ValidationError(
                "Enter a valid 10-digit Indian mobile number.",
                code="INVALID_PHONE",
            )
        return normalize_indian_phone(value)


class OTPVerifySerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=15)
    otp = serializers.CharField(max_length=6, min_length=6)

    def validate_phone(self, value: str) -> str:
        if not is_valid_indian_phone(value):
            raise serializers.ValidationError(
                "Enter a valid 10-digit Indian mobile number.",
                code="INVALID_PHONE",
            )
        return normalize_indian_phone(value)

    def validate_otp(self, value: str) -> str:
        otp = value.strip()
        if len(otp) != 6 or not otp.isdigit():
            raise serializers.ValidationError(
                "OTP must be exactly 6 digits.",
                code="INVALID_OTP",
            )
        return otp


class UserProfileSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "phone",
            "name",
            "role",
            "is_first_login",
            "date_joined",
        )
        read_only_fields = fields


class ProfileConfirmSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=200)


class RegistrationSerializer(serializers.Serializer):
    registration_token = serializers.CharField()
    name = serializers.CharField(min_length=2, max_length=200)


class StaffProfileSerializer(UserProfileSerializer):
    branch = serializers.SerializerMethodField()

    class Meta(UserProfileSerializer.Meta):
        fields = UserProfileSerializer.Meta.fields + ("branch",)

    def get_branch(self, obj: User):
        from branches.serializers import BranchSerializer

        try:
            assignment = obj.admin_branch
        except Exception:
            return None
        return BranchSerializer(assignment.branch).data
