"""Shared helpers for property image serializers."""

from __future__ import annotations

from django.db.models import FileField


def absolute_media_url(request, file_field: FileField | None) -> str | None:
    if not file_field:
        return None
    url = file_field.url
    if request:
        return request.build_absolute_uri(url)
    return url
