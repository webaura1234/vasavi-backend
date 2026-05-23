"""Coupon API views."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Count, Q
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
    CouponWalletSerializer,
)
from permissions import IsAdminOrAbove, IsDonorOrAbove, IsSuperAdmin
from rest_framework.permissions import IsAuthenticated
from utils.responses import error_response, paginated_response, success_response


class CouponBatchListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsSuperAdmin]
    lookup_field = "pk"

    def get_queryset(self):
        qs = CouponBatch.objects.select_related("donation").order_by("-created_at")
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
        batch = CouponBatch.objects.select_related("donation").get(pk=batch.pk)
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
            try:
                branch = user.admin_branch.branch
            except Exception:
                return Coupon.objects.none()
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

        return qs.order_by("serial_number")

    def list(self, request, *args, **kwargs):
        return paginated_response(self.get_queryset(), request, CouponSerializer)


class DonorCouponWalletView(APIView):
    permission_classes = [IsDonorOrAbove]

    def get(self, request):
        user = request.user
        base = (
            Coupon.objects.filter(is_deleted=False)
            .annotate(assigned_count=Count("assigned_donors"))
            .filter(Q(assigned_count=0) | Q(assigned_donors=user))
            .select_related("batch", "redeemed_by", "redeemed_at_booking")
            .prefetch_related("assigned_donors")
            .distinct()
        )

        available = base.filter(status=Coupon.Status.DISPATCHED)
        used = base.filter(status=Coupon.Status.REDEEMED, redeemed_by=user)
        dispatched = base.filter(status=Coupon.Status.DISPATCHED)

        payload = {
            "available": CouponSerializer(available, many=True).data,
            "used": CouponSerializer(used, many=True).data,
            "dispatched": CouponSerializer(dispatched, many=True).data,
        }
        return success_response(payload)


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
