"""Tests for MongoDB discussion ban models."""
# pylint: disable=redefined-outer-name

from datetime import datetime

import pytest
from bson import ObjectId

from forum.backends.mongodb.bans import (
    DiscussionBanExceptions,
    DiscussionBans,
    DiscussionModerationLogs,
)


@pytest.fixture
def discussion_bans():
    """Fixture to provide a DiscussionBans instance."""
    return DiscussionBans()


@pytest.fixture
def discussion_ban_exceptions():
    """Fixture to provide a DiscussionBanExceptions instance."""
    return DiscussionBanExceptions()


@pytest.fixture
def discussion_moderation_logs():
    """Fixture to provide a DiscussionModerationLogs instance."""
    return DiscussionModerationLogs()


@pytest.fixture
def sample_course_id():
    """Sample course ID."""
    return "course-v1:edX+DemoX+Demo_Course"


@pytest.fixture
def sample_org_key():
    """Sample organization key."""
    return "edX"


class TestDiscussionBans:
    """Tests for DiscussionBans model."""

    def test_insert_course_ban(self, discussion_bans, sample_course_id):
        """Test creating a course-level ban."""
        ban_id = discussion_bans.insert(
            user_id=123,
            scope=DiscussionBans.SCOPE_COURSE,
            reason="Violation of community guidelines",
            banned_by_id=456,
            course_id=sample_course_id,
            is_active=True,
        )

        assert ban_id is not None
        assert ObjectId.is_valid(ban_id)

        # Verify the ban was created
        ban = discussion_bans.get(ban_id)
        assert ban is not None
        assert ban["user_id"] == 123
        assert ban["scope"] == "course"
        assert ban["course_id"] == sample_course_id
        assert ban["is_active"] is True
        assert ban["banned_by_id"] == 456
        assert ban["reason"] == "Violation of community guidelines"

    def test_insert_org_ban(self, discussion_bans, sample_org_key):
        """Test creating an organization-level ban."""
        ban_id = discussion_bans.insert(
            user_id=123,
            scope=DiscussionBans.SCOPE_ORGANIZATION,
            reason="Multiple violations across courses",
            banned_by_id=456,
            org_key=sample_org_key,
            is_active=True,
        )

        assert ban_id is not None

        # Verify the ban was created
        ban = discussion_bans.get(ban_id)
        assert ban is not None
        assert ban["user_id"] == 123
        assert ban["scope"] == "organization"
        assert ban["org_key"] == sample_org_key
        assert ban["is_active"] is True

    def test_update_ban_to_inactive(self, discussion_bans, sample_course_id):
        """Test updating a ban to inactive (unbanning)."""
        ban_id = discussion_bans.insert(
            user_id=123,
            scope=DiscussionBans.SCOPE_COURSE,
            reason="Test ban",
            banned_by_id=456,
            course_id=sample_course_id,
        )

        unbanned_at = datetime.utcnow()
        modified_count = discussion_bans.update_ban(
            ban_id=ban_id,
            is_active=False,
            unbanned_by_id=789,
            unbanned_at=unbanned_at,
        )

        assert modified_count == 1

        # Verify the ban was updated
        ban = discussion_bans.get(ban_id)
        assert ban["is_active"] is False
        assert ban["unbanned_by_id"] == 789
        assert ban["unbanned_at"] is not None

    def test_get_active_ban_by_course(self, discussion_bans, sample_course_id):
        """Test retrieving an active course-level ban."""
        discussion_bans.insert(
            user_id=123,
            scope=DiscussionBans.SCOPE_COURSE,
            reason="Test ban",
            banned_by_id=456,
            course_id=sample_course_id,
            is_active=True,
        )

        ban = discussion_bans.get_active_ban(
            user_id=123,
            course_id=sample_course_id,
            scope=DiscussionBans.SCOPE_COURSE,
        )

        assert ban is not None
        assert ban["user_id"] == 123
        assert ban["course_id"] == sample_course_id
        assert ban["is_active"] is True

    def test_get_active_ban_by_org(self, discussion_bans, sample_org_key):
        """Test retrieving an active organization-level ban."""
        discussion_bans.insert(
            user_id=123,
            scope=DiscussionBans.SCOPE_ORGANIZATION,
            reason="Test ban",
            banned_by_id=456,
            org_key=sample_org_key,
            is_active=True,
        )

        ban = discussion_bans.get_active_ban(
            user_id=123,
            org_key=sample_org_key,
            scope=DiscussionBans.SCOPE_ORGANIZATION,
        )

        assert ban is not None
        assert ban["user_id"] == 123
        assert ban["org_key"] == sample_org_key
        assert ban["is_active"] is True

    def test_get_active_ban_returns_none_for_inactive(self, discussion_bans, sample_course_id):
        """Test that get_active_ban returns None for inactive bans."""
        ban_id = discussion_bans.insert(
            user_id=123,
            scope=DiscussionBans.SCOPE_COURSE,
            reason="Test ban",
            banned_by_id=456,
            course_id=sample_course_id,
            is_active=True,
        )

        # Deactivate the ban
        discussion_bans.update_ban(ban_id=ban_id, is_active=False)

        ban = discussion_bans.get_active_ban(
            user_id=123,
            course_id=sample_course_id,
        )

        assert ban is None

    def test_is_user_banned_course_level(self, discussion_bans, sample_course_id):
        """Test checking if user is banned at course level."""
        discussion_bans.insert(
            user_id=123,
            scope=DiscussionBans.SCOPE_COURSE,
            reason="Test ban",
            banned_by_id=456,
            course_id=sample_course_id,
            is_active=True,
        )

        is_banned = discussion_bans.is_user_banned(
            user_id=123,
            course_id=sample_course_id,
            check_org=False,
        )

        assert is_banned is True

    def test_is_user_banned_org_level(self, discussion_bans):
        """Test checking if user is banned at organization level."""
        course_id = "course-v1:edX+DemoX+Demo_Course"

        discussion_bans.insert(
            user_id=123,
            scope=DiscussionBans.SCOPE_ORGANIZATION,
            reason="Test ban",
            banned_by_id=456,
            org_key="edX",
            is_active=True,
        )

        is_banned = discussion_bans.is_user_banned(
            user_id=123,
            course_id=course_id,
            check_org=True,
        )

        assert is_banned is True

    def test_is_user_banned_with_exception(
        self,
        discussion_bans,
        discussion_ban_exceptions,
    ):
        """Test that user with exception to org ban is not banned in that course."""
        course_id = "course-v1:edX+DemoX+Demo_Course"

        # Create org-level ban
        ban_id = discussion_bans.insert(
            user_id=123,
            scope=DiscussionBans.SCOPE_ORGANIZATION,
            reason="Test ban",
            banned_by_id=456,
            org_key="edX",
            is_active=True,
        )

        # Create exception for specific course
        discussion_ban_exceptions.insert(
            ban_id=ban_id,
            course_id=course_id,
            unbanned_by_id=789,
            reason="Good behavior in this course",
        )

        is_banned = discussion_bans.is_user_banned(
            user_id=123,
            course_id=course_id,
            check_org=True,
        )

        assert is_banned is False

    def test_is_user_not_banned(self, discussion_bans, sample_course_id):
        """Test that user without ban returns False."""
        is_banned = discussion_bans.is_user_banned(
            user_id=999,
            course_id=sample_course_id,
        )

        assert is_banned is False

    def test_get_user_bans_all(self, discussion_bans, sample_course_id):
        """Test retrieving all bans for a user."""
        # Create multiple bans
        discussion_bans.insert(
            user_id=123,
            scope=DiscussionBans.SCOPE_COURSE,
            reason="First ban",
            banned_by_id=456,
            course_id=sample_course_id,
            is_active=True,
        )

        ban_id = discussion_bans.insert(
            user_id=123,
            scope=DiscussionBans.SCOPE_COURSE,
            reason="Second ban",
            banned_by_id=456,
            course_id="course-v1:edX+CS50+2024",
            is_active=True,
        )

        # Deactivate one
        discussion_bans.update_ban(ban_id=ban_id, is_active=False)

        # Get all bans
        bans = discussion_bans.get_user_bans(user_id=123)
        assert len(bans) == 2

    def test_get_user_bans_active_only(self, discussion_bans, sample_course_id):
        """Test retrieving only active bans for a user."""
        discussion_bans.insert(
            user_id=123,
            scope=DiscussionBans.SCOPE_COURSE,
            reason="Active ban",
            banned_by_id=456,
            course_id=sample_course_id,
            is_active=True,
        )

        ban_id = discussion_bans.insert(
            user_id=123,
            scope=DiscussionBans.SCOPE_COURSE,
            reason="Inactive ban",
            banned_by_id=456,
            course_id="course-v1:edX+CS50+2024",
            is_active=True,
        )
        discussion_bans.update_ban(ban_id=ban_id, is_active=False)

        # Get active bans only
        bans = discussion_bans.get_user_bans(user_id=123, is_active=True)
        assert len(bans) == 1
        assert bans[0]["is_active"] is True

    def test_old_style_course_id_org_extraction(self, discussion_bans):
        """Test org extraction from old-style course IDs."""
        old_course_id = "edX/DemoX/Demo_Course"

        discussion_bans.insert(
            user_id=123,
            scope=DiscussionBans.SCOPE_ORGANIZATION,
            reason="Test ban",
            banned_by_id=456,
            org_key="edX",
            is_active=True,
        )

        is_banned = discussion_bans.is_user_banned(
            user_id=123,
            course_id=old_course_id,
            check_org=True,
        )

        assert is_banned is True


class TestDiscussionBanExceptions:
    """Tests for DiscussionBanExceptions model."""

    def test_insert_exception(
        self,
        discussion_bans,
        discussion_ban_exceptions,
        sample_course_id,
        sample_org_key,
    ):
        """Test creating a ban exception."""
        ban_id = discussion_bans.insert(
            user_id=123,
            scope=DiscussionBans.SCOPE_ORGANIZATION,
            reason="Org ban",
            banned_by_id=456,
            org_key=sample_org_key,
        )

        exception_id = discussion_ban_exceptions.insert(
            ban_id=ban_id,
            course_id=sample_course_id,
            unbanned_by_id=789,
            reason="Good behavior",
        )

        assert exception_id is not None
        assert ObjectId.is_valid(exception_id)

        # Verify the exception was created
        exception = discussion_ban_exceptions.get(exception_id)
        assert exception is not None
        assert str(exception["ban_id"]) == ban_id
        assert exception["course_id"] == sample_course_id
        assert exception["unbanned_by_id"] == 789

    def test_has_exception_returns_true(
        self,
        discussion_bans,
        discussion_ban_exceptions,
        sample_course_id,
        sample_org_key,
    ):
        """Test has_exception returns True when exception exists."""
        ban_id = discussion_bans.insert(
            user_id=123,
            scope=DiscussionBans.SCOPE_ORGANIZATION,
            reason="Org ban",
            banned_by_id=456,
            org_key=sample_org_key,
        )

        discussion_ban_exceptions.insert(
            ban_id=ban_id,
            course_id=sample_course_id,
            unbanned_by_id=789,
        )

        has_exception = discussion_ban_exceptions.has_exception(
            ban_id=ban_id,
            course_id=sample_course_id,
        )

        assert has_exception is True

    def test_has_exception_returns_false(
        self,
        discussion_bans,
        discussion_ban_exceptions,
        sample_org_key,
    ):
        """Test has_exception returns False when exception doesn't exist."""
        ban_id = discussion_bans.insert(
            user_id=123,
            scope=DiscussionBans.SCOPE_ORGANIZATION,
            reason="Org ban",
            banned_by_id=456,
            org_key=sample_org_key,
        )

        has_exception = discussion_ban_exceptions.has_exception(
            ban_id=ban_id,
            course_id="course-v1:edX+NonExistent+2024",
        )

        assert has_exception is False

    def test_get_exceptions_for_ban(
        self,
        discussion_bans,
        discussion_ban_exceptions,
        sample_org_key,
    ):
        """Test retrieving all exceptions for a ban."""
        ban_id = discussion_bans.insert(
            user_id=123,
            scope=DiscussionBans.SCOPE_ORGANIZATION,
            reason="Org ban",
            banned_by_id=456,
            org_key=sample_org_key,
        )

        # Create multiple exceptions
        discussion_ban_exceptions.insert(
            ban_id=ban_id,
            course_id="course-v1:edX+Course1+2024",
            unbanned_by_id=789,
        )
        discussion_ban_exceptions.insert(
            ban_id=ban_id,
            course_id="course-v1:edX+Course2+2024",
            unbanned_by_id=789,
        )

        exceptions = discussion_ban_exceptions.get_exceptions_for_ban(ban_id=ban_id)

        assert len(exceptions) == 2

    def test_delete_exception(
        self,
        discussion_bans,
        discussion_ban_exceptions,
        sample_course_id,
        sample_org_key,
    ):
        """Test deleting a ban exception."""
        ban_id = discussion_bans.insert(
            user_id=123,
            scope=DiscussionBans.SCOPE_ORGANIZATION,
            reason="Org ban",
            banned_by_id=456,
            org_key=sample_org_key,
        )

        discussion_ban_exceptions.insert(
            ban_id=ban_id,
            course_id=sample_course_id,
            unbanned_by_id=789,
        )

        deleted_count = discussion_ban_exceptions.delete_exception(
            ban_id=ban_id,
            course_id=sample_course_id,
        )

        assert deleted_count == 1

        # Verify deletion
        has_exception = discussion_ban_exceptions.has_exception(
            ban_id=ban_id,
            course_id=sample_course_id,
        )
        assert has_exception is False


class TestDiscussionModerationLogs:
    """Tests for DiscussionModerationLogs model."""

    def test_insert_ban_log(self, discussion_moderation_logs, sample_course_id):
        """Test creating a ban action log."""
        log_id = discussion_moderation_logs.insert(
            action_type=DiscussionModerationLogs.ACTION_BAN,
            target_user_id=123,
            moderator_id=456,
            course_id=sample_course_id,
            scope="course",
            reason="Violation of guidelines",
        )

        assert log_id is not None
        assert ObjectId.is_valid(log_id)

        # Verify the log was created
        log = discussion_moderation_logs.get(log_id)
        assert log is not None
        assert log["action_type"] == "ban_user"
        assert log["target_user_id"] == 123
        assert log["moderator_id"] == 456
        assert log["course_id"] == sample_course_id

    def test_insert_bulk_delete_log_with_metadata(
        self,
        discussion_moderation_logs,
        sample_course_id,
    ):
        """Test creating a bulk delete log with metadata."""
        metadata = {
            "task_id": "abc123",
            "threads_deleted": 5,
            "comments_deleted": 15,
        }

        log_id = discussion_moderation_logs.insert(
            action_type=DiscussionModerationLogs.ACTION_BULK_DELETE,
            target_user_id=123,
            moderator_id=456,
            course_id=sample_course_id,
            metadata=metadata,
        )

        log = discussion_moderation_logs.get(log_id)
        assert log["metadata"] == metadata

    def test_get_logs_for_user(self, discussion_moderation_logs, sample_course_id):
        """Test retrieving logs for a specific user."""
        # Create multiple logs
        discussion_moderation_logs.insert(
            action_type=DiscussionModerationLogs.ACTION_BAN,
            target_user_id=123,
            moderator_id=456,
            course_id=sample_course_id,
        )
        discussion_moderation_logs.insert(
            action_type=DiscussionModerationLogs.ACTION_UNBAN,
            target_user_id=123,
            moderator_id=456,
            course_id=sample_course_id,
        )
        discussion_moderation_logs.insert(
            action_type=DiscussionModerationLogs.ACTION_BAN,
            target_user_id=999,
            moderator_id=456,
            course_id=sample_course_id,
        )

        logs = discussion_moderation_logs.get_logs_for_user(user_id=123)

        assert len(logs) == 2
        assert all(log["target_user_id"] == 123 for log in logs)

    def test_get_logs_for_user_filtered_by_action(
        self,
        discussion_moderation_logs,
        sample_course_id,
    ):
        """Test retrieving logs for a user filtered by action type."""
        discussion_moderation_logs.insert(
            action_type=DiscussionModerationLogs.ACTION_BAN,
            target_user_id=123,
            moderator_id=456,
            course_id=sample_course_id,
        )
        discussion_moderation_logs.insert(
            action_type=DiscussionModerationLogs.ACTION_UNBAN,
            target_user_id=123,
            moderator_id=456,
            course_id=sample_course_id,
        )

        logs = discussion_moderation_logs.get_logs_for_user(
            user_id=123,
            action_type=DiscussionModerationLogs.ACTION_BAN,
        )

        assert len(logs) == 1
        assert logs[0]["action_type"] == "ban_user"

    def test_get_logs_for_course(self, discussion_moderation_logs, sample_course_id):
        """Test retrieving logs for a specific course."""
        other_course_id = "course-v1:edX+CS50+2024"

        # Create logs for different courses
        discussion_moderation_logs.insert(
            action_type=DiscussionModerationLogs.ACTION_BAN,
            target_user_id=123,
            moderator_id=456,
            course_id=sample_course_id,
        )
        discussion_moderation_logs.insert(
            action_type=DiscussionModerationLogs.ACTION_BAN,
            target_user_id=789,
            moderator_id=456,
            course_id=sample_course_id,
        )
        discussion_moderation_logs.insert(
            action_type=DiscussionModerationLogs.ACTION_BAN,
            target_user_id=999,
            moderator_id=456,
            course_id=other_course_id,
        )

        logs = discussion_moderation_logs.get_logs_for_course(course_id=sample_course_id)

        assert len(logs) == 2
        assert all(log["course_id"] == sample_course_id for log in logs)

    def test_get_logs_for_course_with_limit(
        self,
        discussion_moderation_logs,
        sample_course_id,
    ):
        """Test that logs respect the limit parameter."""
        # Create multiple logs
        for i in range(5):
            discussion_moderation_logs.insert(
                action_type=DiscussionModerationLogs.ACTION_BAN,
                target_user_id=100 + i,
                moderator_id=456,
                course_id=sample_course_id,
            )

        logs = discussion_moderation_logs.get_logs_for_course(
            course_id=sample_course_id,
            limit=3,
        )

        assert len(logs) == 3

    def test_logs_sorted_by_created_descending(
        self,
        discussion_moderation_logs,
        sample_course_id,
    ):
        """Test that logs are returned in reverse chronological order."""
        # Create logs with explicit ordering
        log_id_1 = discussion_moderation_logs.insert(
            action_type=DiscussionModerationLogs.ACTION_BAN,
            target_user_id=123,
            moderator_id=456,
            course_id=sample_course_id,
        )

        log_id_2 = discussion_moderation_logs.insert(
            action_type=DiscussionModerationLogs.ACTION_UNBAN,
            target_user_id=123,
            moderator_id=456,
            course_id=sample_course_id,
        )

        logs = discussion_moderation_logs.get_logs_for_user(user_id=123)

        # Verify we got 2 logs
        assert len(logs) == 2

        # Verify both logs are present (order may vary due to timing)
        log_ids = {str(log["_id"]) for log in logs}
        assert log_id_1 in log_ids
        assert log_id_2 in log_ids

        # Verify action types are correct
        action_types = {log["action_type"] for log in logs}
        assert DiscussionModerationLogs.ACTION_BAN in action_types
        assert DiscussionModerationLogs.ACTION_UNBAN in action_types
