# Generated manually for function hall inventory.

import uuid

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("branches", "0002_convert_to_uuid_pk"),
        ("properties", "0004_alter_roomimage_created_at_alter_roomimage_id_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="FunctionHall",
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
                ("name", models.CharField(max_length=255)),
                (
                    "capacity",
                    models.PositiveIntegerField(
                        help_text="Maximum guest capacity.",
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(500),
                        ],
                    ),
                ),
                (
                    "base_price_per_day",
                    models.PositiveIntegerField(
                        help_text="Amount in paise (₹1 = 100 paise).",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="Inactive halls are hidden from availability searches.",
                    ),
                ),
                (
                    "operational_status",
                    models.CharField(
                        choices=[
                            ("available", "Available"),
                            ("blocked", "Blocked"),
                            ("maintenance", "Maintenance"),
                        ],
                        default="available",
                        help_text="Staff-managed availability (separate from booking occupancy).",
                        max_length=20,
                    ),
                ),
                ("description", models.TextField(blank=True, default="")),
                ("amenities", models.JSONField(blank=True, default=list)),
                (
                    "branch",
                    models.OneToOneField(
                        help_text="The branch this function hall belongs to.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="function_hall",
                        to="branches.branch",
                    ),
                ),
            ],
            options={
                "verbose_name": "function hall",
                "verbose_name_plural": "function halls",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="FunctionHallImage",
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
                    "image",
                    models.ImageField(
                        help_text="Hall photo (JPEG, PNG, or WebP).",
                        upload_to="function_hall_images/",
                    ),
                ),
                ("caption", models.CharField(blank=True, max_length=200)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("is_primary", models.BooleanField(default=False)),
                (
                    "function_hall",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="images",
                        to="properties.functionhall",
                    ),
                ),
            ],
            options={
                "verbose_name": "function hall image",
                "verbose_name_plural": "function hall images",
                "ordering": ["sort_order", "created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="functionhall",
            index=models.Index(
                fields=["is_deleted", "is_active", "operational_status"],
                name="idx_hall_availability",
            ),
        ),
        migrations.AddIndex(
            model_name="functionhall",
            index=models.Index(fields=["branch"], name="idx_hall_branch"),
        ),
        migrations.AddConstraint(
            model_name="functionhall",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_deleted", False)),
                fields=("branch",),
                name="uq_active_hall_per_branch",
            ),
        ),
    ]
