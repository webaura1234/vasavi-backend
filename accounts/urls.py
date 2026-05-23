"""Accounts URL routes."""

from django.urls import path

from accounts.views import (
    LogoutView,
    OTPSendView,
    OTPVerifyView,
    ProfileConfirmView,
    RegistrationView,
    TokenRefreshView,
)

app_name = "accounts"

urlpatterns = [
    path("otp/send/", OTPSendView.as_view(), name="otp-send"),
    path("otp/verify/", OTPVerifyView.as_view(), name="otp-verify"),
    path("register/", RegistrationView.as_view(), name="register"),
    path("me/", ProfileConfirmView.as_view(), name="profile-me"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
]
