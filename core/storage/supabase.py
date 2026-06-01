"""Store uploaded property images in a Supabase Storage bucket."""

from __future__ import annotations

import mimetypes
from typing import IO
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible


@deconstructible
class SupabaseStorage(Storage):
    """Persist files to Supabase Storage (public ``images`` bucket by default)."""

    def __init__(self, bucket: str | None = None) -> None:
        self.bucket = bucket or settings.SUPABASE_STORAGE_BUCKET

    def _object_path(self, name: str) -> str:
        return name.lstrip("/")

    def _headers(self) -> dict[str, str]:
        key = settings.SUPABASE_SERVICE_ROLE_KEY
        if not key:
            raise OSError("SUPABASE_SERVICE_ROLE_KEY is required for storage operations.")
        return {
            "Authorization": f"Bearer {key}",
            "apikey": key,
        }

    def _storage_url(self, path: str) -> str:
        base = settings.SUPABASE_URL.rstrip("/")
        encoded = quote(path, safe="/")
        return f"{base}/storage/v1/object/{self.bucket}/{encoded}"

    def _save(self, name: str, content: IO[bytes]) -> str:
        path = self._object_path(name)
        data = content.read()
        content_type = (
            getattr(content, "content_type", None)
            or mimetypes.guess_type(path)[0]
            or "application/octet-stream"
        )
        response = requests.post(
            self._storage_url(path),
            headers={
                **self._headers(),
                "Content-Type": content_type,
                "x-upsert": "true",
            },
            data=data,
            timeout=60,
        )
        if response.status_code not in (200, 201):
            raise OSError(
                f"Supabase upload failed ({response.status_code}): {response.text}"
            )
        return name

    def delete(self, name: str) -> None:
        path = self._object_path(name)
        headers = self._headers()
        base = settings.SUPABASE_URL.rstrip("/")

        response = requests.delete(
            self._storage_url(path),
            headers=headers,
            timeout=30,
        )
        if response.status_code in (200, 204, 404):
            return

        # Documented batch delete: DELETE /object/{bucket} with prefixes.
        batch = requests.delete(
            f"{base}/storage/v1/object/{self.bucket}",
            headers={**headers, "Content-Type": "application/json"},
            json={"prefixes": [path]},
            timeout=30,
        )
        if batch.status_code in (200, 204, 404):
            return

        raise OSError(
            f"Supabase delete failed ({response.status_code}): {response.text}; "
            f"batch ({batch.status_code}): {batch.text}"
        )

    def exists(self, name: str) -> bool:
        path = self._object_path(name)
        response = requests.head(
            self._storage_url(path),
            headers=self._headers(),
            timeout=15,
        )
        return response.status_code == 200

    def url(self, name: str) -> str:
        path = self._object_path(name)
        base = settings.SUPABASE_URL.rstrip("/")
        encoded = quote(path, safe="/")
        return f"{base}/storage/v1/object/public/{self.bucket}/{encoded}"

    def size(self, name: str) -> int:
        return 0
