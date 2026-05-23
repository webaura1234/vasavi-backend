"""Core HTTP middleware."""

from __future__ import annotations

import logging

from django.http import HttpRequest, HttpResponse

from core import idempotency

logger = logging.getLogger("vasavi.middleware")


class IdempotencyMiddleware:
    """
    Enforce ``X-Idempotency-Key`` on configured mutating API routes.

    See ``docs/security.md`` for client usage and endpoint matrix.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not idempotency.method_is_mutating(request):
            return self.get_response(request)

        if not idempotency.path_is_protected(request):
            return self.get_response(request)

        try:
            result = idempotency.check_idempotency(request)
        except idempotency.IdempotencyError as exc:
            return idempotency.error_response(exc)

        if isinstance(result, HttpResponse):
            return result

        if result is None:
            return self.get_response(request)

        request.idempotency = result
        response = self.get_response(request)

        if not result.is_replay:
            success = response.status_code < 500
            idempotency.complete_idempotency(
                result.record,
                response,
                success=success,
            )
            response["X-Idempotency-Key-Status"] = (
                "completed" if success else "failed"
            )

        return response
