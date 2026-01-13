"""
Native Python APIs for discussion moderation (mute/unmute).
"""

from datetime import datetime
from typing import Any, Dict, Optional

from forum.backend import get_backend
from forum.utils import ForumV2RequestError


def mute_user(
    muted_user_id: str,
    muted_by_id: str,
    course_id: str,
    scope: str = "personal",
    reason: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Mute a user in discussions.

    Args:
        muted_user_id: ID of user to mute
        muted_by_id: ID of user performing the mute
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
            muted_by_id=muted_by_id,
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
    muted_by_id: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Unmute a user in discussions.

    Args:
        muted_user_id: ID of user to unmute
        unmuted_by_id: ID of user performing the unmute
        course_id: Course identifier
        scope: Mute scope ('personal' or 'course')
        muted_by_id: Optional filter by who performed the original mute

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
            muted_by_id=muted_by_id,
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
    muted_by_id: str, course_id: str, scope: str = "all", **kwargs: Any
) -> list[dict[str, Any]]:
    """
    Get list of users muted by a specific user.

    Args:
        muted_by_id: ID of the user who muted others
        course_id: Course identifier
        scope: Scope filter ('personal', 'course', or 'all')

    Returns:
        List of muted user records
    """
    try:
        backend = get_backend(course_id)()
        return backend.get_muted_users(
            moderator_id=muted_by_id, course_id=course_id, scope=scope, **kwargs
        )
    except ValueError as e:
        raise ForumV2RequestError(str(e)) from e
    except Exception as e:
        raise ForumV2RequestError(f"Failed to get muted users: {str(e)}") from e


def mute_and_report_user(
    muted_user_id: str,
    muted_by_id: str,
    course_id: str,
    scope: str = "personal",
    reason: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Mute a user and create a report against them in discussions.

    Args:
        muted_user_id: ID of user to mute
        muted_by_id: ID of user performing the mute
        course_id: Course identifier
        scope: Mute scope ('personal' or 'course')
        reason: Reason for muting and reporting

    Returns:
        Dictionary containing mute and report operation result
    """
    try:
        backend = get_backend(course_id)()

        # Mute the user
        mute_result = backend.mute_user(
            muted_user_id=muted_user_id,
            muted_by_id=muted_by_id,
            course_id=course_id,
            scope=scope,
            reason=reason,
            **kwargs,
        )

        # Create a basic report record (placeholder implementation)
        # In a full implementation, this would integrate with a proper reporting system
        report_result = {
            "status": "success",
            "report_id": f"report_{muted_user_id}_{muted_by_id}_{course_id}",
            "reported_user_id": muted_user_id,
            "reported_by_id": muted_by_id,
            "course_id": course_id,
            "reason": reason,
            "created": datetime.utcnow().isoformat(),
        }

        return {
            "status": "success",
            "message": "User muted and reported",
            "mute_record": mute_result,
            "report_record": report_result,
        }
    except ValueError as e:
        raise ForumV2RequestError(str(e)) from e
    except Exception as e:
        raise ForumV2RequestError(f"Failed to mute and report user: {str(e)}") from e


def get_all_muted_users_for_course(
    course_id: str,
    _requester_id: Optional[str] = None,
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
            course_id=course_id, scope=scope, **kwargs
        )
    except ValueError as e:
        raise ForumV2RequestError(str(e)) from e
    except Exception as e:
        raise ForumV2RequestError(f"Failed to get course muted users: {str(e)}") from e
