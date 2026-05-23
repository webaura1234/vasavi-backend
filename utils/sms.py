"""SMS delivery abstraction — swap providers via SMS_BACKEND setting."""

from __future__ import annotations

import importlib
import logging
from abc import ABC, abstractmethod

from django.conf import settings

logger = logging.getLogger("vasavi.security")


class SMSBackend(ABC):
    """Provider interface for outbound SMS."""

    @abstractmethod
    def send(self, phone: str, message: str) -> bool:
        raise NotImplementedError


class ConsoleSMSBackend(SMSBackend):
    """Development backend — logs OTP to console (never in production logs with OTP)."""

    def send(self, phone: str, message: str) -> bool:
        if settings.DEBUG:
            logger.info("[DEV SMS] Phone: %s (message length %s)", phone, len(message))
            print(f"\n{'=' * 40}\nSMS to {phone}\n{message}\n{'=' * 40}\n")
        return True


class CustomRESTSMSBackend(SMSBackend):
    """Generic REST SMS gateway (configure via env)."""

    def send(self, phone: str, message: str) -> bool:
        import requests

        api_key = getattr(settings, "SMS_API_KEY", "")
        sender_id = getattr(settings, "SMS_SENDER_ID", "VASAVI")
        url = getattr(settings, "SMS_API_URL", "")

        if not url or not api_key:
            logger.error("SMS_API_URL or SMS_API_KEY not configured")
            return False

        try:
            response = requests.post(
                url,
                json={
                    "to": phone,
                    "from": sender_id,
                    "message": message,
                },
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            response.raise_for_status()
            logger.info("SMS sent to %s", phone)
            return True
        except Exception:
            logger.exception("SMS delivery failed for %s", phone)
            return False


def _load_backend() -> SMSBackend:
    path = getattr(
        settings,
        "SMS_BACKEND",
        "utils.sms.ConsoleSMSBackend",
    )
    module_path, class_name = path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    backend_cls = getattr(module, class_name)
    return backend_cls()


def send_otp_sms(phone: str, otp: str) -> bool:
    """
    Send OTP via configured SMS backend.

    In DEBUG mode the console backend prints the OTP for local testing.
    """
    message = f"Your Vasavi verification code is {otp}. Valid for 60 seconds."
    backend = _load_backend()
    return backend.send(phone, message)
