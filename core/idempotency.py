"""
Idempotency key handling for mutating API requests.

Clients send ``X-Idempotency-Key`` (or ``Idempotency-Key``) on POST/PUT/PATCH.
The server returns the same response for duplicate keys within the TTL window.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone

from core.idempotency_models import IdempotencyRecord

logger = logging.getLogger("vasavi.idempotency")


class IdempotencyError(Exception):
    """Base idempotency error with HTTP status."""

    status_code: int = 400

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


class IdempotencyKeyMissing(IdempotencyError):
    status_code = 400


class IdempotencyConflict(IdempotencyError):
    """Same key reused with a different payload."""

    status_code = 409


class IdempotencyInProgress(IdempotencyError):
    """Original request still processing."""

    status_code = 409


@dataclass(frozen=True)
class IdempotencyScope:
    """Well-known scopes — extend as new write endpoints ship."""

    BOOKING_CREATE = "booking.create"
    BOOKING_PAYMENT_ORDER = "booking.payment_order"
    BOOKING_CANCEL = "booking.cancel"
    OTP_SEND = "otp.send"
    OTP_VERIFY = "otp.verify"
    DONOR_EXPORT = "donor.export"
    DONATION_CREATE = "donation.create"
    COUPON_DISPATCH = "coupon.dispatch"


# Header names (case-insensitive in HTTP; Django META uses HTTP_* form)
IDEMPOTENCY_HEADER_NAMES = (
    "HTTP_X_IDEMPOTENCY_KEY",
    "HTTP_IDEMPOTENCY_KEY",
)


def get_client_idempotency_key(request: HttpRequest) -> str | None:
    """Extract idempotency key from request headers."""
    for meta_key in IDEMPOTENCY_HEADER_NAMES:
        value = request.META.get(meta_key, "").strip()
        if value:
            return value
    return None


def validate_client_key(raw_key: str) -> str:
    """
    Validate client-supplied key format.

    Accepts UUIDs or URL-safe strings (8–128 chars).
    """
    if not raw_key or len(raw_key) < 8 or len(raw_key) > 128:
        raise IdempotencyKeyMissing(
            "X-Idempotency-Key must be 8–128 characters.",
            status_code=400,
        )
    if not re.fullmatch(r"[A-Za-z0-9._-]+", raw_key):
        raise IdempotencyKeyMissing(
            "X-Idempotency-Key may only contain letters, digits, '.', '_', '-'.",
            status_code=400,
        )
    return raw_key


def hash_body(request: HttpRequest) -> str:
    """Stable SHA-256 of request body for conflict detection."""
    body = request.body or b""
    return hashlib.sha256(body).hexdigest()


def resolve_scope(request: HttpRequest) -> str:
    """
    Map request path to an idempotency scope.

    Override via view attribute ``idempotency_scope`` when using the decorator.
    """
    if hasattr(request, "idempotency_scope"):
        return request.idempotency_scope

    path = request.path
    if path.startswith("/api/v1/staff/bookings/") or path.startswith(
        "/api/staff/bookings/"
    ):
        return IdempotencyScope.BOOKING_CREATE
    if path.startswith("/api/v1/bookings/") or (
        path.startswith("/api/bookings/") and "webhooks" not in path
    ):
        if path.endswith("/payment/order/") or "payment" in path:
            return IdempotencyScope.BOOKING_PAYMENT_ORDER
        return IdempotencyScope.BOOKING_CREATE
    if path.startswith("/api/v1/accounts/") or path.startswith("/api/accounts/"):
        if "otp/send" in path or path.endswith("/otp/"):
            return IdempotencyScope.OTP_SEND
        if "otp/verify" in path:
            return IdempotencyScope.OTP_VERIFY
    if (path.startswith("/api/v1/donors/") or path.startswith("/api/donors/")) and "export" in path:
        return IdempotencyScope.DONOR_EXPORT
    return "api.write"


def actor_id(request: HttpRequest) -> str:
    """Stable actor for scoping keys (user pk or anonymous bucket)."""
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return str(user.pk)
    return "anon"


def build_key_hash(*, scope: str, actor: str, client_key: str) -> str:
    """Hash scope + actor + client key — raw client key is not persisted."""
    material = f"{scope}:{actor}:{client_key}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def ttl() -> timedelta:
    hours = getattr(settings, "IDEMPOTENCY_TTL_HOURS", 24)
    return timedelta(hours=hours)


def path_is_protected(request: HttpRequest) -> bool:
    """Return True if this path requires / accepts idempotency."""
    path = request.path

    for prefix in getattr(settings, "IDEMPOTENCY_EXCLUDED_PREFIXES", []):
        if path.startswith(prefix):
            return False

    for prefix in getattr(settings, "IDEMPOTENCY_PROTECTED_PREFIXES", []):
        if path.startswith(prefix):
            return True
    return False


def method_is_mutating(request: HttpRequest) -> bool:
    return request.method.upper() in {"POST", "PUT", "PATCH"}


@dataclass
class IdempotencyContext:
    """Attached to ``request.idempotency`` during protected handling."""

    record: IdempotencyRecord
    is_replay: bool = False


def check_idempotency(request: HttpRequest) -> IdempotencyContext | HttpResponse:
    """
    Pre-flight idempotency check. Returns context or an HTTP response to short-circuit.
    """
    raw_key = get_client_idempotency_key(request)
    required = getattr(settings, "IDEMPOTENCY_KEY_REQUIRED", True)

    if not raw_key:
        if required and path_is_protected(request):
            return JsonResponse(
                {
                    "error": "idempotency_key_required",
                    "detail": "Send X-Idempotency-Key header on this endpoint.",
                },
                status=400,
            )
        return None  # type: ignore[return-value]

    client_key = validate_client_key(raw_key)
    scope = resolve_scope(request)
    key_hash = build_key_hash(
        scope=scope,
        actor=actor_id(request),
        client_key=client_key,
    )
    body_hash = hash_body(request)
    now = timezone.now()

    existing = IdempotencyRecord.objects.filter(key_hash=key_hash).first()

    if existing:
        if existing.request_body_hash != body_hash:
            raise IdempotencyConflict(
                "Idempotency key was already used with a different request body.",
            )

        if existing.status == IdempotencyRecord.Status.COMPLETED:
            return replay_response(existing)

        if existing.status == IdempotencyRecord.Status.PENDING:
            raise IdempotencyInProgress(
                "A request with this idempotency key is still being processed.",
            )

        # FAILED — allow retry with same key/body
        existing.status = IdempotencyRecord.Status.PENDING
        existing.save(update_fields=["status"])
        return IdempotencyContext(record=existing)

    record = IdempotencyRecord.objects.create(
        key_hash=key_hash,
        scope=scope,
        method=request.method,
        path=request.path[:255],
        request_body_hash=body_hash,
        status=IdempotencyRecord.Status.PENDING,
        user_id=_user_pk(request),
        expires_at=now + ttl(),
    )
    return IdempotencyContext(record=record)


def _user_pk(request: HttpRequest):
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user.pk
    return None


def replay_response(record: IdempotencyRecord) -> HttpResponse:
    """Return a cached JSON response and mark it as a replay."""
    response = JsonResponse(
        record.response_body or {},
        status=record.response_status_code or 200,
        safe=False,
    )
    response["X-Idempotency-Replayed"] = "true"
    for key, value in (record.response_headers or {}).items():
        if key.lower() not in ("content-type", "content-length"):
            response[key] = value
    return response


def complete_idempotency(
    record: IdempotencyRecord,
    response: HttpResponse,
    *,
    success: bool = True,
) -> None:
    """Persist response body for future replays."""
    try:
        if hasattr(response, "content"):
            body = json.loads(response.content.decode("utf-8") or "{}")
        else:
            body = {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = {"_non_json_response": True}

    record.status = (
        IdempotencyRecord.Status.COMPLETED
        if success and response.status_code < 500
        else IdempotencyRecord.Status.FAILED
    )
    record.response_status_code = response.status_code
    record.response_body = body
    record.response_headers = {
        k: v
        for k, v in response.items()
        if k.lower() in ("content-type", "x-request-id")
    }
    record.save(
        update_fields=[
            "status",
            "response_status_code",
            "response_body",
            "response_headers",
        ]
    )


def error_response(exc: IdempotencyError) -> JsonResponse:
    """Standard JSON error for idempotency failures."""
    payload: dict[str, Any] = {
        "error": exc.__class__.__name__,
        "detail": str(exc),
    }
    headers = {}
    if isinstance(exc, IdempotencyInProgress):
        headers["Retry-After"] = str(
            getattr(settings, "IDEMPOTENCY_RETRY_AFTER_SECONDS", 2)
        )
    return JsonResponse(payload, status=exc.status_code, headers=headers)
