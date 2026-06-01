"""Object key paths for property photos (Supabase ``images`` bucket or local ``MEDIA_ROOT``).

Uploaded files are stored locally via ``FileSystemStorage`` today. When
Cloudflare R2 (or another CDN) is wired in, keep these logical prefixes and
switch ``STORAGES["default"]`` — existing DB paths stay valid.
"""

from __future__ import annotations

import os
import uuid

from django.conf import settings

# Logical directories inside MEDIA_ROOT (see config.settings MEDIA_*_DIR).
ROOMS_MEDIA_DIR = getattr(settings, "MEDIA_ROOMS_DIR", "rooms")
FUNCTION_HALLS_MEDIA_DIR = getattr(
    settings, "MEDIA_FUNCTION_HALLS_DIR", "function_halls"
)


def _unique_name(filename: str) -> str:
    base, ext = os.path.splitext(filename or "upload")
    ext = ext.lower() if ext else ".jpg"
    return f"{uuid.uuid4().hex}{ext}"


def room_image_upload_to(_instance, filename: str) -> str:
    return f"{ROOMS_MEDIA_DIR}/{_unique_name(filename)}"


def function_hall_image_upload_to(_instance, filename: str) -> str:
    return f"{FUNCTION_HALLS_MEDIA_DIR}/{_unique_name(filename)}"
