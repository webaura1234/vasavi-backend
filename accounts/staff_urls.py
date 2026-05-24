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
from bookings.staff_views import StaffBookingRefundView, StaffManualBookingCreateView
from properties.staff_views import (
    StaffRoomDetailView,
    StaffRoomImageDeleteView,
    StaffRoomImageUploadView,
    StaffRoomListCreateView,
    StaffRoomSearchView,
)

app_name = "staff"

urlpatterns = [
    path("otp/send/", StaffOTPSendView.as_view(), name="staff-otp-send"),
    path("otp/verify/", StaffOTPVerifyView.as_view(), name="staff-otp-verify"),
    path("token/refresh/", StaffTokenRefreshView.as_view(), name="staff-token-refresh"),
    path("logout/", StaffLogoutView.as_view(), name="staff-logout"),
    path("me/", StaffMeView.as_view(), name="staff-me"),
    path("admins/", StaffManagementView.as_view(), name="staff-admins"),
    path("bookings/", StaffManualBookingCreateView.as_view(), name="staff-bookings-create"),
    path(
        "bookings/<uuid:pk>/refund/",
        StaffBookingRefundView.as_view(),
        name="staff-booking-refund",
    ),
    path("rooms/", StaffRoomListCreateView.as_view(), name="staff-rooms"),
    path("rooms/search/", StaffRoomSearchView.as_view(), name="staff-rooms-search"),
    path("rooms/<uuid:pk>/", StaffRoomDetailView.as_view(), name="staff-room-detail"),
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
]
