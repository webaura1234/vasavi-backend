"""Staff portal booking serializers (walk-in / phone reservations)."""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from accounts.models import AdminBranch, User
from bookings.models import Booking, BookingStatusLog
from bookings.services.payments import confirm_cash_payment
from properties.models import Room
from utils.phone import is_valid_indian_phone, normalize_indian_phone


class StaffManualBookingCreateSerializer(serializers.Serializer):
    room_id = serializers.UUIDField()
    check_in_date = serializers.DateField()
    check_out_date = serializers.DateField()
    guest_count = serializers.IntegerField(default=1, min_value=1)
    guest_name = serializers.CharField(max_length=200)
    guest_phone = serializers.CharField(max_length=15)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    source = serializers.ChoiceField(
        choices=("walk_in", "phone"),
        default="walk_in",
    )
    record_cash_payment = serializers.BooleanField(default=False)
    check_in_immediately = serializers.BooleanField(default=False)

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

        try:
            room = Room.objects.select_related("branch").get(
                pk=attrs["room_id"],
                is_deleted=False,
                is_active=True,
            )
        except Room.DoesNotExist as exc:
            raise serializers.ValidationError({"room_id": "Room not found."}) from exc

        staff = self.context["request"].user
        if staff.role == "admin":
            try:
                admin_branch = staff.admin_branch.branch
            except AdminBranch.DoesNotExist as exc:
                raise serializers.ValidationError(
                    {"room_id": "Your account is not assigned to a branch."}
                ) from exc
            if room.branch_id != admin_branch.id:
                raise serializers.ValidationError(
                    {"room_id": "This room is outside your assigned branch."}
                )

        if room.capacity < attrs.get("guest_count", 1):
            raise serializers.ValidationError(
                {"guest_count": f"Room capacity is {room.capacity} guests."}
            )

        attrs["room"] = room
        attrs["check_in"] = check_in
        attrs["check_out"] = check_out
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
        room = validated_data["room"]
        check_in = validated_data["check_in"]
        check_out = validated_data["check_out"]
        nights = validated_data["nights"]
        guest_name = validated_data["guest_name"].strip()
        guest_phone = validated_data["guest_phone"]
        record_cash = validated_data.get("record_cash_payment", False)
        check_in_now = validated_data.get("check_in_immediately", False)
        notes = self._compose_notes(
            validated_data.get("source", "walk_in"),
            validated_data.get("notes", ""),
        )

        base_amount = room.base_price_per_night * nights
        guest_user = self._resolve_guest_user(guest_phone, guest_name)

        with transaction.atomic():
            room = Room.objects.select_for_update().get(
                pk=room.pk,
                is_deleted=False,
                is_active=True,
            )
            if self._room_has_overlap(room, check_in, check_out):
                raise serializers.ValidationError(
                    {"room_id": "Room is not available for the selected dates."}
                )

            booking = Booking.objects.create(
                user=guest_user,
                room=room,
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

        return booking
