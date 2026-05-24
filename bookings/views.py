"""Booking API views."""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import generics
from rest_framework.views import APIView

from accounts.models import AdminBranch
from bookings.models import Booking, BookingStatusLog
from bookings.serializers import (
    BookingCreateSerializer,
    BookingExtendStaySerializer,
    BookingGuestConfirmSerializer,
    BookingRefundRequestSerializer,
    BookingSerializer,
    BookingStatusLogSerializer,
    BookingStatusUpdateSerializer,
    CashPaymentSerializer,
)
from bookings.services.payments import confirm_booking_payment, confirm_cash_payment
from coupons.models import Coupon
from permissions import IsAdminOrAbove
from rest_framework.permissions import IsAuthenticated as PermIsAuthenticated
from throttles import BookingCreateThrottle, PaymentThrottle
from utils.responses import error_response, paginated_response, success_response

logger = logging.getLogger("vasavi.bookings.views")


def _booking_queryset_for_user(user):
    """Scope bookings by role — branch admin uses AdminBranch FK, not query params."""
    qs = Booking.objects.filter(is_deleted=False).select_related(
        "user", "room", "room__room_type", "branch"
    ).prefetch_related("coupons_applied")
    if user.role in ("user", "donor"):
        return qs.filter(user=user)
    if user.role == "admin":
        try:
            branch = user.admin_branch.branch
        except AdminBranch.DoesNotExist:
            return qs.none()
        return qs.filter(branch=branch)
    # super_admin: all branches (optional branch_id filter in list view only)
    return qs


class BookingListCreateView(generics.ListCreateAPIView):
    lookup_field = "pk"

    def get_permissions(self):
        return [PermIsAuthenticated()]

    def get_throttles(self):
        if self.request.method == "POST":
            return [BookingCreateThrottle()]
        return []

    def get_queryset(self):
        qs = _booking_queryset_for_user(self.request.user)
        status_param = self.request.query_params.get("status")
        payment_status = self.request.query_params.get("payment_status")
        check_in = self.request.query_params.get("check_in_date")
        branch_id = self.request.query_params.get("branch_id")

        if status_param:
            qs = qs.filter(status=status_param)
        if payment_status:
            qs = qs.filter(payment_status=payment_status)
        if check_in:
            qs = qs.filter(check_in_date=check_in)
        if branch_id and self.request.user.role == "super_admin":
            qs = qs.filter(branch_id=branch_id)
        return qs.order_by("-created_at")

    def list(self, request, *args, **kwargs):
        return paginated_response(self.get_queryset(), request, BookingSerializer)

    def create(self, request, *args, **kwargs):
        serializer = BookingCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        booking = serializer.save()
        booking = self.get_queryset().get(pk=booking.pk)
        return success_response(BookingSerializer(booking).data, status=201)


class BookingDetailView(generics.RetrieveAPIView):
    lookup_field = "pk"
    permission_classes = [PermIsAuthenticated]
    serializer_class = BookingSerializer

    def get_queryset(self):
        return _booking_queryset_for_user(self.request.user)

    def retrieve(self, request, *args, **kwargs):
        return success_response(BookingSerializer(self.get_object()).data)


class BookingStatusUpdateView(APIView):
    permission_classes = [IsAdminOrAbove]

    def patch(self, request, pk):
        try:
            booking = Booking.objects.select_related("branch").get(pk=pk, is_deleted=False)
        except Booking.DoesNotExist:
            return error_response("NOT_FOUND", "Booking not found.", status=404)

        if request.user.role == "admin":
            try:
                if booking.branch_id != request.user.admin_branch.branch_id:
                    return error_response("PERMISSION_DENIED", "Out of branch scope.", status=403)
            except AdminBranch.DoesNotExist:
                return error_response("PERMISSION_DENIED", "No branch assigned.", status=403)

        serializer = BookingStatusUpdateSerializer(
            data=request.data,
            context={"booking": booking},
        )
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data["status"]
        reason = serializer.validated_data.get("reason", "")

        with transaction.atomic():
            old_status = booking.status
            booking.status = new_status

            # Track who cancelled
            if new_status == Booking.Status.CANCELLED:
                booking.cancelled_at = timezone.now()
                booking.cancellation_reason = reason
                booking.cancelled_by = request.user
                booking.cancel_initiated_by_role = request.user.role
                booking.save(update_fields=[
                    "status", "cancelled_at", "cancellation_reason",
                    "cancelled_by", "cancel_initiated_by_role", "updated_at",
                ])
                # Revert coupons
                _revert_booking_coupons(booking)
            else:
                booking.save(update_fields=["status", "updated_at"])

            BookingStatusLog.objects.create(
                booking=booking,
                from_status=old_status,
                to_status=new_status,
                changed_by=request.user,
                reason=reason,
            )

        booking.refresh_from_db()
        return success_response(BookingSerializer(booking).data)


class BookingExtendStayView(APIView):
    """Extend checkout date for a booking (staff portal stay extensions)."""

    permission_classes = [IsAdminOrAbove]

    def patch(self, request, pk):
        try:
            booking = Booking.objects.select_related("room", "branch").get(
                pk=pk, is_deleted=False
            )
        except Booking.DoesNotExist:
            return error_response("NOT_FOUND", "Booking not found.", status=404)

        if request.user.role == "admin":
            try:
                if booking.branch_id != request.user.admin_branch.branch_id:
                    return error_response("PERMISSION_DENIED", "Out of branch scope.", status=403)
            except AdminBranch.DoesNotExist:
                return error_response("PERMISSION_DENIED", "No branch assigned.", status=403)

        if booking.status not in (
            Booking.Status.CONFIRMED,
            Booking.Status.CHECKED_IN,
        ):
            return error_response(
                "VALIDATION_ERROR",
                "Only confirmed or checked-in bookings can be extended.",
                status=400,
            )

        serializer = BookingExtendStaySerializer(
            data=request.data,
            context={"booking": booking},
        )
        serializer.is_valid(raise_exception=True)
        new_check_out = serializer.validated_data["check_out_date"]
        nights = serializer.validated_data["nights"]
        notes = serializer.validated_data.get("notes", "")

        extra_nights = (new_check_out - booking.check_out_date).days
        extra_amount = booking.room.base_price_per_night * extra_nights

        with transaction.atomic():
            old_check_out = booking.check_out_date
            booking.check_out_date = new_check_out
            booking.nights = nights
            booking.base_amount += extra_amount
            booking.final_amount += extra_amount
            if notes:
                booking.notes = (
                    f"{booking.notes}\n{notes}".strip()
                    if booking.notes
                    else notes
                )
            booking.save(
                update_fields=[
                    "check_out_date",
                    "nights",
                    "base_amount",
                    "final_amount",
                    "notes",
                    "updated_at",
                ]
            )
            BookingStatusLog.objects.create(
                booking=booking,
                from_status=booking.status,
                to_status=booking.status,
                changed_by=request.user,
                reason=(
                    f"Stay extended from {old_check_out} to {new_check_out}"
                    + (f": {notes}" if notes else "")
                ),
            )

        booking.refresh_from_db()
        return success_response(BookingSerializer(booking).data)


class BookingCancelView(APIView):
    """
    Guest-facing cancellation. Guests can cancel only before check-in date.
    - UNPAID bookings → cancelled immediately, coupons reverted.
    - PAID bookings → cancelled + payment_status set to REFUND_PENDING
      (guest's refund request must be approved by staff).
    """

    permission_classes = [PermIsAuthenticated]

    def post(self, request, pk):
        try:
            booking = Booking.objects.select_related("branch").get(pk=pk, is_deleted=False)
        except Booking.DoesNotExist:
            return error_response("NOT_FOUND", "Booking not found.", status=404)

        user = request.user

        # Ownership check for regular users
        if user.role in ("user", "donor") and booking.user_id != user.pk:
            return error_response("PERMISSION_DENIED", "Not your booking.", status=403)

        # Branch scope for admins
        if user.role == "admin":
            try:
                if booking.branch_id != user.admin_branch.branch_id:
                    return error_response("PERMISSION_DENIED", "Out of branch scope.", status=403)
            except AdminBranch.DoesNotExist:
                return error_response("PERMISSION_DENIED", "No branch assigned.", status=403)

        # Only cancellable if PENDING or CONFIRMED
        if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED):
            return error_response(
                "VALIDATION_ERROR",
                "Booking cannot be cancelled in its current status.",
                status=400,
            )

        # Guests cannot cancel after check-in date
        if user.role in ("user", "donor") and booking.check_in_date <= timezone.localdate():
            return error_response(
                "VALIDATION_ERROR",
                "Cancellations are only allowed before the check-in date. "
                "Please contact the property desk.",
                status=400,
            )

        reason = (request.data.get("reason") or "").strip()
        if not reason:
            return error_response(
                "VALIDATION_ERROR",
                "Cancellation reason is required.",
                status=400,
                fields={"reason": ["This field is required."]},
            )

        with transaction.atomic():
            booking = Booking.objects.select_for_update().get(pk=booking.pk)
            old_status = booking.status
            booking.status = Booking.Status.CANCELLED
            booking.cancelled_at = timezone.now()
            booking.cancellation_reason = reason
            booking.cancelled_by = user
            booking.cancel_initiated_by_role = user.role

            # If the booking was paid, put refund in pending state
            if booking.payment_status == Booking.PaymentStatus.PAID:
                booking.payment_status = Booking.PaymentStatus.REFUND_PENDING
                booking.refund_requested_at = timezone.now()
                booking.refund_requested_reason = reason
                save_fields = [
                    "status", "cancelled_at", "cancellation_reason",
                    "cancelled_by", "cancel_initiated_by_role",
                    "payment_status", "refund_requested_at",
                    "refund_requested_reason", "updated_at",
                ]
            else:
                save_fields = [
                    "status", "cancelled_at", "cancellation_reason",
                    "cancelled_by", "cancel_initiated_by_role", "updated_at",
                ]

            booking.save(update_fields=save_fields)

            # Revert coupons (only if payment wasn't made)
            if booking.payment_status != Booking.PaymentStatus.PAID:
                _revert_booking_coupons(booking)

            BookingStatusLog.objects.create(
                booking=booking,
                from_status=old_status,
                to_status=Booking.Status.CANCELLED,
                changed_by=user,
                reason=reason,
            )

        booking.refresh_from_db()
        return success_response(BookingSerializer(booking).data)


class BookingRefundRequestView(APIView):
    """
    Guest submits a refund request for a cancelled paid booking.
    Sets payment_status = REFUND_PENDING for staff to process.
    """

    permission_classes = [PermIsAuthenticated]

    def post(self, request, pk):
        try:
            booking = Booking.objects.get(pk=pk, is_deleted=False)
        except Booking.DoesNotExist:
            return error_response("NOT_FOUND", "Booking not found.", status=404)

        if booking.user_id != request.user.pk and request.user.role not in ("admin", "super_admin"):
            return error_response("PERMISSION_DENIED", "Not your booking.", status=403)

        if booking.status != Booking.Status.CANCELLED:
            return error_response(
                "VALIDATION_ERROR",
                "Refund requests can only be submitted for cancelled bookings.",
                status=400,
            )

        if booking.payment_status not in (
            Booking.PaymentStatus.PAID,
            Booking.PaymentStatus.REFUND_PENDING,
        ):
            return error_response(
                "VALIDATION_ERROR",
                "No payment to refund.",
                status=400,
            )

        if booking.payment_status == Booking.PaymentStatus.REFUND_PENDING:
            return error_response(
                "VALIDATION_ERROR",
                "A refund request has already been submitted. Please wait for staff to process it.",
                status=400,
            )

        serializer = BookingRefundRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            booking = Booking.objects.select_for_update().get(pk=booking.pk)
            booking.payment_status = Booking.PaymentStatus.REFUND_PENDING
            booking.refund_requested_at = timezone.now()
            booking.refund_requested_reason = serializer.validated_data["reason"]
            booking.save(update_fields=[
                "payment_status", "refund_requested_at",
                "refund_requested_reason", "updated_at",
            ])
            BookingStatusLog.objects.create(
                booking=booking,
                from_status=booking.status,
                to_status=booking.status,
                changed_by=request.user,
                reason=f"Refund requested: {serializer.validated_data['reason']}",
            )

        booking.refresh_from_db()
        return success_response(BookingSerializer(booking).data)


class BookingPaymentOrderView(APIView):
    """Razorpay order creation — gated behind RAZORPAY_ENABLED flag."""

    permission_classes = [PermIsAuthenticated]
    throttle_classes = [PaymentThrottle]

    def post(self, request, pk):
        if not getattr(settings, "RAZORPAY_ENABLED", False):
            return error_response(
                "NOT_IMPLEMENTED",
                "Online payments are not available. Please pay at the property desk.",
                status=503,
            )
        # (Razorpay implementation kept dormant — activate when RAZORPAY_ENABLED=True)
        return error_response("NOT_IMPLEMENTED", "Razorpay not configured.", status=503)


class BookingGuestConfirmView(APIView):
    """Guest finalizes a pending hold (confirmed, pay at property)."""

    permission_classes = [PermIsAuthenticated]
    throttle_classes = [BookingCreateThrottle]

    def post(self, request, pk):
        try:
            booking = _booking_queryset_for_user(request.user).get(pk=pk)
        except Booking.DoesNotExist:
            return error_response("NOT_FOUND", "Booking not found.", status=404)

        if request.user.role not in ("user", "donor"):
            return error_response(
                "PERMISSION_DENIED",
                "Only guests can confirm reservations through this endpoint.",
                status=403,
            )

        serializer = BookingGuestConfirmSerializer(
            data=request.data,
            context={"request": request, "booking": booking},
        )
        serializer.is_valid(raise_exception=True)
        booking = serializer.save()
        booking = _booking_queryset_for_user(request.user).get(pk=booking.pk)
        return success_response(BookingSerializer(booking).data)


class BookingCashPaymentView(APIView):
    """Confirm a pending/confirmed booking with cash (staff at desk)."""

    permission_classes = [PermIsAuthenticated]
    throttle_classes = [PaymentThrottle]

    def post(self, request, pk):
        user = request.user

        # Only staff can record cash payments (guests pay at desk)
        if user.role in ("user", "donor"):
            return error_response(
                "PERMISSION_DENIED",
                "Cash payment must be recorded by property staff.",
                status=403,
            )

        try:
            booking = Booking.objects.select_related("branch").get(pk=pk, is_deleted=False)
        except Booking.DoesNotExist:
            return error_response("NOT_FOUND", "Booking not found.", status=404)

        # Branch scope for admins
        if user.role == "admin":
            try:
                if booking.branch_id != user.admin_branch.branch_id:
                    return error_response("PERMISSION_DENIED", "Out of branch scope.", status=403)
            except AdminBranch.DoesNotExist:
                return error_response("PERMISSION_DENIED", "No branch assigned.", status=403)

        if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED):
            return error_response(
                "VALIDATION_ERROR",
                "Only pending or confirmed bookings can accept cash payment.",
                status=400,
            )
        if booking.payment_status != Booking.PaymentStatus.UNPAID:
            return error_response(
                "VALIDATION_ERROR",
                "Booking is already paid or has a pending refund.",
                status=400,
            )

        body = CashPaymentSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        try:
            confirm_cash_payment(
                booking,
                changed_by=user,
                notes=body.validated_data.get("notes", ""),
                payment_reference=body.validated_data.get("payment_reference", ""),
            )
        except ValueError as exc:
            return error_response("VALIDATION_ERROR", str(exc), status=400)

        booking.refresh_from_db()
        return success_response(BookingSerializer(booking).data)


class BookingStatusLogView(generics.ListAPIView):
    permission_classes = [IsAdminOrAbove]
    serializer_class = BookingStatusLogSerializer
    lookup_field = "pk"

    def get_queryset(self):
        booking_id = self.kwargs["pk"]
        user = self.request.user
        qs = BookingStatusLog.objects.filter(booking_id=booking_id).select_related(
            "changed_by"
        )
        if user.role == "admin":
            try:
                branch_id = user.admin_branch.branch_id
            except AdminBranch.DoesNotExist:
                return BookingStatusLog.objects.none()
            qs = qs.filter(booking__branch_id=branch_id)
        return qs.order_by("-created_at")

    def list(self, request, *args, **kwargs):
        return paginated_response(self.get_queryset(), request, BookingStatusLogSerializer)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _revert_booking_coupons(booking: Booking) -> None:
    """Revert all coupons on a booking back to DISPATCHED status."""
    coupon_ids = list(booking.coupons_applied.values_list("pk", flat=True))
    if coupon_ids:
        Coupon.objects.filter(pk__in=coupon_ids).update(
            status=Coupon.Status.DISPATCHED,
            redeemed_by=None,
            redeemed_at_booking=None,
            redeemed_at_branch=None,
            redeemed_on=None,
        )
        booking.coupons_applied.clear()
