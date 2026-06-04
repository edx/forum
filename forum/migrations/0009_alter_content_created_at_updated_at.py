# Generated migration to fix created_at/updated_at on Content so that
# historical timestamps can be preserved during MongoDB → MySQL migration.
# Removes auto_now_add/auto_now behaviour and replaces with a plain default
# so the migration script (and the backfill command) can write correct values.

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("forum", "0008_discussionmuterecord_and_more"),
    ]

    operations = [
        # Comment
        migrations.AlterField(
            model_name="comment",
            name="created_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AlterField(
            model_name="comment",
            name="updated_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        # CommentThread
        migrations.AlterField(
            model_name="commentthread",
            name="created_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AlterField(
            model_name="commentthread",
            name="updated_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
    ]
