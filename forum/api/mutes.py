"""
Native Python APIs for discussion moderation (mute/unmute).
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from django.http import HttpRequest
from forum.backend import get_backend
from forum.utils import ForumV2RequestError

log = logging.getLogger(__name__)


def mute_user(
    muted_user_id: str,
    muter_id: str,
    course_id: str,
    scope: str = "personal",
    reason: str = "",
    requester_is_privileged: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Mute a user in discussions.

    Args:
        muted_user_id: ID of user to mute
        muter_id: ID of user performing the mute
        course_id: Course identifier
        scope: Mute scope ('personal' or 'course')
        reason: Optional reason for mute
        requester_is_privileged: Whether requester has course-level privileges

    Returns:
        Dictionary containing mute record data
    """
    try:
        backend = get_backend(course_id)()
        return backend.mute_user(
            muted_user_id=muted_user_id,
            muter_id=muter_id,
            course_id=course_id,
            scope=scope,
            reason=reason,
            requester_is_privileged=requester_is_privileged,
            **kwargs,
        )
    except ValueError as e:
        raise ForumV2RequestError(str(e)) from e
    except Exception as e:
        raise ForumV2RequestError(f"Failed to mute user: {str(e)}") from e


def unmute_user(
    muted_user_id: str,
    unmuted_by_id: str,
    course_id: str,
    scope: str = "personal",
    muter_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Unmute a user in discussions.

    Args:
        muted_user_id: ID of user to unmute
        unmuted_by_id: ID of user performing the unmute
        course_id: Course identifier
        scope: Mute scope ('personal' or 'course')
        muter_id: Optional filter by who performed the original mute

    Returns:
        Dictionary containing unmute operation result
    """
    try:
        backend = get_backend(course_id)()
        return backend.unmute_user(
            muted_user_id=muted_user_id,
            unmuted_by_id=unmuted_by_id,
            course_id=course_id,
            scope=scope,
            muter_id=muter_id,
            **kwargs,
        )
    except ValueError as e:
        raise ForumV2RequestError(str(e)) from e
    except Exception as e:
        raise ForumV2RequestError(f"Failed to unmute user: {str(e)}") from e


def get_user_mute_status(
    user_id: str, course_id: str, viewer_id: str, **kwargs: Any
) -> Dict[str, Any]:
    """
    Get mute status for a user in a course.

    Args:
        user_id: ID of user to check
        course_id: Course identifier
        viewer_id: ID of user requesting the status

    Returns:
        Dictionary containing mute status information
    """
    try:
        backend = get_backend(course_id)()
        return backend.get_user_mute_status(
            muted_user_id=user_id,
            course_id=course_id,
            requesting_user_id=viewer_id,
            **kwargs,
        )
    except ValueError as e:
        raise ForumV2RequestError(str(e)) from e
    except Exception as e:
        raise ForumV2RequestError(f"Failed to get mute status: {str(e)}") from e


def get_muted_users(
    muter_id: str, course_id: str, scope: str = "all", **kwargs: Any
) -> list[dict[str, Any]]:
    """
    Get list of users muted by a specific user.

    Args:
        muter_id: ID of the user who muted others
        course_id: Course identifier
        scope: Scope filter ('personal', 'course', or 'all')

    Returns:
        List of muted user records
    """
    try:
        backend = get_backend(course_id)()
        return backend.get_muted_users(
            moderator_id=muter_id, course_id=course_id, scope=scope, **kwargs
        )
    except ValueError as e:
        raise ForumV2RequestError(str(e)) from e
    except Exception as e:
        raise ForumV2RequestError(f"Failed to get muted users: {str(e)}") from e


def _flag_content(
    backend: Any,
    user_id: str,
    entity_id: str,
    entity_type: str,
) -> Dict[str, Any]:
    """
    Helper to flag a single piece of content and return standardized result.

    Args:
        backend: Forum backend instance
        user_id: User performing the flag
        entity_id: ID of content to flag
        entity_type: Type of entity ('CommentThread' or 'Comment')

    Returns:
        Dictionary with flag operation result
    """
    content_type = "thread" if entity_type == "CommentThread" else "comment"

    try:
        backend.flag_as_abuse(
            user_id=user_id, entity_id=entity_id, entity_type=entity_type
        )
        log.info(
            "%s %s flagged as abusive by user %s",
            content_type.capitalize(),
            entity_id,
            user_id,
        )
        return {"content_type": content_type, "content_id": entity_id, "flagged": True}
    except Exception as e:  # pylint: disable=broad-except
        log.warning("Failed to flag %s %s: %s", content_type, entity_id, str(e))
        return {
            "content_type": content_type,
            "content_id": entity_id,
            "flagged": False,
            "error": str(e),
        }


def mute_and_report_user(
    muted_user_id: str,
    muter_id: str,
    course_id: str,
    scope: str = "personal",
    reason: str = "",
    thread_id: str = "",
    comment_id: str = "",
    request: Optional[HttpRequest] = None,
    requester_is_privileged: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Mute a user and flag their content as abusive in discussions.

    Args:
        muted_user_id: ID of user to mute
        muter_id: ID of user performing the mute
        course_id: Course identifier
        scope: Mute scope ('personal' or 'course')
        reason: Reason for muting and reporting
        thread_id: Optional content ID to flag (tries as thread, then comment)
        comment_id: Optional comment ID to flag as abusive
        request: Django request object for content flagging
        requester_is_privileged: Whether requester has course-level privileges
        **kwargs: Additional parameters to pass to backend.mute_user

    Returns:
        Dictionary containing mute and report operation result
    """
    try:
        backend = get_backend(course_id)()

        # Mute the user
        mute_result = backend.mute_user(
            muted_user_id=muted_user_id,
            muter_id=muter_id,
            course_id=course_id,
            scope=scope,
            reason=reason,
            requester_is_privileged=requester_is_privileged,
            **kwargs,
        )

        # Handle content flagging
        flagged_items = []
        if (thread_id or comment_id) and request:
            user_id = str(getattr(request.user, "id", ""))

            # Flag thread_id (may be thread or comment)
            if thread_id:
                result = _flag_content(backend, user_id, thread_id, "CommentThread")
                if not result["flagged"]:
                    # Retry as comment
                    result = _flag_content(backend, user_id, thread_id, "Comment")
                flagged_items.append(result)

            # Flag comment_id separately
            if comment_id:
                flagged_items.append(
                    _flag_content(backend, user_id, comment_id, "Comment")
                )

        # Build report result
        if flagged_items:
            all_flagged = all(item["flagged"] for item in flagged_items)
            report_result = {
                "status": "success" if all_flagged else "partial",
                "flagged_items": flagged_items,
            }
        else:
            # No content to flag
            report_result = {
                "status": "success",
                "report_id": f"report_{muted_user_id}_{muter_id}_{course_id}",
                "reported_user_id": muted_user_id,
                "reported_by_id": muter_id,
                "course_id": course_id,
                "reason": reason,
                "created": datetime.utcnow().isoformat(),
                "message": "User reported (no specific content flagged)",
            }

        return {
            "status": "success",
            "message": (
                "User muted and content flagged"
                if flagged_items
                else "User muted and reported"
            ),
            "mute_record": mute_result,
            "report_record": report_result,
        }
    except ValueError as e:
        raise ForumV2RequestError(str(e)) from e
    except Exception as e:  # pylint: disable=broad-except
        raise ForumV2RequestError(f"Failed to mute and report user: {str(e)}") from e


def get_all_muted_users_for_course(
    course_id: str,
    requester_id: Optional[str] = None,
    scope: str = "all",
    requester_is_privileged: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Get all muted users in a course with role-based access control.

    Args:
        course_id: Course identifier
        requester_id: ID of the user requesting the list
        scope: Scope filter ('personal', 'course', or 'all')
        requester_is_privileged: Whether the requester has course-level privileges

    Returns:
        Dictionary containing list of muted users based on requester role and scope

    Authorization:
        - Learners: Can only see their own personal mutes
        - Staff: Can see course-wide mutes and all personal mutes
    """
    try:
        backend = get_backend(course_id)()
        return backend.get_all_muted_users_for_course(
            course_id=course_id,
            requester_id=requester_id,
            scope=scope,
            requester_is_privileged=requester_is_privileged,
            **kwargs,
        )
    except ValueError as e:
        raise ForumV2RequestError(str(e)) from e
    except Exception as e:  # pylint: disable=broad-except
        raise ForumV2RequestError(f"Failed to get course muted users: {str(e)}") from e
