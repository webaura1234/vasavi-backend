"""API views for accounts (OTP auth, profile, tokens)."""

from __future__ import annotations

import secrets
import string

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import OTPLog, ProfileConfirmation, User
from accounts.serializers import (
    ProfileUpdateSerializer,
    OTPVerifySerializer,
    OTPSendSerializer,
    ProfileConfirmSerializer,
    RegistrationSerializer,
    UserProfileSerializer,
)
from accounts.services.otp import otp_send_cooldown_seconds
from permissions import IsPublic
from throttles import OTPVerifyThrottle, OTPSendThrottle
from utils.auth_tokens import RegistrationTokenError, issue_registration_token, verify_registration_token
from utils.responses import error_response, success_response
from utils.sms import send_otp_sms


REFRESH_COOKIE = "vasavi_refresh"


def _generate_otp_code() -> str:
    return "".join(secrets.choice(string.digits) for _ in range(6))


def _issue_jwt_pair(user: User) -> tuple[str, str]:
    refresh = RefreshToken.for_user(user)
    return str(refresh.access_token), str(refresh)


def _set_refresh_cookie(response, refresh_token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=30 * 24 * 3600,
        httponly=True,
        secure=getattr(settings, "REFRESH_COOKIE_SECURE", not settings.DEBUG),
        samesite="Lax",
        path="/",
    )


def _clear_refresh_cookie(response) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        "",
        max_age=0,
        httponly=True,
        secure=getattr(settings, "REFRESH_COOKIE_SECURE", not settings.DEBUG),
        samesite="Lax",
        path="/",
    )


def _profile_state(user: User) -> str:
    """Staff roles skip guest profile confirmation."""
    if user.role in ("admin", "super_admin"):
        return "dashboard"
    confirmation = ProfileConfirmation.objects.filter(user=user).first()
    if confirmation and confirmation.is_confirmed:
        return "dashboard"
    return "confirm_profile"


def _login_payload(user: User, access: str) -> dict:
    from donors.serializers import DonorProfileSerializer

    donor_profile = None
    if user.role == "donor" and hasattr(user, "donor_profile"):
        try:
            donor_profile = DonorProfileSerializer(user.donor_profile).data
        except Exception:
            donor_profile = None

    return {
        "access": access,
        "user": UserProfileSerializer(user).data,
        "state": _profile_state(user),
        "donor_profile": donor_profile,
    }


class OTPSendView(APIView):
    permission_classes = [IsPublic]
    throttle_classes = [OTPSendThrottle]

    def post(self, request):
        serializer = OTPSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data["phone"]

        cooldown = otp_send_cooldown_seconds(phone)
        if cooldown > 0:
            return error_response(
                "RATE_LIMITED",
                f"Please wait {cooldown}s before requesting another OTP.",
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                extra={"cooldown_seconds": cooldown},
            )

        if not OTPLog.can_send(phone):
            cooldown = otp_send_cooldown_seconds(phone) or 3600
            return error_response(
                "RATE_LIMITED",
                "Too many OTP requests. Try again later.",
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                extra={"cooldown_seconds": cooldown},
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
            pass

        if settings.DEBUG:
            print(f"\n{'=' * 40}\nOTP for {phone}: {otp_code}\n{'=' * 40}\n")

        return success_response(
            {
                "ok": True,
                "expires_in": 60,
                "cooldown_seconds": 60,
            },
            message="OTP sent successfully.",
        )


class OTPVerifyView(APIView):
    permission_classes = [IsPublic]
    throttle_classes = [OTPVerifyThrottle]

    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data["phone"]
        otp = serializer.validated_data["otp"]

        result, log = OTPLog.verify(phone, otp)

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
                "OTP has expired. Request a new code.",
                status=status.HTTP_400_BAD_REQUEST,
            )

        if result == "invalid":
            attempts_remaining = 0
            if log:
                attempts_remaining = max(0, 3 - log.attempts)
            return error_response(
                "OTP_INVALID",
                "Invalid OTP. Please try again.",
                status=status.HTTP_400_BAD_REQUEST,
                extra={"attempts_remaining": attempts_remaining},
            )

        # Same OTP flow for all roles (user, donor, admin, super_admin).
        user = User.objects.filter(
            phone=phone,
            is_active=True,
            is_deleted=False,
        ).first()
        if user:
            access, refresh = _issue_jwt_pair(user)
            response = success_response(_login_payload(user, access))
            _set_refresh_cookie(response, refresh)
            return response

        registration_token = issue_registration_token(phone)
        return success_response(
            {
                "access": None,
                "state": "registration",
                "phone": phone,
                "registration_token": registration_token,
            }
        )


class RegistrationView(APIView):
    permission_classes = [IsPublic]

    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            phone = verify_registration_token(serializer.validated_data["registration_token"])
        except RegistrationTokenError as exc:
            return error_response(
                "AUTH_FAILED",
                str(exc),
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if User.objects.filter(phone=phone).exists():
            return error_response(
                "VALIDATION_ERROR",
                "This phone number is already registered.",
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.create_user(
            phone=phone,
            name=serializer.validated_data["name"],
            role="user",
        )
        ProfileConfirmation.objects.create(
            user=user,
            is_confirmed=True,
            confirmed_at=timezone.now(),
        )
        user.is_first_login = False
        user.save(update_fields=["is_first_login", "updated_at"])

        access, refresh = _issue_jwt_pair(user)
        response = success_response(_login_payload(user, access), status=status.HTTP_201_CREATED)
        _set_refresh_cookie(response, refresh)
        return response


class ProfileConfirmView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserProfileSerializer

    def get_object(self):
        return self.request.user

    def retrieve(self, request, *args, **kwargs):
        return success_response(UserProfileSerializer(request.user).data)

    def partial_update(self, request, *args, **kwargs):
        user = request.user
        confirmation, _ = ProfileConfirmation.objects.get_or_create(user=user)

        if confirmation.is_confirmed:
            body = ProfileUpdateSerializer(data=request.data, partial=True)
            body.is_valid(raise_exception=True)
            if "name" in body.validated_data:
                user.name = body.validated_data["name"]
                user.save(update_fields=["name", "updated_at"])
                try:
                    from notifications.services import notify_profile_updated

                    notify_profile_updated(user)
                except Exception:
                    import logging

                    logging.getLogger("vasavi.accounts").exception(
                        "Could not create profile updated notification for user %s",
                        user.pk,
                    )
            return success_response(UserProfileSerializer(user).data)

        body = ProfileConfirmSerializer(data=request.data, partial=True)
        body.is_valid(raise_exception=True)

        if "name" in body.validated_data:
            user.name = body.validated_data["name"]
            user.save(update_fields=["name", "updated_at"])

        confirmation.is_confirmed = True
        confirmation.confirmed_at = timezone.now()
        confirmation.save(update_fields=["is_confirmed", "confirmed_at", "updated_at"])

        user.is_first_login = False
        user.save(update_fields=["is_first_login", "updated_at"])

        try:
            from notifications.services import notify_account_approved

            notify_account_approved(user)
        except Exception:
            import logging

            logging.getLogger("vasavi.accounts").exception(
                "Could not create account approved notification for user %s", user.pk
            )

        return success_response(
            {
                **UserProfileSerializer(user).data,
                "state": "dashboard",
            }
        )

    def patch(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)


class TokenRefreshView(APIView):
    permission_classes = [IsPublic]

    def post(self, request):
        raw = request.COOKIES.get(REFRESH_COOKIE)
        if not raw:
            return error_response(
                "AUTH_FAILED",
                "Refresh token missing.",
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            refresh = RefreshToken(raw)
            user = User.objects.get(pk=refresh["user_id"])
            new_refresh = RefreshToken.for_user(user)
            access = str(new_refresh.access_token)
            try:
                refresh.blacklist()
            except AttributeError:
                pass
            response = success_response({"access": access})
            _set_refresh_cookie(response, str(new_refresh))
            return response
        except (TokenError, User.DoesNotExist, KeyError):
            response = error_response(
                "AUTH_FAILED",
                "Invalid or expired refresh token.",
                status=status.HTTP_401_UNAUTHORIZED,
            )
            _clear_refresh_cookie(response)
            return response


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw = request.COOKIES.get(REFRESH_COOKIE)
        if raw:
            try:
                refresh = RefreshToken(raw)
                refresh.blacklist()
            except (TokenError, AttributeError):
                pass

        response = success_response({"ok": True})
        _clear_refresh_cookie(response)
        return response
