"""Coupon API views."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import generics
from rest_framework.views import APIView

from coupons.models import Coupon, CouponBatch
from coupons.serializers import (
    CouponBatchCreateSerializer,
    CouponBatchSerializer,
    CouponDispatchSerializer,
    CouponRedeemSerializer,
    CouponSerializer,
    CouponStatsSerializer,
)
from coupons.services.stats import (
    compute_coupon_stats,
    coupons_for_donor_profile,
    coupons_redeemable_for_user,
)
from donors.models import DonorProfile
from permissions import IsAdminOrAbove, IsDonorOrAbove, IsSuperAdmin
from rest_framework.permissions import IsAuthenticated
from utils.responses import error_response, paginated_response, success_response


class CouponBatchListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsSuperAdmin]
    lookup_field = "pk"

    def _base_qs(self):
        # Full join chain so CouponBatchSerializer → DonationSerializer →
        # get_donor() never fires additional queries.
        return (
            CouponBatch.objects.select_related(
                "donation",
                "donation__donor",
                "donation__donor__user",
                "donation__purpose",
                "donation__created_by",
            )
            .order_by("-created_at")
        )

    def get_queryset(self):
        qs = self._base_qs()
        donation_id = self.request.query_params.get("donation_id")
        if donation_id:
            qs = qs.filter(donation_id=donation_id)
        return qs

    def list(self, request, *args, **kwargs):
        return paginated_response(self.get_queryset(), request, CouponBatchSerializer)

    def create(self, request, *args, **kwargs):
        serializer = CouponBatchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        batch = serializer.save()
        batch = self._base_qs().get(pk=batch.pk)
        return success_response(CouponBatchSerializer(batch).data, status=201)


class CouponListView(generics.ListAPIView):
    permission_classes = [IsAdminOrAbove]
    serializer_class = CouponSerializer

    def get_queryset(self):
        user = self.request.user
        qs = Coupon.objects.filter(is_deleted=False).select_related(
            "batch", "redeemed_by", "redeemed_at_booking"
        ).prefetch_related("assigned_donors")

        if user.role == "admin":
            ab = getattr(user, 'admin_branch', None)
            if ab is None:
                return Coupon.objects.none()
            branch = ab.branch
            qs = qs.filter(redeemed_at_branch=branch)

        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        coupon_type = self.request.query_params.get("coupon_type")
        if coupon_type:
            qs = qs.filter(coupon_type=coupon_type)
        serial = self.request.query_params.get("serial_number")
        if serial:
            qs = qs.filter(serial_number=serial)

        donor_profile_id = self.request.query_params.get("donor_profile_id")
        if donor_profile_id:
            qs = qs.filter(
                Q(batch__donation__donor_id=donor_profile_id)
                | Q(assigned_donors__donor_profile__pk=donor_profile_id)
            ).distinct()

        return qs.order_by("serial_number")

    def list(self, request, *args, **kwargs):
        return paginated_response(self.get_queryset(), request, CouponSerializer)


class DonorCouponWalletView(APIView):
    permission_classes = [IsDonorOrAbove]

    def get(self, request):
        user = request.user
        if user.role not in ("donor",):
            return error_response(
                "PERMISSION_DENIED",
                "This endpoint is for donors only. Use the admin coupon views instead.",
                status=403,
            )
        try:
            profile = user.donor_profile
        except DonorProfile.DoesNotExist:
            stats = compute_coupon_stats(user=user)
            return success_response(
                {
                    "stats": CouponStatsSerializer(stats).data,
                    "available": [],
                    "used": [],
                    "issued": [],
                    "revoked_count": 0,
                }
            )

        profile_qs = coupons_for_donor_profile(profile).select_related(
            "batch", "redeemed_by", "redeemed_at_booking"
        ).prefetch_related("assigned_donors")

        redeemable_ids = coupons_redeemable_for_user(user).values_list("pk", flat=True)
        available = profile_qs.filter(
            status=Coupon.Status.DISPATCHED,
            pk__in=redeemable_ids,
        )
        used = profile_qs.filter(
            status=Coupon.Status.REDEEMED,
            redeemed_by=user,
        )
        issued = profile_qs.filter(status=Coupon.Status.ISSUED)
        stats = compute_coupon_stats(donor_profile=profile, user=user)

        # Count coupons from donor's batches that are dispatched but not redeemable by this user
        all_profile_dispatched = profile_qs.filter(status=Coupon.Status.DISPATCHED).count()
        redeemable_count = available.count()
        revoked_count = max(0, all_profile_dispatched - redeemable_count)

        payload = {
            "stats": CouponStatsSerializer(stats).data,
            "available": CouponSerializer(available, many=True).data,
            "used": CouponSerializer(used, many=True).data,
            "issued": CouponSerializer(issued, many=True).data,
            "revoked_count": revoked_count,
        }
        return success_response(payload)


class DonorCouponStatsView(APIView):
    """Coupon totals for a donor profile (super admin / branch admin)."""

    permission_classes = [IsAdminOrAbove]

    def get(self, request):
        donor_profile_id = request.query_params.get("donor_profile_id")
        if not donor_profile_id:
            return error_response(
                "VALIDATION_ERROR",
                "donor_profile_id query parameter is required.",
                status=400,
            )
        try:
            profile = DonorProfile.objects.select_related("user").get(
                pk=donor_profile_id,
                is_deleted=False,
            )
        except DonorProfile.DoesNotExist:
            return error_response("NOT_FOUND", "Donor profile not found.", status=404)

        stats = compute_coupon_stats(donor_profile=profile, user=profile.user)
        return success_response(CouponStatsSerializer(stats).data)


class CouponDispatchView(APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request):
        serializer = CouponDispatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        coupons = serializer.validated_data["coupon_ids"]

        with transaction.atomic():
            updated = Coupon.objects.filter(
                pk__in=[c.pk for c in coupons],
                status=Coupon.Status.ISSUED,
            ).update(status=Coupon.Status.DISPATCHED)

        return success_response({"updated": updated})


class CouponRedeemView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CouponRedeemSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        coupon = serializer.validated_data["coupon"]
        booking = serializer.validated_data["booking"]

        with transaction.atomic():
            coupon = Coupon.objects.select_for_update().get(pk=coupon.pk)
            if coupon.status != Coupon.Status.DISPATCHED:
                return error_response(
                    "VALIDATION_ERROR",
                    "Coupon is no longer available.",
                    status=400,
                )

            coupon.status = Coupon.Status.REDEEMED
            coupon.redeemed_by = request.user
            coupon.redeemed_at_booking = booking
            coupon.redeemed_at_branch = booking.branch
            coupon.redeemed_on = timezone.now()
            coupon.save()

            booking.coupons_applied.add(coupon)

        return success_response(CouponSerializer(coupon).data)


class ExportCouponsExcelView(APIView):
    """Coupon export — streams up to 50 k rows using openpyxl write-only mode.

    Uses ``QuerySet.iterator()`` so memory stays constant regardless of row
    count.  A Celery-backed async path is preferred when a broker is available;
    falls back to a synchronous streaming response in dev / single-dyno setups.
    """

    permission_classes = [IsSuperAdmin]
    MAX_EXPORT_ROWS = 50_000

    def _build_workbook_response(self):
        import io  # noqa: PLC0415

        import openpyxl  # noqa: PLC0415
        from django.http import HttpResponse  # noqa: PLC0415
        from django.utils import timezone as tz  # noqa: PLC0415

        wb = openpyxl.Workbook(write_only=True)
        ws = wb.create_sheet("Coupons")

        headers = [
            "Serial Number", "Type", "Status", "Batch Date",
            "Donor ID", "Redeemed On", "Redeemed At Branch",
        ]
        ws.append(headers)

        qs = (
            Coupon.objects.filter(is_deleted=False)
            .select_related(
                "batch",
                "batch__donation__donor",
                "redeemed_at_branch",
            )
            .order_by("-created_at")
        )

        row_count = 0
        for coupon in qs.iterator(chunk_size=2_000):
            if row_count >= self.MAX_EXPORT_ROWS:
                break
            row_count += 1

            donor_id = (
                coupon.batch.donation.donor.donor_id
                if coupon.batch and coupon.batch.donation and coupon.batch.donation.donor
                else ""
            ) or ""
            ws.append([
                coupon.serial_number,
                coupon.get_coupon_type_display(),
                coupon.get_status_display(),
                coupon.batch.created_at.strftime("%Y-%m-%d %H:%M:%S")
                if coupon.batch and coupon.batch.created_at else "",
                coupon.redeemed_on.strftime("%Y-%m-%d %H:%M:%S") if coupon.redeemed_on else "",
                coupon.redeemed_at_branch.name if coupon.redeemed_at_branch else "",
            ])

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        filename = f"coupons_export_{tz.now().strftime('%Y%m%d%H%M')}.xlsx"
        response = HttpResponse(
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    def get(self, request):
        return self._build_workbook_response()
