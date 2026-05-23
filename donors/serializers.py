"""Donor serializers."""

from __future__ import annotations

import random
import string

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import serializers

from accounts.models import ProfileConfirmation, User
from accounts.serializers import UserProfileSerializer
from branches.serializers import BranchSerializer
from coupons.models import Coupon
from donors.models import (
    Donation,
    DonationPurpose,
    DonorProfile,
    MembershipTier,
    ReceiptNumber,
)
from utils.money import paise_to_rupees_display
from utils.phone import is_valid_indian_phone, normalize_indian_phone


class MembershipTierSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)

    class Meta:
        model = MembershipTier
        fields = ("id", "name")
        read_only_fields = ("id",)


class DonationPurposeSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)

    class Meta:
        model = DonationPurpose
        fields = ("id", "name")
        read_only_fields = ("id",)


class ReceiptNumberSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)

    class Meta:
        model = ReceiptNumber
        fields = ("id", "receipt_number", "created_at")
        read_only_fields = ("id", "receipt_number", "created_at")


class DonationSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    donor = serializers.SerializerMethodField()
    amount_paise = serializers.IntegerField(source="amount")
    amount_display = serializers.SerializerMethodField()
    purpose = DonationPurposeSerializer(read_only=True)
    receipts = ReceiptNumberSerializer(source="receipt_numbers", many=True, read_only=True)
    created_by = UserProfileSerializer(read_only=True)

    class Meta:
        model = Donation
        fields = (
            "id",
            "donor",
            "amount_paise",
            "amount_display",
            "purpose",
            "receipts",
            "dispatch_date",
            "dispatch_method",
            "dispatch_notes",
            "created_by",
            "created_at",
        )
        read_only_fields = fields

    def get_donor(self, obj: Donation) -> dict:
        return UserProfileSerializer(obj.donor.user).data

    def get_amount_display(self, obj: Donation) -> str:
        return paise_to_rupees_display(obj.amount)


class DonationCreateSerializer(serializers.Serializer):
    donor_id = serializers.UUIDField()
    amount_paise = serializers.IntegerField(min_value=1)
    purpose_id = serializers.UUIDField()
    receipt_numbers = serializers.ListField(
        child=serializers.CharField(max_length=50),
        allow_empty=False,
    )
    dispatch_date = serializers.DateField(required=False, allow_null=True)
    dispatch_method = serializers.CharField(required=False, allow_blank=True)
    dispatch_notes = serializers.CharField(required=False, allow_blank=True)

    def validate_donor_id(self, value):
        try:
            user = User.objects.get(pk=value, role="donor", is_deleted=False)
        except User.DoesNotExist as exc:
            raise serializers.ValidationError("Donor user not found.") from exc
        try:
            return DonorProfile.objects.get(user=user, is_deleted=False)
        except DonorProfile.DoesNotExist as exc:
            raise serializers.ValidationError("Donor profile not found.") from exc

    def validate_purpose_id(self, value):
        try:
            return DonationPurpose.objects.get(pk=value, is_active=True)
        except DonationPurpose.DoesNotExist as exc:
            raise serializers.ValidationError("Purpose not found.") from exc

    def create(self, validated_data):
        request = self.context["request"]
        donor_profile = validated_data["donor_id"]
        purpose = validated_data["purpose_id"]
        receipts = validated_data["receipt_numbers"]

        with transaction.atomic():
            donation = Donation.objects.create(
                donor=donor_profile,
                amount=validated_data["amount_paise"],
                purpose=purpose,
                dispatch_date=validated_data.get("dispatch_date"),
                dispatch_method=validated_data.get("dispatch_method", ""),
                dispatch_notes=validated_data.get("dispatch_notes", ""),
                created_by=request.user,
            )
            ReceiptNumber.objects.bulk_create(
                [
                    ReceiptNumber(donation=donation, receipt_number=num.strip())
                    for num in receipts
                    if num.strip()
                ]
            )
        return donation


class DonorProfileSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    phone = serializers.CharField(source="user.phone", read_only=True)
    name = serializers.CharField(source="user.name", read_only=True)
    tier = MembershipTierSerializer(source="membership_tier", read_only=True)
    for_place = BranchSerializer(read_only=True)
    total_donated_paise = serializers.SerializerMethodField()
    total_donated_display = serializers.SerializerMethodField()
    available_coupons_count = serializers.SerializerMethodField()
    used_coupons_count = serializers.SerializerMethodField()
    date_joined = serializers.DateTimeField(source="user.date_joined", read_only=True)

    class Meta:
        model = DonorProfile
        fields = (
            "id",
            "phone",
            "name",
            "donor_id",
            "tier",
            "district_code",
            "club_name",
            "for_place",
            "total_donated_paise",
            "total_donated_display",
            "available_coupons_count",
            "used_coupons_count",
            "date_joined",
        )
        read_only_fields = fields

    def get_total_donated_paise(self, obj: DonorProfile) -> int:
        total = obj.donations.aggregate(total=Sum("amount"))["total"]
        return int(total or 0)

    def get_total_donated_display(self, obj: DonorProfile) -> str:
        return paise_to_rupees_display(self.get_total_donated_paise(obj))

    def get_available_coupons_count(self, obj: DonorProfile) -> int:
        user = obj.user
        return (
            Coupon.objects.filter(
                status=Coupon.Status.DISPATCHED,
                is_deleted=False,
            )
            .annotate(assigned_count=Count("assigned_donors"))
            .filter(Q(assigned_count=0) | Q(assigned_donors=user))
            .distinct()
            .count()
        )

    def get_used_coupons_count(self, obj: DonorProfile) -> int:
        return Coupon.objects.filter(
            redeemed_by=obj.user,
            status=Coupon.Status.REDEEMED,
            is_deleted=False,
        ).count()


def _generate_donor_id() -> str:
    year = timezone.now().year
    digits = "".join(random.choices(string.digits, k=5))
    candidate = f"VCI-{year}-{digits}"
    while DonorProfile.all_objects.filter(donor_id=candidate).exists():
        digits = "".join(random.choices(string.digits, k=5))
        candidate = f"VCI-{year}-{digits}"
    return candidate


class DonorCreateSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=15)
    name = serializers.CharField(min_length=2, max_length=200)
    donor_id = serializers.CharField(max_length=30, required=False, allow_blank=True)
    tier_id = serializers.UUIDField()
    district_code = serializers.CharField(required=False, allow_blank=True)
    club_name = serializers.CharField(required=False, allow_blank=True)
    for_place_id = serializers.UUIDField()

    def validate_phone(self, value):
        if not is_valid_indian_phone(value):
            raise serializers.ValidationError("Invalid phone number.")
        phone = normalize_indian_phone(value)
        if User.objects.filter(phone=phone).exists():
            raise serializers.ValidationError("Phone is already registered.")
        return phone

    def validate_tier_id(self, value):
        try:
            return MembershipTier.objects.get(pk=value, is_active=True)
        except MembershipTier.DoesNotExist as exc:
            raise serializers.ValidationError("Tier not found.") from exc

    def validate_for_place_id(self, value):
        from branches.models import Branch

        try:
            branch = Branch.objects.get(pk=value, is_deleted=False, is_active=True)
        except Branch.DoesNotExist as exc:
            raise serializers.ValidationError("Branch not found.") from exc
        return branch

    def create(self, validated_data):
        donor_id = (validated_data.get("donor_id") or "").strip() or _generate_donor_id()
        if DonorProfile.all_objects.filter(donor_id=donor_id).exists():
            raise serializers.ValidationError({"donor_id": "Donor ID already exists."})

        with transaction.atomic():
            user = User.objects.create_user(
                phone=validated_data["phone"],
                name=validated_data["name"],
                role="donor",
            )
            ProfileConfirmation.objects.create(
                user=user,
                is_confirmed=True,
                confirmed_at=timezone.now(),
            )
            profile = DonorProfile.objects.create(
                user=user,
                donor_id=donor_id,
                membership_tier=validated_data["tier_id"],
                district_code=validated_data.get("district_code", ""),
                club_name=validated_data.get("club_name", ""),
                for_place=validated_data["for_place_id"],
            )
        return profile


class DonorListSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    phone = serializers.CharField(source="user.phone", read_only=True)
    name = serializers.CharField(source="user.name", read_only=True)
    tier = serializers.CharField(source="membership_tier.name", read_only=True)
    city = serializers.SerializerMethodField()

    class Meta:
        model = DonorProfile
        fields = (
            "id",
            "phone",
            "name",
            "donor_id",
            "tier",
            "club_name",
            "city",
            "date_joined",
        )
        read_only_fields = fields

    def get_city(self, obj: DonorProfile) -> str:
        return obj.for_place.city if obj.for_place else ""

    date_joined = serializers.DateTimeField(source="user.date_joined", read_only=True)


class DonorUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, min_length=2, max_length=200)
    tier_id = serializers.UUIDField(required=False)
    district_code = serializers.CharField(required=False, allow_blank=True)
    club_name = serializers.CharField(required=False, allow_blank=True)
    for_place_id = serializers.UUIDField(required=False)

    def validate_tier_id(self, value):
        try:
            return MembershipTier.objects.get(pk=value, is_active=True)
        except MembershipTier.DoesNotExist as exc:
            raise serializers.ValidationError("Tier not found.") from exc

    def validate_for_place_id(self, value):
        from branches.models import Branch

        try:
            return Branch.objects.get(pk=value, is_deleted=False, is_active=True)
        except Branch.DoesNotExist as exc:
            raise serializers.ValidationError("Branch not found.") from exc

    def update(self, instance, validated_data):
        tier = validated_data.get("tier_id")
        branch = validated_data.get("for_place_id")
        name = validated_data.get("name")

        if name is not None:
            instance.user.name = name
            instance.user.save(update_fields=["name", "updated_at"])

        if tier is not None:
            instance.membership_tier = tier
        if branch is not None:
            instance.for_place = branch

        for field in ("district_code", "club_name"):
            if field in validated_data:
                setattr(instance, field, validated_data[field])

        instance.save()
        return instance