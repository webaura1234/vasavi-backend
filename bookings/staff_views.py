"""Staff portal booking operations."""

from __future__ import annotations

import csv
import io
import logging
from pathlib import Path

from django.db import transaction
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from rest_framework import serializers as drf_serializers
from rest_framework.views import APIView

from bookings.models import Booking, BookingStatusLog
from bookings.query_filters import apply_booking_list_filters, bookings_to_csv_rows
from bookings.serializers import BookingSerializer
from bookings.services.staff_guest import lookup_guest_by_phone
from bookings.staff_serializers import StaffManualBookingCreateSerializer
from bookings.views import _booking_queryset_for_user
from permissions import IsAdminOrAbove
from utils.phone import is_valid_indian_phone, normalize_indian_phone
from utils.responses import error_response, success_response

logger = logging.getLogger("vasavi.bookings.staff_views")


class StaffGuestLookupView(APIView):
    """Look up a guest or donor by phone for manual booking."""

    permission_classes = [IsAdminOrAbove]

    def get(self, request):
        raw = (request.query_params.get("phone") or "").strip()
        if not is_valid_indian_phone(raw):
            return error_response(
                "VALIDATION_ERROR",
                "Enter a valid 10-digit Indian mobile number.",
                status=400,
            )
        phone = normalize_indian_phone(raw)
        return success_response(lookup_guest_by_phone(phone))


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

        booking = _booking_queryset_for_user(request.user).get(pk=booking.pk)
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
            booking = _booking_queryset_for_user(request.user).get(pk=booking.pk)
            return success_response(BookingSerializer(booking).data)

        # Approve → delegate to StaffBookingRefundView logic
        return StaffBookingRefundView().post(request, pk)


class StaffBookingExportRequestView(APIView):
    """Create or list async xlsx export jobs.

    POST /api/v1/staff/bookings/export/
        Create a new export job (returns export_id, status, estimated_count).

    GET /api/v1/staff/bookings/export/
        Paginated history of exports for the current user (super_admin sees all).
    """

    permission_classes = [IsAdminOrAbove]

    def get(self, request):
        from bookings.models import BookingExport
        from bookings.services.export import serialize_booking_export

        qs = (
            BookingExport.objects.select_related("branch", "requested_by")
            .order_by("-created_at")
        )
        if request.user.role != "super_admin":
            qs = qs.filter(requested_by=request.user)

        page = max(int(request.query_params.get("page", 1)), 1)
        page_size = min(max(int(request.query_params.get("page_size", 20)), 1), 100)
        start = (page - 1) * page_size
        end = start + page_size
        total = qs.count()
        exports = qs[start:end]

        return success_response({
            "count": total,
            "next": page * page_size < total,
            "previous": page > 1,
            "page": page,
            "page_size": page_size,
            "results": [serialize_booking_export(item) for item in exports],
        })

    def post(self, request):
        from bookings.models import BookingExport
        from bookings.services.export import build_booking_export_queryset
        from bookings.tasks import generate_booking_export

        user    = request.user
        filters = {k: v for k, v in request.data.items() if isinstance(v, str)}

        # Audit snapshot: capture role at request time so the task can
        # reconstruct the correct security scope even if role changes later.
        filters["_requesting_user_role"] = user.role
        filters["_requesting_user_id"]   = str(user.pk)

        # Cheap count query — uses the same scoped + filtered queryset the
        # task will use, but only runs COUNT(*) instead of fetching rows.
        try:
            count_qs = build_booking_export_queryset(filters, user)
            estimated_count = count_qs.count()
        except Exception:
            estimated_count = None

        # Resolve branch FK for the audit record
        branch_id = None
        if user.role == "admin":
            from accounts.branch_scope import staff_branch_id
            branch_id = staff_branch_id(user)
        elif user.role == "super_admin":
            branch_id = (filters.get("branch_id") or None)

        export = BookingExport.objects.create(
            requested_by    = user,
            branch_id       = branch_id,
            status          = BookingExport.Status.PENDING,
            filters_applied = filters,
            estimated_count = estimated_count,
            progress_percent = 5,
        )

        export_id = str(export.pk)
        enqueued = False
        try:
            generate_booking_export.apply_async(
                kwargs={"export_id": export_id},
                queue="exports",
            )
            enqueued = True
        except Exception:
            logger.warning(
                "Celery unavailable — running booking export synchronously: id=%s",
                export_id,
                exc_info=True,
            )
            from bookings.services.export import run_booking_export

            run_booking_export(export_id=export_id, requesting_user_id=None)
            export.refresh_from_db()

        logger.info(
            "Booking export %s: id=%s user=%s role=%s estimated=%s",
            "enqueued" if enqueued else "completed_inline",
            export.pk,
            user.phone,
            user.role,
            estimated_count,
        )

        return success_response({
            "export_id":         export_id,
            "status":            export.status,
            "estimated_count":   estimated_count,
            "progress_percent":  export.progress_percent,
        }, status=202)


class StaffBookingExportStatusView(APIView):
    """Poll the status of an async export job.

    GET /api/v1/staff/bookings/export/{pk}/

    Returns:
        { export_id, status, download_url, record_count, error_message }

    ``download_url`` is a staff-authenticated API path — not a public media URL.
    The portal must fetch it with the user's bearer token (via its backend proxy).

    Security: only the requesting user can see their own export.
    Super admins can see any export for oversight.
    """

    permission_classes = [IsAdminOrAbove]

    def get(self, request, pk):
        from bookings.models import BookingExport
        from bookings.services.export import (
            serialize_booking_export,
            user_can_access_booking_export,
        )

        try:
            export = BookingExport.objects.select_related("branch").get(pk=pk)
        except (BookingExport.DoesNotExist, Exception):
            return error_response("NOT_FOUND", "Export job not found.", status=404)

        if not user_can_access_booking_export(export, request.user):
            return error_response(
                "PERMISSION_DENIED",
                "You do not have access to this export.",
                status=403,
            )

        return success_response(serialize_booking_export(export))


class StaffBookingExportDownloadView(APIView):
    """Download a completed booking export (.xlsx).

    GET /api/v1/staff/bookings/export/{pk}/download/

    Streams the file with ``Content-Disposition: attachment`` after verifying
    ownership and expiry. Never expose files via unauthenticated ``/media/``.
    """

    permission_classes = [IsAdminOrAbove]

    def get(self, request, pk):
        from bookings.models import BookingExport
        from bookings.services.export import (
            export_is_downloadable,
            user_can_access_booking_export,
        )

        try:
            export = BookingExport.objects.get(pk=pk)
        except BookingExport.DoesNotExist:
            return error_response("NOT_FOUND", "Export job not found.", status=404)

        if not user_can_access_booking_export(export, request.user):
            return error_response(
                "PERMISSION_DENIED",
                "You do not have access to this export.",
                status=403,
            )

        if export.status in (
            BookingExport.Status.PENDING,
            BookingExport.Status.PROCESSING,
        ):
            return error_response(
                "NOT_READY",
                "Export is still being generated. Please try again shortly.",
                status=409,
            )

        if export.status == BookingExport.Status.FAILED:
            return error_response(
                "EXPORT_FAILED",
                export.error_message or "Export generation failed.",
                status=410,
            )

        if export.expires_at and export.expires_at <= timezone.now():
            return error_response(
                "EXPIRED",
                "This export has expired. Please generate a new export.",
                status=410,
            )

        if not export_is_downloadable(export):
            return error_response(
                "NOT_FOUND",
                "Export file is no longer available.",
                status=404,
            )

        filename = Path(export.file_path).name
        response = FileResponse(
            open(export.file_path, "rb"),
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            as_attachment=True,
            filename=filename,
        )
        response["Cache-Control"] = "private, no-store"
        return response


class StaffBookingExportCountView(APIView):
    """Return the estimated record count for the current filter set.

    GET /api/v1/staff/bookings/export/count/?status=confirmed&date_from=2026-01-01

    Uses the same scoped queryset as the export itself but only executes
    a COUNT(*) query — cheap enough to call on every filter change in the UI.
    """

    permission_classes = [IsAdminOrAbove]

    def get(self, request):
        from bookings.services.export import build_booking_export_queryset

        filters = dict(request.query_params)
        # query_params returns lists; flatten single-value params to strings
        filters = {k: v[0] if isinstance(v, list) and len(v) == 1 else v
                   for k, v in filters.items()}

        try:
            qs    = build_booking_export_queryset(filters, request.user)
            count = qs.count()
        except Exception:
            count = 0

        return success_response({"count": count})


class StaffBookingExportView(APIView):
    """Export bookings to CSV."""

    permission_classes = [IsAdminOrAbove]

    def get(self, request):
        qs = _booking_queryset_for_user(request.user)
        branch_id = request.query_params.get("branch_id")
        if branch_id and request.user.role == "super_admin":
            qs = qs.filter(branch_id=branch_id)
        qs = apply_booking_list_filters(qs, request.query_params)
        bookings = list(qs.order_by("-created_at"))

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="bookings.csv"'

        writer = csv.writer(response)
        rows = bookings_to_csv_rows(bookings)
        writer.writerows(rows)

        return response

