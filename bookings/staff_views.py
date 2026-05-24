"""Staff portal booking operations."""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers as drf_serializers
from rest_framework.views import APIView

from bookings.models import Booking, BookingStatusLog
from bookings.serializers import BookingSerializer
from bookings.staff_serializers import StaffManualBookingCreateSerializer
from bookings.views import _booking_queryset_for_user
from permissions import IsAdminOrAbove
from utils.responses import error_response, success_response

logger = logging.getLogger("vasavi.bookings.staff_views")


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
    """
    Process a cash refund for a paid or refund-pending booking.

    Supports full and partial refunds. Records the cash refund reference
    and updates payment_status accordingly. Does NOT call Razorpay (deferred).
    """

    permission_classes = [IsAdminOrAbove]

    def post(self, request, pk):
        try:
            booking = _booking_queryset_for_user(request.user).get(pk=pk, is_deleted=False)
        except Booking.DoesNotExist:
            return error_response("NOT_FOUND", "Booking not found.", status=404)

        if booking.payment_status not in (
            Booking.PaymentStatus.PAID,
            Booking.PaymentStatus.REFUND_PENDING,
        ):
            return error_response(
                "VALIDATION_ERROR",
                "Only paid or refund-pending bookings can be refunded.",
                status=400,
            )

        # Validate request body
        class _RefundSerializer(drf_serializers.Serializer):
            reason = drf_serializers.CharField(required=True, min_length=5)
            refund_amount_paise = drf_serializers.IntegerField(
                required=False,
                min_value=0,
                help_text="Amount to refund in paise. Defaults to full booking amount.",
            )
            refund_reference = drf_serializers.CharField(
                required=False,
                allow_blank=True,
                max_length=200,
                help_text="Cash receipt or cheque number for the refund.",
            )

        body = _RefundSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        reason = body.validated_data["reason"]
        refund_amount_paise = body.validated_data.get(
            "refund_amount_paise", booking.final_amount
        )
        refund_reference = body.validated_data.get("refund_reference", "").strip()

        if refund_amount_paise > booking.final_amount:
            return error_response(
                "VALIDATION_ERROR",
                f"Refund amount ({refund_amount_paise} paise) cannot exceed "
                f"the booking total ({booking.final_amount} paise).",
                status=400,
            )

        is_full_refund = refund_amount_paise == booking.final_amount
        new_payment_status = (
            Booking.PaymentStatus.REFUNDED
            if is_full_refund
            else Booking.PaymentStatus.PARTIALLY_REFUNDED
        )

        with transaction.atomic():
            booking = Booking.objects.select_for_update().get(pk=booking.pk)
            old_payment = booking.payment_status
            booking.payment_status = new_payment_status
            booking.refund_amount = refund_amount_paise
            booking.refund_reference = refund_reference
            booking.refund_processed_at = timezone.now()
            booking.refund_reason = reason
            booking.save(update_fields=[
                "payment_status",
                "refund_amount",
                "refund_reference",
                "refund_processed_at",
                "refund_reason",
                "updated_at",
            ])
            BookingStatusLog.objects.create(
                booking=booking,
                from_status=booking.status,
                to_status=booking.status,
                changed_by=request.user,
                reason=(
                    f"Refund processed by {request.user.name or request.user.phone} "
                    f"({old_payment} → {new_payment_status}): {reason}"
                ),
            )

        logger.info(
            "Refund processed for booking %s: %d paise by %s",
            booking.booking_reference,
            refund_amount_paise,
            request.user.phone,
        )

        booking.refresh_from_db()
        return success_response(BookingSerializer(booking).data)


class StaffRefundApprovalView(APIView):
    """
    Staff approves or rejects a guest refund request.
    GET  → view pending refund requests in this admin's branch.
    POST → approve (process refund) or reject.
    """

    permission_classes = [IsAdminOrAbove]

    def get(self, request):
        """List bookings with pending refund requests for this branch."""
        qs = _booking_queryset_for_user(request.user).filter(
            payment_status=Booking.PaymentStatus.REFUND_PENDING
        ).order_by("refund_requested_at")
        from bookings.serializers import BookingSerializer as BS
        data = BS(qs, many=True).data
        return success_response(data)

    def post(self, request, pk):
        """Approve or reject a refund request."""
        try:
            booking = _booking_queryset_for_user(request.user).get(pk=pk, is_deleted=False)
        except Booking.DoesNotExist:
            return error_response("NOT_FOUND", "Booking not found.", status=404)

        if booking.payment_status != Booking.PaymentStatus.REFUND_PENDING:
            return error_response(
                "VALIDATION_ERROR",
                "This booking does not have a pending refund request.",
                status=400,
            )

        action = request.data.get("action")  # "approve" | "reject"
        if action not in ("approve", "reject"):
            return error_response(
                "VALIDATION_ERROR",
                "action must be 'approve' or 'reject'.",
                status=400,
            )

        if action == "reject":
            reason = (request.data.get("reason") or "").strip()
            if not reason:
                return error_response(
                    "VALIDATION_ERROR",
                    "A reason is required when rejecting a refund request.",
                    status=400,
                )
            with transaction.atomic():
                booking = Booking.objects.select_for_update().get(pk=booking.pk)
                booking.payment_status = Booking.PaymentStatus.PAID
                booking.save(update_fields=["payment_status", "updated_at"])
                BookingStatusLog.objects.create(
                    booking=booking,
                    from_status=booking.status,
                    to_status=booking.status,
                    changed_by=request.user,
                    reason=f"Refund request rejected: {reason}",
                )
            booking.refresh_from_db()
            return success_response(BookingSerializer(booking).data)

        # Approve → delegate to StaffBookingRefundView logic
        return StaffBookingRefundView().post(request, pk)
