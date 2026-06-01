"""Serializers for staff portal authentication."""

from __future__ import annotations

from rest_framework import serializers

from accounts.models import AdminBranch, User
from utils.phone import is_valid_indian_phone, normalize_indian_phone


def _staff_validation_error(code: str, message: str) -> serializers.ValidationError:
    """Raise a validation error with a machine-readable code for the exception handler."""
    return serializers.ValidationError({"code": code, "message": message})


# SECURITY: PHONE_NOT_REGISTERED confirms the number exists in our system.
# Acceptable on this staff-only endpoint (not exposed on the public main-site flow).


class StaffOTPSendSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=15)

    def validate_phone(self, value: str) -> str:
        if not is_valid_indian_phone(value):
            raise _staff_validation_error(
                "INVALID_PHONE",
                "Enter a valid 10-digit Indian mobile number.",
            )
        return normalize_indian_phone(value)

    def validate(self, attrs):
        """Staff eligibility — raised at object level so error codes surface correctly."""
        phone = attrs["phone"]
        user = User.objects.filter(phone=phone, is_deleted=False).first()

        if not user or not user.is_active:
            raise _staff_validation_error(
                "PHONE_NOT_REGISTERED",
                "This number is not registered as a staff account. "
                "Contact your administrator.",
            )

        if user.role not in ("admin", "super_admin"):
            raise _staff_validation_error(
                "ACCESS_DENIED",
                "This portal is for staff only. Please use the main site to login.",
            )

        return attrs


class StaffOTPVerifySerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=15)
    otp = serializers.CharField(max_length=6, min_length=6)

    def validate_phone(self, value: str) -> str:
        if not is_valid_indian_phone(value):
            raise _staff_validation_error(
                "INVALID_PHONE",
                "Enter a valid 10-digit Indian mobile number.",
            )
        return normalize_indian_phone(value)

    def validate_otp(self, value: str) -> str:
        otp = value.strip()
        if len(otp) != 6 or not otp.isdigit():
            raise _staff_validation_error("INVALID_OTP", "OTP must be exactly 6 digits.")
        return otp


ADMIN_PERMISSIONS = [
    "rooms.view",
    "rooms.create",
    "rooms.update",
    "halls.view",
    "halls.create",
    "halls.update",
    "halls.manage_status",
    "halls.manage_images",
    "bookings.view",
    "bookings.create",
    "bookings.update_status",
    "bookings.cancel",
    "checkin.manage",
    "donors.verify",
    "extensions.view",
    "extensions.manage",
]

SUPER_ADMIN_PERMISSIONS = [
    "rooms.view",
    "rooms.create",
    "rooms.update",
    "halls.view",
    "halls.create",
    "halls.update",
    "halls.manage_status",
    "halls.manage_images",
    "bookings.view",
    "bookings.create",
    "bookings.update_status",
    "bookings.cancel",
    "checkin.manage",
    "donors.view",
    "donors.create",
    "donors.update",
    "coupons.view",
    "coupons.create",
    "coupons.dispatch",
    "coupons.redeem",
    "branches.view",
    "branches.create",
    "branches.update",
    "branches.assign_admin",
    "branches.revoke_admin",
    "donations.view",
    "donations.create",
    "extensions.view",
    "extensions.manage",
    "analytics.view",
]


class StaffMeSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    branch = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "phone",
            "name",
            "role",
            "is_active",
            "date_joined",
            "branch",
            "permissions",
        )
        read_only_fields = ("id", "phone", "role", "is_active", "date_joined")

    def get_branch(self, obj: User) -> dict | None:
        if obj.role != "admin":
            return None
        try:
            assignment = AdminBranch.objects.select_related("branch").get(user=obj)
        except AdminBranch.DoesNotExist:
            return None
        branch = assignment.branch
        return {
            "id": str(branch.id),
            "name": branch.name,
            "city": branch.city,
            "address": branch.address,
            "phone": branch.phone,
        }

    def get_permissions(self, obj: User) -> list[str]:
        if obj.role == "super_admin":
            return list(SUPER_ADMIN_PERMISSIONS)
        if obj.role == "admin":
            return list(ADMIN_PERMISSIONS)
        return []


class StaffMeUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=200)

class StaffManagementSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    phone = serializers.CharField(max_length=15)
    email = serializers.EmailField(required=False, allow_blank=True)

    def validate_phone(self, value: str) -> str:
        if not is_valid_indian_phone(value):
            raise serializers.ValidationError("Enter a valid 10-digit Indian mobile number.")
        return normalize_indian_phone(value)
