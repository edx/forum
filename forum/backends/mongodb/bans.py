"""Discussion ban models for MongoDB backend."""

from datetime import datetime
from typing import Any, Optional

from bson import ObjectId
from pymongo.results import InsertOneResult, UpdateResult

from forum.backends.mongodb.base_model import MongoBaseModel


class DiscussionBans(MongoBaseModel):
    """
    MongoDB model for tracking users banned from course or organization discussions.

    Document schema:
    {
        "_id": ObjectId,
        "user_id": int,  # Django User ID
        "course_id": str,  # Optional, for course-level bans
        "org_key": str,  # Optional, for org-level bans
        "scope": str,  # "course" or "organization"
        "is_active": bool,
        "banned_by_id": int,  # Django User ID
        "reason": str,
        "banned_at": datetime,
        "unbanned_at": datetime,  # Optional
        "unbanned_by_id": int,  # Optional, Django User ID
        "created": datetime,
        "modified": datetime
    }
    """

    COLLECTION_NAME = "discussion_bans"

    SCOPE_COURSE = "course"
    SCOPE_ORGANIZATION = "organization"

    def insert(
        self,
        user_id: int,
        scope: str,
        reason: str,
        banned_by_id: int,
        course_id: Optional[str] = None,
        org_key: Optional[str] = None,
        is_active: bool = True,
    ) -> str:
        """
        Create a new discussion ban.

        Args:
            user_id: ID of the user being banned
            scope: "course" or "organization"
            reason: Reason for the ban
            banned_by_id: ID of the moderator issuing the ban
            course_id: Course ID for course-level bans
            org_key: Organization key for org-level bans
            is_active: Whether the ban is active

        Returns:
            The string ID of the inserted document
        """
        now = datetime.utcnow()

        ban_data: dict[str, Any] = {
            "user_id": user_id,
            "scope": scope,
            "is_active": is_active,
            "banned_by_id": banned_by_id,
            "reason": reason,
            "banned_at": now,
            "created": now,
            "modified": now,
        }

        if course_id:
            ban_data["course_id"] = course_id
        if org_key:
            ban_data["org_key"] = org_key

        result: InsertOneResult = self._collection.insert_one(ban_data)
        return str(result.inserted_id)

    def update_ban(
        self,
        ban_id: str,
        is_active: Optional[bool] = None,
        unbanned_by_id: Optional[int] = None,
        unbanned_at: Optional[datetime] = None,
    ) -> int:
        """
        Update a discussion ban.

        Args:
            ban_id: ID of the ban to update
            is_active: New active status
            unbanned_by_id: ID of moderator unbanning the user
            unbanned_at: Timestamp of unban

        Returns:
            Number of documents modified
        """
        update_data: dict[str, Any] = {
            "modified": datetime.utcnow(),
        }

        if is_active is not None:
            update_data["is_active"] = is_active
        if unbanned_by_id is not None:
            update_data["unbanned_by_id"] = unbanned_by_id
        if unbanned_at is not None:
            update_data["unbanned_at"] = unbanned_at

        result: UpdateResult = self._collection.update_one(
            {"_id": ObjectId(ban_id)}, {"$set": update_data}
        )
        return result.modified_count

    def get_active_ban(
        self,
        user_id: int,
        course_id: Optional[str] = None,
        org_key: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Get an active ban for a user.

        Args:
            user_id: ID of the user
            course_id: Course ID to check
            org_key: Organization key to check
            scope: Specific scope to filter by

        Returns:
            Ban document if found, None otherwise
        """
        query: dict[str, Any] = {
            "user_id": user_id,
            "is_active": True,
        }

        if scope:
            query["scope"] = scope
        if course_id:
            query["course_id"] = course_id
        if org_key:
            query["org_key"] = org_key

        return self._collection.find_one(query)

    def is_user_banned(
        self,
        user_id: int,
        course_id: str,
        check_org: bool = True,
    ) -> bool:
        """
        Check if a user is banned from discussions.

        Priority:
        1. Check for course-level exception to org ban (allows user)
        2. Organization-level ban (applies to all courses in org)
        3. Course-level ban (applies to specific course)

        Args:
            user_id: User ID to check
            course_id: Course ID string (e.g., "course-v1:edX+DemoX+Demo_Course")
            check_org: If True, also check organization-level bans

        Returns:
            True if user has active ban, False otherwise
        """
        # Extract organization from course_id (format: "course-v1:ORG+COURSE+RUN")
        try:
            if course_id.startswith("course-v1:"):
                org_name = course_id.split(":")[1].split("+")[0]
            else:
                # Fallback for old-style course IDs
                org_name = course_id.split("/")[0]
        except (IndexError, AttributeError):
            org_name = None

        # Check organization-level ban first
        if check_org and org_name:
            org_ban = self.get_active_ban(
                user_id=user_id, org_key=org_name, scope=self.SCOPE_ORGANIZATION
            )

            if org_ban:
                # Check if there's an exception for this specific course
                exceptions = DiscussionBanExceptions()
                if exceptions.has_exception(str(org_ban["_id"]), course_id):
                    return False
                # Org ban applies, no exception
                return True

        # Check course-level ban
        course_ban = self.get_active_ban(
            user_id=user_id, course_id=course_id, scope=self.SCOPE_COURSE
        )

        return course_ban is not None

    def get_user_bans(
        self,
        user_id: int,
        is_active: Optional[bool] = None,
    ) -> list[dict[str, Any]]:
        """
        Get all bans for a user.

        Args:
            user_id: User ID
            is_active: Filter by active status if provided

        Returns:
            List of ban documents
        """
        query: dict[str, Any] = {"user_id": user_id}

        if is_active is not None:
            query["is_active"] = is_active

        return list(self._collection.find(query).sort("banned_at", -1))


class DiscussionBanExceptions(MongoBaseModel):
    """
    MongoDB model for course-level exceptions to organization-level bans.

    Allows moderators to unban a user from specific courses while
    maintaining an organization-wide ban for all other courses.

    Document schema:
    {
        "_id": ObjectId,
        "ban_id": ObjectId,  # Reference to discussion_bans document
        "course_id": str,
        "unbanned_by_id": int,  # Django User ID
        "reason": str,  # Optional
        "created": datetime,
        "modified": datetime
    }
    """

    COLLECTION_NAME = "discussion_ban_exceptions"

    def insert(
        self,
        ban_id: str,
        course_id: str,
        unbanned_by_id: int,
        reason: Optional[str] = None,
    ) -> str:
        """
        Create a new ban exception.

        Args:
            ban_id: ID of the organization-level ban
            course_id: Course where user is unbanned
            unbanned_by_id: ID of moderator creating exception
            reason: Optional reason for exception

        Returns:
            The string ID of the inserted document
        """
        now = datetime.utcnow()

        exception_data: dict[str, Any] = {
            "ban_id": ObjectId(ban_id),
            "course_id": course_id,
            "unbanned_by_id": unbanned_by_id,
            "created": now,
            "modified": now,
        }

        if reason:
            exception_data["reason"] = reason

        result: InsertOneResult = self._collection.insert_one(exception_data)
        return str(result.inserted_id)

    def has_exception(
        self,
        ban_id: str,
        course_id: str,
    ) -> bool:
        """
        Check if an exception exists for a ban and course.

        Args:
            ban_id: ID of the ban
            course_id: Course ID to check

        Returns:
            True if exception exists, False otherwise
        """
        exception = self._collection.find_one(
            {
                "ban_id": ObjectId(ban_id),
                "course_id": course_id,
            }
        )
        return exception is not None

    def get_exceptions_for_ban(
        self,
        ban_id: str,
    ) -> list[dict[str, Any]]:
        """
        Get all exceptions for a ban.

        Args:
            ban_id: ID of the ban

        Returns:
            List of exception documents
        """
        return list(self._collection.find({"ban_id": ObjectId(ban_id)}))

    def delete_exception(
        self,
        ban_id: str,
        course_id: str,
    ) -> int:
        """
        Delete a specific exception.

        Args:
            ban_id: ID of the ban
            course_id: Course ID

        Returns:
            Number of documents deleted
        """
        result = self._collection.delete_one(
            {
                "ban_id": ObjectId(ban_id),
                "course_id": course_id,
            }
        )
        return result.deleted_count


class DiscussionModerationLogs(MongoBaseModel):
    """
    MongoDB model for discussion moderation audit logs.

    Tracks ban, unban, and bulk delete actions for compliance.

    Document schema:
    {
        "_id": ObjectId,
        "action_type": str,  # "ban_user", "unban_user", "ban_exception", "bulk_delete"
        "target_user_id": int,  # Django User ID
        "moderator_id": int,  # Django User ID
        "course_id": str,
        "scope": str,  # Optional
        "reason": str,  # Optional
        "metadata": dict,  # Optional, task IDs, counts, etc.
        "created": datetime
    }
    """

    COLLECTION_NAME = "discussion_moderation_logs"

    ACTION_BAN = "ban_user"
    ACTION_UNBAN = "unban_user"
    ACTION_BAN_EXCEPTION = "ban_exception"
    ACTION_BULK_DELETE = "bulk_delete"

    def insert(
        self,
        action_type: str,
        target_user_id: int,
        moderator_id: int,
        course_id: str,
        scope: Optional[str] = None,
        reason: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """
        Create a new moderation log entry.

        Args:
            action_type: Type of action performed
            target_user_id: ID of user being moderated
            moderator_id: ID of moderator performing action
            course_id: Course ID
            scope: Optional scope of action
            reason: Optional reason for action
            metadata: Optional additional data (task IDs, counts, etc.)

        Returns:
            The string ID of the inserted document
        """
        log_data: dict[str, Any] = {
            "action_type": action_type,
            "target_user_id": target_user_id,
            "moderator_id": moderator_id,
            "course_id": course_id,
            "created": datetime.utcnow(),
        }

        if scope:
            log_data["scope"] = scope
        if reason:
            log_data["reason"] = reason
        if metadata:
            log_data["metadata"] = metadata

        result: InsertOneResult = self._collection.insert_one(log_data)
        return str(result.inserted_id)

    def get_logs_for_user(
        self,
        user_id: int,
        action_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get moderation logs for a user.

        Args:
            user_id: User ID
            action_type: Optional filter by action type
            limit: Maximum number of logs to return

        Returns:
            List of log documents
        """
        query: dict[str, Any] = {"target_user_id": user_id}

        if action_type:
            query["action_type"] = action_type

        return list(self._collection.find(query).sort("created", -1).limit(limit))

    def get_logs_for_course(
        self,
        course_id: str,
        action_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get moderation logs for a course.

        Args:
            course_id: Course ID
            action_type: Optional filter by action type
            limit: Maximum number of logs to return

        Returns:
            List of log documents
        """
        query: dict[str, Any] = {"course_id": course_id}

        if action_type:
            query["action_type"] = action_type

        return list(self._collection.find(query).sort("created", -1).limit(limit))
