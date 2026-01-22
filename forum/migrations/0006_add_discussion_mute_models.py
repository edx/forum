# Generated on 2025-12-16 for mute functionality

from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ("forum", "0005_moderationauditlog_comment_is_spam_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DiscussionMute",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "course_id",
                    models.CharField(
                        db_index=True,
                        help_text="Course in which mute applies",
                        max_length=255,
                    ),
                ),
                (
                    "scope",
                    models.CharField(
                        choices=[("personal", "Personal"), ("course", "Course-wide")],
                        db_index=True,
                        default="personal",
                        help_text="Scope of the mute (personal or course-wide)",
                        max_length=10,
                    ),
                ),
                (
                    "reason",
                    models.TextField(
                        blank=True, help_text="Optional reason for muting"
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True, help_text="Whether the mute is currently active"
                    ),
                ),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("modified", models.DateTimeField(auto_now=True)),
                ("muted_at", models.DateTimeField(auto_now_add=True)),
                ("unmuted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "muted_by",
                    models.ForeignKey(
                        db_index=True,
                        help_text="User performing the mute",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="forum_muted_users",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "muted_user",
                    models.ForeignKey(
                        db_index=True,
                        help_text="User being muted",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="forum_muted_by_users",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "unmuted_by",
                    models.ForeignKey(
                        blank=True,
                        help_text="User who performed the unmute action",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="forum_mute_unactions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "forum_discussion_user_mute",
            },
        ),
        migrations.CreateModel(
            name="DiscussionMuteException",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "course_id",
                    models.CharField(
                        db_index=True,
                        help_text="Course where the exception applies",
                        max_length=255,
                    ),
                ),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("modified", models.DateTimeField(auto_now=True)),
                (
                    "exception_user",
                    models.ForeignKey(
                        db_index=True,
                        help_text="User who unmuted the muted_user for themselves",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="forum_mute_exceptions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "muted_user",
                    models.ForeignKey(
                        db_index=True,
                        help_text="User who is globally muted in this course",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="forum_mute_exceptions_for",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "forum_discussion_mute_exception",
            },
        ),
        migrations.AddConstraint(
            model_name="discussionmute",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True), ("scope", "personal")),
                fields=("muted_user", "muted_by", "course_id", "scope"),
                name="forum_unique_active_personal_mute",
            ),
        ),
        migrations.AddConstraint(
            model_name="discussionmute",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True), ("scope", "course")),
                fields=("muted_user", "course_id"),
                name="forum_unique_active_course_mute",
            ),
        ),
        migrations.AddIndex(
            model_name="discussionmute",
            index=models.Index(
                fields=["muted_user", "course_id", "is_active"],
                name="forum_discussion_user_mute_muted_user_course_id_is_active_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="discussionmute",
            index=models.Index(
                fields=["muted_by", "course_id", "scope"],
                name="forum_discussion_user_mute_muted_by_course_id_scope_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="discussionmute",
            index=models.Index(
                fields=["scope", "course_id", "is_active"],
                name="forum_discussion_user_mute_scope_course_id_is_active_idx",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="discussionmuteexception",
            unique_together={("muted_user", "exception_user", "course_id")},
        ),
        migrations.AddIndex(
            model_name="discussionmuteexception",
            index=models.Index(
                fields=["muted_user", "course_id"],
                name="forum_discussion_mute_exception_muted_user_course_id_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="discussionmuteexception",
            index=models.Index(
                fields=["exception_user", "course_id"],
                name="forum_discussion_mute_exception_exception_user_course_id_idx",
            ),
        ),
    ]
