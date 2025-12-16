"""Discussion moderation models for MongoDB backend."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from forum.backends.mongodb.base_model import MongoBaseModel


class DiscussionMutes(MongoBaseModel):
    """
    MongoDB model for discussion user mutes.
    Supports both personal and course-wide mutes.
    """

    COLLECTION_NAME: str = "discussion_mutes"

    def get_active_mutes(
        self, 
        muted_user_id: str, 
        course_id: str, 
        muted_by_id: Optional[str] = None,
        scope: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get active mutes for a user in a course.
        
        Args:
            muted_user_id: ID of the muted user
            course_id: Course identifier
            muted_by_id: ID of user who performed the mute (optional)
            scope: Scope filter (personal/course) (optional)
            
        Returns:
            List of active mute documents
        """
        query = {
            "muted_user_id": muted_user_id,
            "course_id": course_id,
            "is_active": True
        }
        
        if muted_by_id:
            query["muted_by_id"] = muted_by_id
        if scope:
            query["scope"] = scope
            
        return list(self._collection.find(query))

    def create_mute(
        self, 
        muted_user_id: str, 
        muted_by_id: str,
        course_id: str, 
        scope: str = "personal", 
        reason: str = ""
    ) -> Dict[str, Any]:
        """
        Create a new mute record.
        
        Args:
            muted_user_id: ID of user to mute
            muted_by_id: ID of user performing the mute
            course_id: Course identifier
            scope: Mute scope ('personal' or 'course')
            reason: Optional reason for muting
            
        Returns:
            Created mute document
        """
        # Check for existing active mute
        existing = self.get_active_mutes(
            muted_user_id=muted_user_id,
            course_id=course_id,
            muted_by_id=muted_by_id if scope == "personal" else None,
            scope=scope
        )
        
        if existing:
            raise ValueError("User is already muted in this scope")
        
        mute_doc = {
            "_id": ObjectId(),
            "muted_user_id": muted_user_id,
            "muted_by_id": muted_by_id,
            "course_id": course_id,
            "scope": scope,
            "reason": reason,
            "is_active": True,
            "created_at": datetime.utcnow(),
            "modified_at": datetime.utcnow(),
            "muted_at": datetime.utcnow(),
            "unmuted_at": None,
            "unmuted_by_id": None
        }
        
        try:
            result = self._collection.insert_one(mute_doc)
            mute_doc["_id"] = str(result.inserted_id)
            return mute_doc
        except DuplicateKeyError as e:
            raise ValueError("Duplicate mute record") from e

    def deactivate_mutes(
        self, 
        muted_user_id: str,
        unmuted_by_id: str, 
        course_id: str, 
        scope: str = "personal",
        muted_by_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Deactivate (unmute) existing mute records.
        
        Args:
            muted_user_id: ID of user to unmute
            unmuted_by_id: ID of user performing the unmute
            course_id: Course identifier
            scope: Unmute scope ('personal' or 'course')
            muted_by_id: Original muter ID (for personal unmutes)
            
        Returns:
            Result of unmute operation
        """
        query = {
            "muted_user_id": muted_user_id,
            "course_id": course_id,
            "scope": scope,
            "is_active": True
        }
        
        if scope == "personal" and muted_by_id:
            query["muted_by_id"] = muted_by_id
            
        update_doc = {
            "$set": {
                "is_active": False,
                "unmuted_by_id": unmuted_by_id,
                "unmuted_at": datetime.utcnow(),
                "modified_at": datetime.utcnow()
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
            "modified_count": result.modified_count
        }

    def get_all_muted_users_for_course(
        self, 
        course_id: str, 
        requester_id: Optional[str] = None,
        scope: str = "all"
    ) -> List[Dict[str, Any]]:
        """
        Get all muted users in a course.
        
        Args:
            course_id: Course identifier
            requester_id: ID of user requesting the list (for personal mutes)
            scope: Scope filter ('personal', 'course', or 'all')
            
        Returns:
            List of active mute records
        """
        query = {"course_id": course_id, "is_active": True}
        
        if scope == "personal":
            query["scope"] = "personal"
            if requester_id:
                query["muted_by_id"] = requester_id
        elif scope == "course":
            query["scope"] = "course"
        
        return list(self._collection.find(query))

    def get_user_mute_status(
        self, 
        user_id: str, 
        course_id: str, 
        viewer_id: str
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
            muted_by_id=viewer_id,
            scope="personal"
        )
        
        # Check course-wide mutes
        course_mutes = self.get_active_mutes(
            muted_user_id=user_id,
            course_id=course_id,
            scope="course"
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
            "mute_details": personal_mutes + course_mutes
        }

    def _check_exceptions(self, muted_user_id: str, viewer_id: str, course_id: str) -> bool:
        """
        Check if viewer has an exception for a course-wide muted user.
        
        Args:
            muted_user_id: ID of muted user
            viewer_id: ID of viewer
            course_id: Course identifier
            
        Returns:
            True if exception exists, False otherwise
        """
        exceptions_model = DiscussionMuteExceptions()
        return exceptions_model.has_exception(muted_user_id, viewer_id, course_id)


class DiscussionMuteExceptions(MongoBaseModel):
    """
    MongoDB model for course-wide mute exceptions.
    Allows specific users to unmute course-wide muted users for themselves.
    """

    COLLECTION_NAME: str = "discussion_mute_exceptions"

    def create_exception(
        self, 
        muted_user_id: str, 
        exception_user_id: str, 
        course_id: str
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
        mutes_model = DiscussionMutes()
        course_mutes = mutes_model.get_active_mutes(
            muted_user_id=muted_user_id,
            course_id=course_id,
            scope="course"
        )
        
        if not course_mutes:
            raise ValueError("No active course-wide mute found for this user")
        
        exception_doc = {
            "_id": ObjectId(),
            "muted_user_id": muted_user_id,
            "exception_user_id": exception_user_id,
            "course_id": course_id,
            "created_at": datetime.utcnow(),
            "modified_at": datetime.utcnow()
        }
        
        # Use upsert to handle duplicates gracefully
        result = self._collection.update_one(
            {
                "muted_user_id": muted_user_id,
                "exception_user_id": exception_user_id,
                "course_id": course_id
            },
            {"$set": exception_doc},
            upsert=True
        )
        
        if result.upserted_id:
            exception_doc["_id"] = str(result.upserted_id)
        
        return exception_doc

    def remove_exception(
        self, 
        muted_user_id: str, 
        exception_user_id: str, 
        course_id: str
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
        result = self._collection.delete_one({
            "muted_user_id": muted_user_id,
            "exception_user_id": exception_user_id,
            "course_id": course_id
        })
        
        return result.deleted_count > 0

    def has_exception(
        self, 
        muted_user_id: str, 
        exception_user_id: str, 
        course_id: str
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
        count = self._collection.count_documents({
            "muted_user_id": muted_user_id,
            "exception_user_id": exception_user_id,
            "course_id": course_id
        })
        
        return count > 0

    def get_exceptions_for_course(self, course_id: str) -> List[Dict[str, Any]]:
        """
        Get all mute exceptions in a course.
        
        Args:
            course_id: Course identifier
            
        Returns:
            List of exception documents
        """
        return list(self._collection.find({"course_id": course_id}))


class DiscussionModerationLogs(MongoBaseModel):
    """
    MongoDB model for logging moderation actions.
    """

    COLLECTION_NAME: str = "discussion_moderation_logs"

    def log_action(
        self,
        action_type: str,
        target_user_id: str,
        moderator_id: str,
        course_id: str,
        scope: str = "personal",
        reason: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Log a moderation action.
        
        Args:
            action_type: Type of action ('mute', 'unmute', 'mute_and_report')
            target_user_id: ID of user who was targeted
            moderator_id: ID of user performing the action
            course_id: Course identifier
            scope: Action scope ('personal' or 'course')
            reason: Optional reason for the action
            metadata: Additional metadata for the action
            
        Returns:
            Created log document
        """
        log_doc = {
            "_id": ObjectId(),
            "action_type": action_type,
            "target_user_id": target_user_id,
            "moderator_id": moderator_id,
            "course_id": course_id,
            "scope": scope,
            "reason": reason,
            "metadata": metadata or {},
            "timestamp": datetime.utcnow()
        }
        
        result = self._collection.insert_one(log_doc)
        log_doc["_id"] = str(result.inserted_id)
        
        return log_doc

    def get_logs_for_user(
        self, 
        user_id: str, 
        course_id: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get moderation logs for a user.
        
        Args:
            user_id: ID of user to get logs for
            course_id: Optional course filter
            limit: Maximum number of logs to return
            
        Returns:
            List of log documents
        """
        query = {"target_user_id": user_id}
        if course_id:
            query["course_id"] = course_id
            
        return list(
            self._collection.find(query)
            .sort("timestamp", -1)
            .limit(limit)
        )

    def get_logs_for_course(
        self, 
        course_id: str, 
        action_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get moderation logs for a course.
        
        Args:
            course_id: Course identifier
            action_type: Optional action type filter
            limit: Maximum number of logs to return
            
        Returns:
            List of log documents
        """
        query = {"course_id": course_id}
        if action_type:
            query["action_type"] = action_type
            
        return list(
            self._collection.find(query)
            .sort("timestamp", -1)
            .limit(limit)
        )