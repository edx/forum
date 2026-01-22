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


# pylint: disable=too-many-statements
def mute_and_report_user(
    muted_user_id: str,
    muter_id: str,
    course_id: str,
    scope: str = "personal",
    reason: str = "",
    thread_id: str = "",
    comment_id: str = "",
    request: Optional[HttpRequest] = None,
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
        thread_id: Optional thread ID to flag as abusive
        comment_id: Optional comment ID to flag as abusive
        request: Django request object for content flagging
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
            **kwargs,
        )

        # Handle content flagging if thread_id or comment_id is provided
        report_result: Dict[str, Any] = {}
        if (thread_id or comment_id) and request:  # pylint: disable=broad-except
            try:
                backend = get_backend(course_id)()

                # Flag the content as abusive using forum's backend
                content_type: Optional[str] = None
                content_id: Optional[str] = None

                if thread_id:
                    try:
                        # Try as thread first
                        backend.flag_as_abuse(
                            user_id=str(getattr(request.user, "id", "")),
                            entity_id=thread_id,
                            entity_type="CommentThread",
                        )
                        content_type = "thread"
                        content_id = thread_id
                        report_result = {
                            "status": "success",
                            "content_type": content_type,
                            "content_id": content_id,
                            "flagged": True,
                            "message": "Thread flagged as abusive",
                        }
                    except Exception:  # pylint: disable=broad-except
                        try:
                            # If thread fails, try as comment
                            backend.flag_as_abuse(
                                user_id=str(getattr(request.user, "id", "")),
                                entity_id=thread_id,
                                entity_type="Comment",
                            )
                            content_type = "comment"
                            content_id = thread_id
                            report_result = {
                                "status": "success",
                                "content_type": content_type,
                                "content_id": content_id,
                                "flagged": True,
                                "message": "Comment flagged as abusive",
                            }
                        except Exception as e:  # pylint: disable=broad-except
                            report_result = {
                                "status": "partial",
                                "content_type": "unknown",
                                "content_id": thread_id,
                                "error": str(e),
                                "flagged": False,
                                "message": "Mute successful, but content flagging failed",
                            }

                elif comment_id:
                    try:
                        backend.flag_as_abuse(
                            user_id=str(getattr(request.user, "id", "")),
                            entity_id=comment_id,
                            entity_type="Comment",
                        )
                        report_result = {
                            "status": "success",
                            "content_type": "comment",
                            "content_id": comment_id,
                            "flagged": True,
                            "message": "Comment flagged as abusive",
                        }
                    except Exception as e:  # pylint: disable=broad-except
                        report_result = {
                            "status": "partial",
                            "content_type": "comment",
                            "content_id": comment_id,
                            "error": str(e),
                            "flagged": False,
                            "message": "Mute successful, but content flagging failed",
                        }

            except Exception as e:  # pylint: disable=broad-except
                log.exception("Report system failed after mute")
                report_result = {
                    "status": "error",
                    "error": str(e),
                    "message": "Mute successful, but report system unavailable",
                }
        else:
            # Basic report record when no content ID is provided
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
                if report_result.get("flagged")
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
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Get all muted users in a course (requires appropriate permissions).

    Args:
        course_id: Course identifier
        requester_id: ID of the user requesting the list (optional)
        scope: Scope filter ('personal', 'course', or 'all')

    Returns:
        Dictionary containing list of all muted users in the course
    """
    try:
        backend = get_backend(course_id)()
        return backend.get_all_muted_users_for_course(
            course_id=course_id, requester_id=requester_id, scope=scope, **kwargs
        )
    except ValueError as e:
        raise ForumV2RequestError(str(e)) from e
    except Exception as e:  # pylint: disable=broad-except
        raise ForumV2RequestError(f"Failed to get course muted users: {str(e)}") from e
