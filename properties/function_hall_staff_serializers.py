"""Staff portal function hall management serializers."""

from __future__ import annotations

from rest_framework import serializers

from accounts.models import AdminBranch
from bookings.models import Booking
from branches.models import Branch
from properties.image_utils import absolute_media_url
from properties.models import FunctionHall, FunctionHallImage
from properties.staff_serializers import _branch_for_staff


class FunctionHallImageStaffSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    url = serializers.SerializerMethodField()

    class Meta:
        model = FunctionHallImage
        fields = ("id", "url", "caption", "is_primary", "sort_order")
        read_only_fields = fields

    def get_url(self, obj: FunctionHallImage) -> str | None:
        return absolute_media_url(self.context.get("request"), obj.image)


class StaffFunctionHallDetailSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    branch = serializers.SerializerMethodField()
    base_price_display = serializers.SerializerMethodField()
    images = FunctionHallImageStaffSerializer(many=True, read_only=True)
    booking_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = FunctionHall
        fields = (
            "id",
            "branch",
            "name",
            "capacity",
            "base_price_per_day",
            "base_price_display",
            "is_active",
            "operational_status",
            "description",
            "amenities",
            "images",
            "booking_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_branch(self, obj: FunctionHall) -> dict:
        return {
            "id": str(obj.branch_id),
            "name": obj.branch.name,
            "city": obj.branch.city,
            "address": obj.branch.address,
            "phone": obj.branch.phone,
        }

    def get_base_price_display(self, obj: FunctionHall) -> str:
        from utils.money import paise_to_rupees_display

        return paise_to_rupees_display(obj.base_price_per_day)


class StaffFunctionHallCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    capacity = serializers.IntegerField(min_value=1, max_value=500)
    base_price_per_day = serializers.IntegerField(min_value=0)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    amenities = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
    )

    def validate_capacity(self, value: int) -> int:
        if value < 1 or value > 500:
            raise serializers.ValidationError("Capacity must be between 1 and 500.")
        return value

    def validate_base_price_per_day(self, value: int) -> int:
        if value < 0:
            raise serializers.ValidationError("Price cannot be negative.")
        return value

    def validate(self, attrs):
        branch = self.context.get("branch")
        if branch is None:
            raise serializers.ValidationError(
                {"branch": "Branch context is required to create a function hall."}
            )
        if FunctionHall.objects.filter(branch=branch, is_deleted=False).exists():
            raise serializers.ValidationError(
                "This branch already has an active function hall.",
                code="hall_exists",
            )
        return attrs

    def create(self, validated_data):
        branch = self.context["branch"]
        return FunctionHall.objects.create(branch=branch, **validated_data)


class StaffFunctionHallUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    capacity = serializers.IntegerField(min_value=1, max_value=500, required=False)
    base_price_per_day = serializers.IntegerField(min_value=0, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    amenities = serializers.ListField(
        child=serializers.CharField(),
        required=False,
    )
    is_active = serializers.BooleanField(required=False)

    def update(self, instance: FunctionHall, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        return instance


class StaffFunctionHallOperationalStatusSerializer(serializers.Serializer):
    operational_status = serializers.ChoiceField(
        choices=("available", "blocked", "maintenance"),
    )
    reason = serializers.CharField(required=False, allow_blank=True, write_only=True)

    def validate_operational_status(self, value: str) -> str:
        hall = self.context["hall"]
        if value in ("blocked", "maintenance"):
            if Booking.objects.filter(
                function_hall=hall,
                status=Booking.Status.CHECKED_IN,
                is_deleted=False,
            ).exists():
                raise serializers.ValidationError(
                    "Cannot block or mark maintenance while a guest is checked in. "
                    "Check the guest out first."
                )
        return value

    def save(self) -> FunctionHall:
        hall: FunctionHall = self.context["hall"]
        hall.operational_status = self.validated_data["operational_status"]
        hall.save(update_fields=["operational_status", "updated_at"])
        return hall


def resolve_branch_for_hall_staff(user, branch_id_param: str | None = None) -> Branch | None:
    """Resolve branch for hall create — admin uses assignment; super admin uses param."""
    if user.role == "admin":
        return _branch_for_staff(user)
    if not branch_id_param:
        return None
    try:
        return Branch.objects.get(pk=branch_id_param, is_deleted=False)
    except Branch.DoesNotExist:
        return None
