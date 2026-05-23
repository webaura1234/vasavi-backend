"""Custom DRF throttle classes."""

from __future__ import annotations

from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class OTPSendThrottle(AnonRateThrottle):
    scope = "otp_send"

    def get_cache_key(self, request, view):
        phone = ""
        if hasattr(request, "data"):
            phone = str(request.data.get("phone", "")).strip()
        ident = phone or self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class OTPVerifyThrottle(AnonRateThrottle):
    scope = "otp_verify"

    def parse_rate(self, rate):
        # DRF only supports s/m/h/d — map our 10-minute window explicitly.
        if rate == "3/10minute":
            return (3, 600)
        return super().parse_rate(rate)

    def get_cache_key(self, request, view):
        phone = ""
        if hasattr(request, "data"):
            phone = str(request.data.get("phone", "")).strip()
        ident = phone or self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class BookingCreateThrottle(UserRateThrottle):
    scope = "booking_create"


class PaymentThrottle(UserRateThrottle):
    scope = "payment"


class StaffOTPSendThrottle(AnonRateThrottle):
    scope = "staff_otp_send"

    def get_cache_key(self, request, view):
        phone = ""
        if hasattr(request, "data"):
            phone = str(request.data.get("phone", "")).strip()
        ident = phone or self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class StaffOTPVerifyThrottle(AnonRateThrottle):
    scope = "staff_otp_verify"

    def parse_rate(self, rate):
        if rate == "3/10minute":
            return (3, 600)
        return super().parse_rate(rate)

    def get_cache_key(self, request, view):
        phone = ""
        if hasattr(request, "data"):
            phone = str(request.data.get("phone", "")).strip()
        ident = phone or self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
