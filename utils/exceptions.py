"""DRF exception handler with a consistent JSON error envelope."""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException, Throttled, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("vasavi.security")

_STATUS_TO_CODE = {
    status.HTTP_400_BAD_REQUEST: "VALIDATION_ERROR",
    status.HTTP_401_UNAUTHORIZED: "AUTH_FAILED",
    status.HTTP_403_FORBIDDEN: "PERMISSION_DENIED",
    status.HTTP_404_NOT_FOUND: "NOT_FOUND",
    status.HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMITED",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "SERVER_ERROR",
}


def _build_error(
    code: str,
    message: str,
    *,
    fields: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if fields:
        payload["error"]["fields"] = fields
    return payload


def _scalar_validation_value(value: Any) -> str:
    """Extract a plain string from DRF ErrorDetail / list wrappers."""
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value)


def _validation_fields(exc: ValidationError) -> dict[str, list[str]]:
    detail = exc.detail
    if isinstance(detail, dict):
        return {
            str(key): [str(item) for item in (value if isinstance(value, list) else [value])]
            for key, value in detail.items()
        }
    if isinstance(detail, list):
        return {"non_field_errors": [str(item) for item in detail]}
    return {"non_field_errors": [str(detail)]}


def custom_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Map DRF/Django exceptions to the Vasavi API error format."""
    if isinstance(exc, Http404):
        return Response(
            _build_error("NOT_FOUND", "Resource not found."),
            status=status.HTTP_404_NOT_FOUND,
        )

    if isinstance(exc, DjangoPermissionDenied):
        return Response(
            _build_error("PERMISSION_DENIED", "You do not have permission to perform this action."),
            status=status.HTTP_403_FORBIDDEN,
        )

    response = drf_exception_handler(exc, context)

    if response is None:
        logger.exception("Unhandled server error", exc_info=exc)
        return Response(
            _build_error("SERVER_ERROR", "An unexpected error occurred."),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    status_code = response.status_code
    code = _STATUS_TO_CODE.get(status_code, "SERVER_ERROR")

    if status_code >= 500:
        logger.exception("API 5xx response", exc_info=exc)

    message = "Request failed."
    fields: dict[str, list[str]] | None = None

    if isinstance(exc, ValidationError):
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail and "message" in detail:
            code = _scalar_validation_value(detail["code"])
            message = _scalar_validation_value(detail["message"])
            response.data = _build_error(code, message)
            return response
        fields = _validation_fields(exc)
        message = "Validation failed."
    elif isinstance(exc, Throttled):
        message = str(exc.detail) if exc.detail else "Too many requests."
        code = "RATE_LIMITED"
    elif isinstance(exc, APIException):
        detail = exc.detail
        if isinstance(detail, dict) and "message" in detail:
            message = str(detail["message"])
        elif isinstance(detail, (list, tuple)) and detail:
            message = str(detail[0])
        else:
            message = str(detail)

    response.data = _build_error(code, message, fields=fields)
    return response
