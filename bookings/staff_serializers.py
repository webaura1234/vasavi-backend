"""Staff portal booking serializers (walk-in / phone reservations)."""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from accounts.models import AdminBranch, User
from bookings.models import Booking, BookingStatusLog
from bookings.services.availability import check_availability_with_lock
from bookings.services.guest_confirm import redeem_coupons_on_booking
from bookings.services.payments import confirm_cash_payment
from bookings.services.pricing import compute_coupon_discount
from bookings.services.guest_count import resolve_guest_count
from bookings.services.staff_guest import validate_coupons_for_guest
from properties.models import FunctionHall, Room
from utils.phone import is_valid_indian_phone, normalize_indian_phone


class StaffManualBookingCreateSerializer(serializers.Serializer):
    room_id = serializers.UUIDField(required=False)
    function_hall_id = serializers.UUIDField(required=False)
    check_in_date = serializers.DateField()
    check_out_date = serializers.DateField()
    guest_count = serializers.IntegerField(required=False, min_value=1)
    adults = serializers.IntegerField(required=False, min_value=1)
    children = serializers.IntegerField(required=False, min_value=0, default=0)
    guest_name = serializers.CharField(max_length=200)
    guest_phone = serializers.CharField(max_length=15)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    source = serializers.ChoiceField(
        choices=("walk_in", "phone"),
        default="walk_in",
    )
    record_cash_payment = serializers.BooleanField(default=False)
    check_in_immediately = serializers.BooleanField(default=False)
    coupon_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        default=list,
    )

    def validate_guest_phone(self, value: str) -> str:
        if not is_valid_indian_phone(value):
            raise serializers.ValidationError(
                "Enter a valid 10-digit Indian mobile number."
            )
        return normalize_indian_phone(value)

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
        attrs["check_in"] = check_in
        attrs["check_out"] = check_out

        has_room = bool(attrs.get("room_id"))
        has_hall = bool(attrs.get("function_hall_id"))
        if has_room == has_hall:
            raise serializers.ValidationError(
                "Provide exactly one of room_id or function_hall_id.",
                code="invalid_resource",
            )

        staff = self.context["request"].user
        guest_count = resolve_guest_count(attrs)

        def _enforce_branch_scope(resource_branch_id):
            if staff.role != "admin":
                return
            try:
                admin_branch = staff.admin_branch.branch
            except AdminBranch.DoesNotExist as exc:
                raise serializers.ValidationError(
                    {"branch": "Your account is not assigned to a branch."}
                ) from exc
            if resource_branch_id != admin_branch.id:
                raise serializers.ValidationError(
                    {"branch": "This resource is outside your assigned branch."}
                )

        if has_room:
            try:
                room = Room.objects.select_related("branch").get(
                    pk=attrs["room_id"],
                    is_deleted=False,
                    is_active=True,
                )
            except Room.DoesNotExist as exc:
                raise serializers.ValidationError({"room_id": "Room not found."}) from exc

            _enforce_branch_scope(room.branch_id)

            if guest_count > room.capacity:
                raise serializers.ValidationError(
                    {"guest_count": f"Room capacity is {room.capacity} guests."}
                )

            if room.operational_status != "available":
                raise serializers.ValidationError(
                    {
                        "room_id": (
                            f"This room is currently {room.operational_status} "
                            "and cannot be booked."
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

            _enforce_branch_scope(hall.branch_id)

            if guest_count > hall.capacity:
                raise serializers.ValidationError(
                    {"guest_count": f"Hall capacity is {hall.capacity} guests."}
                )

            if hall.operational_status != "available":
                raise serializers.ValidationError(
                    {
                        "function_hall_id": (
                            f"This hall is currently {hall.operational_status} "
                            "and cannot be booked."
                        )
                    }
                )

            attrs["function_hall"] = hall
            attrs["booking_kind"] = Booking.BookingKind.FUNCTION_HALL

        coupon_ids = attrs.get("coupon_ids") or []
        if coupon_ids:
            guest_user = User.objects.filter(
                phone=attrs["guest_phone"],
                is_deleted=False,
            ).first()
            if not guest_user:
                raise serializers.ValidationError(
                    {
                        "coupon_ids": (
                            "Guest must already be registered as a donor before "
                            "applying coupons."
                        )
                    }
                )
            attrs["coupons"] = validate_coupons_for_guest(
                coupon_ids,
                guest_user,
                room_booking=attrs["booking_kind"] == Booking.BookingKind.ROOM,
            )
        else:
            attrs["coupons"] = []

        return attrs

    def _resolve_guest_user(self, phone: str, name: str) -> User:
        existing = User.objects.filter(phone=phone, is_deleted=False).first()
        if existing:
            if existing.role in ("admin", "super_admin"):
                raise serializers.ValidationError(
                    {
                        "guest_phone": (
                            "This number belongs to a staff account. "
                            "Use the guest's mobile number."
                        )
                    }
                )
            if name and not (existing.name or "").strip():
                existing.name = name.strip()
                existing.save(update_fields=["name", "updated_at"])
            return existing
        return User.objects.create_user(
            phone=phone,
            role="user",
            name=name.strip(),
            is_active=True,
        )

    def _compose_notes(self, source: str, notes: str) -> str:
        channel = "Walk-in" if source == "walk_in" else "Phone"
        body = (notes or "").strip()
        prefix = f"[In-house · {channel}]"
        if body:
            return f"{prefix} {body}"
        return f"{prefix} Created by staff portal"

    def create(self, validated_data):
        staff = self.context["request"].user
        check_in = validated_data["check_in"]
        check_out = validated_data["check_out"]
        nights = validated_data["nights"]
        guest_name = validated_data["guest_name"].strip()
        guest_phone = validated_data["guest_phone"]
        record_cash = validated_data.get("record_cash_payment", False)
        check_in_now = validated_data.get("check_in_immediately", False)
        booking_kind = validated_data["booking_kind"]
        notes = self._compose_notes(
            validated_data.get("source", "walk_in"),
            validated_data.get("notes", ""),
        )

        guest_user = self._resolve_guest_user(guest_phone, guest_name)
        coupons = validated_data.get("coupons") or []

        with transaction.atomic():
            if booking_kind == Booking.BookingKind.ROOM:
                room = validated_data["room"]
                base_amount = room.base_price_per_night * nights
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
                    user=guest_user,
                    room=room,
                    booking_kind=booking_kind,
                    check_in_date=validated_data["check_in_date"],
                    check_out_date=validated_data["check_out_date"],
                    nights=nights,
                    guest_count=validated_data.get("guest_count", 1),
                    guest_name=guest_name,
                    guest_phone=guest_phone,
                    status=Booking.Status.PENDING,
                    base_amount=base_amount,
                    discount_amount=0,
                    final_amount=base_amount,
                    payment_status=Booking.PaymentStatus.UNPAID,
                    notes=notes,
                )
            else:
                hall = validated_data["function_hall"]
                base_amount = hall.base_price_per_day * nights
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
                    user=guest_user,
                    function_hall=hall,
                    booking_kind=booking_kind,
                    check_in_date=validated_data["check_in_date"],
                    check_out_date=validated_data["check_out_date"],
                    nights=nights,
                    guest_count=validated_data.get("guest_count", 1),
                    guest_name=guest_name,
                    guest_phone=guest_phone,
                    status=Booking.Status.PENDING,
                    base_amount=base_amount,
                    discount_amount=0,
                    final_amount=base_amount,
                    payment_status=Booking.PaymentStatus.UNPAID,
                    notes=notes,
                )

            BookingStatusLog.objects.create(
                booking=booking,
                from_status=Booking.Status.PENDING,
                to_status=Booking.Status.PENDING,
                changed_by=staff,
                reason="Manual booking created by staff",
            )

            if coupons:
                discount_amount, final_amount = compute_coupon_discount(
                    booking.base_amount, coupons
                )
                booking.discount_amount = discount_amount
                booking.final_amount = final_amount
                booking.save(
                    update_fields=[
                        "discount_amount",
                        "final_amount",
                        "updated_at",
                    ]
                )
                redeem_coupons_on_booking(booking, coupons, changed_by=staff)

            if record_cash and booking.final_amount > 0:
                booking = confirm_cash_payment(
                    booking,
                    changed_by=staff,
                    notes="Recorded at front desk (manual booking)",
                )
            elif record_cash and booking.final_amount == 0:
                booking.status = Booking.Status.CONFIRMED
                booking.payment_status = Booking.PaymentStatus.PAID
                booking.payment_gateway = Booking.PaymentGateway.OTHER
                booking.payment_reference = "COMPLIMENTARY"
                booking.payment_paid_at = timezone.now()
                booking.save(
                    update_fields=[
                        "status",
                        "payment_status",
                        "payment_gateway",
                        "payment_reference",
                        "payment_paid_at",
                        "updated_at",
                    ]
                )
                BookingStatusLog.objects.create(
                    booking=booking,
                    from_status=Booking.Status.PENDING,
                    to_status=Booking.Status.CONFIRMED,
                    changed_by=staff,
                    reason="Complimentary stay confirmed",
                )
            elif check_in_now:
                booking.status = Booking.Status.CONFIRMED
                booking.save(update_fields=["status", "updated_at"])
                BookingStatusLog.objects.create(
                    booking=booking,
                    from_status=Booking.Status.PENDING,
                    to_status=Booking.Status.CONFIRMED,
                    changed_by=staff,
                    reason="Confirmed for desk check-in (pay at checkout)",
                )
            else:
                booking.status = Booking.Status.CONFIRMED
                booking.save(update_fields=["status", "updated_at"])
                BookingStatusLog.objects.create(
                    booking=booking,
                    from_status=Booking.Status.PENDING,
                    to_status=Booking.Status.CONFIRMED,
                    changed_by=staff,
                    reason="Manual booking confirmed by staff",
                )

            if check_in_now and booking.status == Booking.Status.CONFIRMED:
                old = booking.status
                booking.status = Booking.Status.CHECKED_IN
                booking.save(update_fields=["status", "updated_at"])
                BookingStatusLog.objects.create(
                    booking=booking,
                    from_status=old,
                    to_status=Booking.Status.CHECKED_IN,
                    changed_by=staff,
                    reason="Checked in at front desk",
                )

        from notifications.services.staff import schedule_staff_new_booking_notification

        schedule_staff_new_booking_notification(booking.pk, exclude_user_id=staff.pk)

        return booking
