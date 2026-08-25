"""Tests for AI moderation functionality."""

import sys
from typing import Any, Generator
from unittest.mock import Mock, MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings

from forum.ai_moderation.service import AIModerationService, moderate_and_flag_spam
from forum.backends.mysql.models import ModerationAuditLog
from forum.utils import ForumV2RequestError

User = get_user_model()

pytestmark = pytest.mark.django_db


# Mock openedx module to prevent import errors
if "openedx" not in sys.modules:
    # Create a mock CourseWaffleFlag class
    class MockCourseWaffleFlag:
        """Mock implementation of openedx CourseWaffleFlag for testing."""

        def __init__(self, flag_name: str, module_name: str) -> None:
            self.flag_name = flag_name
            self.module_name = module_name

        def is_enabled(self, _course_key: Any) -> bool:
            # This will be overridden by our fixture patches
            return False

    mock_openedx = MagicMock()
    mock_waffle_utils = MagicMock()
    mock_waffle_utils.CourseWaffleFlag = MockCourseWaffleFlag

    sys.modules["openedx"] = mock_openedx
    sys.modules["openedx.core"] = MagicMock()
    sys.modules["openedx.core.djangoapps"] = MagicMock()
    sys.modules["openedx.core.djangoapps.waffle_utils"] = mock_waffle_utils


XPERT_BACKEND = "forum.ai_moderation.backends.xpert.XPertModerationBackend"


def classifier_response(payload: str) -> Mock:
    """
    Build a mocked classifier response, in the shape the configured backend reads.

    Args:
        payload: The JSON document the classifier answered with.
    """
    response = Mock()
    response.status_code = 200
    response.json.return_value = [{"content": payload}]
    return response


SPAM_RESPONSE = (
    '{"classification": "spam", "reasoning": "Spam detected", "confidence_score": 0.9}'
)
NOT_SPAM_RESPONSE = (
    '{"classification": "not_spam", "reasoning": "This is legitimate content", '
    '"confidence_score": 0.9}'
)


@pytest.fixture(autouse=True)
def clear_moderation_cache() -> Generator[None, None, None]:
    """Keep cached spam verdicts from leaking between tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def mock_ai_moderation_settings() -> Any:
    """
    Configure AI moderation against a provider backend.

    Which backend does not matter to any test in this module -- they are about
    the provider-agnostic workflow -- but one has to be named, because forum
    ships no default.
    """
    with override_settings(
        AI_MODERATION_BACKEND=XPERT_BACKEND,
        AI_MODERATION_API_URL="http://test-api.example.com",
        AI_MODERATION_CLIENT_ID="test-client-id",
        AI_MODERATION_USER_ID="999",
        AI_MODERATION_FLAGGED_CACHE_TTL=60 * 60,
        AI_MODERATION_FLAGGED_CACHE_PREFIX="ai_moderation:flagged:v1",
    ):
        yield


@pytest.fixture
def mock_waffle_flags() -> Any:
    """Mock waffle flags for AI moderation."""
    # Now we can safely import forum.toggles since openedx is mocked
    import forum.toggles  # pylint: disable=import-outside-toplevel

    mock_enabled = Mock(return_value=True)
    mock_auto_delete = Mock(return_value=True)

    with patch.object(
        forum.toggles, "is_ai_moderation_enabled", mock_enabled
    ), patch.object(forum.toggles, "is_ai_auto_delete_spam_enabled", mock_auto_delete):
        yield {"enabled": mock_enabled, "auto_delete": mock_auto_delete}


@pytest.fixture
def ai_service(
    mock_ai_moderation_settings: Any,  # pylint: disable=redefined-outer-name,unused-argument
) -> AIModerationService:
    """Create an AI moderation service instance."""
    return AIModerationService()


@pytest.fixture
def sample_thread_content() -> dict[str, Any]:
    """Create sample thread content for testing."""
    return {
        "_id": "thread123",
        "_type": "CommentThread",
        "course_id": "course-v1:edX+DemoX+Demo",
        "title": "Test Thread",
        "body": "This is test content",
        "author_id": "1",
        "author_username": "testuser",
    }


@pytest.fixture
def sample_comment_content() -> dict[str, Any]:
    """Create sample comment content for testing."""
    return {
        "_id": "comment456",
        "_type": "Comment",
        "course_id": "course-v1:edX+DemoX+Demo",
        "body": "This is a test comment",
        "author_id": "1",
        "author_username": "testuser",
        "comment_thread_id": "thread123",
    }


class TestAIModerationAutoDelete:  # pylint: disable=redefined-outer-name,unused-argument
    """Tests for AI moderation auto-delete functionality."""

    def test_auto_delete_triggered_when_enabled(
        self,
        ai_service: AIModerationService,
        mock_waffle_flags: dict[str, Mock],
        sample_thread_content: dict[str, Any],
    ) -> None:
        """Test that auto-delete is triggered when waffle flag is enabled."""
        # Mock API response indicating spam
        mock_response = classifier_response(SPAM_RESPONSE)

        backend = Mock()

        with patch("requests.post", return_value=mock_response), patch.object(
            ai_service, "_delete_content"
        ) as mock_delete:

            result = ai_service.moderate_and_flag_content(
                "spam content",
                sample_thread_content,
                course_id="course-v1:edX+DemoX+Demo",
                backend=backend,
            )

            # Verify auto-delete was called
            mock_delete.assert_called_once_with(sample_thread_content)

            # Verify actions_taken includes both flagged and soft_deleted
            assert "flagged" in result["actions_taken"]
            assert "soft_deleted" in result["actions_taken"]
            assert result["is_spam"] is True

    def test_auto_delete_not_triggered_when_disabled(
        self,
        ai_service: AIModerationService,
        mock_waffle_flags: dict[str, Mock],
        sample_thread_content: dict[str, Any],
    ) -> None:
        """Test that auto-delete is NOT triggered when waffle flag is disabled."""
        # Disable auto-delete flag
        mock_waffle_flags["auto_delete"].return_value = False

        # Mock API response indicating spam
        mock_response = classifier_response(SPAM_RESPONSE)

        backend = Mock()

        with patch("requests.post", return_value=mock_response), patch.object(
            ai_service, "_delete_content"
        ) as mock_delete:

            result = ai_service.moderate_and_flag_content(
                "spam content",
                sample_thread_content,
                course_id="course-v1:edX+DemoX+Demo",
                backend=backend,
            )

            # Verify auto-delete was NOT called
            mock_delete.assert_not_called()

            # Verify actions_taken includes only flagged
            assert "flagged" in result["actions_taken"]
            assert "soft_deleted" not in result["actions_taken"]
            assert result["is_spam"] is True

    def test_auto_delete_not_triggered_for_non_spam(
        self,
        ai_service: AIModerationService,
        mock_waffle_flags: dict[str, Mock],
        sample_thread_content: dict[str, Any],
    ) -> None:
        """Test that auto-delete is NOT triggered for non-spam content."""
        # Mock API response indicating NOT spam
        mock_response = classifier_response(NOT_SPAM_RESPONSE)

        backend = Mock()

        with patch("requests.post", return_value=mock_response), patch.object(
            ai_service, "_delete_content"
        ) as mock_delete:

            result = ai_service.moderate_and_flag_content(
                "legitimate content",
                sample_thread_content,
                course_id="course-v1:edX+DemoX+Demo",
                backend=backend,
            )

            # Verify auto-delete was NOT called
            mock_delete.assert_not_called()

            # Verify no actions taken
            assert result["actions_taken"] == ["no_action"]
            assert result["is_spam"] is False

    def test_actions_taken_reflects_flagged_only_when_delete_disabled(
        self,
        ai_service: AIModerationService,
        mock_waffle_flags: dict[str, Mock],
        sample_comment_content: dict[str, Any],
    ) -> None:
        """Test that actions_taken correctly reflects flagging without deletion."""
        # Disable auto-delete
        mock_waffle_flags["auto_delete"].return_value = False

        mock_response = classifier_response(SPAM_RESPONSE)

        backend = Mock()

        with patch("requests.post", return_value=mock_response):
            result = ai_service.moderate_and_flag_content(
                "spam content",
                sample_comment_content,
                course_id="course-v1:edX+DemoX+Demo",
                backend=backend,
            )

            assert result["actions_taken"] == ["flagged"]
            assert result["flagged"] is True

    def test_actions_taken_reflects_both_when_delete_enabled(
        self,
        ai_service: AIModerationService,
        mock_waffle_flags: dict[str, Mock],
        sample_comment_content: dict[str, Any],
    ) -> None:
        """Test that actions_taken correctly reflects both flagging and deletion."""
        mock_response = classifier_response(SPAM_RESPONSE)

        backend = Mock()

        with patch("requests.post", return_value=mock_response), patch.object(
            ai_service, "_delete_content"
        ):

            result = ai_service.moderate_and_flag_content(
                "spam content",
                sample_comment_content,
                course_id="course-v1:edX+DemoX+Demo",
                backend=backend,
            )

            assert "flagged" in result["actions_taken"]
            assert "soft_deleted" in result["actions_taken"]
            assert len(result["actions_taken"]) == 2


class TestAIModerationBackendDelegation:  # pylint: disable=redefined-outer-name,unused-argument
    """Tests that the service delegates classification to the configured backend."""

    def test_service_calls_backend_classify(
        self,
        ai_service: AIModerationService,
        mock_waffle_flags: dict[str, Mock],
        sample_thread_content: dict[str, Any],
    ) -> None:
        """The service asks the backend to classify, and acts on what it returns."""
        classify = Mock(
            return_value={
                "classification": "spam_or_scam",
                "reasoning": "Spam detected",
                "confidence_score": 0.9,
            }
        )
        mock_waffle_flags["auto_delete"].return_value = False

        with patch.object(ai_service.moderation_backend, "classify", classify):
            result = ai_service.moderate_and_flag_content(
                "spam content",
                sample_thread_content,
                course_id="course-v1:edX+DemoX+Demo",
                backend=Mock(),
            )

        classify.assert_called_once_with("spam content")
        assert result["is_spam"] is True
        assert result["actions_taken"] == ["flagged"]

    def test_service_has_no_provider_specific_request_code(self) -> None:
        """The service no longer talks to any provider itself."""
        assert not hasattr(AIModerationService, "_make_api_request")

    def test_backend_failure_leaves_content_alone(
        self,
        ai_service: AIModerationService,
        mock_waffle_flags: dict[str, Mock],
        sample_thread_content: dict[str, Any],
    ) -> None:
        """A backend that cannot classify degrades moderation, it does not raise."""
        backend = Mock()

        with patch.object(
            ai_service.moderation_backend, "classify", Mock(return_value=None)
        ):
            result = ai_service.moderate_and_flag_content(
                "spam content",
                sample_thread_content,
                course_id="course-v1:edX+DemoX+Demo",
                backend=backend,
            )

        assert result["is_spam"] is False
        assert result["actions_taken"] == ["no_action"]
        assert result["reasoning"] == "AI moderation API failed"
        backend.flag_content_as_spam.assert_not_called()

    def test_unexpected_backend_error_is_contained(
        self,
        ai_service: AIModerationService,
        mock_waffle_flags: dict[str, Mock],
        sample_thread_content: dict[str, Any],
    ) -> None:
        """An exception from a third party backend must not break posting."""
        with patch.object(
            ai_service.moderation_backend,
            "classify",
            Mock(side_effect=RuntimeError("boom")),
        ):
            result = ai_service.moderate_and_flag_content(
                "spam content",
                sample_thread_content,
                course_id="course-v1:edX+DemoX+Demo",
                backend=Mock(),
            )

        assert result["is_spam"] is False
        assert result["actions_taken"] == ["no_action"]


class TestAIModerationUserId:  # pylint: disable=redefined-outer-name,unused-argument
    """Tests for attributing moderation actions to AI_MODERATION_USER_ID."""

    def test_actions_are_attributed_to_configured_user(
        self,
        ai_service: AIModerationService,
        mock_waffle_flags: dict[str, Mock],
        sample_thread_content: dict[str, Any],
    ) -> None:
        """Flagging is performed as the configured moderation user."""
        mock_waffle_flags["auto_delete"].return_value = False
        backend = Mock()

        with patch("requests.post", return_value=classifier_response(SPAM_RESPONSE)):
            ai_service.moderate_and_flag_content(
                "spam content",
                sample_thread_content,
                course_id="course-v1:edX+DemoX+Demo",
                backend=backend,
            )

        backend.flag_as_abuse.assert_called_once_with(
            "999", "thread123", entity_type="CommentThread"
        )

    def test_missing_user_id_reports_a_configuration_error(
        self,
        ai_service: AIModerationService,
        mock_waffle_flags: dict[str, Mock],
        sample_thread_content: dict[str, Any],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Without AI_MODERATION_USER_ID nothing is moderated, and it is logged."""
        backend = Mock()

        with override_settings(AI_MODERATION_USER_ID=None), patch(
            "requests.post", return_value=classifier_response(SPAM_RESPONSE)
        ):
            result = ai_service.moderate_and_flag_content(
                "spam content",
                sample_thread_content,
                course_id="course-v1:edX+DemoX+Demo",
                backend=backend,
            )

        assert result["is_spam"] is True
        assert result["flagged"] is False
        assert result["actions_taken"] == ["no_action"]
        backend.flag_as_abuse.assert_not_called()
        assert "AI_MODERATION_USER_ID" in caplog.text


class TestAIModerationCaching:  # pylint: disable=redefined-outer-name,unused-argument
    """Tests for caching of flagged moderation results."""

    def test_flagged_result_is_cached_and_reused(
        self,
        ai_service: AIModerationService,
        mock_waffle_flags: dict[str, Mock],
        sample_thread_content: dict[str, Any],
    ) -> None:
        cache.clear()
        mock_waffle_flags["auto_delete"].return_value = False

        # Mock API response indicating spam
        mock_response = classifier_response(SPAM_RESPONSE)

        backend = Mock()

        with patch("requests.post", return_value=mock_response) as mock_post:
            # First call should hit the classifier and then cache
            first = ai_service.moderate_and_flag_content(
                "spam content",
                sample_thread_content,
                course_id="course-v1:edX+DemoX+Demo",
                backend=backend,
            )
            assert first["is_spam"] is True
            assert mock_post.call_count == 1

            # Second call with identical content should use cached result
            second = ai_service.moderate_and_flag_content(
                "spam content",
                sample_thread_content,
                course_id="course-v1:edX+DemoX+Demo",
                backend=backend,
            )
            assert second["is_spam"] is True
            assert mock_post.call_count == 1


class TestAIModerationErrorHandling:  # pylint: disable=redefined-outer-name,unused-argument
    """Tests for error handling in AI moderation auto-delete."""

    def test_deletion_failure_after_successful_flagging(
        self,
        ai_service: AIModerationService,
        mock_waffle_flags: dict[str, Mock],
        sample_thread_content: dict[str, Any],
    ) -> None:
        """Test that flagging succeeds even if deletion fails."""
        mock_response = classifier_response(SPAM_RESPONSE)

        backend = Mock()

        with patch("requests.post", return_value=mock_response), patch.object(
            ai_service,
            "_delete_content",
            side_effect=ForumV2RequestError("Delete failed"),
        ):

            result = ai_service.moderate_and_flag_content(
                "spam content",
                sample_thread_content,
                course_id="course-v1:edX+DemoX+Demo",
                backend=backend,
            )

            # Flagging should still succeed
            assert result["is_spam"] is True
            assert "flagged" in result["actions_taken"]
            # soft_deleted should not be in actions since deletion failed
            assert "soft_deleted" not in result["actions_taken"]

    def test_flagging_failure_prevents_deletion(
        self,
        ai_service: AIModerationService,
        mock_waffle_flags: dict[str, Mock],
        sample_thread_content: dict[str, Any],
    ) -> None:
        """Test that if flagging fails, deletion is not attempted."""
        mock_response = classifier_response(SPAM_RESPONSE)

        backend = Mock()
        backend.flag_content_as_spam.side_effect = ValueError("Flag failed")

        with patch("requests.post", return_value=mock_response), patch.object(
            ai_service, "_delete_content"
        ) as mock_delete:

            result = ai_service.moderate_and_flag_content(
                "spam content",
                sample_thread_content,
                course_id="course-v1:edX+DemoX+Demo",
                backend=backend,
            )

            # Delete should not be called if flagging fails
            mock_delete.assert_not_called()
            assert result["actions_taken"] == ["no_action"]


class TestDeleteContentMethod:  # pylint: disable=redefined-outer-name,protected-access
    """Tests for the _delete_content method."""

    def test_delete_thread_calls_api_correctly(
        self,
        ai_service: AIModerationService,
        sample_thread_content: dict[str, Any],
    ) -> None:
        """Test that deleting a thread calls the API layer correctly."""
        with patch("forum.api.threads.delete_thread") as mock_delete_thread:
            ai_service._delete_content(sample_thread_content)

            mock_delete_thread.assert_called_once_with(
                "thread123",
                course_id="course-v1:edX+DemoX+Demo",
                deleted_by="999",
            )

    def test_delete_comment_calls_api_correctly(
        self,
        ai_service: AIModerationService,
        sample_comment_content: dict[str, Any],
    ) -> None:
        """Test that deleting a comment calls the API layer correctly."""
        with patch("forum.api.comments.delete_comment") as mock_delete_comment:
            ai_service._delete_content(sample_comment_content)

            mock_delete_comment.assert_called_once_with(
                "comment456",
                course_id="course-v1:edX+DemoX+Demo",
                deleted_by="999",
            )

    def test_delete_handles_api_errors(
        self,
        ai_service: AIModerationService,
        sample_thread_content: dict[str, Any],
    ) -> None:
        """Test that deletion errors propagate to caller."""
        with patch("forum.api.threads.delete_thread") as mock_delete_thread:
            mock_delete_thread.side_effect = ForumV2RequestError("API Error")

            # Should raise exception to caller
            with pytest.raises(ForumV2RequestError):
                ai_service._delete_content(sample_thread_content)


class TestModerateAndFlagSpamFunction:  # pylint: disable=redefined-outer-name
    """Tests for the module-level moderate_and_flag_spam function."""

    def test_moderate_and_flag_spam_with_auto_delete(  # pylint: disable=unused-argument
        self,
        mock_ai_moderation_settings: Any,
        mock_waffle_flags: dict[str, Mock],
        sample_thread_content: dict[str, Any],
    ) -> None:
        """Test the module-level function with auto-delete enabled."""
        mock_response = classifier_response(SPAM_RESPONSE)

        backend = Mock()

        with patch("requests.post", return_value=mock_response), patch(
            "forum.api.threads.delete_thread"
        ):

            result = moderate_and_flag_spam(
                "spam content",
                sample_thread_content,
                course_id="course-v1:edX+DemoX+Demo",
                backend=backend,
            )

            assert result["is_spam"] is True
            assert "flagged" in result["actions_taken"]
            assert "soft_deleted" in result["actions_taken"]


class TestAuditLogging:  # pylint: disable=redefined-outer-name,unused-argument
    """Tests for audit logging with auto-delete."""

    def test_audit_log_created_for_auto_deleted_content(
        self,
        ai_service: AIModerationService,
        mock_ai_moderation_settings: Any,
        mock_waffle_flags: dict[str, Mock],
        sample_thread_content: dict[str, Any],
    ) -> None:
        """Test that audit log is created with correct actions for auto-deleted content."""
        mock_response = classifier_response(SPAM_RESPONSE)

        backend = Mock()
        user = User.objects.create(username="testuser")
        sample_thread_content["author_id"] = str(user.pk)

        with patch("requests.post", return_value=mock_response), patch(
            "forum.api.threads.delete_thread"
        ):

            ai_service.moderate_and_flag_content(
                "spam content",
                sample_thread_content,
                course_id="course-v1:edX+DemoX+Demo",
                backend=backend,
            )

            # Verify audit log was created
            audit_logs = ModerationAuditLog.objects.filter(body="This is test content")
            assert audit_logs.exists()

            audit_log = audit_logs.first()
            assert audit_log is not None
            assert "flagged" in audit_log.actions_taken
            assert "soft_deleted" in audit_log.actions_taken
