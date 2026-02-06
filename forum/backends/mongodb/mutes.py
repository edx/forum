"""Discussion moderation models for MongoDB backend."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from django.contrib.auth import get_user_model
from forum.backends.mongodb.base_model import MongoBaseModel

User = get_user_model()


class DiscussionMuteRecord(MongoBaseModel):
    """
    MongoDB model for discussion user mutes.
    Supports both personal and course-wide mutes.
    """

    COLLECTION_NAME: str = "discussion_mutes"

    def get_active_mutes(
        self,
        muted_user_id: str,
        course_id: str,
        muter_id: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get active mutes for a user in a course.

        Args:
            muted_user_id: ID of the muted user
            course_id: Course identifier
            muter_id: ID of user who performed the mute (optional)
            scope: Scope filter (personal/course) (optional)

        Returns:
            List of active mute documents with serialized ObjectIds
        """
        query = {
            "muted_user_id": muted_user_id,
            "course_id": course_id,
            "is_active": True,
        }

        if muter_id:
            query["muter_id"] = muter_id
        if scope:
            query["scope"] = scope

        # Get mute documents and convert ObjectId to string for JSON compatibility
        mute_docs = list(self._collection.find(query))
        for doc in mute_docs:
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])
        return mute_docs

    @staticmethod
    def user_has_privileges(user: object) -> bool:
        """Check if user has any privileges"""
        # Basic Django privileges
        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return True

        # Check if user has any forum role or course role
        return (
            hasattr(user, "role_set")
            and user.role_set.exists()
            or hasattr(user, "courseaccessrole_set")
            and user.courseaccessrole_set.exists()
        )

    def mute_user(
        self,
        muted_user_id: str,
        muter_id: str,
        course_id: str,
        scope: str = "personal",
        reason: str = "",
        requester_is_privileged: bool = False,
    ) -> Dict[str, Any]:
        """
        Create a new mute record.

        Args:
            muted_user_id: ID of user to mute
            muter_id: ID of user performing the mute
            course_id: Course identifier
            scope: Mute scope ('personal' or 'course')
            reason: Optional reason for muting
            requester_is_privileged: Whether requester has course-level privileges

        Returns:
            Created mute document

        Raises:
            ValueError: If rules are violated (staff requirement for course scope, etc.)
        """
        # Validate scope parameter
        valid_scopes = {"personal", "course"}
        if scope not in valid_scopes:
            raise ValueError(
                f"Invalid scope '{scope}'. Must be one of: {', '.join(valid_scopes)}"
            )

        try:
            muted_user = User.objects.get(pk=int(muted_user_id))
            muter_user = User.objects.get(pk=int(muter_id))
        except User.DoesNotExist as e:
            raise ValueError(f"User not found: {e}") from e

        # Prevent self-muting
        if muted_user_id == muter_id:
            raise ValueError("Users cannot mute themselves")

        target_is_privileged = self.user_has_privileges(muted_user)
        requester_has_privileges = self.user_has_privileges(muter_user)
        is_privileged = requester_is_privileged or requester_has_privileges

        # Prevent muting of staff and privileged users
        if target_is_privileged:
            raise ValueError("Staff and privileged users cannot be muted")

        # Only privileged users can create course-wide mutes
        if scope == "course" and not is_privileged:
            raise ValueError(
                "Only privileged users (staff, instructors, CTAs, moderators) "
                "can create course-wide mutes"
            )

        # Check for existing active mute
        existing = self.get_active_mutes(
            muted_user_id=muted_user_id,
            course_id=course_id,
            muter_id=muter_id if scope == "personal" else None,
            scope=scope,
        )

        if existing:
            raise ValueError("User is already muted in this scope")

        mute_doc = {
            "_id": ObjectId(),
            "muted_user_id": muted_user_id,
            "muter_id": muter_id,
            "course_id": course_id,
            "scope": scope,
            "reason": reason,
            "is_active": True,
            "created_at": datetime.utcnow(),
            "modified_at": datetime.utcnow(),
            "muted_at": datetime.utcnow(),
            "unmuted_at": None,
            "unmuted_by_id": None,
        }

        try:
            result = self._collection.insert_one(mute_doc)
            mute_doc["_id"] = str(result.inserted_id)
            return mute_doc
        except DuplicateKeyError as e:
            raise ValueError("Duplicate mute record") from e

    def unmute_user(
        self,
        muted_user_id: str,
        unmuted_by_id: str,
        course_id: str,
        scope: str = "personal",
        muter_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Deactivate (unmute) existing mute records.

        Args:
            muted_user_id: ID of user to unmute
            unmuted_by_id: ID of user performing the unmute
            course_id: Course identifier
            scope: Unmute scope ('personal' or 'course')
            muter_id: Original muter ID (for personal unmutes)

        Returns:
            Result of unmute operation
        """
        query = {
            "muted_user_id": muted_user_id,
            "course_id": course_id,
            "scope": scope,
            "is_active": True,
        }

        if scope == "personal" and muter_id:
            query["muter_id"] = muter_id

        update_doc = {
            "$set": {
                "is_active": False,
                "unmuted_by_id": unmuted_by_id,
                "unmuted_at": datetime.utcnow(),
                "modified_at": datetime.utcnow(),
            }
        }

        result = self._collection.update_many(query, update_doc)

        if result.matched_count == 0:
            raise ValueError("No active mute found")

        return {
            "message": "User unmuted successfully",
            "muted_user_id": muted_user_id,
            "unmuted_by_id": unmuted_by_id,
            "course_id": course_id,
            "scope": scope,
            "modified_count": result.modified_count,
        }

    def fetch_muted_users_for_course(
        self,
        course_id: str,
        requester_id: Optional[str] = None,
        scope: str = "all",
        requester_is_privileged: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Get all muted users in a course with role-based filtering.

        Args:
            course_id: Course identifier
            requester_id: ID of user requesting the list (for personal mutes)
            scope: Scope filter ('personal', 'course', or 'all')
            requester_is_privileged: Whether requester has course-level privileges (controls what data is returned)

        Returns:
            List of active mute records based on requester permissions

        Authorization:
            - Learners: Can only see their own personal mutes
            - Privileged users: Can see course-wide mutes and all personal mutes
        """

        # Only verify staff status if the requester_is_privileged flag is False
        if requester_id and not requester_is_privileged:
            try:
                requester = User.objects.get(pk=int(requester_id))
                requester_is_privileged = self.user_has_privileges(requester)
            except User.DoesNotExist:
                # If requester user does not exist, treat as not privileged and continue.
                # This prevents errors from breaking the mute listing for non-existent users.
                pass

        query = {"course_id": course_id, "is_active": True}

        # Apply scope-based filtering based on requester role
        if requester_is_privileged:
            # Privileged users can see all mutes based on scope requested
            if scope == "personal":
                # Show only personal mutes
                query["scope"] = "personal"
            elif scope == "course":
                # Show only course-wide mutes
                query["scope"] = "course"
            # For "all" scope, show both personal and course mutes (no additional filter)
        else:
            # Learners can only see their own personal mutes
            query["scope"] = "personal"
            query["muter_id"] = requester_id

        # Get mute documents and convert ObjectId to string for JSON compatibility
        mute_docs = list(self._collection.find(query))
        for doc in mute_docs:
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])
        return mute_docs

    def get_user_mute_status(
        self, user_id: str, course_id: str, viewer_id: str
    ) -> Dict[str, Any]:
        """
        Get comprehensive mute status for a user.

        Args:
            user_id: ID of user to check
            course_id: Course identifier
            viewer_id: ID of user requesting the status

        Returns:
            Dictionary with mute status information
        """
        # Check personal mutes (viewer → user)
        personal_mutes = self.get_active_mutes(
            muted_user_id=user_id,
            course_id=course_id,
            muter_id=viewer_id,
            scope="personal",
        )

        # Check course-wide mutes
        course_mutes = self.get_active_mutes(
            muted_user_id=user_id, course_id=course_id, scope="course"
        )

        # Check for exceptions (viewer has unmuted this user for themselves)
        exceptions = self._check_exceptions(user_id, viewer_id, course_id)

        is_personally_muted = len(personal_mutes) > 0
        is_course_muted = len(course_mutes) > 0 and not exceptions

        return {
            "user_id": user_id,
            "course_id": course_id,
            "is_muted": is_personally_muted or is_course_muted,
            "personal_mute": is_personally_muted,
            "course_mute": is_course_muted,
            "has_exception": exceptions,
            "mute_details": personal_mutes + course_mutes,
        }

    def _check_exceptions(
        self, muted_user_id: str, viewer_id: str, course_id: str
    ) -> bool:
        """
        Check if viewer has an exception for a course-wide muted user.

        Args:
            muted_user_id: ID of muted user
            viewer_id: ID of viewer
            course_id: Course identifier

        Returns:
            True if exception exists, False otherwise
        """
        exceptions_model = DiscussionMuteException()
        return exceptions_model.has_exception(muted_user_id, viewer_id, course_id)


class DiscussionMuteException(MongoBaseModel):
    """
    MongoDB model for course-wide mute exceptions.
    Allows specific users to unmute course-wide muted users for themselves.
    """

    COLLECTION_NAME: str = "discussion_mute_exceptions"

    def create_mute_exception(
        self, muted_user_id: str, exception_user_id: str, course_id: str
    ) -> Dict[str, Any]:
        """
        Create a mute exception for a user.

        Args:
            muted_user_id: ID of the course-wide muted user
            exception_user_id: ID of user creating the exception
            course_id: Course identifier

        Returns:
            Created exception document
        """
        # Check if course-wide mute exists
        mutes_model = DiscussionMuteRecord()
        course_mutes = mutes_model.get_active_mutes(
            muted_user_id=muted_user_id, course_id=course_id, scope="course"
        )

        if not course_mutes:
            raise ValueError("No active course-wide mute found for this user")

        now = datetime.utcnow()
        set_on_insert = {
            "_id": ObjectId(),
            "created_at": now,
        }
        set_fields = {
            "muted_user_id": muted_user_id,
            "exception_user_id": exception_user_id,
            "course_id": course_id,
            "modified_at": now,
        }

        # Use upsert to handle duplicates gracefully and avoid immutable _id update error
        self._collection.update_one(
            {
                "muted_user_id": muted_user_id,
                "exception_user_id": exception_user_id,
                "course_id": course_id,
            },
            {"$set": set_fields, "$setOnInsert": set_on_insert},
            upsert=True,
        )

        # Retrieve the upserted or existing document
        doc = self._collection.find_one(
            {
                "muted_user_id": muted_user_id,
                "exception_user_id": exception_user_id,
                "course_id": course_id,
            }
        )
        if doc is None:
            return {}
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
        return doc

    def remove_exception(
        self, muted_user_id: str, exception_user_id: str, course_id: str
    ) -> bool:
        """
        Remove a mute exception.

        Args:
            muted_user_id: ID of the muted user
            exception_user_id: ID of user removing the exception
            course_id: Course identifier

        Returns:
            True if exception was removed, False if not found
        """
        result = self._collection.delete_one(
            {
                "muted_user_id": muted_user_id,
                "exception_user_id": exception_user_id,
                "course_id": course_id,
            }
        )

        return result.deleted_count > 0

    def has_exception(
        self, muted_user_id: str, exception_user_id: str, course_id: str
    ) -> bool:
        """
        Check if a mute exception exists.

        Args:
            muted_user_id: ID of the muted user
            exception_user_id: ID of user to check
            course_id: Course identifier

        Returns:
            True if exception exists, False otherwise
        """
        count = self._collection.count_documents(
            {
                "muted_user_id": muted_user_id,
                "exception_user_id": exception_user_id,
                "course_id": course_id,
            }
        )

        return count > 0

    def get_exceptions_for_course(self, course_id: str) -> List[Dict[str, Any]]:
        """
        Get all mute exceptions in a course.

        Args:
            course_id: Course identifier

        Returns:
            List of exception documents with serialized ObjectIds
        """
        # Get exception documents and convert ObjectId to string for JSON compatibility
        exception_docs = list(self._collection.find({"course_id": course_id}))
        for doc in exception_docs:
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])
        return exception_docs
