"""
core/models.py

Shared abstract base models and managers for the Vasavi Clubs International
platform. These provide consistent timestamp tracking and soft-delete behaviour
across every concrete model in the system.

Concrete infrastructure models (e.g. idempotency) live in sibling modules
and are imported below for Django's model discovery.
"""

from django.db import models
from django.utils import timezone

from utils.models import UUIDModel


# ---------------------------------------------------------------------------
# Managers
# ---------------------------------------------------------------------------

class SoftDeleteManager(models.Manager):
    """
    Default manager that automatically excludes soft-deleted rows.

    Use ``all_objects`` (an unfiltered Manager instance) on any model that
    inherits SoftDeleteModel when you explicitly need deleted records —
    e.g. for admin audit views or data-recovery scripts.
    """

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class AllObjectsManager(models.Manager):
    """
    Unfiltered manager — returns *all* rows including soft-deleted ones.
    Attach this as ``all_objects`` on SoftDeleteModel subclasses.
    """
    pass


# ---------------------------------------------------------------------------
# Abstract base models
# ---------------------------------------------------------------------------

class TimeStampedModel(UUIDModel):
    """
    Adds ``created_at`` and ``updated_at`` to every inheriting model.
    """

    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Row creation timestamp (set once, never updated).",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Row last-modification timestamp (auto-updated on save).",
    )

    class Meta:
        abstract = True


class SoftDeleteModel(TimeStampedModel):
    """
    Extends TimeStampedModel with soft-delete semantics.

    * ``objects`` — default manager; excludes deleted rows.
    * ``all_objects`` — includes deleted rows for admin / audit access.
    * Call ``soft_delete()`` instead of ``delete()`` for safe removal.
    * Call ``restore()`` to un-delete a row.
    """

    is_deleted = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Soft-delete flag. True = logically deleted.",
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the row was soft-deleted.",
    )

    # Default manager (excludes deleted)
    objects = SoftDeleteManager()
    # Unfiltered manager
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    # -- helpers -------------------------------------------------------------

    def soft_delete(self):
        """Mark this record as deleted without removing it from the DB."""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    def restore(self):
        """Reverse a soft-delete."""
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])


from core.idempotency_models import IdempotencyRecord  # noqa: E402, F401
