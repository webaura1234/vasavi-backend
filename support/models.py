"""Support tickets (staff) and public contact inquiries."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import SoftDeleteModel, TimeStampedModel


class SupportTicket(SoftDeleteModel, TimeStampedModel):
    """Branch or platform support request raised by staff."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        RESOLVED = "resolved", "Resolved"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_tickets",
        help_text="Branch context; null for platform-wide issues.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="support_tickets_created",
    )
    subject = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    guest_name = models.CharField(max_length=200, blank=True)
    category = models.CharField(max_length=80, blank=True)
    booking_reference = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "support ticket"
        verbose_name_plural = "support tickets"
        indexes = [
            # Staff portal filters tickets by branch + status frequently.
            models.Index(
                fields=["branch", "status"],
                name="idx_ticket_branch_status",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.subject[:50]} ({self.get_status_display()})"


class ContactInquiry(TimeStampedModel):
    """Public contact form submission from the main website."""

    class InquiryType(models.TextChoices):
        GENERAL = "general", "General"
        BRANCH = "branch", "Branch-specific"

    name = models.CharField(max_length=200)
    email = models.EmailField()
    message = models.TextField()
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contact_inquiries",
    )
    inquiry_type = models.CharField(
        max_length=20,
        choices=InquiryType.choices,
        default=InquiryType.GENERAL,
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "contact inquiry"
        verbose_name_plural = "contact inquiries"
