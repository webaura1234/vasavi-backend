"""Booking serializers."""

from __future__ import annotations

import re
from datetime import date

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from accounts.serializers import UserProfileSerializer
from bookings.models import Booking, BookingStatusLog
from branches.serializers import BranchSerializer
from coupons.models import Coupon
from coupons.serializers import CouponSerializer
from properties.models import Room
from properties.serializers import RoomSerializer
from utils.money import paise_to_rupees_display


def _parse_concession_percent(extra_benefit: str) -> int:
    match = re.search(r"(\d+)\s*%", extra_benefit or "")
    if match:
        return min(100, max(0, int(match.group(1))))
    return 50


class BookingSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    user = UserProfileSerializer(read_only=True)
    room = RoomSerializer(read_only=True)
    branch = BranchSerializer(read_only=True)
    base_amount_display = serializers.SerializerMethodField()
    discount_display = serializers.SerializerMethodField()
    final_amount_display = serializers.SerializerMethodField()
    base_amount_paise = serializers.IntegerField(source="base_amount", read_only=True)
    discount_amount_paise = serializers.IntegerField(source="discount_amount", read_only=True)
    final_amount_paise = serializers.IntegerField(source="final_amount", read_only=True)
    coupons_applied = CouponSerializer(many=True, read_only=True)

    class Meta:
        model = Booking
        fields = (
            "id",
            "booking_reference",
            "user",
            "room",
            "branch",
            "check_in_date",
            "check_out_date",
            "nights",
            "guest_count",
            "guest_name",
            "guest_phone",
            "status",
            "base_amount_paise",
            "discount_amount_paise",
            "final_amount_paise",
            "base_amount_display",
            "discount_display",
            "final_amount_display",
            "payment_status",
            "payment_reference",
            "payment_gateway",
            "payment_paid_at",
            "coupons_applied",
            "notes",
            "cancelled_at",
            "cancellation_reason",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_base_amount_display(self, obj: Booking) -> str:
        return paise_to_rupees_display(obj.base_amount)

    def get_discount_display(self, obj: Booking) -> str:
        return paise_to_rupees_display(obj.discount_amount)

    def get_final_amount_display(self, obj: Booking) -> str:
        return paise_to_rupees_display(obj.final_amount)


class BookingCreateSerializer(serializers.Serializer):
    room_id = serializers.UUIDField()
    check_in_date = serializers.DateField()
    check_out_date = serializers.DateField()
    guest_count = serializers.IntegerField(default=1, min_value=1)
    guest_name = serializers.CharField(required=False, allow_blank=True)
    guest_phone = serializers.CharField(required=False, allow_blank=True)
    coupon_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
    )
    notes = serializers.CharField(required=False, allow_blank=True)

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
        nights = (check_out - check_in).days
        if nights > 30:
            raise serializers.ValidationError(
                {"check_out_date": "Maximum stay is 30 nights."}
            )
        attrs["nights"] = nights

        try:
            room = Room.objects.select_related("branch").get(
                pk=attrs["room_id"],
                is_deleted=False,
                is_active=True,
            )
        except Room.DoesNotExist as exc:
            raise serializers.ValidationError({"room_id": "Room not found."}) from exc
        attrs["room"] = room
        attrs["check_in"] = check_in
        attrs["check_out"] = check_out

        coupon_ids = attrs.get("coupon_ids") or []
        if len(coupon_ids) > 2:
            raise serializers.ValidationError(
                {"coupon_ids": "Maximum two coupons allowed per booking."}
            )

        request = self.context["request"]
        coupons = []
        types_seen = set()
        for coupon_id in coupon_ids:
            try:
                coupon = Coupon.objects.select_related("batch").get(pk=coupon_id)
            except Coupon.DoesNotExist as exc:
                raise serializers.ValidationError(
                    {"coupon_ids": f"Coupon {coupon_id} not found."}
                ) from exc
            if coupon.status != Coupon.Status.DISPATCHED:
                raise serializers.ValidationError(
                    {"coupon_ids": f"Coupon {coupon.serial_number} is not dispatched."}
                )
            if coupon.assigned_donors.exists() and not coupon.assigned_donors.filter(
                pk=request.user.pk
            ).exists():
                raise serializers.ValidationError(
                    {"coupon_ids": f"Coupon {coupon.serial_number} is not assigned to you."}
                )
            if coupon.coupon_type in types_seen:
                raise serializers.ValidationError(
                    {"coupon_ids": "Cannot apply two coupons of the same type."}
                )
            types_seen.add(coupon.coupon_type)
            coupons.append(coupon)

        attrs["coupons"] = coupons
        return attrs

    def _room_has_overlap(self, room: Room, check_in: date, check_out: date) -> bool:
        return Booking.objects.filter(
            room=room,
            status__in=[
                Booking.Status.PENDING,
                Booking.Status.CONFIRMED,
                Booking.Status.CHECKED_IN,
            ],
            check_in_date__lt=check_out,
            check_out_date__gt=check_in,
            is_deleted=False,
        ).exists()

    def create(self, validated_data):
        request = self.context["request"]
        room = validated_data["room"]
        check_in = validated_data["check_in"]
        check_out = validated_data["check_out"]
        nights = validated_data["nights"]
        coupons = validated_data.get("coupons", [])

        base_amount = room.base_price_per_night * nights
        discount_amount = 0
        final_amount = base_amount

        has_free = any(c.coupon_type == Coupon.CouponType.FREE for c in coupons)
        concession = next(
            (c for c in coupons if c.coupon_type == Coupon.CouponType.CONCESSION),
            None,
        )

        if has_free:
            discount_amount = base_amount
            final_amount = 0
        elif concession:
            percent = _parse_concession_percent(concession.batch.extra_benefit)
            discount_amount = (base_amount * percent) // 100
            final_amount = base_amount - discount_amount

        with transaction.atomic():
            # Lock room row to prevent concurrent double bookings for same dates.
            room = Room.objects.select_for_update().get(
                pk=room.pk,
                is_deleted=False,
                is_active=True,
            )
            if self._room_has_overlap(room, check_in, check_out):
                raise serializers.ValidationError(
                    {"room_id": "Room is not available for the selected dates."}
                )

            user = request.user
            guest_name = (validated_data.get("guest_name") or "").strip() or (
                user.name or ""
            )
            guest_phone = (validated_data.get("guest_phone") or "").strip() or (
                user.phone or ""
            )

            booking = Booking.objects.create(
                user=user,
                room=room,
                check_in_date=validated_data["check_in_date"],
                check_out_date=validated_data["check_out_date"],
                nights=nights,
                guest_count=validated_data.get("guest_count", 1),
                guest_name=guest_name,
                guest_phone=guest_phone,
                status=Booking.Status.PENDING,
                base_amount=base_amount,
                discount_amount=discount_amount,
                final_amount=final_amount,
                payment_status=Booking.PaymentStatus.UNPAID,
                notes=validated_data.get("notes", ""),
            )

            if coupons:
                now = timezone.now()
                locked_coupons = []
                for coupon in coupons:
                    locked = Coupon.objects.select_for_update().get(pk=coupon.pk)
                    if locked.status != Coupon.Status.DISPATCHED:
                        raise serializers.ValidationError(
                            {
                                "coupon_ids": (
                                    f"Coupon {locked.serial_number} is no longer available."
                                )
                            }
                        )
                    locked_coupons.append(locked)

                booking.coupons_applied.set(locked_coupons)
                booking.validate_coupons()
                for locked in locked_coupons:
                    locked.status = Coupon.Status.REDEEMED
                    locked.redeemed_by = request.user
                    locked.redeemed_at_booking = booking
                    locked.redeemed_at_branch = booking.branch
                    locked.redeemed_on = now
                    locked.save()

            BookingStatusLog.objects.create(
                booking=booking,
                from_status=Booking.Status.PENDING,
                to_status=Booking.Status.PENDING,
                changed_by=request.user,
                reason="Booking created",
            )

        return booking


class BookingStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Booking.Status.choices)
    reason = serializers.CharField(required=False, allow_blank=True)

    _ALLOWED = {
        Booking.Status.PENDING: {
            Booking.Status.CONFIRMED,
            Booking.Status.CANCELLED,
        },
        Booking.Status.CONFIRMED: {
            Booking.Status.CHECKED_IN,
            Booking.Status.CANCELLED,
            Booking.Status.NO_SHOW,
        },
        Booking.Status.CHECKED_IN: {Booking.Status.CHECKED_OUT},
        Booking.Status.CHECKED_OUT: set(),
        Booking.Status.CANCELLED: set(),
        Booking.Status.NO_SHOW: set(),
    }

    def validate(self, attrs):
        booking = self.context["booking"]
        new_status = attrs["status"]
        allowed = self._ALLOWED.get(booking.status, set())
        if new_status not in allowed:
            raise serializers.ValidationError(
                {
                    "status": (
                        f"Cannot transition from {booking.status} to {new_status}."
                    )
                }
            )
        if new_status == Booking.Status.CANCELLED and not attrs.get("reason"):
            raise serializers.ValidationError(
                {"reason": "Cancellation reason is required."}
            )
        return attrs


class BookingStatusLogSerializer(serializers.ModelSerializer):
    changed_by = UserProfileSerializer(read_only=True)
    from_status = serializers.CharField(source="from_status", read_only=True)
    to_status = serializers.CharField(source="to_status", read_only=True)
    timestamp = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = BookingStatusLog
        fields = ("from_status", "to_status", "changed_by", "reason", "timestamp")
        read_only_fields = fields


class PaymentOrderSerializer(serializers.Serializer):
    order_id = serializers.CharField(allow_null=True, required=False)
    amount_paise = serializers.IntegerField()
    currency = serializers.CharField(required=False)
    razorpay_key_id = serializers.CharField(required=False, allow_blank=True)
    booking_reference = serializers.CharField()


class CashPaymentSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, max_length=500)


class BookingExtendStaySerializer(serializers.Serializer):
    check_out_date = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate(self, attrs):
        booking = self.context["booking"]
        new_out = attrs["check_out_date"]
        if new_out <= booking.check_out_date:
            raise serializers.ValidationError(
                {"check_out_date": "New checkout must be after the current checkout."}
            )
        if new_out <= booking.check_in_date:
            raise serializers.ValidationError(
                {"check_out_date": "Checkout must be after check-in."}
            )
        nights = (new_out - booking.check_in_date).days
        if nights > 30:
            raise serializers.ValidationError(
                {"check_out_date": "Maximum stay is 30 nights."}
            )
        attrs["nights"] = nights
        return attrs
