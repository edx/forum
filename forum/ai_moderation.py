"""
AI Moderation utilities for forum content.
"""

import json
import logging
from typing import Dict, Optional, Any

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from opaque_keys.edx.keys import CourseKey

from forum.backends.mysql.models import ModerationAuditLog

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

    DEFAULT_API_URL = "https://example.com"
    DEFAULT_CLIENT_ID = "example_client_id"
    DEFAULT_SYSTEM_MESSAGE = (
        "Filter posts from a discussion forum platform to identify and flag "
        "content that is likely to be spam or a scam.\n\n"
        "**Instructions**:\n"
        "- Carefully analyze each post's text for language, links, or patterns typical of spam or scams.\n"
        "- Use clear reasoning to identify suspicious indicators such as:\n"
        "  * Promotional language or unsolicited commercial content\n"
        '  * Misleading claims or "too good to be true" offers\n'
        "  * Excessive external links (especially non-educational domains)\n"
        "  * Requests for personal information (phone numbers, email, social media)\n"
        "  * Suspicious offers (money, investment, guaranteed results)\n"
        "  * Impersonation of authority figures (course staff, professors)\n"
        "  * Directing users to external communication platforms "
        "(WhatsApp, Telegram)\n"
        "  * Cryptocurrency, forex, or investment scheme language\n"
        '  * Urgent pressure tactics ("act now", "limited time")\n\n'
        "- After thoroughly explaining your reasoning and highlighting specific "
        'suspicious features, classify the post as either "spam_or_scam" or '
        '"not_spam".\n'
        "- **Do not make a classification before detailing your reasoning.** "
        "Always present your analysis of the post's content before your final "
        "determination.\n"
        "- If uncertainty exists, explain which factors made detection difficult "
        "before concluding.\n"
        "- Consider legitimate use cases: Course-related external links "
        "(.edu domains), genuine help requests, study group formation.\n\n"
        "**Output Format** (strict JSON):\n"
        "{\n"
        '  "reasoning": "[Detailed explanation of why this post may or may '
        "not be spam/scam, referencing specific features of the post. "
        'Minimum 2 sentences.]",\n'
        '  "classification": "[spam_or_scam | not_spam]"\n'
        "}\n\n"
        "**Examples**:\n\n"
        "Example 1 (Spam):\n"
        "Post: \"Hi everyone! I'm Professor Johnson. Contact me on WhatsApp "
        '+1-555-0123 for guaranteed A+ grades. Limited slots!"\n'
        "Output:\n"
        "{\n"
        '  "reasoning": "This post exhibits multiple red flags: (1) '
        "Impersonation of a professor with no verification, (2) request to "
        "contact via WhatsApp with phone number, (3) unrealistic promise of "
        "'guaranteed A+ grades', (4) urgency tactic 'limited slots'. These are "
        'classic patterns of academic scams targeting students.",\n'
        '  "classification": "spam_or_scam"\n'
        "}\n\n"
        "Example 2 (Not Spam):\n"
        'Post: "Can someone explain the difference between merge sort and quick '
        "sort? I'm struggling with the time complexity analysis.\"\n"
        "Output:\n"
        "{\n"
        '  "reasoning": "This is a legitimate academic question about sorting '
        "algorithms. The post contains no suspicious links, no requests for "
        "external contact, no promotional language, and is directly related to "
        'course content. The tone is appropriate for a learner seeking help.",\n'
        '  "classification": "not_spam"\n'
        "}"
    )

    def __init__(self):  # type: ignore[no-untyped-def]
        """Initialize the AI moderation service."""
        self.api_url = getattr(settings, "AI_MODERATION_API_URL", self.DEFAULT_API_URL)
        self.client_id = getattr(
            settings, "AI_MODERATION_CLIENT_ID", self.DEFAULT_CLIENT_ID
        )
        self.system_message = getattr(
            settings, "AI_MODERATION_SYSTEM_MESSAGE", self.DEFAULT_SYSTEM_MESSAGE
        )
        self.timeout = getattr(settings, "AI_MODERATION_TIMEOUT", 30)  # seconds

    def _make_api_request(self, content: str) -> Optional[Dict[str, Any]]:
        """
        Make API request to AI moderation service.

        Args:
            content: The text content to moderate

        Returns:
            Dictionary with 'reasoning' and 'classification' keys, or None if failed
        """
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
                self.api_url, headers=headers, json=payload, timeout=self.timeout
            )
            response.raise_for_status()

            response_data = response.json()

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
            try:
                content_instance["is_spam"] = True

                self._mark_as_spam_and_flag_abuse(content_instance, backend)

                result["actions_taken"] = ["flagged"]
                result["flagged"] = True
            except (AttributeError, ValueError, TypeError) as e:
                log.error(f"Failed to flag content as spam: {e}")
                result["actions_taken"] = ["no_action"]
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

    def _mark_as_spam_and_flag_abuse(self, content_instance: Any, backend: Any) -> None:
        """Flag content as abuse using backend methods."""
        content_id = str(content_instance.get("_id"))
        content_type = str(content_instance.get("_type"))
        extra_data = {
            "entity_type": (
                "CommentThread" if content_type == "CommentThread" else "Comment"
            )
        }
        reason = "AI Moderation detected spam or scam content."
        try:
            system_user, _ = User.objects.get_or_create(
                username="discussion_admin",
                defaults={
                    "email": "discussion_admin@example.com",
                    "is_active": False,  # System user, not a real user
                },
            )
            backend.flag_content_as_spam(content_type, content_id, reason)
            backend.flag_as_abuse(str(system_user.id), content_id, **extra_data)  # type: ignore[attr-defined]
        except (AttributeError, ValueError, TypeError, ImportError) as e:
            log.error(f"Failed to flag content via backend: {e}")


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
