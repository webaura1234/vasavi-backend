"""Staff portal analytics API."""

from __future__ import annotations

from bookings.services.analytics import (
    build_dashboard_collections_chart,
    build_dashboard_stats,
    build_finance_analytics,
    build_reports_analytics,
)
from donors.services.analytics import build_donor_analytics
from permissions import IsAdminOrAbove, IsSuperAdmin
from rest_framework.views import APIView
from utils.responses import error_response, success_response


class StaffDashboardAnalyticsView(APIView):
    """Operations dashboard live stats (today, occupancy, rolling 7d totals)."""

    permission_classes = [IsAdminOrAbove]

    def get(self, request):
        branch_id = request.query_params.get("branch_id")
        data = build_dashboard_stats(request.user, branch_id)
        return success_response(data)


class StaffDashboardCollectionsChartView(APIView):
    """Collections & donor savings chart for a selected period."""

    permission_classes = [IsAdminOrAbove]

    def get(self, request):
        branch_id = request.query_params.get("branch_id")
        data = build_dashboard_collections_chart(
            request.user,
            branch_id,
            query_params=request.query_params,
        )
        return success_response(data)


class StaffReportsAnalyticsView(APIView):
    """Reports page summary and revenue trend."""

    permission_classes = [IsAdminOrAbove]

    def get(self, request):
        branch_id = request.query_params.get("branch_id")
        data = build_reports_analytics(
            request.user,
            branch_id,
            query_params=request.query_params,
        )
        return success_response(data)


class StaffFinanceAnalyticsView(APIView):
    """Finance module summary cards."""

    permission_classes = [IsAdminOrAbove]

    def get(self, request):
        branch_id = request.query_params.get("branch_id")
        data = build_finance_analytics(
            request.user,
            branch_id,
            query_params=request.query_params,
        )
        return success_response(data)


class StaffDonorAnalyticsView(APIView):
    """Platform-wide donor analytics (super admin)."""

    permission_classes = [IsSuperAdmin]

    def get(self, request):
        try:
            data = build_donor_analytics()
        except Exception as exc:  # pragma: no cover
            return error_response(
                "SERVER_ERROR",
                str(exc),
                status=500,
            )
        return success_response(data)
