"""Persisted idempotency records for safe request replay."""

from __future__ import annotations

from django.db import models

from utils.models import UUIDModel


class IdempotencyRecord(UUIDModel):
    """
    Stores the outcome of a mutating API request keyed by ``X-Idempotency-Key``.

    See ``docs/security.md`` for client and server behaviour.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    # SHA-256 hex of scope + actor + client key (raw key never stored)
    key_hash = models.CharField(max_length=64, unique=True, db_index=True)
    scope = models.CharField(max_length=64, db_index=True)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=255)
    request_body_hash = models.CharField(max_length=64)

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    response_status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    response_headers = models.JSONField(default=dict, blank=True)

    user_id = models.UUIDField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        verbose_name = "idempotency record"
        verbose_name_plural = "idempotency records"
        indexes = [
            models.Index(fields=["scope", "status"], name="idx_idem_scope_status"),
        ]

    def __str__(self) -> str:
        return f"{self.scope} [{self.status}] {self.method} {self.path}"
