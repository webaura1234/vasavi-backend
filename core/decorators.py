"""View decorators for cross-cutting API concerns."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps

from django.http import HttpRequest, HttpResponse


def idempotency_scope(scope: str) -> Callable:
    """
    Pin an explicit idempotency scope on a view.

    Usage::

        @idempotency_scope("booking.create")
        def create_booking(request):
            ...
    """

    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def wrapper(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            request.idempotency_scope = scope
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
