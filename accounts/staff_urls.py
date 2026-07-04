"""Staff portal URL routes (vasavi-role-portal)."""

from django.urls import path

from accounts.staff_views import (
    StaffLogoutView,
    StaffMeView,
    StaffManagementView,
    StaffOTPSendView,
    StaffOTPVerifyView,
    StaffTokenRefreshView,
)
from bookings.staff_analytics_views import (
    StaffDashboardAnalyticsView,
    StaffDashboardCollectionsChartView,
    StaffDonorAnalyticsView,
    StaffFinanceAnalyticsView,
    StaffReportsAnalyticsView,
)
from bookings.staff_views import (
    StaffBookingExportRequestView,
    StaffBookingExportStatusView,
    StaffBookingExportDownloadView,
    StaffBookingExportCountView,
    StaffBookingRefundView,
    StaffGuestLookupView,
    StaffManualBookingCreateView,
    StaffRefundApprovalView,
)
from donors.staff_views import StaffDonorCouponListView
from support.staff_views import (
    StaffSupportTicketListCreateView,
    StaffSupportTicketStatusView,
)
from properties.staff_views import (
    StaffRoomDetailView,
    StaffRoomImageDeleteView,
    StaffRoomImageUploadView,
    StaffRoomListCreateView,
    StaffRoomOperationalStatusView,
    StaffRoomSearchView,
)
from properties.function_hall_staff_views import (
    StaffFunctionHallDetailUpdateView,
    StaffFunctionHallImageDeleteView,
    StaffFunctionHallImageUploadView,
    StaffFunctionHallListCreateView,
    StaffFunctionHallOperationalStatusView,
    StaffFunctionHallSearchView,
)

app_name = "staff"

urlpatterns = [
    path("otp/send/", StaffOTPSendView.as_view(), name="staff-otp-send"),
    path("otp/verify/", StaffOTPVerifyView.as_view(), name="staff-otp-verify"),
    path("token/refresh/", StaffTokenRefreshView.as_view(), name="staff-token-refresh"),
    path("logout/", StaffLogoutView.as_view(), name="staff-logout"),
    path("me/", StaffMeView.as_view(), name="staff-me"),
    path("admins/", StaffManagementView.as_view(), name="staff-admins"),
    path(
        "donors/coupons/",
        StaffDonorCouponListView.as_view(),
        name="staff-donor-coupons",
    ),
    path(
        "analytics/dashboard/",
        StaffDashboardAnalyticsView.as_view(),
        name="staff-analytics-dashboard",
    ),
    path(
        "analytics/dashboard/collections/",
        StaffDashboardCollectionsChartView.as_view(),
        name="staff-analytics-dashboard-collections",
    ),
    path(
        "analytics/reports/",
        StaffReportsAnalyticsView.as_view(),
        name="staff-analytics-reports",
    ),
    path(
        "analytics/finance/",
        StaffFinanceAnalyticsView.as_view(),
        name="staff-analytics-finance",
    ),
    path(
        "analytics/donors/",
        StaffDonorAnalyticsView.as_view(),
        name="staff-analytics-donors",
    ),
    path(
        "guests/lookup/",
        StaffGuestLookupView.as_view(),
        name="staff-guest-lookup",
    ),
    path("bookings/", StaffManualBookingCreateView.as_view(), name="staff-bookings-create"),
    path(
        "bookings/export/",
        StaffBookingExportRequestView.as_view(),
        name="staff-bookings-export",
    ),
    path(
        "bookings/export/count/",
        StaffBookingExportCountView.as_view(),
        name="staff-bookings-export-count",
    ),
    path(
        "bookings/export/<uuid:pk>/download/",
        StaffBookingExportDownloadView.as_view(),
        name="staff-bookings-export-download",
    ),
    path(
        "bookings/export/<uuid:pk>/",
        StaffBookingExportStatusView.as_view(),
        name="staff-bookings-export-status",
    ),
    path(
        "bookings/<uuid:pk>/refund/",
        StaffBookingRefundView.as_view(),
        name="staff-booking-refund",
    ),
    path(
        "bookings/refund-requests/",
        StaffRefundApprovalView.as_view(),
        name="staff-refund-requests",
    ),
    path(
        "bookings/<uuid:pk>/refund-approval/",
        StaffRefundApprovalView.as_view(),
        name="staff-refund-approval",
    ),
    path("support/tickets/", StaffSupportTicketListCreateView.as_view(), name="staff-support-tickets"),
    path(
        "support/tickets/<uuid:pk>/status/",
        StaffSupportTicketStatusView.as_view(),
        name="staff-support-ticket-status",
    ),
    path("rooms/", StaffRoomListCreateView.as_view(), name="staff-rooms"),
    path("rooms/search/", StaffRoomSearchView.as_view(), name="staff-rooms-search"),
    path("rooms/<uuid:pk>/", StaffRoomDetailView.as_view(), name="staff-room-detail"),
    path(
        "rooms/<uuid:pk>/operational-status/",
        StaffRoomOperationalStatusView.as_view(),
        name="staff-room-operational-status",
    ),
    path(
        "rooms/<uuid:pk>/images/",
        StaffRoomImageUploadView.as_view(),
        name="staff-room-images",
    ),
    path(
        "rooms/<uuid:pk>/images/<uuid:image_id>/",
        StaffRoomImageDeleteView.as_view(),
        name="staff-room-image-delete",
    ),
    path(
        "function-halls/",
        StaffFunctionHallListCreateView.as_view(),
        name="staff-function-hall-list",
    ),
    path(
        "function-halls/search/",
        StaffFunctionHallSearchView.as_view(),
        name="staff-function-hall-search",
    ),
    path(
        "function-halls/<uuid:pk>/",
        StaffFunctionHallDetailUpdateView.as_view(),
        name="staff-function-hall-detail",
    ),
    path(
        "function-halls/<uuid:pk>/operational-status/",
        StaffFunctionHallOperationalStatusView.as_view(),
        name="staff-function-hall-status",
    ),
    path(
        "function-halls/<uuid:pk>/images/",
        StaffFunctionHallImageUploadView.as_view(),
        name="staff-function-hall-images",
    ),
    path(
        "function-halls/<uuid:pk>/images/<uuid:image_pk>/",
        StaffFunctionHallImageDeleteView.as_view(),
        name="staff-function-hall-image-delete",
    ),
]
