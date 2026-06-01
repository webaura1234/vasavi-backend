"""Booking serializers."""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from accounts.serializers import UserProfileSerializer
from bookings.messages import status_transition_not_allowed
from bookings.models import Booking, BookingStatusLog
from bookings.services.availability import (
    check_availability_with_lock,
)
from bookings.services.pricing import compute_coupon_discount
from branches.serializers import BranchSerializer
from coupons.models import Coupon
from coupons.serializers import CouponSerializer
from properties.function_hall_serializers import FunctionHallSerializer
from properties.models import FunctionHall, Room
from properties.serializers import RoomSerializer
from utils.money import paise_to_rupees_display


class BookingSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    user = UserProfileSerializer(read_only=True)
    room = RoomSerializer(read_only=True)
    function_hall = FunctionHallSerializer(read_only=True)
    booking_kind = serializers.CharField(read_only=True)
    branch = BranchSerializer(read_only=True)
    base_amount_display = serializers.SerializerMethodField()
    discount_display = serializers.SerializerMethodField()
    final_amount_display = serializers.SerializerMethodField()
    base_amount_paise = serializers.IntegerField(source="base_amount", read_only=True)
    discount_amount_paise = serializers.IntegerField(source="discount_amount", read_only=True)
    final_amount_paise = serializers.IntegerField(source="final_amount", read_only=True)
    coupons_applied = CouponSerializer(many=True, read_only=True)
    is_cancellable_by_guest = serializers.BooleanField(read_only=True)
    needs_refund_approval = serializers.BooleanField(read_only=True)

    class Meta:
        model = Booking
        fields = (
            "id",
            "booking_reference",
            "user",
            "room",
            "function_hall",
            "booking_kind",
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
            "cancel_initiated_by_role",
            "refund_amount",
            "refund_reference",
            "refund_processed_at",
            "refund_reason",
            "refund_requested_at",
            "refund_requested_reason",
            "expires_at",
            "is_cancellable_by_guest",
            "needs_refund_approval",
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
    room_id = serializers.UUIDField(required=False)
    function_hall_id = serializers.UUIDField(required=False)
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

    def _validate_dates(self, attrs):
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
        attrs["check_in"] = check_in
        attrs["check_out"] = check_out
        return attrs

    def validate(self, attrs):
        has_room = bool(attrs.get("room_id"))
        has_hall = bool(attrs.get("function_hall_id"))
        if has_room == has_hall:
            raise serializers.ValidationError(
                "Provide exactly one of room_id or function_hall_id.",
                code="invalid_resource",
            )

        attrs = self._validate_dates(attrs)
        request = self.context["request"]
        guest_count = attrs.get("guest_count", 1)

        if has_room:
            try:
                room = Room.objects.select_related("branch").get(
                    pk=attrs["room_id"],
                    is_deleted=False,
                    is_active=True,
                )
            except Room.DoesNotExist as exc:
                raise serializers.ValidationError({"room_id": "Room not found."}) from exc

            if room.operational_status != "available":
                raise serializers.ValidationError(
                    {
                        "room_id": (
                            f"This room is currently {room.operational_status} "
                            "and cannot be booked."
                        )
                    }
                )

            if room.is_donor_exclusive and request.user.role not in (
                "donor",
                "admin",
                "super_admin",
            ):
                raise serializers.ValidationError(
                    {"room_id": "This room is reserved for donors only."}
                )

            if guest_count > room.capacity:
                raise serializers.ValidationError(
                    {
                        "guest_count": (
                            f"This room accommodates a maximum of {room.capacity} guest(s)."
                        )
                    }
                )

            attrs["room"] = room
            attrs["booking_kind"] = Booking.BookingKind.ROOM
        else:
            try:
                hall = FunctionHall.objects.select_related("branch").get(
                    pk=attrs["function_hall_id"],
                    is_deleted=False,
                    is_active=True,
                )
            except FunctionHall.DoesNotExist as exc:
                raise serializers.ValidationError(
                    {"function_hall_id": "Function hall not found."}
                ) from exc

            if hall.operational_status != "available":
                raise serializers.ValidationError(
                    {
                        "function_hall_id": (
                            f"This hall is currently {hall.operational_status} "
                            "and cannot be booked."
                        )
                    }
                )

            if guest_count > hall.capacity:
                raise serializers.ValidationError(
                    {
                        "guest_count": (
                            f"This hall accommodates a maximum of {hall.capacity} guest(s)."
                        )
                    }
                )

            attrs["function_hall"] = hall
            attrs["booking_kind"] = Booking.BookingKind.FUNCTION_HALL

        # --- Coupon validations ---------------------------------------------
        coupon_ids = attrs.get("coupon_ids") or []
        if len(coupon_ids) > 2:
            raise serializers.ValidationError(
                {"coupon_ids": "Maximum two coupons allowed per booking."}
            )

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

    def create(self, validated_data):
        request = self.context["request"]
        check_in = validated_data["check_in"]
        check_out = validated_data["check_out"]
        nights = validated_data["nights"]
        coupons = validated_data.get("coupons", [])
        booking_kind = validated_data["booking_kind"]

        user = request.user
        guest_name = (validated_data.get("guest_name") or "").strip() or (
            user.name or ""
        )
        guest_phone = (validated_data.get("guest_phone") or "").strip() or (
            user.phone or ""
        )

        common_booking_fields = {
            "user": user,
            "check_in_date": validated_data["check_in_date"],
            "check_out_date": validated_data["check_out_date"],
            "nights": nights,
            "guest_count": validated_data.get("guest_count", 1),
            "guest_name": guest_name,
            "guest_phone": guest_phone,
            "status": Booking.Status.PENDING,
            "payment_status": Booking.PaymentStatus.UNPAID,
            "notes": validated_data.get("notes", ""),
            "booking_kind": booking_kind,
        }

        with transaction.atomic():
            if booking_kind == Booking.BookingKind.ROOM:
                room = validated_data["room"]
                base_amount = room.base_price_per_night * nights
                discount_amount, final_amount = compute_coupon_discount(
                    base_amount, coupons
                )
                room = Room.objects.select_for_update().get(
                    pk=room.pk,
                    is_deleted=False,
                    is_active=True,
                )
                if not check_availability_with_lock(room, check_in, check_out):
                    raise serializers.ValidationError(
                        {"room_id": "Room is not available for the selected dates."}
                    )
                booking = Booking.objects.create(
                    room=room,
                    base_amount=base_amount,
                    discount_amount=discount_amount,
                    final_amount=final_amount,
                    **common_booking_fields,
                )
            else:
                hall = validated_data["function_hall"]
                base_amount = hall.base_price_per_day * nights
                discount_amount, final_amount = compute_coupon_discount(
                    base_amount, coupons
                )
                hall = FunctionHall.objects.select_for_update().get(
                    pk=hall.pk,
                    is_deleted=False,
                    is_active=True,
                )
                if not check_availability_with_lock(hall, check_in, check_out):
                    raise serializers.ValidationError(
                        {
                            "function_hall_id": (
                                "Function hall is not available for the selected dates."
                            )
                        }
                    )
                booking = Booking.objects.create(
                    function_hall=hall,
                    base_amount=base_amount,
                    discount_amount=discount_amount,
                    final_amount=final_amount,
                    **common_booking_fields,
                )

            if coupons:
                from bookings.services.guest_confirm import redeem_coupons_on_booking

                try:
                    redeem_coupons_on_booking(
                        booking, coupons, changed_by=request.user
                    )
                except ValueError as exc:
                    raise serializers.ValidationError(
                        {"coupon_ids": str(exc)}
                    ) from exc

            BookingStatusLog.objects.create(
                booking=booking,
                from_status=Booking.Status.PENDING,
                to_status=Booking.Status.PENDING,
                changed_by=request.user,
                reason="Pending reservation created (guest checkout in progress)",
            )

        return booking


class BookingGuestConfirmSerializer(serializers.Serializer):
    """Finalize a pending guest booking (apply coupons, confirm, pay at desk)."""

    coupon_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
    )
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        request = self.context["request"]
        booking: Booking = self.context["booking"]

        if booking.user_id != request.user.pk:
            raise serializers.ValidationError("Not your booking.")
        if booking.status != Booking.Status.PENDING:
            raise serializers.ValidationError(
                "Only pending bookings can be confirmed."
            )
        if booking.payment_status != Booking.PaymentStatus.UNPAID:
            raise serializers.ValidationError("Booking is not awaiting payment.")

        coupon_ids = attrs.get("coupon_ids") or []
        if len(coupon_ids) > 2:
            raise serializers.ValidationError(
                {"coupon_ids": "Maximum two coupons allowed per booking."}
            )

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

    def save(self):
        booking: Booking = self.context["booking"]
        request = self.context["request"]
        from bookings.services.guest_confirm import confirm_guest_reservation

        try:
            return confirm_guest_reservation(
                booking,
                coupons=self.validated_data.get("coupons", []),
                changed_by=request.user,
                notes=self.validated_data.get("notes", ""),
            )
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


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
        Booking.Status.CHECKED_IN: {
            Booking.Status.CHECKED_OUT,
            Booking.Status.CONFIRMED,
        },
        Booking.Status.CHECKED_OUT: set(),
        Booking.Status.CANCELLED: set(),
        Booking.Status.NO_SHOW: {Booking.Status.CONFIRMED},
    }

    def validate(self, attrs):
        booking = self.context["booking"]
        new_status = attrs["status"]
        allowed = self._ALLOWED.get(booking.status, set())

        if new_status not in allowed:
            raise serializers.ValidationError(
                {
                    "status": status_transition_not_allowed(
                        booking.status, new_status
                    )
                }
            )

        needs_reason = new_status in (
            Booking.Status.CANCELLED,
            Booking.Status.NO_SHOW,
            Booking.Status.CONFIRMED,
        ) and booking.status in (
            Booking.Status.NO_SHOW,
            Booking.Status.CHECKED_IN,
        )
        if new_status in (Booking.Status.CANCELLED, Booking.Status.NO_SHOW):
            needs_reason = True
        if needs_reason and not (attrs.get("reason") or "").strip():
            raise serializers.ValidationError(
                {
                    "reason": (
                        "Please add a short reason so your team can see why "
                        "this change was made."
                    )
                }
            )

        # --- Check-in guards ------------------------------------------------
        if new_status == Booking.Status.CHECKED_IN:
            # Must be paid before check-in
            if booking.payment_status != Booking.PaymentStatus.PAID:
                raise serializers.ValidationError(
                    {
                        "status": (
                            "Cannot check in: cash payment has not been recorded for this booking. "
                            "Record payment first."
                        )
                    }
                )
            # Cannot check in before the check-in date
            today = timezone.localdate()
            if today < booking.check_in_date:
                raise serializers.ValidationError(
                    {
                        "status": (
                            f"Cannot check in before the scheduled date "
                            f"({booking.check_in_date})."
                        )
                    }
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
    payment_reference = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
        help_text="Optional cash receipt number.",
    )


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

        # --- Overlap check: ensure no booking conflicts with the extension ---
        overlap_exists = Booking.objects.filter(
            room=booking.room,
            status__in=[
                Booking.Status.PENDING,
                Booking.Status.CONFIRMED,
                Booking.Status.CHECKED_IN,
            ],
            check_in_date__lt=new_out,
            check_out_date__gt=booking.check_out_date,
            is_deleted=False,
        ).exclude(pk=booking.pk).exists()

        if overlap_exists:
            raise serializers.ValidationError(
                {
                    "check_out_date": (
                        "Cannot extend: another booking overlaps with the new checkout date. "
                        "Please choose an earlier date."
                    )
                }
            )

        attrs["nights"] = nights
        return attrs


class BookingRefundRequestSerializer(serializers.Serializer):
    """Guest-submitted refund request for a cancelled paid booking."""

    reason = serializers.CharField(
        min_length=10,
        max_length=1000,
        help_text="Reason for requesting a refund (min 10 characters).",
    )
