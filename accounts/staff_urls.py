"""Staff portal URL routes (vasavi-role-portal)."""

from django.urls import path

from accounts.staff_views import (
    StaffLogoutView,
    StaffMeView,
    StaffOTPSendView,
    StaffOTPVerifyView,
    StaffTokenRefreshView,
)

app_name = "staff"

urlpatterns = [
    path("otp/send/", StaffOTPSendView.as_view(), name="staff-otp-send"),
    path("otp/verify/", StaffOTPVerifyView.as_view(), name="staff-otp-verify"),
    path("token/refresh/", StaffTokenRefreshView.as_view(), name="staff-token-refresh"),
    path("logout/", StaffLogoutView.as_view(), name="staff-logout"),
    path("me/", StaffMeView.as_view(), name="staff-me"),
]
