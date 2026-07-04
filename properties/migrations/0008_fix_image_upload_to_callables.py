# Generated manually — use callable upload_to, not a literal path string.

import properties.media_paths
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("properties", "0007_property_image_upload_paths"),
    ]

    operations = [
        migrations.AlterField(
            model_name="functionhallimage",
            name="image",
            field=models.ImageField(
                help_text="Hall photo (JPEG, PNG, or WebP).",
                upload_to=properties.media_paths.function_hall_image_upload_to,
            ),
        ),
        migrations.AlterField(
            model_name="roomimage",
            name="image",
            field=models.ImageField(
                help_text="Room photo (JPEG, PNG, or WebP).",
                upload_to=properties.media_paths.room_image_upload_to,
            ),
        ),
    ]
