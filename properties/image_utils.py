"""Shared helpers for property image serializers."""

from __future__ import annotations

from urllib.parse import quote

from django.conf import settings
from django.db.models import FileField

_LEGACY_ROOM_PREFIX = "properties.media_paths.room_image_upload_to/"
_LEGACY_HALL_PREFIX = "properties.media_paths.function_hall_image_upload_to/"


def normalize_property_image_path(name: str) -> str:
    """Map mistaken string ``upload_to`` paths to ``rooms/`` or ``function_halls/`` keys."""
    if name.startswith(_LEGACY_ROOM_PREFIX):
        return f"{settings.MEDIA_ROOMS_DIR}/{name[len(_LEGACY_ROOM_PREFIX):]}"
    if name.startswith(_LEGACY_HALL_PREFIX):
        return f"{settings.MEDIA_FUNCTION_HALLS_DIR}/{name[len(_LEGACY_HALL_PREFIX):]}"
    return name.lstrip("/")


def supabase_public_url(object_path: str | None) -> str | None:
    """HTTPS URL for a public object in the Supabase ``images`` bucket."""
    if not object_path or not getattr(settings, "SUPABASE_URL", ""):
        return None
    path = normalize_property_image_path(object_path)
    rooms = getattr(settings, "MEDIA_ROOMS_DIR", "rooms")
    halls = getattr(settings, "MEDIA_FUNCTION_HALLS_DIR", "function_halls")
    if not (path.startswith(f"{rooms}/") or path.startswith(f"{halls}/")):
        return None
    bucket = getattr(settings, "SUPABASE_STORAGE_BUCKET", "images")
    base = settings.SUPABASE_URL.rstrip("/")
    return f"{base}/storage/v1/object/public/{bucket}/{quote(path, safe='/')}"


def absolute_media_url(request, file_field: FileField | None) -> str | None:
    if not file_field:
        return None
    name = file_field.name
    if not name:
        return None

    public = supabase_public_url(name)
    if public:
        return public

    url = file_field.url
    if url.startswith(("http://", "https://")):
        return url
    if request:
        return request.build_absolute_uri(url)
    return url
