"""Serializers for support tickets and contact inquiries."""

from __future__ import annotations

from rest_framework import serializers

from branches.models import Branch
from support.models import ContactInquiry, SupportTicket


class SupportTicketSerializer(serializers.ModelSerializer):
    hotel_id = serializers.UUIDField(source="branch_id", read_only=True, allow_null=True)
    created_by_name = serializers.CharField(source="created_by.name", read_only=True)

    class Meta:
        model = SupportTicket
        fields = (
            "id",
            "hotel_id",
            "subject",
            "description",
            "guest_name",
            "category",
            "booking_reference",
            "status",
            "priority",
            "created_by_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_by_name", "created_at", "updated_at")


class SupportTicketCreateSerializer(serializers.Serializer):
    subject = serializers.CharField(min_length=3, max_length=300)
    description = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    guest_name = serializers.CharField(required=False, allow_blank=True, max_length=200)
    category = serializers.CharField(required=False, allow_blank=True, max_length=80)
    booking_reference = serializers.CharField(required=False, allow_blank=True, max_length=64)
    priority = serializers.ChoiceField(
        choices=SupportTicket.Priority.choices,
        default=SupportTicket.Priority.MEDIUM,
    )
    hotel_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_hotel_id(self, value):
        if value is None:
            return None
        try:
            return Branch.objects.get(pk=value, is_deleted=False, is_active=True)
        except Branch.DoesNotExist:
            raise serializers.ValidationError("Invalid branch.", code="INVALID_BRANCH")


class SupportTicketStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=SupportTicket.Status.choices)


class ContactInquirySerializer(serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=200)
    email = serializers.EmailField()
    message = serializers.CharField(min_length=10, max_length=5000)
    hotel_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_hotel_id(self, value):
        if value is None:
            return None
        try:
            return Branch.objects.get(pk=value, is_deleted=False)
        except Branch.DoesNotExist:
            raise serializers.ValidationError("Invalid guest house.", code="INVALID_BRANCH")

    def create(self, validated_data):
        branch = validated_data.pop("hotel_id", None)
        inquiry_type = (
            ContactInquiry.InquiryType.BRANCH
            if branch
            else ContactInquiry.InquiryType.GENERAL
        )
        return ContactInquiry.objects.create(
            name=validated_data["name"],
            email=validated_data["email"],
            message=validated_data["message"],
            branch=branch,
            inquiry_type=inquiry_type,
        )
