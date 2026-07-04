# Generated manually for room operational status and images.

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("properties", "0002_convert_to_uuid_pk"),
    ]

    operations = [
        migrations.AddField(
            model_name="room",
            name="description",
            field=models.TextField(
                blank=True,
                help_text="Optional notes shown to staff (amenities, view, etc.).",
            ),
        ),
        migrations.AddField(
            model_name="room",
            name="operational_status",
            field=models.CharField(
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
        migrations.CreateModel(
            name="RoomImage",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "image",
                    models.ImageField(
                        help_text="Room photo (JPEG, PNG, or WebP).",
                        upload_to="rooms/%Y/%m/",
                    ),
                ),
                (
                    "caption",
                    models.CharField(blank=True, max_length=200),
                ),
                (
                    "sort_order",
                    models.PositiveSmallIntegerField(default=0),
                ),
                (
                    "is_primary",
                    models.BooleanField(default=False),
                ),
                (
                    "room",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="images",
                        to="properties.room",
                    ),
                ),
            ],
            options={
                "verbose_name": "room image",
                "verbose_name_plural": "room images",
                "ordering": ["sort_order", "created_at"],
            },
        ),
    ]
