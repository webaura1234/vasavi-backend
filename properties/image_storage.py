"""Delete property images from the active storage backend (Supabase or local)."""

from __future__ import annotations

import logging

from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)


def delete_property_image_file(name: str | None) -> None:
    """Remove the object from storage; ignore missing files and transient errors."""
    if not name:
        return
    try:
        default_storage.delete(name)
    except OSError as exc:
        logger.warning("Could not delete property image %s: %s", name, exc)
    except Exception as exc:
        logger.warning("Unexpected error deleting property image %s: %s", name, exc)
