"""
API functions for managing discussion bans.
"""

# mypy: ignore-errors

import logging
from typing import Any, Dict, List, Optional

from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from opaque_keys.edx.keys import CourseKey

from forum.backends.mysql.models import (
    DiscussionBan,
    DiscussionBanException,
    ModerationAuditLog,
)

User = get_user_model()
log = logging.getLogger(__name__)


def ban_user(
    user,
    banned_by,
    course_id: Optional[str] = None,
    org_key: Optional[str] = None,
    scope: str = "course",
    reason: str = "",
) -> Dict[str, Any]:
    """
    Ban a user from discussions.

    Args:
        user: User object to ban
        banned_by: User object performing the ban
        course_id: Course ID for course-level bans
        org_key: Organization key for org-level bans
        scope: 'course' or 'organization'
        reason: Reason for the ban

    Returns:
        dict: Ban record data including id, user info, scope, and timestamps

    Raises:
        ValueError: If invalid parameters provided
    """
    if scope not in ["course", "organization"]:
        raise ValueError(f"Invalid scope: {scope}. Must be 'course' or 'organization'")

    if scope == "course" and not course_id:
        raise ValueError("course_id is required for course-level bans")

    if scope == "organization" and not (org_key or course_id):
        raise ValueError("org_key or course_id is required for organization-level bans")

    # Use provided User objects
    banned_user = user
    moderator = banned_by

    with transaction.atomic():
        # Determine lookup kwargs based on scope
        course_key = None  # Initialize for audit log
        if scope == "organization":
            # Extract org_key from course_id if not provided
            if not org_key and course_id:
                if isinstance(course_id, str):
                    course_key = CourseKey.from_string(course_id)
                else:
                    course_key = course_id
                org_key = str(course_key.org) if hasattr(course_key, "org") else None

            if not org_key:
                raise ValueError(
                    "org_key could not be determined for organization-level ban"
                )

            lookup_kwargs = {
                "user": banned_user,
                "org_key": org_key,
                "scope": "organization",
            }
            ban_kwargs = {
                **lookup_kwargs,
            }
        else:
            # Normalize course_id
            if isinstance(course_id, str):
                course_key = CourseKey.from_string(course_id)
            else:
                course_key = course_id
            # Extract org from course_id for denormalization
            course_org = str(course_key.org) if hasattr(course_key, "org") else org_key
            lookup_kwargs = {
                "user": banned_user,
                "course_id": course_key,
                "scope": "course",
            }
            ban_kwargs = {
                **lookup_kwargs,
                "org_key": course_org,  # Denormalized field for easier querying
            }

        # Create or update ban
        ban, created = DiscussionBan.objects.get_or_create(
            **lookup_kwargs,
            defaults={
                **ban_kwargs,
                "banned_by": moderator,
                "reason": reason or "No reason provided",
                "is_active": True,
                "banned_at": timezone.now(),
            },
        )

        reactivated = False
        if not created and not ban.is_active:
            # Reactivate previously deactivated ban
            ban.is_active = True
            ban.banned_by = moderator
            ban.reason = reason or ban.reason
            ban.banned_at = timezone.now()
            ban.unbanned_at = None
            ban.unbanned_by = None
            ban.save()
            reactivated = True

        # Create audit log
        ModerationAuditLog.objects.create(
            action_type=ModerationAuditLog.ACTION_BAN,
            source=ModerationAuditLog.SOURCE_HUMAN,
            target_user=banned_user,
            moderator=moderator,
            course_id=str(course_key) if course_key else None,
            scope=scope,
            reason=reason,
            metadata={
                "ban_id": ban.id,
                "created": created,
            },
            # AI moderation fields (required by schema, not applicable for ban actions)
            body="",
            original_author=banned_user,
            classification="",
            classifier_output={},
            actions_taken=[],
            confidence_score=None,
            reasoning="",
            moderator_override=False,
        )

        log.info(
            "User banned: user_id=%s, scope=%s, course_id=%s, org_key=%s, banned_by=%s",
            banned_user.id,
            scope,
            course_id,
            org_key,
            moderator.id,
        )

    result = _serialize_ban(ban)
    if reactivated:
        result["reactivated"] = True
    return result


def unban_user(
    ban_id: int = None,
    user=None,
    unbanned_by=None,
    course_id: Optional[str] = None,
    scope: str = None,
    reason: str = "",
) -> Dict[str, Any]:
    """
    Unban a user from discussions.

    For course-level bans: Deactivates the ban completely.
    For org-level bans with course_id: Creates an exception for that course.
    For org-level bans without course_id: Deactivates the entire org ban.

    Args:
        ban_id: ID of the ban to unban (optional if user provided)
        user: User object to unban (optional if ban_id provided)
        unbanned_by: User object performing the unban
        course_id: Optional course ID for org-level ban exceptions
        scope: Ban scope (course/organization) - used to find ban when user provided
        reason: Reason for unbanning

    Returns:
        dict: Response with status, message, and ban/exception data

    Raises:
        DiscussionBan.DoesNotExist: If ban not found
        ValueError: If neither ban_id nor user provided
    """
    # Find the ban either by ID or by user
    if ban_id:
        try:
            ban = DiscussionBan.objects.get(id=ban_id, is_active=True)
        except DiscussionBan.DoesNotExist as exc:
            raise ValueError(f"Active ban with id {ban_id} not found") from exc
    elif user:
        # Find active ban for this user based on scope
        query = {"user": user, "is_active": True}
        if scope:
            query["scope"] = scope
        # For course-level bans, include course_id
        # For org-level bans, course_id is NULL in DB
        if scope == "course" and course_id:
            course_key = (
                CourseKey.from_string(course_id)
                if isinstance(course_id, str)
                else course_id
            )
            query["course_id"] = course_key
        try:
            ban = DiscussionBan.objects.get(**query)
        except DiscussionBan.DoesNotExist as exc:
            raise ValueError(
                f"No active ban found for user {user.username} with scope {scope}"
            ) from exc
    else:
        raise ValueError("Either ban_id or user must be provided")

    moderator = unbanned_by
    exception_created = False
    exception_data = None

    with transaction.atomic():
        # For org-level bans with course_id: create exception instead of full unban
        if ban.scope == "organization" and course_id:
            course_key = (
                CourseKey.from_string(course_id)
                if isinstance(course_id, str)
                else course_id
            )

            # Create exception for this specific course
            exception, created = DiscussionBanException.objects.get_or_create(
                ban=ban,
                course_id=course_key,
                defaults={
                    "unbanned_by": moderator,
                    "reason": reason or "Course-level exception to organization ban",
                },
            )

            exception_created = True
            exception_data = {
                "id": exception.id,
                "ban_id": ban.id,
                "course_id": str(course_id),
                "unbanned_by": moderator.username,
                "reason": exception.reason,
                "created_at": (
                    exception.created.isoformat()
                    if hasattr(exception, "created")
                    else None
                ),
            }

            message = (
                f"User {ban.user.username} unbanned from {course_id} "
                f"(org-level ban still active for other courses)"
            )

            # Audit log for exception
            ModerationAuditLog.objects.create(
                action_type=ModerationAuditLog.ACTION_BAN_EXCEPTION,
                source=ModerationAuditLog.SOURCE_HUMAN,
                target_user=ban.user,
                moderator=moderator,
                course_id=str(course_key),
                scope="organization",
                reason=f"Exception to org ban: {reason}",
                metadata={
                    "ban_id": ban.id,
                    "exception_id": exception.id,
                    "exception_created": created,
                    "org_key": ban.org_key,
                },
                # AI moderation fields (required by schema, not applicable for ban actions)
                body="",
                original_author=ban.user,
                classification="",
                classifier_output={},
                actions_taken=[],
                confidence_score=None,
                reasoning="",
                moderator_override=False,
            )
        else:
            # Full unban (course-level or complete org-level unban)
            ban.is_active = False
            ban.unbanned_at = timezone.now()
            ban.unbanned_by = moderator
            ban.save()

            message = f"User {ban.user.username} unbanned successfully"

            # Audit log
            ModerationAuditLog.objects.create(
                action_type=ModerationAuditLog.ACTION_UNBAN,
                source=ModerationAuditLog.SOURCE_HUMAN,
                target_user=ban.user,
                moderator=moderator,
                course_id=str(ban.course_id) if ban.course_id else None,
                scope=ban.scope,
                reason=f"Unban: {reason}",
                metadata={
                    "ban_id": ban.id,
                },
                # AI moderation fields (required by schema, not applicable for ban actions)
                body="",
                original_author=ban.user,
                classification="",
                classifier_output={},
                actions_taken=[],
                confidence_score=None,
                reasoning="",
                moderator_override=False,
            )

        log.info(
            "User unbanned: ban_id=%s, user_id=%s, exception_created=%s, unbanned_by=%s",
            ban_id,
            ban.user.id,
            exception_created,
            moderator.id,
        )

    return {
        "status": "success",
        "message": message,
        "exception_created": exception_created,
        "ban": _serialize_ban(ban),
        "exception": exception_data,
    }


def get_banned_users(
    course_id: Optional[str] = None,
    org_key: Optional[str] = None,
    include_inactive: bool = False,
    scope: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Get list of banned users.

    Args:
        course_id: Filter by course ID (includes org-level bans for that course's org)
        org_key: Filter by organization key
        include_inactive: Include inactive (unbanned) users
        scope: Filter by scope ('course' or 'organization')

    Returns:
        list: List of ban records
    """
    queryset = DiscussionBan.objects.select_related("user", "banned_by", "unbanned_by")

    if not include_inactive:
        queryset = queryset.filter(is_active=True)

    if scope:
        queryset = queryset.filter(scope=scope)

    if course_id:
        course_key = (
            CourseKey.from_string(course_id)
            if isinstance(course_id, str)
            else course_id
        )
        # Include both course-level bans and org-level bans for this course's org unless scope is specified
        if not scope:
            org = str(course_key.org) if hasattr(course_key, "org") else None
            if org:
                queryset = queryset.filter(
                    models.Q(course_id=course_key)
                    | models.Q(org_key=org, scope="organization")
                )
            else:
                # Fallback to just course-level bans if can't extract org
                queryset = queryset.filter(course_id=course_key)
        else:
            # If scope is specified, just filter by course_id for course scope
            if scope == "course":
                queryset = queryset.filter(course_id=course_key)
            # For org scope, we already filtered by scope above
    elif org_key:
        queryset = queryset.filter(org_key=org_key)

    queryset = queryset.order_by("-banned_at")

    return [_serialize_ban(ban) for ban in queryset]


def get_ban(
    ban_id: int = None, user=None, course_id: Optional[str] = None, scope: str = None
) -> Optional[Dict[str, Any]]:
    """
    Get a specific ban by ID or by user/course/scope.

    Args:
        ban_id: ID of the ban (optional if user provided)
        user: User object (optional if ban_id provided)
        course_id: CourseKey or string (required with user)
        scope: 'course' or 'organization' (optional with user)

    Returns:
        dict: Ban record data, or None if not found

    Raises:
        ValueError: If neither ban_id nor user provided
    """
    try:
        if ban_id:
            ban = DiscussionBan.objects.select_related(
                "user", "banned_by", "unbanned_by"
            ).get(id=ban_id)
        elif user:
            query = {"user": user, "is_active": True}
            if scope:
                query["scope"] = scope
            if course_id:
                course_key = (
                    CourseKey.from_string(course_id)
                    if isinstance(course_id, str)
                    else course_id
                )
                query["course_id"] = course_key
            ban = DiscussionBan.objects.select_related(
                "user", "banned_by", "unbanned_by"
            ).get(**query)
        else:
            raise ValueError("Either ban_id or user must be provided")
        return _serialize_ban(ban)
    except DiscussionBan.DoesNotExist:
        return None


def _serialize_ban(ban: DiscussionBan) -> Dict[str, Any]:
    """
    Serialize a ban object to dictionary.

    Args:
        ban: DiscussionBan instance

    Returns:
        dict: Serialized ban data
    """
    return {
        "id": ban.id,
        "user": {
            "id": ban.user.id,
            "username": ban.user.username,
            "email": ban.user.email,
        },
        "course_id": str(ban.course_id) if ban.course_id else None,
        "org_key": ban.org_key,
        "scope": ban.scope,
        "reason": ban.reason,
        "is_active": ban.is_active,
        "banned_at": ban.banned_at.isoformat() if ban.banned_at else None,
        "banned_by": (
            {
                "id": ban.banned_by.id,
                "username": ban.banned_by.username,
            }
            if ban.banned_by
            else None
        ),
        "unbanned_at": ban.unbanned_at.isoformat() if ban.unbanned_at else None,
        "unbanned_by": (
            {
                "id": ban.unbanned_by.id,
                "username": ban.unbanned_by.username,
            }
            if ban.unbanned_by
            else None
        ),
    }


def is_user_banned(user, course_id, check_org=True):
    """
    Check if user is banned from discussions.

    Args:
        user: User object or user ID
        course_id: CourseKey or string
        check_org: If True, also check organization-level bans

    Returns:
        bool: True if user has active ban
    """
    return DiscussionBan.is_user_banned(user, course_id, check_org)


def get_user_ban_scope(user, course_id):
    """
    Get the scope of a user's active ban ('course' or 'organization').

    Args:
        user: User object or user ID
        course_id: CourseKey or string

    Returns:
        str or None: 'course', 'organization', or None if not banned
    """
    # Normalize course_id
    if isinstance(course_id, str):
        course_id = CourseKey.from_string(course_id)

    # Check organization-level ban first
    try:
        # pylint: disable=import-outside-toplevel
        from openedx.core.djangoapps.content.course_overviews.models import (
            CourseOverview,
        )

        course = CourseOverview.objects.get(id=course_id)
        org_name = course.org
    except (ImportError, Exception):  # pylint: disable=broad-exception-caught
        org_name = course_id.org

    # Check org-level ban
    org_ban = DiscussionBan.objects.filter(
        user=user,
        org_key=org_name,
        scope=DiscussionBan.SCOPE_ORGANIZATION,
        is_active=True,
    ).first()

    if org_ban:
        # Check if there's an exception for this course
        if DiscussionBanException.objects.filter(
            ban=org_ban, course_id=course_id
        ).exists():
            # Exception exists - check for course-level ban
            if DiscussionBan.objects.filter(
                user=user,
                course_id=course_id,
                scope=DiscussionBan.SCOPE_COURSE,
                is_active=True,
            ).exists():
                return "course"
            return None
        return "organization"

    # Check course-level ban
    if DiscussionBan.objects.filter(
        user=user,
        course_id=course_id,
        scope=DiscussionBan.SCOPE_COURSE,
        is_active=True,
    ).exists():
        return "course"

    return None


def get_banned_usernames(course_id=None, org_key=None):
    """
    Get set of banned usernames for filtering.

    Args:
        course_id: CourseKey or string (optional)
        org_key: Organization key string (optional)

    Returns:
        set: Set of banned usernames
    """
    queryset = DiscussionBan.objects.filter(is_active=True)

    if course_id:
        if isinstance(course_id, str):
            course_id = CourseKey.from_string(course_id)

        # Get org from course
        organization = course_id.org if hasattr(course_id, "org") else org_key

        # Include both course-level and org-level bans
        queryset = queryset.filter(
            Q(course_id=course_id) | Q(org_key=organization, scope="organization")
        )
    elif org_key:
        queryset = queryset.filter(org_key=org_key)

    return set(queryset.values_list("user__username", flat=True))


def create_audit_log(
    action_type,
    target_user,
    moderator,
    course_id=None,
    scope=None,
    reason="",
    metadata=None,
):
    """
    Create a moderation audit log entry.

    Args:
        action_type: Action type constant from ModerationAuditLog
        target_user: User being moderated
        moderator: User performing moderation
        course_id: Course ID string (optional)
        scope: Scope of action ('course' or 'organization')
        reason: Reason for action
        metadata: Additional metadata dict

    Returns:
        ModerationAuditLog: Created audit log instance
    """
    return ModerationAuditLog.objects.create(
        action_type=action_type,
        source=ModerationAuditLog.SOURCE_HUMAN,
        target_user=target_user,
        moderator=moderator,
        course_id=course_id,
        scope=scope,
        reason=reason,
        metadata=metadata or {},
        # AI moderation fields (required by schema, not applicable for ban actions)
        body="",
        original_author=target_user,
        classification="",
        classifier_output={},
        actions_taken=[],
        confidence_score=None,
        reasoning="",
        moderator_override=False,
    )
