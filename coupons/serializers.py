"""Coupon serializers."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import serializers

from accounts.serializers import UserProfileSerializer
from coupons.models import Coupon, CouponBatch
from donors.serializers import DonationSerializer


class CouponBatchSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    donation = DonationSerializer(read_only=True)

    class Meta:
        model = CouponBatch
        fields = (
            "id",
            "donation",
            "coupon_type",
            "serial_start",
            "serial_end",
            "count",
            "extra_benefit",
            "created_at",
        )
        read_only_fields = fields


class CouponBatchCreateSerializer(serializers.Serializer):
    donation_id = serializers.UUIDField()
    coupon_type = serializers.ChoiceField(choices=CouponBatch.CouponType.choices)
    serial_start = serializers.IntegerField(min_value=1)
    serial_end = serializers.IntegerField(min_value=1)
    extra_benefit = serializers.CharField(required=False, allow_blank=True)
    assigned_donor_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
    )

    def validate(self, attrs):
        from accounts.models import User
        from donors.models import Donation

        start = attrs["serial_start"]
        end = attrs["serial_end"]
        if end < start:
            raise serializers.ValidationError(
                {"serial_end": "serial_end must be >= serial_start."}
            )
        count = end - start + 1
        attrs["count"] = count

        if Coupon.objects.filter(
            serial_number__gte=start,
            serial_number__lte=end,
        ).exists():
            raise serializers.ValidationError(
                "Serial number range overlaps existing coupons."
            )

        try:
            attrs["donation"] = Donation.objects.get(pk=attrs["donation_id"])
        except Donation.DoesNotExist as exc:
            raise serializers.ValidationError({"donation_id": "Donation not found."}) from exc

        donor_ids = attrs.get("assigned_donor_ids") or []
        donors = []
        for donor_user_id in donor_ids:
            try:
                user = User.objects.get(pk=donor_user_id, role="donor")
            except User.DoesNotExist as exc:
                raise serializers.ValidationError(
                    {"assigned_donor_ids": f"Donor {donor_user_id} not found."}
                ) from exc
            donors.append(user)
        attrs["assigned_donors"] = donors
        return attrs

    def create(self, validated_data):
        assigned = validated_data.pop("assigned_donors", [])
        validated_data.pop("donation_id", None)
        donation = validated_data.pop("donation")
        count = validated_data.pop("count")

        with transaction.atomic():
            batch = CouponBatch.objects.create(
                donation=donation,
                coupon_type=validated_data["coupon_type"],
                serial_start=validated_data["serial_start"],
                serial_end=validated_data["serial_end"],
                count=count,
                extra_benefit=validated_data.get("extra_benefit", ""),
            )
            if assigned:
                for coupon in batch.coupons.all():
                    coupon.assigned_donors.set(assigned)
        return batch


class CouponSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    batch = CouponBatchSerializer(read_only=True)
    assigned_donors = UserProfileSerializer(many=True, read_only=True)
    redeemed_by = UserProfileSerializer(read_only=True)
    redeemed_at_booking_reference = serializers.SerializerMethodField()

    class Meta:
        model = Coupon
        fields = (
            "id",
            "serial_number",
            "coupon_type",
            "status",
            "batch",
            "assigned_donors",
            "redeemed_by",
            "redeemed_at_booking_reference",
            "redeemed_on",
            "created_at",
        )
        read_only_fields = fields

    def get_redeemed_at_booking_reference(self, obj: Coupon) -> str | None:
        if obj.redeemed_at_booking_id:
            return obj.redeemed_at_booking.booking_reference
        return None


class CouponStatsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    issued = serializers.IntegerField()
    dispatched = serializers.IntegerField()
    available = serializers.IntegerField()
    used = serializers.IntegerField()


class CouponWalletSerializer(serializers.Serializer):
    stats = CouponStatsSerializer()
    available = CouponSerializer(many=True)
    used = CouponSerializer(many=True)
    issued = CouponSerializer(many=True)


class CouponDispatchSerializer(serializers.Serializer):
    coupon_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)

    def validate_coupon_ids(self, value):
        coupons = list(
            Coupon.objects.filter(pk__in=value).select_related("batch")
        )
        if len(coupons) != len(value):
            raise serializers.ValidationError("One or more coupons not found.")
        batch_ids = {c.batch_id for c in coupons}
        if len(batch_ids) > 1:
            raise serializers.ValidationError("All coupons must belong to the same batch.")
        for coupon in coupons:
            if coupon.status != Coupon.Status.ISSUED:
                raise serializers.ValidationError(
                    f"Coupon {coupon.pk} is not in issued status."
                )
        return coupons


class CouponRedeemSerializer(serializers.Serializer):
    coupon_id = serializers.UUIDField()
    booking_id = serializers.UUIDField()

    def validate(self, attrs):
        from bookings.models import Booking

        request = self.context["request"]
        try:
            coupon = Coupon.objects.get(pk=attrs["coupon_id"])
        except Coupon.DoesNotExist as exc:
            raise serializers.ValidationError({"coupon_id": "Coupon not found."}) from exc

        if coupon.status != Coupon.Status.DISPATCHED:
            raise serializers.ValidationError(
                {"coupon_id": "Coupon must be in dispatched status."}
            )

        if coupon.assigned_donors.exists() and not coupon.assigned_donors.filter(
            pk=request.user.pk
        ).exists():
            raise serializers.ValidationError(
                {"coupon_id": "Coupon is not assigned to you."}
            )

        try:
            booking = Booking.objects.get(pk=attrs["booking_id"], user=request.user)
        except Booking.DoesNotExist as exc:
            raise serializers.ValidationError({"booking_id": "Booking not found."}) from exc

        if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED):
            raise serializers.ValidationError(
                {"booking_id": "Booking cannot accept coupons in this status."}
            )

        same_type = booking.coupons_applied.filter(coupon_type=coupon.coupon_type)
        if same_type.exists():
            raise serializers.ValidationError(
                {"coupon_id": "Booking already has a coupon of this type."}
            )

        attrs["coupon"] = coupon
        attrs["booking"] = booking
        return attrs
