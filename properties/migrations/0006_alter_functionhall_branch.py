# OneToOneField on branch blocks re-creating a hall after soft-delete.
# Use ForeignKey plus a partial unique index: one active (non-deleted) hall per branch.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("properties", "0005_add_function_hall"),
    ]

    operations = [
        migrations.AlterField(
            model_name="functionhall",
            name="branch",
            field=models.ForeignKey(
                help_text="The branch this function hall belongs to.",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="function_halls",
                to="branches.branch",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="functionhall",
            name="uq_active_hall_per_branch",
        ),
        migrations.AddConstraint(
            model_name="functionhall",
            constraint=models.UniqueConstraint(
                fields=["branch"],
                condition=models.Q(is_deleted=False),
                name="uq_one_active_hall_per_branch",
            ),
        ),
    ]
