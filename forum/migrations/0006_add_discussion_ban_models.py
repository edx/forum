# Generated migration for discussion moderation models
# Migrated from lms.djangoapps.discussion to forum app

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import model_utils.fields
import opaque_keys.edx.django.models


def populate_source_with_ai(apps, schema_editor):
    """
    Populate existing ModerationAuditLog records with source='ai'.
    
    This migration updates all existing records in production to have source='ai'.
    After AlterField runs, the field will exist with default='ai', but any records
    that were created before this migration might have source='human' (the old default).
    This function updates those records to 'ai'.
    
    Note: This assumes the 'source' field already exists in the database.
    If migration 0005 didn't create it, AlterField will add it with default='ai'.
    """
    ModerationAuditLog = apps.get_model('forum', 'ModerationAuditLog')
    
    # Update all existing records that don't have source='ai'
    # This handles records that may have source='human' from the old default
    # If field doesn't exist yet, this will be skipped (AlterField will add it)
    try:
        ModerationAuditLog.objects.exclude(source='ai').update(source='ai')
    except Exception:
        # Field might not exist yet, AlterField will handle adding it
        pass


def reverse_populate_source(apps, schema_editor):
    """
    Reverse migration: Set source back to 'human' for records that were updated.
    
    Note: This is a best-effort reversal. We can't perfectly restore the original
    state since we don't know which records were originally 'human' vs 'ai'.
    We set them all back to 'human' as a safe default.
    """
    ModerationAuditLog = apps.get_model('forum', 'ModerationAuditLog')
    
    # Set all records back to 'human' as a safe default
    ModerationAuditLog.objects.filter(source='ai').update(source='human')


class Migration(migrations.Migration):

    dependencies = [
        ('forum', '0005_moderationauditlog_comment_is_spam_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Create models - tables may already exist in production from discussion app
        # but must be created in test environments
        migrations.CreateModel(
            name='DiscussionBan',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('course_id', opaque_keys.edx.django.models.CourseKeyField(blank=True, db_index=True, help_text='Specific course for course-level bans, NULL for org-level bans', max_length=255, null=True)),
                ('org_key', models.CharField(blank=True, db_index=True, help_text="Organization name for org-level bans (e.g., 'HarvardX'), NULL for course-level", max_length=255, null=True)),
                ('scope', models.CharField(choices=[('course', 'Course'), ('organization', 'Organization')], db_index=True, default='course', max_length=20)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('reason', models.TextField()),
                ('banned_at', models.DateTimeField(auto_now_add=True)),
                ('unbanned_at', models.DateTimeField(blank=True, null=True)),
                ('banned_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='bans_issued', to=settings.AUTH_USER_MODEL)),
                ('unbanned_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='bans_reversed', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='discussion_bans', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Discussion Ban',
                'verbose_name_plural': 'Discussion Bans',
                'db_table': 'discussion_user_ban',
            },
        ),
        migrations.CreateModel(
            name='DiscussionModerationLog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action_type', models.CharField(choices=[('ban_user', 'Ban User'), ('unban_user', 'Unban User'), ('ban_exception', 'Ban Exception Created'), ('bulk_delete', 'Bulk Delete')], db_index=True, max_length=50)),
                ('course_id', opaque_keys.edx.django.models.CourseKeyField(db_index=True, max_length=255)),
                ('scope', models.CharField(blank=True, max_length=20, null=True)),
                ('reason', models.TextField(blank=True, null=True)),
                ('metadata', models.JSONField(blank=True, null=True)),
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('moderator', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='moderation_actions_performed', to=settings.AUTH_USER_MODEL)),
                ('target_user', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='moderation_actions_received', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Discussion Moderation Log',
                'verbose_name_plural': 'Discussion Moderation Logs',
                'db_table': 'discussion_moderation_log',
            },
        ),
        migrations.CreateModel(
            name='DiscussionBanException',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('course_id', opaque_keys.edx.django.models.CourseKeyField(db_index=True, help_text='Specific course where user is unbanned despite org-level ban', max_length=255)),
                ('reason', models.TextField(blank=True, null=True)),
                ('ban', models.ForeignKey(help_text='The organization-level ban this exception applies to', on_delete=django.db.models.deletion.CASCADE, related_name='exceptions', to='forum.discussionban')),
                ('unbanned_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ban_exceptions_created', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Discussion Ban Exception',
                'verbose_name_plural': 'Discussion Ban Exceptions',
                'db_table': 'discussion_ban_exception',
            },
        ),
        migrations.AddIndex(
            model_name='discussionmoderationlog',
            index=models.Index(fields=['target_user', '-created'], name='idx_target_user'),
        ),
        migrations.AddIndex(
            model_name='discussionmoderationlog',
            index=models.Index(fields=['moderator', '-created'], name='idx_moderator'),
        ),
        migrations.AddIndex(
            model_name='discussionmoderationlog',
            index=models.Index(fields=['course_id', '-created'], name='idx_course'),
        ),
        migrations.AddIndex(
            model_name='discussionmoderationlog',
            index=models.Index(fields=['action_type', '-created'], name='idx_action_type'),
        ),
        migrations.AddConstraint(
            model_name='discussionbanexception',
            constraint=models.UniqueConstraint(fields=('ban', 'course_id'), name='unique_ban_exception'),
        ),
        migrations.AddIndex(
            model_name='discussionbanexception',
            index=models.Index(fields=['ban', 'course_id'], name='idx_ban_course'),
        ),
        migrations.AddIndex(
            model_name='discussionbanexception',
            index=models.Index(fields=['course_id'], name='idx_exception_course'),
        ),
        migrations.AddIndex(
            model_name='discussionban',
            index=models.Index(fields=['user', 'is_active'], name='idx_user_active'),
        ),
        migrations.AddIndex(
            model_name='discussionban',
            index=models.Index(fields=['course_id', 'is_active'], name='idx_course_active'),
        ),
        migrations.AddIndex(
            model_name='discussionban',
            index=models.Index(fields=['org_key', 'is_active'], name='idx_org_active'),
        ),
        migrations.AddIndex(
            model_name='discussionban',
            index=models.Index(fields=['scope', 'is_active'], name='idx_scope_active'),
        ),
        migrations.AddConstraint(
            model_name='discussionban',
            constraint=models.UniqueConstraint(condition=models.Q(('is_active', True), ('scope', 'course')), fields=('user', 'course_id'), name='unique_active_course_ban'),
        ),
        migrations.AddConstraint(
            model_name='discussionban',
            constraint=models.UniqueConstraint(condition=models.Q(('is_active', True), ('scope', 'organization')), fields=('user', 'org_key'), name='unique_active_org_ban'),
        ),
        # Set default value for ModerationAuditLog.source field to 'ai' and update existing production data
        # First, alter/add the field definition to set default='ai' in Django
        # This will add the field if it doesn't exist, or alter it if it does
        migrations.AlterField(
            model_name='moderationauditlog',
            name='source',
            field=models.CharField(
                choices=[
                    ('human', 'Human Moderator'),
                    ('ai', 'AI Classifier'),
                    ('system', 'System/Automated'),
                ],
                db_index=True,
                default='ai',  # Changed from 'human' to 'ai'
                help_text='Who initiated the moderation action',
                max_length=20,
            ),
        ),
        # Then populate existing records with source='ai'
        # This updates any records that might have been created with the old default
        migrations.RunPython(
            populate_source_with_ai,
            reverse_populate_source,
        ),
    ]
