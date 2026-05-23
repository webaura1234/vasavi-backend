"""Standard success response helpers."""

from __future__ import annotations

from typing import Any

from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response


def success_response(
    data: Any = None,
    *,
    message: str | None = None,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> Response:
    """Return ``{ success: true, data, message? }``."""
    body: dict[str, Any] = {"success": True}
    if data is not None:
        body["data"] = data
    if message:
        body["message"] = message
    return Response(body, status=status, headers=headers or {})


def error_response(
    code: str,
    message: str,
    *,
    status: int = 400,
    fields: dict[str, list[str]] | None = None,
    extra: dict | None = None,
) -> Response:
    """Return a structured error body matching the Vasavi API contract."""
    error: dict[str, Any] = {"code": code, "message": message}
    if fields:
        error["fields"] = fields
    if extra:
        error.update(extra)
    return Response({"success": False, "error": error}, status=status)


def paginated_response(
    queryset,
    request: Request,
    serializer_class,
    *,
    page_size: int | None = None,
) -> Response:
    """Paginate *queryset* and wrap results in the success envelope."""
    paginator = PageNumberPagination()
    if page_size is not None:
        paginator.page_size = page_size
    page = paginator.paginate_queryset(queryset, request)
    context = {"request": request}
    if page is not None:
        serializer = serializer_class(page, many=True, context=context)
        return success_response(
            {
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "results": serializer.data,
            }
        )
    return success_response(
        {
            "count": 0,
            "next": None,
            "previous": None,
            "results": [],
        }
    )
