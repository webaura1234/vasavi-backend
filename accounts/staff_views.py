# COOKIE ARCHITECTURE
#
# Customer app (vasavi-main-site):
#   Cookie name : vasavi_refresh
#   Cookie path : /api/v1/accounts/  (default path /)
#   Used by     : TokenRefreshView in accounts/views.py
#
# Staff app (vasavi-role-portal):
#   Cookie name : vasavi_staff_refresh
#   Cookie path : /api/v1/staff/
#   Used by     : StaffTokenRefreshView in this module
#
# WHY separate cookies:
#   If both apps ever run on the same domain (e.g. vasavihotels.org
#   and portal.vasavihotels.org share a parent), separate cookie names
#   and scoped paths prevent token bleed between apps.
#   A customer refresh token can never be used on a staff endpoint.
#
# JWT payload is identical for both — role field determines access.
# The separation is at the cookie transport layer only.

"""Staff portal authentication API (vasavi-role-portal)."""

from __future__ import annotations

import logging
import random
import string

from django.conf import settings
from django.contrib.auth.hashers import make_password
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import OTPLog, User
from accounts.services.otp import otp_send_cooldown_seconds
from accounts.staff_serializers import (
    StaffMeSerializer,
    StaffMeUpdateSerializer,
    StaffOTPSendSerializer,
    StaffOTPVerifySerializer,
)
from accounts.views import _issue_jwt_pair
from permissions import IsAdminOrAbove, IsPublic, IsSuperAdmin
from throttles import StaffOTPVerifyThrottle, StaffOTPSendThrottle
from utils.responses import error_response, success_response
from utils.sms import send_otp_sms

security_logger = logging.getLogger("vasavi.security")

STAFF_REFRESH_COOKIE = "vasavi_staff_refresh"
STAFF_COOKIE_PATH = "/api/v1/staff/"


def _access_expires_in_seconds() -> int:
  return int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds())


def _generate_otp_code() -> str:
    return "".join(random.choices(string.digits, k=6))


def _phone_suffix(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    return digits[-4:] if len(digits) >= 4 else "****"


def _set_staff_refresh_cookie(response, refresh_token: str) -> None:
    response.set_cookie(
        STAFF_REFRESH_COOKIE,
        refresh_token,
        max_age=30 * 24 * 3600,
        httponly=True,
        secure=getattr(settings, "SESSION_COOKIE_SECURE", False),
        samesite="Lax",
        path=STAFF_COOKIE_PATH,
    )


def _clear_staff_refresh_cookie(response) -> None:
    response.delete_cookie(
        STAFF_REFRESH_COOKIE,
        path=STAFF_COOKIE_PATH,
    )


class StaffOTPSendView(APIView):
    permission_classes = [IsPublic]
    throttle_classes = [StaffOTPSendThrottle]

    def post(self, request):
        serializer = StaffOTPSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data["phone"]

        cooldown = otp_send_cooldown_seconds(phone)
        if cooldown > 0:
            return error_response(
                "RATE_LIMITED",
                f"Please wait {cooldown}s before requesting another OTP.",
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                extra={"retry_after_seconds": cooldown, "cooldown_seconds": cooldown},
            )

        if not OTPLog.can_send(phone):
            cooldown = otp_send_cooldown_seconds(phone) or 3600
            return error_response(
                "RATE_LIMITED",
                "Too many OTP requests. Try again later.",
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                extra={"retry_after_seconds": cooldown, "cooldown_seconds": cooldown},
            )

        otp_code = _generate_otp_code()
        OTPLog.objects.create(
            phone=phone,
            hashed_otp=make_password(otp_code),
            purpose="login",
        )

        try:
            send_otp_sms(phone, otp_code)
        except Exception:
            security_logger.exception("Staff OTP SMS delivery failed")

        if settings.DEBUG:
            print(f"\n{'=' * 40}\n[STAFF OTP] {phone}: {otp_code}\n{'=' * 40}\n")

        return success_response(
            {
                "ok": True,
                "expires_in": 60,
                "cooldown_seconds": 60,
            },
            message="OTP sent successfully.",
        )


class StaffOTPVerifyView(APIView):
    permission_classes = [IsPublic]
    throttle_classes = [StaffOTPVerifyThrottle]

    def post(self, request):
        serializer = StaffOTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data["phone"]
        otp = serializer.validated_data["otp"]

        log = (
            OTPLog.objects.filter(phone=phone, is_verified=False)
            .order_by("-created_at")
            .first()
        )

        result = OTPLog.verify(phone, otp)

        if result == "locked":
            locked_until = log.locked_until if log else None
            return error_response(
                "OTP_LOCKED",
                "Too many failed attempts. Try again later.",
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                extra={
                    "locked_until": locked_until.isoformat() if locked_until else None,
                },
            )

        if result == "expired":
            return error_response(
                "OTP_EXPIRED",
                "OTP has expired. Request a new one.",
                status=status.HTTP_400_BAD_REQUEST,
            )

        if result == "invalid":
            attempts_remaining = max(0, 3 - (log.attempts if log else 0))
            return error_response(
                "OTP_INVALID",
                "Incorrect OTP.",
                status=status.HTTP_400_BAD_REQUEST,
                extra={"attempts_remaining": attempts_remaining},
            )

        user = User.objects.filter(
            phone=phone,
            is_active=True,
            is_deleted=False,
        ).first()

        if not user:
            return error_response(
                "ACCOUNT_NOT_FOUND",
                "Staff account not found. Contact your administrator.",
                status=status.HTTP_404_NOT_FOUND,
            )

        if user.role not in ("admin", "super_admin"):
            security_logger.warning(
                "Non-staff attempted staff login endpoint",
                extra={
                    "phone_suffix": _phone_suffix(phone),
                    "actual_role": user.role,
                    "ip": request.META.get("REMOTE_ADDR"),
                },
            )
            return error_response(
                "ACCESS_DENIED",
                "This portal is for staff only.",
                status=status.HTTP_403_FORBIDDEN,
            )

        access, refresh = _issue_jwt_pair(user)

        branch_id = None
        if user.role == "admin":
            try:
                branch_id = user.admin_branch.branch_id
            except Exception:
                branch_id = None

        security_logger.info(
            "Staff login success",
            extra={
                "phone_suffix": _phone_suffix(phone),
                "role": user.role,
                "branch": str(branch_id) if branch_id else None,
                "ip": request.META.get("REMOTE_ADDR"),
            },
        )

        response = success_response(
            {
                "access": access,
                "access_expires_in": _access_expires_in_seconds(),
                "user": StaffMeSerializer(user, context={"request": request}).data,
                "state": "dashboard",
            }
        )
        _set_staff_refresh_cookie(response, refresh)
        return response


class StaffTokenRefreshView(APIView):
    permission_classes = [IsPublic]

    def post(self, request):
        raw = request.COOKIES.get(STAFF_REFRESH_COOKIE)
        if not raw:
            return error_response(
                "AUTH_FAILED",
                "Session expired. Please login again.",
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            old_refresh = RefreshToken(raw)
            user = User.objects.get(pk=old_refresh["user_id"])

            if user.role not in ("admin", "super_admin") or not user.is_active:
                raise TokenError("Staff role required")

            try:
                old_refresh.blacklist()
            except AttributeError:
                pass

            new_refresh = RefreshToken.for_user(user)
            access = str(new_refresh.access_token)

            response = success_response(
                {
                    "access": access,
                    "access_expires_in": _access_expires_in_seconds(),
                }
            )
            _set_staff_refresh_cookie(response, str(new_refresh))
            return response
        except (TokenError, User.DoesNotExist, KeyError):
            response = error_response(
                "AUTH_FAILED",
                "Session expired. Please login again.",
                status=status.HTTP_401_UNAUTHORIZED,
            )
            _clear_staff_refresh_cookie(response)
            return response


class StaffLogoutView(APIView):
    """Sign out using Bearer token and/or httpOnly refresh cookie."""

    permission_classes = [IsPublic]

    def post(self, request):
        raw = request.COOKIES.get(STAFF_REFRESH_COOKIE)

        if (
            getattr(request, "user", None)
            and request.user.is_authenticated
            and request.user.role not in ("admin", "super_admin")
        ):
            return error_response(
                "ACCESS_DENIED",
                "This portal is for staff only.",
                status=status.HTTP_403_FORBIDDEN,
            )

        if raw:
            try:
                refresh = RefreshToken(raw)
                refresh.blacklist()
            except (TokenError, AttributeError):
                pass

        response = success_response({"ok": True})
        _clear_staff_refresh_cookie(response)
        return response


class StaffMeView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAdminOrAbove]

    def get_object(self):
        return self.request.user

    def retrieve(self, request, *args, **kwargs):
        return success_response(
            StaffMeSerializer(request.user, context={"request": request}).data
        )

    def partial_update(self, request, *args, **kwargs):
        user = request.user
        body = StaffMeUpdateSerializer(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        user.name = body.validated_data["name"]
        user.save(update_fields=["name", "updated_at"])
        return success_response(
            StaffMeSerializer(user, context={"request": request}).data
        )

    def patch(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)


class StaffManagementView(generics.ListCreateAPIView):
    permission_classes = [IsSuperAdmin]

    def get_serializer_class(self):
        if self.request.method == "POST":
            from accounts.staff_serializers import StaffManagementSerializer
            return StaffManagementSerializer
        from accounts.staff_serializers import StaffMeSerializer
        return StaffMeSerializer

    def get_queryset(self):
        return User.objects.filter(role="admin", is_deleted=False).order_by("-date_joined")

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        from utils.responses import paginated_response
        from accounts.staff_serializers import StaffMeSerializer
        return paginated_response(queryset, request, StaffMeSerializer)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data["phone"]
        name = serializer.validated_data["name"]
        email = serializer.validated_data.get("email", "")

        user = User.objects.filter(phone=phone).first()
        if user:
            if user.role == "admin":
                return error_response("ALREADY_EXISTS", "Admin with this phone number already exists.")
            else:
                # Upgrade role if needed
                user.role = "admin"
                user.name = name
                user.email = email
                user.save(update_fields=["role", "name", "email", "updated_at"])
        else:
            user = User.objects.create_user(
                phone=phone,
                role="admin",
                name=name,
                email=email,
                is_active=True
            )

        from accounts.tasks import send_staff_invite_sms_task
        send_staff_invite_sms_task.delay(phone=phone, name=name)

        from accounts.staff_serializers import StaffMeSerializer
        return success_response(
            StaffMeSerializer(user, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
            message="Staff member invited successfully."
        )
