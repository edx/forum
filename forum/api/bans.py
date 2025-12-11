"""
API functions for managing discussion bans.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.utils import timezone
from opaque_keys.edx.keys import CourseKey

from forum.backends.mysql.models import (
    DiscussionBan,
    DiscussionBanException,
    DiscussionModerationLog,
)

User = get_user_model()
log = logging.getLogger(__name__)


def ban_user(
    user_id: str,
    banned_by_id: str,
    course_id: Optional[str] = None,
    org_key: Optional[str] = None,
    scope: str = 'course',
    reason: str = '',
) -> Dict[str, Any]:
    """
    Ban a user from discussions.
    
    Args:
        user_id: ID of user to ban
        banned_by_id: ID of user performing the ban
        course_id: Course ID for course-level bans
        org_key: Organization key for org-level bans
        scope: 'course' or 'organization'
        reason: Reason for the ban
        
    Returns:
        dict: Ban record data including id, user info, scope, and timestamps
        
    Raises:
        ValueError: If invalid parameters provided
        User.DoesNotExist: If user or banned_by user not found
    """
    if scope not in ['course', 'organization']:
        raise ValueError(f"Invalid scope: {scope}. Must be 'course' or 'organization'")
    
    if scope == 'course' and not course_id:
        raise ValueError("course_id is required for course-level bans")
    
    if scope == 'organization' and not org_key:
        raise ValueError("org_key is required for organization-level bans")
    
    # Get user objects
    banned_user = User.objects.get(id=user_id)
    moderator = User.objects.get(id=banned_by_id)
    
    with transaction.atomic():
        # Determine lookup kwargs based on scope
        if scope == 'organization':
            lookup_kwargs = {
                'user': banned_user,
                'org_key': org_key,
                'scope': 'organization',
            }
            ban_kwargs = {
                **lookup_kwargs,
            }
        else:
            course_key = CourseKey.from_string(course_id)
            # Extract org from course_id for denormalization
            course_org = str(course_key.org) if hasattr(course_key, 'org') else org_key
            lookup_kwargs = {
                'user': banned_user,
                'course_id': course_key,
                'scope': 'course',
            }
            ban_kwargs = {
                **lookup_kwargs,
                'org_key': course_org,  # Denormalized field for easier querying
            }
        
        # Create or update ban
        ban, created = DiscussionBan.objects.get_or_create(
            **lookup_kwargs,
            defaults={
                **ban_kwargs,
                'banned_by': moderator,
                'reason': reason or 'No reason provided',
                'is_active': True,
                'banned_at': timezone.now(),
            }
        )
        
        if not created and not ban.is_active:
            # Reactivate previously deactivated ban
            ban.is_active = True
            ban.banned_by = moderator
            ban.reason = reason or ban.reason
            ban.banned_at = timezone.now()
            ban.unbanned_at = None
            ban.unbanned_by = None
            ban.save()
        
        # Create audit log
        DiscussionModerationLog.objects.create(
            action_type=DiscussionModerationLog.ACTION_BAN,
            target_user=banned_user,
            moderator=moderator,
            course_id=course_key if scope == 'course' else None,
            scope=scope,
            reason=reason,
            metadata={
                'ban_id': ban.id,
                'created': created,
            }
        )
        
        log.info(
            "User banned: user_id=%s, scope=%s, course_id=%s, org_key=%s, banned_by=%s",
            user_id, scope, course_id, org_key, banned_by_id
        )
    
    return _serialize_ban(ban)


def unban_user(
    ban_id: int,
    unbanned_by_id: str,
    course_id: Optional[str] = None,
    reason: str = '',
) -> Dict[str, Any]:
    """
    Unban a user from discussions.
    
    For course-level bans: Deactivates the ban completely.
    For org-level bans with course_id: Creates an exception for that course.
    For org-level bans without course_id: Deactivates the entire org ban.
    
    Args:
        ban_id: ID of the ban to unban
        unbanned_by_id: ID of user performing the unban
        course_id: Optional course ID for org-level ban exceptions
        reason: Reason for unbanning
        
    Returns:
        dict: Response with status, message, and ban/exception data
        
    Raises:
        DiscussionBan.DoesNotExist: If ban not found
        User.DoesNotExist: If unbanned_by user not found
    """
    try:
        ban = DiscussionBan.objects.get(id=ban_id, is_active=True)
    except DiscussionBan.DoesNotExist:
        raise ValueError(f"Active ban with id {ban_id} not found")
    
    moderator = User.objects.get(id=unbanned_by_id)
    exception_created = False
    exception_data = None
    
    with transaction.atomic():
        # For org-level bans with course_id: create exception instead of full unban
        if ban.scope == 'organization' and course_id:
            course_key = CourseKey.from_string(course_id)
            
            # Create exception for this specific course
            exception, created = DiscussionBanException.objects.get_or_create(
                ban=ban,
                course_id=course_key,
                defaults={
                    'unbanned_by': moderator,
                    'reason': reason or 'Course-level exception to organization ban',
                }
            )
            
            exception_created = True
            exception_data = {
                'id': exception.id,
                'ban_id': ban.id,
                'course_id': str(course_id),
                'unbanned_by': moderator.username,
                'reason': exception.reason,
                'created_at': exception.created.isoformat() if hasattr(exception, 'created') else None,
            }
            
            message = f'User {ban.user.username} unbanned from {course_id} (org-level ban still active for other courses)'
            
            # Audit log for exception
            DiscussionModerationLog.objects.create(
                action_type=DiscussionModerationLog.ACTION_BAN_EXCEPTION,
                target_user=ban.user,
                moderator=moderator,
                course_id=course_key,
                scope='organization',
                reason=f"Exception to org ban: {reason}",
                metadata={
                    'ban_id': ban.id,
                    'exception_id': exception.id,
                    'exception_created': created,
                    'org_key': ban.org_key,
                }
            )
        else:
            # Full unban (course-level or complete org-level unban)
            ban.is_active = False
            ban.unbanned_at = timezone.now()
            ban.unbanned_by = moderator
            ban.save()
            
            message = f'User {ban.user.username} unbanned successfully'
            
            # Audit log
            DiscussionModerationLog.objects.create(
                action_type=DiscussionModerationLog.ACTION_UNBAN,
                target_user=ban.user,
                moderator=moderator,
                course_id=ban.course_id,
                scope=ban.scope,
                reason=f"Unban: {reason}",
                metadata={
                    'ban_id': ban.id,
                }
            )
        
        log.info(
            "User unbanned: ban_id=%s, user_id=%s, exception_created=%s, unbanned_by=%s",
            ban_id, ban.user.id, exception_created, unbanned_by_id
        )
    
    return {
        'status': 'success',
        'message': message,
        'exception_created': exception_created,
        'ban': _serialize_ban(ban),
        'exception': exception_data,
    }


def get_banned_users(
    course_id: Optional[str] = None,
    org_key: Optional[str] = None,
    include_inactive: bool = False,
) -> List[Dict[str, Any]]:
    """
    Get list of banned users.
    
    Args:
        course_id: Filter by course ID (includes org-level bans for that course's org)
        org_key: Filter by organization key
        include_inactive: Include inactive (unbanned) users
        
    Returns:
        list: List of ban records
    """
    queryset = DiscussionBan.objects.select_related('user', 'banned_by', 'unbanned_by')
    
    if not include_inactive:
        queryset = queryset.filter(is_active=True)
    
    if course_id:
        course_key = CourseKey.from_string(course_id)
        # Include both course-level bans and org-level bans for this course's org
        from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
        try:
            course = CourseOverview.objects.get(id=course_key)
            queryset = queryset.filter(
                models.Q(course_id=course_key) | models.Q(org_key=course.org)
            )
        except CourseOverview.DoesNotExist:
            # Fallback to just course-level bans
            queryset = queryset.filter(course_id=course_key)
    elif org_key:
        queryset = queryset.filter(org_key=org_key)
    
    queryset = queryset.order_by('-banned_at')
    
    return [_serialize_ban(ban) for ban in queryset]


def get_ban(ban_id: int) -> Dict[str, Any]:
    """
    Get a specific ban by ID.
    
    Args:
        ban_id: ID of the ban
        
    Returns:
        dict: Ban record data
        
    Raises:
        DiscussionBan.DoesNotExist: If ban not found
    """
    ban = DiscussionBan.objects.select_related('user', 'banned_by', 'unbanned_by').get(id=ban_id)
    return _serialize_ban(ban)


def _serialize_ban(ban: DiscussionBan) -> Dict[str, Any]:
    """
    Serialize a ban object to dictionary.
    
    Args:
        ban: DiscussionBan instance
        
    Returns:
        dict: Serialized ban data
    """
    return {
        'id': ban.id,
        'user': {
            'id': ban.user.id,
            'username': ban.user.username,
            'email': ban.user.email,
        },
        'course_id': str(ban.course_id) if ban.course_id else None,
        'org_key': ban.org_key,
        'scope': ban.scope,
        'reason': ban.reason,
        'is_active': ban.is_active,
        'banned_at': ban.banned_at.isoformat() if ban.banned_at else None,
        'banned_by': {
            'id': ban.banned_by.id,
            'username': ban.banned_by.username,
        } if ban.banned_by else None,
        'unbanned_at': ban.unbanned_at.isoformat() if ban.unbanned_at else None,
        'unbanned_by': {
            'id': ban.unbanned_by.id,
            'username': ban.unbanned_by.username,
        } if ban.unbanned_by else None,
    }
