"""
AI Moderation utilities for forum content.
"""

import json
import logging
from typing import Dict, Optional, Any

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from opaque_keys.edx.keys import CourseKey
from rest_framework.serializers import ValidationError

from forum.backends.mysql.models import ModerationAuditLog
from forum.utils import ForumV2RequestError

User = get_user_model()
log = logging.getLogger(__name__)


def _get_author_from_content(content_instance: Any) -> Any:
    """
    Get author from content instance.

    Args:
        content_instance: Dict containing all content related data
    Returns:
        Author object or user ID
    """
    author_id = content_instance.get("author_id")
    if author_id:
        try:
            return User.objects.get(pk=author_id)
        except (User.DoesNotExist, ValueError, TypeError):
            # If we can't get the User object, return the ID as fallback
            return author_id
    return None


def create_moderation_audit_log(
    content_instance: Any,
    moderation_result: Dict[str, Any],
    actions_taken: list[str],
    original_author: Any,
) -> None:
    """
    Create an audit log entry for AI moderation decisions.

    Only creates audit logs for spam content to reduce database load.

    Args:
        content_instance: The content object (Thread or Comment, dict or model)
        moderation_result: Full result from AI moderation
        actions_taken: List of actions taken (e.g., ['flagged'], ['flagged', 'soft_deleted'])
        original_author: User who created the content
    """
    if original_author is None:
        original_author = _get_author_from_content(content_instance)

    content_id = str(content_instance.get("_id"))
    content_body = content_instance.get("body", "")

    enhanced_moderation_result = moderation_result.copy()
    enhanced_moderation_result.update(
        {
            "content_id": content_id,
            "metadata": {
                "_id": content_id,
                "title": content_instance.get("title", ""),
                "body": (
                    content_instance.get("body", "")[:200] + "..."
                    if len(content_instance.get("body", "")) > 200
                    else content_instance.get("body", "")
                ),
                "course_id": content_instance.get("course_id", ""),
                "created_at": str(content_instance.get("created_at", "")),
            },
        }
    )

    try:
        audit_log = ModerationAuditLog(
            timestamp=timezone.now(),
            body=content_body,  # Store full body content
            classifier_output=enhanced_moderation_result,
            reasoning=moderation_result.get("reasoning", "No reasoning provided"),
            classification=moderation_result.get("classification", "spam"),
            actions_taken=actions_taken,
            confidence_score=moderation_result.get("confidence_score"),
            original_author=original_author,
        )
        audit_log.save()
    except (ValueError, TypeError, AttributeError) as db_error:
        log.error(f"Failed to create database audit log: {db_error}")


class AIModerationService:
    """
    Service for AI-based content moderation.

    Waffle Flag "discussion.enable_ai_moderation" controls whether AI moderation is active.

    XPERT AI Moderation API is used to classify content as spam or not spam.
    """

    def __init__(self):  # type: ignore[no-untyped-def]
        """Initialize the AI moderation service."""
        self.api_url = getattr(settings, "AI_MODERATION_API_URL", None)
        self.client_id = getattr(settings, "AI_MODERATION_CLIENT_ID", None)
        self.system_message = getattr(settings, "AI_MODERATION_SYSTEM_MESSAGE", None)
        self.connection_timeout = getattr(
            settings, "AI_MODERATION_CONNECTION_TIMEOUT", 30
        )  # seconds
        self.read_timeout = getattr(
            settings, "AI_MODERATION_READ_TIMEOUT", 30
        )  # seconds
        self.ai_moderation_user_id = getattr(settings, "AI_MODERATION_USER_ID", None)

    def _make_api_request(self, content: str) -> Optional[Dict[str, Any]]:
        """
        Make API request to XPert Service.

        Args:
            content: The text content to moderate

        Returns:
            Dictionary with 'reasoning' and 'classification' keys, or None if failed
        """
        if not self.api_url:
            log.error("AI_MODERATION_API_URL setting is not configured")
            return None

        headers = {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json",
            "user-agent": "Mozilla/5.0 (compatible; edX-Forum-AI-Moderation/1.0)",
        }

        payload = {
            "messages": [{"role": "user", "content": content}],
            "client_id": self.client_id,
            "system_message": self.system_message,
        }

        try:
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=(self.connection_timeout, self.read_timeout),
            )
            response.raise_for_status()

            response_data = response.json()
            # Validate response data structure
            if not isinstance(response_data, list):
                log.error(
                    f"Expected list response from XPert API, got {type(response_data)}"
                )
                return None

            if len(response_data) == 0:
                log.error("Empty response list from XPert API")
                return None

            if not isinstance(response_data[0], dict):
                log.error(
                    f"Expected dict in response list, got {type(response_data[0])}"
                )
                return None

            assistant_content = response_data[0].get("content", "")
            # Parse the JSON content from the assistant response
            try:
                moderation_result = json.loads(assistant_content)
                # full API response for audit purposes
                moderation_result["full_api_response"] = response_data
                return moderation_result
            except json.JSONDecodeError as e:
                log.error(f"Failed to parse AI moderation response JSON: {e}")
                return None
        except (
            requests.RequestException,
            requests.Timeout,
            requests.ConnectionError,
        ) as e:
            log.error(f"AI moderation API request failed: {e}")
            return None

    def moderate_and_flag_content(
        self,
        content: str,
        content_instance: Any,
        course_id: Optional[str] = None,
        backend: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Moderate content and flag as spam and flag abuse if detected.

        Args:
            content: The text content to check
            content_instance: The content model instance (Thread or Comment)
            course_id: Optional course ID for waffle flag checking
            backend: Backend instance for database operations

        Returns:
            Dictionary with moderation results and actions taken
        """
        result = {
            "is_spam": False,
            "reasoning": "AI moderation disabled or unavailable",
            "classification": "not_spam",
            "actions_taken": ["no_action"],
            "flagged": False,
        }
        # Check if AI moderation is enabled
        # pylint: disable=import-outside-toplevel
        from forum.toggles import (
            is_ai_moderation_enabled,
            is_ai_auto_delete_spam_enabled,
        )

        course_key = CourseKey.from_string(course_id) if course_id else None
        if not is_ai_moderation_enabled(course_key):  # type: ignore[no-untyped-call]
            return result

        # Make API request
        moderation_result = self._make_api_request(content)

        if moderation_result is None:
            result["reasoning"] = "AI moderation API failed"
            log.warning("AI moderation API failed")
            return result

        classification = moderation_result.get("classification", "not_spam")
        reasoning = moderation_result.get("reasoning", "No reasoning provided")
        is_spam = classification in ["spam", "spam_or_scam"]

        result.update(
            {
                "is_spam": is_spam,
                "reasoning": reasoning,
                "classification": classification,
                "moderation_result": moderation_result,
            }
        )

        if is_spam:
            # Flag content as spam and abuse first
            try:
                content_instance["is_spam"] = True

                self._mark_as_spam_and_moderate(content_instance, backend)
                result["actions_taken"] = ["flagged"]
                result["flagged"] = True
            except (AttributeError, ValueError, TypeError) as e:
                log.error(f"Failed to flag content as spam: {e}")
                result["actions_taken"] = ["no_action"]

            # Only attempt deletion if flagging succeeded
            if is_ai_auto_delete_spam_enabled(course_key) and result["flagged"]:  # type: ignore[no-untyped-call]
                try:
                    self._delete_content(content_instance)
                    result["actions_taken"] = result["actions_taken"] + ["soft_deleted"]  # type: ignore[operator]
                except (ForumV2RequestError, ObjectDoesNotExist, ValidationError) as e:
                    log.error(f"Failed to delete content after flagging: {e}")
        else:
            result["actions_taken"] = ["no_action"]

        # Only create audit log for spam content (or API failures, handled above)
        if is_spam:
            create_moderation_audit_log(
                content_instance,
                moderation_result,
                result["actions_taken"],  # type: ignore[arg-type]
                _get_author_from_content(content_instance),
            )
        return result

    def _mark_as_spam_and_moderate(self, content_instance: Any, backend: Any) -> None:
        """Flag content as abuse using backend methods."""
        content_id = str(content_instance.get("_id"))
        content_type = str(content_instance.get("_type"))
        extra_data = {
            "entity_type": (
                "CommentThread" if content_type == "CommentThread" else "Comment"
            )
        }
        if not self.ai_moderation_user_id:
            raise ValueError("AI_MODERATION_USER_ID setting is not configured.")
        backend.flag_content_as_spam(content_type, content_id)
        backend.flag_as_abuse(str(self.ai_moderation_user_id), content_id, **extra_data)

    def _delete_content(self, content_instance: Any) -> None:
        """
        Soft delete content using API layer delete functions.

        Uses the API layer which handles all business logic including:
        - Content validation
        - Soft deletion
        - Stats updates
        - Subscription cleanup (for threads)
        - Anonymous content handling

        Args:
            content_instance: Dict containing content data including _id, _type, and course_id
        """
        # Import here to avoid circular dependency (api modules import from ai_moderation)
        # pylint: disable=import-outside-toplevel,cyclic-import
        from forum.api.comments import delete_comment
        from forum.api.threads import delete_thread

        content_id = str(content_instance.get("_id"))
        content_type = str(content_instance.get("_type"))
        course_id = content_instance.get("course_id")
        deleted_by = (
            str(self.ai_moderation_user_id) if self.ai_moderation_user_id else None
        )

        # Use API layer functions which handle all business logic
        # Exceptions propagate to caller for proper error handling
        if content_type == "CommentThread":
            delete_thread(content_id, course_id=course_id, deleted_by=deleted_by)
            log.info(f"AI Moderation Deleted CommentThread: {content_id}")
        elif content_type == "Comment":
            delete_comment(content_id, course_id=course_id, deleted_by=deleted_by)
            log.info(f"AI Moderation Deleted Comment: {content_id}")


# Global instance
ai_moderation_service = AIModerationService()  # type: ignore[no-untyped-call]


def moderate_and_flag_spam(
    content: str,
    content_instance: Any,
    course_id: Optional[str] = None,
    backend: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Moderate content and flag as spam if detected.

    Args:
        content: The text content to moderate
        content_instance: The content model instance
        course_id: Optional course ID for waffle flag checking
        backend: Backend instance for database operations

    Returns:
        Dictionary with moderation results and actions taken

    TODO:-
     - Add content check for images
    """
    return ai_moderation_service.moderate_and_flag_content(
        content, content_instance, course_id, backend
    )
