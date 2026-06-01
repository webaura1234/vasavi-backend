"""Property / room serializers."""

from __future__ import annotations

from datetime import date

from rest_framework import serializers

from branches.serializers import BranchSerializer
from properties.image_utils import absolute_media_url
from properties.models import Room, RoomImage, RoomType
from utils.money import paise_to_rupees_display


class RoomImagePublicSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    url = serializers.SerializerMethodField()

    class Meta:
        model = RoomImage
        fields = ("id", "url", "caption", "is_primary", "sort_order")
        read_only_fields = fields

    def get_url(self, obj: RoomImage) -> str | None:
        return absolute_media_url(self.context.get("request"), obj.image)


class RoomTypeSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)

    class Meta:
        model = RoomType
        fields = ("id", "name", "description")
        read_only_fields = ("id",)


class RoomSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    branch = BranchSerializer(read_only=True)
    room_type = RoomTypeSerializer(read_only=True)
    base_price_display = serializers.SerializerMethodField()
    images = RoomImagePublicSerializer(many=True, read_only=True)

    class Meta:
        model = Room
        fields = (
            "id",
            "branch",
            "room_number",
            "room_type",
            "capacity",
            "base_price_per_night",
            "base_price_display",
            "is_donor_exclusive",
            "is_active",
            "images",
        )
        read_only_fields = ("id",)

    def get_base_price_display(self, obj: Room) -> str:
        return paise_to_rupees_display(obj.base_price_per_night)


class RoomWriteSerializer(serializers.ModelSerializer):
    branch_id = serializers.UUIDField(write_only=True)
    room_type_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = Room
        fields = (
            "branch_id",
            "room_type_id",
            "room_number",
            "capacity",
            "base_price_per_night",
            "is_donor_exclusive",
            "is_active",
        )

    def create(self, validated_data):
        from branches.models import Branch

        branch = Branch.objects.get(pk=validated_data.pop("branch_id"))
        room_type = RoomType.objects.get(pk=validated_data.pop("room_type_id"))
        return Room.objects.create(
            branch=branch,
            room_type=room_type,
            **validated_data,
        )


class RoomSearchSerializer(serializers.Serializer):
    branch_id = serializers.UUIDField(required=False)
    check_in = serializers.DateField()
    check_out = serializers.DateField()
    guests = serializers.IntegerField(default=1, min_value=1)
    donor_exclusive = serializers.BooleanField(default=False)

    def validate(self, attrs):
        check_in = attrs["check_in"]
        check_out = attrs["check_out"]
        if check_out <= check_in:
            raise serializers.ValidationError(
                {"check_out": "Check-out must be after check-in."}
            )
        if check_in < date.today():
            raise serializers.ValidationError(
                {"check_in": "Check-in cannot be in the past."}
            )
        nights = (check_out - check_in).days
        if nights > 30:
            raise serializers.ValidationError(
                {"check_out": "Maximum stay is 30 nights."}
            )
        attrs["nights"] = nights
        return attrs


class RoomAvailabilitySerializer(RoomSerializer):
    is_available = serializers.BooleanField(read_only=True)
    unavailable_reason = serializers.CharField(read_only=True, allow_null=True)

    class Meta(RoomSerializer.Meta):
        fields = RoomSerializer.Meta.fields + ("is_available", "unavailable_reason")
