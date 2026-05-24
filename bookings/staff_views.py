"""Staff portal booking operations."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from bookings.models import Booking, BookingStatusLog
from bookings.serializers import BookingSerializer
from bookings.staff_serializers import StaffManualBookingCreateSerializer
from bookings.views import _booking_queryset_for_user
from permissions import IsAdminOrAbove
from rest_framework.views import APIView
from utils.responses import error_response, success_response


class StaffManualBookingCreateView(APIView):
    """Create a booking on behalf of a walk-in or phone guest."""

    permission_classes = [IsAdminOrAbove]

    def post(self, request):
        serializer = StaffManualBookingCreateSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        booking = serializer.save()
        booking = _booking_queryset_for_user(request.user).get(pk=booking.pk)
        return success_response(BookingSerializer(booking).data, status=201)


class StaffBookingRefundView(APIView):
    """Mark a paid booking as refunded (desk refund)."""

    permission_classes = [IsAdminOrAbove]

    def post(self, request, pk):
        try:
            booking = _booking_queryset_for_user(request.user).get(pk=pk, is_deleted=False)
        except Booking.DoesNotExist:
            return error_response("NOT_FOUND", "Booking not found.", status=404)

        if booking.payment_status != Booking.PaymentStatus.PAID:
            return error_response(
                "VALIDATION_ERROR",
                "Only paid bookings can be marked as refunded.",
                status=400,
            )

        reason = (request.data.get("reason") or "Refund processed at front desk").strip()

        with transaction.atomic():
            booking = Booking.objects.select_for_update().get(pk=booking.pk)
            old_payment = booking.payment_status
            booking.payment_status = Booking.PaymentStatus.REFUNDED
            booking.save(update_fields=["payment_status", "updated_at"])
            BookingStatusLog.objects.create(
                booking=booking,
                from_status=booking.status,
                to_status=booking.status,
                changed_by=request.user,
                reason=f"Payment refunded ({old_payment} → refunded): {reason}",
            )

        booking.refresh_from_db()
        return success_response(BookingSerializer(booking).data)
