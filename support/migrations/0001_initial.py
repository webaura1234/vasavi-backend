# Generated manually for support app

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("branches", "0002_convert_to_uuid_pk"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ContactInquiry",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        db_index=True,
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="Row creation timestamp (set once, never updated).",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        help_text="Row last-modification timestamp (auto-updated on save).",
                    ),
                ),
                ("name", models.CharField(max_length=200)),
                ("email", models.EmailField(max_length=254)),
                ("message", models.TextField()),
                (
                    "inquiry_type",
                    models.CharField(
                        choices=[("general", "General"), ("branch", "Branch-specific")],
                        default="general",
                        max_length=20,
                    ),
                ),
                (
                    "branch",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="contact_inquiries",
                        to="branches.branch",
                    ),
                ),
            ],
            options={
                "verbose_name": "contact inquiry",
                "verbose_name_plural": "contact inquiries",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="SupportTicket",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        db_index=True,
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="Row creation timestamp (set once, never updated).",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        help_text="Row last-modification timestamp (auto-updated on save).",
                    ),
                ),
                (
                    "is_deleted",
                    models.BooleanField(
                        db_index=True,
                        default=False,
                        help_text="Soft-delete flag. True = logically deleted.",
                    ),
                ),
                (
                    "deleted_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="Timestamp when the row was soft-deleted.",
                        null=True,
                    ),
                ),
                ("subject", models.CharField(max_length=300)),
                ("description", models.TextField(blank=True)),
                ("guest_name", models.CharField(blank=True, max_length=200)),
                ("category", models.CharField(blank=True, max_length=80)),
                ("booking_reference", models.CharField(blank=True, max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("open", "Open"),
                            ("in_progress", "In progress"),
                            ("resolved", "Resolved"),
                        ],
                        db_index=True,
                        default="open",
                        max_length=20,
                    ),
                ),
                (
                    "priority",
                    models.CharField(
                        choices=[
                            ("low", "Low"),
                            ("medium", "Medium"),
                            ("high", "High"),
                        ],
                        default="medium",
                        max_length=20,
                    ),
                ),
                (
                    "branch",
                    models.ForeignKey(
                        blank=True,
                        help_text="Branch context; null for platform-wide issues.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="support_tickets",
                        to="branches.branch",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="support_tickets_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "support ticket",
                "verbose_name_plural": "support tickets",
                "ordering": ["-created_at"],
            },
        ),
    ]
