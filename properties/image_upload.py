"""Validation for property images stored in Supabase (or local media)."""

from __future__ import annotations


def validate_property_storage_path(media_dir: str, path: str) -> bool:
    """Ensure ``path`` is a safe object key under ``{media_dir}/``."""
    if not path or ".." in path or "\\" in path:
        return False
    normalized = path.strip().lstrip("/")
    prefix = f"{media_dir.strip('/')}/"
    return normalized.startswith(prefix) and len(normalized) > len(prefix)
