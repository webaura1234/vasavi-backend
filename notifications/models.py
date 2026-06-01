"""Persisted in-app notifications for authenticated users."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class Notification(TimeStampedModel):
    class Category(models.TextChoices):
        COUPON = "coupon", "Coupon"
        DONATION = "donation", "Donation"
        USER = "user", "User"
        SYSTEM = "system", "System"

    class Type(models.TextChoices):
        COUPON_REDEEMED = "coupon_redeemed", "Coupon redeemed"
        COUPON_EXPIRED = "coupon_expired", "Coupon expired"
        COUPON_NEARING_EXPIRY = "coupon_nearing_expiry", "Coupon nearing expiry"
        DONATION_RECEIVED = "donation_received", "Donation received"
        DONATION_APPROVED = "donation_approved", "Donation approved"
        DONATION_REJECTED = "donation_rejected", "Donation rejected"
        PROFILE_UPDATED = "profile_updated", "Profile updated"
        PASSWORD_CHANGED = "password_changed", "Password changed"
        ACCOUNT_APPROVED = "account_approved", "Account approved"
        SYSTEM_ALERT = "system_alert", "System alert"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    category = models.CharField(max_length=20, choices=Category.choices)
    type = models.CharField(max_length=40, choices=Type.choices)
    title = models.CharField(max_length=200)
    message = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    related_entity_type = models.CharField(max_length=50, blank=True)
    related_entity_id = models.UUIDField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "notification"
        verbose_name_plural = "notifications"
        indexes = [
            models.Index(
                fields=["recipient", "read_at", "-created_at"],
                name="idx_notif_recipient_read",
            ),
            models.Index(
                fields=["recipient", "category"],
                name="idx_notif_recipient_category",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} → {self.recipient_id}"

    @property
    def is_read(self) -> bool:
        return self.read_at is not None
