"""Public function hall serializers."""

from __future__ import annotations

from datetime import date

from rest_framework import serializers

from branches.models import Branch
from properties.image_utils import absolute_media_url
from properties.models import FunctionHall, FunctionHallImage
from utils.money import paise_to_rupees_display


class FunctionHallImageSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    image = serializers.SerializerMethodField()

    class Meta:
        model = FunctionHallImage
        fields = ("id", "image", "is_primary")
        read_only_fields = fields

    def get_image(self, obj: FunctionHallImage) -> str | None:
        return absolute_media_url(self.context.get("request"), obj.image)


class FunctionHallSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    branch = serializers.SerializerMethodField()
    base_price_display = serializers.SerializerMethodField()
    images = FunctionHallImageSerializer(many=True, read_only=True)

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
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_branch(self, obj: FunctionHall) -> dict:
        return {
            "id": str(obj.branch_id),
            "name": obj.branch.name,
        }

    def get_base_price_display(self, obj: FunctionHall) -> str:
        return paise_to_rupees_display(obj.base_price_per_day)


class FunctionHallWriteSerializer(serializers.ModelSerializer):
    branch_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = FunctionHall
        fields = (
            "branch_id",
            "name",
            "capacity",
            "base_price_per_day",
            "description",
            "amenities",
        )

    def validate_branch_id(self, value):
        try:
            branch = Branch.objects.get(pk=value, is_deleted=False)
        except Branch.DoesNotExist as exc:
            raise serializers.ValidationError("Branch not found.") from exc
        if FunctionHall.objects.filter(branch=branch, is_deleted=False).exists():
            raise serializers.ValidationError(
                "This branch already has an active function hall.",
                code="hall_exists",
            )
        return value

    def create(self, validated_data):
        branch_id = validated_data.pop("branch_id")
        branch = Branch.objects.get(pk=branch_id)
        return FunctionHall.objects.create(branch=branch, **validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("branch_id", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


class FunctionHallSearchSerializer(serializers.Serializer):
    branch_id = serializers.UUIDField(required=True)
    check_in_date = serializers.DateField()
    check_out_date = serializers.DateField()
    guests = serializers.IntegerField(default=1, min_value=1, required=False)

    def validate(self, attrs):
        check_in = attrs["check_in_date"]
        check_out = attrs["check_out_date"]
        if check_out <= check_in:
            raise serializers.ValidationError(
                {"check_out_date": "Check-out must be after check-in."}
            )
        if check_in < date.today():
            raise serializers.ValidationError(
                {"check_in_date": "Check-in cannot be in the past."}
            )
        days = (check_out - check_in).days
        if days > 30:
            raise serializers.ValidationError(
                {"check_out_date": "Maximum stay is 30 days."}
            )
        return attrs


class FunctionHallAvailabilitySerializer(FunctionHallSerializer):
    is_available = serializers.BooleanField(read_only=True)

    class Meta(FunctionHallSerializer.Meta):
        fields = FunctionHallSerializer.Meta.fields + ("is_available",)
