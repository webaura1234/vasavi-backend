# Generated manually — extend Booking for function hall reservations.

import django.db.models.deletion
from django.db import migrations, models


def backfill_booking_kind_room(apps, schema_editor):
    """Ensure every existing booking is tagged as a room booking."""
    Booking = apps.get_model("bookings", "Booking")
    Booking.objects.exclude(booking_kind="function_hall").update(booking_kind="room")


def reverse_backfill_booking_kind(apps, schema_editor):
    """No-op reverse — booking_kind column is dropped on migration rollback."""


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0005_bookingexport"),
        ("properties", "0005_add_function_hall"),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="booking_kind",
            field=models.CharField(
                choices=[
                    ("room", "Room"),
                    ("function_hall", "Function Hall"),
                ],
                db_index=True,
                default="room",
                help_text="Discriminator: whether this booking is for a room or function hall.",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="booking",
            name="function_hall",
            field=models.ForeignKey(
                blank=True,
                help_text="The function hall being booked. Mutually exclusive with room.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="bookings",
                to="properties.functionhall",
            ),
        ),
        migrations.AlterField(
            model_name="booking",
            name="room",
            field=models.ForeignKey(
                blank=True,
                help_text="The room being booked. Mutually exclusive with function_hall.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="bookings",
                to="properties.room",
            ),
        ),
        migrations.RunPython(
            backfill_booking_kind_room,
            reverse_backfill_booking_kind,
        ),
        migrations.AddIndex(
            model_name="booking",
            index=models.Index(
                fields=["function_hall", "check_in_date", "check_out_date"],
                name="idx_booking_hall_dates",
            ),
        ),
        migrations.AddConstraint(
            model_name="booking",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("room__isnull", False),
                    ("function_hall__isnull", True),
                )
                | models.Q(
                    ("room__isnull", True),
                    ("function_hall__isnull", False),
                ),
                name="chk_booking_exactly_one_resource",
            ),
        ),
    ]
