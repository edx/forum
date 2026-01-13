"""
Management command to create MongoDB indexes for discussion mute functionality.
"""

from typing import Any

import pymongo
from django.core.management.base import BaseCommand
from pymongo import MongoClient
from pymongo.errors import OperationFailure

from forum.backends.mongodb.mutes import (
    DiscussionModerationLogs,
    DiscussionMuteExceptions,
    DiscussionMutes,
)


class Command(BaseCommand):
    """
    Creates MongoDB indexes for optimal mute query performance.

    Usage: python manage.py forum_create_mute_mongodb_indexes
    """

    help = "Create MongoDB indexes for discussion mute functionality"

    def add_arguments(self, parser: Any) -> None:
        """
        Add command-line arguments for the forum_create_mute_mongodb_indexes command.
        """
        parser.add_argument(
            "--drop-existing",
            action="store_true",
            dest="drop_existing",
            help="Drop existing indexes before creating new ones",
        )
        parser.add_argument(
            "--database-url",
            type=str,
            default="mongodb://localhost:27017/",
            help="MongoDB connection URL",
        )
        parser.add_argument(
            "--database-name",
            type=str,
            default="cs_comments_service",
            help="MongoDB database name",
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        """Create the indexes."""
        database_url = options["database_url"]
        database_name = options["database_name"]
        drop_existing = options["drop_existing"]

        self.stdout.write("Creating MongoDB indexes for mute functionality...")

        try:
            # Connect to MongoDB
            client: MongoClient[Any] = MongoClient(database_url)
            db = client[database_name]

            # Create indexes for each collection
            self._create_mute_indexes(db, drop_existing)
            self._create_exception_indexes(db, drop_existing)
            self._create_log_indexes(db, drop_existing)

            client.close()

            self.stdout.write(
                self.style.SUCCESS("Successfully created MongoDB mute indexes!")
            )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error creating indexes: {e}"))
            raise

    def _create_mute_indexes(self, db: Any, drop_existing: bool) -> None:
        """Create indexes for discussion_mutes collection."""
        collection_name = DiscussionMutes.COLLECTION_NAME
        collection = db[collection_name]

        self.stdout.write(f"Creating indexes for {collection_name}...")

        if drop_existing:
            collection.drop_indexes()
            self.stdout.write("  - Dropped existing indexes")

        # Index for finding active mutes by user and course
        try:
            collection.create_index(
                [
                    ("muted_user_id", pymongo.ASCENDING),
                    ("course_id", pymongo.ASCENDING),
                    ("is_active", pymongo.ASCENDING),
                ],
                name="muted_user_course_active",
            )
            self.stdout.write("  ✓ Created muted_user_course_active index")
        except OperationFailure as e:
            if "already exists" not in str(e):
                raise

        # Index for personal mutes (includes muted_by_id)
        try:
            collection.create_index(
                [
                    ("muted_user_id", pymongo.ASCENDING),
                    ("muted_by_id", pymongo.ASCENDING),
                    ("course_id", pymongo.ASCENDING),
                    ("scope", pymongo.ASCENDING),
                    ("is_active", pymongo.ASCENDING),
                ],
                name="personal_mute_lookup",
            )
            self.stdout.write("  ✓ Created personal_mute_lookup index")
        except OperationFailure as e:
            if "already exists" not in str(e):
                raise

        # Index for course-wide mutes
        try:
            collection.create_index(
                [
                    ("course_id", pymongo.ASCENDING),
                    ("scope", pymongo.ASCENDING),
                    ("is_active", pymongo.ASCENDING),
                ],
                name="course_mute_lookup",
            )
            self.stdout.write("  ✓ Created course_mute_lookup index")
        except OperationFailure as e:
            if "already exists" not in str(e):
                raise

        # Index for finding mutes by moderator
        try:
            collection.create_index(
                [
                    ("muted_by_id", pymongo.ASCENDING),
                    ("course_id", pymongo.ASCENDING),
                    ("created_at", pymongo.DESCENDING),
                ],
                name="moderator_activity",
            )
            self.stdout.write("  ✓ Created moderator_activity index")
        except OperationFailure as e:
            if "already exists" not in str(e):
                raise

        # Compound index for preventing duplicate active mutes
        try:
            collection.create_index(
                [
                    ("muted_user_id", pymongo.ASCENDING),
                    ("muted_by_id", pymongo.ASCENDING),
                    ("course_id", pymongo.ASCENDING),
                    ("scope", pymongo.ASCENDING),
                ],
                partialFilterExpression={"is_active": True},
                name="prevent_duplicate_active_mutes",
            )
            self.stdout.write("  ✓ Created prevent_duplicate_active_mutes index")
        except OperationFailure as e:
            if "already exists" not in str(e):
                raise

    def _create_exception_indexes(self, db: Any, drop_existing: bool) -> None:
        """Create indexes for discussion_mute_exceptions collection."""
        collection_name = DiscussionMuteExceptions.COLLECTION_NAME
        collection = db[collection_name]

        self.stdout.write(f"Creating indexes for {collection_name}...")

        if drop_existing:
            collection.drop_indexes()
            self.stdout.write("  - Dropped existing indexes")

        # Unique compound index for exceptions
        try:
            collection.create_index(
                [
                    ("muted_user_id", pymongo.ASCENDING),
                    ("exception_user_id", pymongo.ASCENDING),
                    ("course_id", pymongo.ASCENDING),
                ],
                unique=True,
                name="unique_exception",
            )
            self.stdout.write("  ✓ Created unique_exception index")
        except OperationFailure as e:
            if "already exists" not in str(e):
                raise

        # Index for finding exceptions by course
        try:
            collection.create_index(
                [("course_id", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)],
                name="course_exceptions",
            )
            self.stdout.write("  ✓ Created course_exceptions index")
        except OperationFailure as e:
            if "already exists" not in str(e):
                raise

        # Index for finding exceptions by muted user
        try:
            collection.create_index(
                [
                    ("muted_user_id", pymongo.ASCENDING),
                    ("course_id", pymongo.ASCENDING),
                ],
                name="muted_user_exceptions",
            )
            self.stdout.write("  ✓ Created muted_user_exceptions index")
        except OperationFailure as e:
            if "already exists" not in str(e):
                raise

    def _create_log_indexes(self, db: Any, drop_existing: bool) -> None:
        """Create indexes for discussion_moderation_logs collection."""
        collection_name = DiscussionModerationLogs.COLLECTION_NAME
        collection = db[collection_name]

        self.stdout.write(f"Creating indexes for {collection_name}...")

        if drop_existing:
            collection.drop_indexes()
            self.stdout.write("  - Dropped existing indexes")

        # Index for finding logs by target user
        try:
            collection.create_index(
                [
                    ("target_user_id", pymongo.ASCENDING),
                    ("timestamp", pymongo.DESCENDING),
                ],
                name="user_logs",
            )
            self.stdout.write("  ✓ Created user_logs index")
        except OperationFailure as e:
            if "already exists" not in str(e):
                raise

        # Index for finding logs by course
        try:
            collection.create_index(
                [("course_id", pymongo.ASCENDING), ("timestamp", pymongo.DESCENDING)],
                name="course_logs",
            )
            self.stdout.write("  ✓ Created course_logs index")
        except OperationFailure as e:
            if "already exists" not in str(e):
                raise

        # Index for finding logs by moderator
        try:
            collection.create_index(
                [
                    ("moderator_id", pymongo.ASCENDING),
                    ("timestamp", pymongo.DESCENDING),
                ],
                name="moderator_logs",
            )
            self.stdout.write("  ✓ Created moderator_logs index")
        except OperationFailure as e:
            if "already exists" not in str(e):
                raise

        # Index for finding logs by action type
        try:
            collection.create_index(
                [
                    ("action_type", pymongo.ASCENDING),
                    ("course_id", pymongo.ASCENDING),
                    ("timestamp", pymongo.DESCENDING),
                ],
                name="action_type_logs",
            )
            self.stdout.write("  ✓ Created action_type_logs index")
        except OperationFailure as e:
            if "already exists" not in str(e):
                raise

        # TTL index for automatic log cleanup (optional)
        try:
            # Logs older than 1 year will be automatically deleted
            collection.create_index(
                [("timestamp", pymongo.ASCENDING)],
                expireAfterSeconds=31536000,
                name="log_ttl",
            )  # 365 days * 24 hours * 60 minutes * 60 seconds
            self.stdout.write("  ✓ Created log_ttl index (1 year TTL)")
        except OperationFailure as e:
            if "already exists" not in str(e):
                raise
