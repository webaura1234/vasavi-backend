"""Staff portal donor coupon tracking (branch admin read-only)."""

from __future__ import annotations

from django.db.models import Q, Sum

from accounts.branch_scope import staff_branch_id
from donors.models import DonorProfile
from donors.serializers import StaffDonorCouponSerializer
from permissions import IsAdminOrAbove
from rest_framework.views import APIView
from utils.responses import error_response, paginated_response


class StaffDonorCouponListView(APIView):
    """Donors with coupon lifecycle counts for branch admin coupon tracking."""

    permission_classes = [IsAdminOrAbove]

    def get(self, request):
        if request.user.role != "admin":
            return error_response(
                "PERMISSION_DENIED",
                "Coupon tracking is available to branch admins only.",
                status=403,
            )

        branch_id = staff_branch_id(request.user)
        if not branch_id:
            return error_response(
                "VALIDATION_ERROR",
                "No branch assigned to this admin account.",
                status=400,
            )

        qs = (
            DonorProfile.objects.filter(is_deleted=False, for_place_id=branch_id)
            .select_related("user", "membership_tier", "for_place")
            .annotate(total_donated_paise=Sum("donations__amount"))
            .order_by("user__name")
        )

        search = request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(user__name__icontains=search)
                | Q(user__phone__icontains=search)
                | Q(donor_id__icontains=search)
            )

        return paginated_response(qs, request, StaffDonorCouponSerializer)
