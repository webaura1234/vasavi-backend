"""Rewrite mistaken upload_to string paths to ``rooms/`` / ``function_halls/`` keys."""

from django.db import migrations

ROOM_PREFIX = "properties.media_paths.room_image_upload_to/"
HALL_PREFIX = "properties.media_paths.function_hall_image_upload_to/"


def fix_paths(apps, schema_editor):
    RoomImage = apps.get_model("properties", "RoomImage")
    FunctionHallImage = apps.get_model("properties", "FunctionHallImage")

    for img in RoomImage.objects.filter(image__startswith=ROOM_PREFIX):
        img.image.name = "rooms/" + img.image.name[len(ROOM_PREFIX) :]
        img.save(update_fields=["image"])

    for img in FunctionHallImage.objects.filter(image__startswith=HALL_PREFIX):
        img.image.name = "function_halls/" + img.image.name[len(HALL_PREFIX) :]
        img.save(update_fields=["image"])


class Migration(migrations.Migration):

    dependencies = [
        ("properties", "0008_fix_image_upload_to_callables"),
    ]

    operations = [
        migrations.RunPython(fix_paths, migrations.RunPython.noop),
    ]
