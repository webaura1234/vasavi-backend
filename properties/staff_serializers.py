"""Staff portal room management serializers."""

from __future__ import annotations

from rest_framework import serializers

from accounts.models import AdminBranch
from branches.models import Branch
from properties.models import Room, RoomImage, RoomType


def _branch_for_staff(user):
    if user.role == "admin":
        try:
            return user.admin_branch.branch
        except AdminBranch.DoesNotExist:
            return None
    return None


class RoomImageSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    url = serializers.SerializerMethodField()

    class Meta:
        model = RoomImage
        fields = ("id", "url", "caption", "is_primary", "sort_order")
        read_only_fields = fields

    def get_url(self, obj: RoomImage) -> str | None:
        if not obj.image:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url


class StaffRoomSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    branch = serializers.SerializerMethodField()
    room_type = serializers.SerializerMethodField()
    base_price_display = serializers.SerializerMethodField()
    images = RoomImageSerializer(many=True, read_only=True)

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
            "operational_status",
            "description",
            "images",
        )
        read_only_fields = fields

    def get_branch(self, obj: Room) -> dict:
        return {
            "id": str(obj.branch_id),
            "name": obj.branch.name,
            "city": obj.branch.city,
        }

    def get_room_type(self, obj: Room) -> dict:
        return {
            "id": str(obj.room_type_id),
            "name": obj.room_type.name,
        }

    def get_base_price_display(self, obj: Room) -> str:
        from utils.money import paise_to_rupees_display

        return paise_to_rupees_display(obj.base_price_per_night)


class StaffRoomCreateSerializer(serializers.Serializer):
    branch_id = serializers.UUIDField(required=False)
    room_type_id = serializers.UUIDField()
    room_number = serializers.CharField(max_length=50)
    capacity = serializers.IntegerField(min_value=1, max_value=20)
    base_price_per_night = serializers.IntegerField(min_value=0)
    is_donor_exclusive = serializers.BooleanField(default=False)
    is_active = serializers.BooleanField(default=True)
    operational_status = serializers.ChoiceField(
        choices=("available", "blocked", "maintenance"),
        default="available",
    )
    description = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        request = self.context["request"]
        staff = request.user
        branch_id = attrs.get("branch_id")

        if staff.role == "admin":
            assigned = _branch_for_staff(staff)
            if not assigned:
                raise serializers.ValidationError(
                    {"branch_id": "Your account is not assigned to a branch."}
                )
            if branch_id and str(branch_id) != str(assigned.id):
                raise serializers.ValidationError(
                    {"branch_id": "You can only create rooms at your assigned branch."}
                )
            attrs["branch"] = assigned
        else:
            if not branch_id:
                raise serializers.ValidationError(
                    {"branch_id": "Branch is required."}
                )
            try:
                attrs["branch"] = Branch.objects.get(
                    pk=branch_id, is_deleted=False
                )
            except Branch.DoesNotExist as exc:
                raise serializers.ValidationError(
                    {"branch_id": "Branch not found."}
                ) from exc

        try:
            attrs["room_type"] = RoomType.objects.get(pk=attrs["room_type_id"])
        except RoomType.DoesNotExist as exc:
            raise serializers.ValidationError(
                {"room_type_id": "Room type not found."}
            ) from exc

        branch = attrs["branch"]
        room_number = attrs["room_number"].strip()
        if Room.objects.filter(
            branch=branch,
            room_number=room_number,
            is_deleted=False,
        ).exists():
            raise serializers.ValidationError(
                {"room_number": "A room with this number already exists at this branch."}
            )
        attrs["room_number"] = room_number
        return attrs

    def create(self, validated_data):
        return Room.objects.create(
            branch=validated_data["branch"],
            room_type=validated_data["room_type"],
            room_number=validated_data["room_number"],
            capacity=validated_data["capacity"],
            base_price_per_night=validated_data["base_price_per_night"],
            is_donor_exclusive=validated_data.get("is_donor_exclusive", False),
            is_active=validated_data.get("is_active", True),
            operational_status=validated_data.get("operational_status", "available"),
            description=validated_data.get("description", ""),
        )


class StaffRoomUpdateSerializer(serializers.Serializer):
    room_type_id = serializers.UUIDField(required=False)
    room_number = serializers.CharField(max_length=50, required=False)
    capacity = serializers.IntegerField(min_value=1, max_value=20, required=False)
    base_price_per_night = serializers.IntegerField(min_value=0, required=False)
    is_donor_exclusive = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)
    operational_status = serializers.ChoiceField(
        choices=("available", "blocked", "maintenance"),
        required=False,
    )
    description = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        room = self.context["room"]
        if "room_number" in attrs:
            number = attrs["room_number"].strip()
            if (
                Room.objects.filter(
                    branch=room.branch,
                    room_number=number,
                    is_deleted=False,
                )
                .exclude(pk=room.pk)
                .exists()
            ):
                raise serializers.ValidationError(
                    {"room_number": "Another room already uses this number."}
                )
            attrs["room_number"] = number
        if "room_type_id" in attrs:
            try:
                attrs["room_type"] = RoomType.objects.get(pk=attrs["room_type_id"])
            except RoomType.DoesNotExist as exc:
                raise serializers.ValidationError(
                    {"room_type_id": "Room type not found."}
                ) from exc
        return attrs

    def update(self, instance: Room, validated_data):
        if "room_type" in validated_data:
            instance.room_type = validated_data["room_type"]
        for field in (
            "room_number",
            "capacity",
            "base_price_per_night",
            "is_donor_exclusive",
            "is_active",
            "operational_status",
            "description",
        ):
            if field in validated_data:
                setattr(instance, field, validated_data[field])
        instance.save()
        return instance
