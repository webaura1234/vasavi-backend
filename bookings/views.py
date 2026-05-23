"""Booking API views and Razorpay webhook handler."""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework import generics
from rest_framework.views import APIView

from accounts.models import AdminBranch
from bookings.models import Booking, BookingStatusLog
from bookings.serializers import (
    BookingCreateSerializer,
    BookingExtendStaySerializer,
    BookingSerializer,
    BookingStatusLogSerializer,
    BookingStatusUpdateSerializer,
    CashPaymentSerializer,
    PaymentOrderSerializer,
)
from bookings.tasks import razorpay_create_order
from bookings.services.payments import confirm_booking_payment, confirm_cash_payment
from bookings.services.razorpay import RazorpayError, create_order_for_booking
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
        if self.request.method == "POST":
            return [PermIsAuthenticated()]
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
    permission_classes = [PermIsAuthenticated]

    def post(self, request, pk):
        try:
            booking = Booking.objects.get(pk=pk, is_deleted=False)
        except Booking.DoesNotExist:
            return error_response("NOT_FOUND", "Booking not found.", status=404)

        user = request.user
        if user.role in ("user", "donor") and booking.user_id != user.pk:
            return error_response("PERMISSION_DENIED", "Not your booking.", status=403)
        if user.role == "admin":
            try:
                if booking.branch_id != user.admin_branch.branch_id:
                    return error_response("PERMISSION_DENIED", "Out of branch scope.", status=403)
            except AdminBranch.DoesNotExist:
                return error_response("PERMISSION_DENIED", "No branch assigned.", status=403)

        if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED):
            return error_response(
                "VALIDATION_ERROR",
                "Booking cannot be cancelled in its current status.",
                status=400,
            )

        reason = request.data.get("reason", "")
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
            booking.save(
                update_fields=[
                    "status",
                    "cancelled_at",
                    "cancellation_reason",
                    "updated_at",
                ]
            )

            coupon_ids = list(
                booking.coupons_applied.values_list("pk", flat=True)
            )
            if coupon_ids:
                Coupon.objects.filter(pk__in=coupon_ids).update(
                    status=Coupon.Status.DISPATCHED,
                    redeemed_by=None,
                    redeemed_at_booking=None,
                    redeemed_at_branch=None,
                    redeemed_on=None,
                )
                booking.coupons_applied.clear()

            BookingStatusLog.objects.create(
                booking=booking,
                from_status=old_status,
                to_status=Booking.Status.CANCELLED,
                changed_by=user,
                reason=reason,
            )

            if booking.payment_status == Booking.PaymentStatus.PAID:
                logger.warning(
                    "Paid booking %s cancelled — manual refund may be required.",
                    booking.booking_reference,
                )

        return success_response(BookingSerializer(booking).data)


class BookingPaymentOrderView(APIView):
    permission_classes = [PermIsAuthenticated]
    throttle_classes = [PaymentThrottle]

    def post(self, request, pk):
        try:
            booking = Booking.objects.get(pk=pk, is_deleted=False)
        except Booking.DoesNotExist:
            return error_response("NOT_FOUND", "Booking not found.", status=404)

        if booking.user_id != request.user.pk and request.user.role not in (
            "admin",
            "super_admin",
        ):
            return error_response("PERMISSION_DENIED", "Not allowed.", status=403)

        if booking.status != Booking.Status.PENDING:
            return error_response(
                "VALIDATION_ERROR",
                "Payment can only be initiated for pending bookings.",
                status=400,
            )
        if booking.payment_status != Booking.PaymentStatus.UNPAID:
            return error_response(
                "VALIDATION_ERROR",
                "Booking is already paid or refunded.",
                status=400,
            )

        # Zero payable amount (e.g. free coupon) — skip Razorpay, confirm immediately.
        if booking.final_amount <= 0:
            confirm_booking_payment(
                booking,
                gateway=Booking.PaymentGateway.OTHER,
                payment_reference="COMPLIMENTARY",
                changed_by=request.user,
                reason="Complimentary booking — payment not required",
                amount_paise=0,
            )
            booking.refresh_from_db()
            return success_response(
                {
                    "order_id": None,
                    "amount_paise": 0,
                    "currency": settings.RAZORPAY_CURRENCY,
                    "razorpay_key_id": settings.RAZORPAY_KEY_ID,
                    "booking_reference": booking.booking_reference,
                }
            )

        try:
            async_result = razorpay_create_order.delay(str(booking.pk))
            order_data = async_result.get(timeout=20)
        except Exception:
            try:
                order_data = create_order_for_booking(booking.pk)
            except RazorpayError as exc:
                return error_response("SERVER_ERROR", str(exc), status=502)

        payload = {
            "order_id": order_data["order_id"],
            "amount_paise": order_data["amount"],
            "currency": order_data.get("currency", settings.RAZORPAY_CURRENCY),
            "razorpay_key_id": settings.RAZORPAY_KEY_ID,
            "booking_reference": booking.booking_reference,
        }
        return success_response(PaymentOrderSerializer(payload).data)


def _user_may_access_booking(user, booking: Booking) -> bool:
    if booking.user_id == user.pk:
        return True
    if user.role in ("admin", "super_admin"):
        if user.role == "super_admin":
            return True
        try:
            branch_id = user.admin_branch.branch_id
        except AdminBranch.DoesNotExist:
            return False
        return booking.branch_id == branch_id
    return False


class BookingCashPaymentView(APIView):
    """Confirm a pending booking with cash (guest checkout or staff at desk)."""

    permission_classes = [PermIsAuthenticated]
    throttle_classes = [PaymentThrottle]

    def post(self, request, pk):
        user = request.user
        guest_roles = ("user", "donor")
        if user.role in guest_roles and not getattr(settings, "CASH_CHECKOUT_ENABLED", False):
            return error_response(
                "PERMISSION_DENIED",
                "Cash checkout is not enabled.",
                status=403,
            )

        try:
            booking = Booking.objects.select_related("branch").get(pk=pk, is_deleted=False)
        except Booking.DoesNotExist:
            return error_response("NOT_FOUND", "Booking not found.", status=404)

        if not _user_may_access_booking(user, booking):
            return error_response("PERMISSION_DENIED", "Not allowed.", status=403)

        if booking.status != Booking.Status.PENDING:
            return error_response(
                "VALIDATION_ERROR",
                "Only pending bookings can accept cash payment.",
                status=400,
            )
        if booking.payment_status != Booking.PaymentStatus.UNPAID:
            return error_response(
                "VALIDATION_ERROR",
                "Booking is already paid or refunded.",
                status=400,
            )

        body = CashPaymentSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        try:
            confirm_cash_payment(
                booking,
                changed_by=user,
                notes=body.validated_data.get("notes", ""),
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


@csrf_exempt
@require_POST
def razorpay_webhook(request):
    """
    Accept Razorpay webhooks and process them asynchronously.

    Returns 200 immediately so Razorpay does not retry while work runs in Celery.
    """
    from bookings.tasks import razorpay_verify_payment_webhook

    signature = request.headers.get("X-Razorpay-Signature", "")
    raw_body = request.body.decode("utf-8")

    try:
        payload = json.loads(raw_body) if raw_body else None
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_json"}, status=400)

    razorpay_verify_payment_webhook.delay(raw_body, signature, payload)
    return HttpResponse(status=200)
