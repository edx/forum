"""Backfill created_at and updated_at for threads/comments migrated before
migration 0009 removed auto_now_add/auto_now from the Content model.

Before 0009, Django's auto_now_add/auto_now always overwrote any value passed
during create/save, so all migrated content ended up with the migration run
time instead of the original MongoDB timestamps.

This command reads the original timestamps from MongoDB and writes them back
using QuerySet.update(), which bypasses auto_now* even on older schema versions.
Only created_at and updated_at are touched — all other fields are left as-is.
"""

from typing import Any

from bson import ObjectId
from django.core.management.base import BaseCommand, CommandParser

from forum.migration_helpers import parse_mongo_datetime
from forum.models import Comment, CommentThread, MongoContent
from forum.mongo import get_database


class Command(BaseCommand):
    """Backfill created_at/updated_at from MongoDB for already-migrated content."""

    help = (
        "Backfill created_at and updated_at for CommentThreads and Comments whose "
        "timestamps were set to migration time instead of the original MongoDB value."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Add arguments to the command."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be updated without writing to the database.",
        )

    def handle(self, *args: str, **options: dict[str, Any]) -> None:
        """Handle the command."""
        dry_run: bool = bool(options["dry_run"])
        db = get_database()

        if dry_run:
            self.stdout.write("DRY RUN — no changes will be written.")

        thread_count = self._backfill(db, dry_run, CommentThread, "CommentThread")
        comment_count = self._backfill(db, dry_run, Comment, "Comment")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. CommentThreads updated: {thread_count}, Comments updated: {comment_count}"
            )
        )

    def _backfill(
        self,
        db: Any,
        dry_run: bool,
        model_class: type[CommentThread] | type[Comment],
        label: str,
    ) -> int:
        """Backfill created_at/updated_at for all records of a given model."""
        count = 0

        for obj in model_class.objects.iterator():
            mapping = MongoContent.objects.filter(
                content_object_id=obj.pk,
                content_type=obj.content_type,
            ).first()
            if not mapping:
                self.stderr.write(
                    f"No MongoContent mapping for {label} pk={obj.pk}, skipping."
                )
                continue

            mongo_doc = db.contents.find_one({"_id": ObjectId(mapping.mongo_id)})
            if not mongo_doc:
                self.stderr.write(
                    f"MongoDB document not found for mongo_id={mapping.mongo_id}, skipping."
                )
                continue

            created_at = parse_mongo_datetime(mongo_doc.get("created_at"))
            updated_at = parse_mongo_datetime(mongo_doc.get("updated_at"))

            if not created_at or not updated_at:
                self.stderr.write(
                    f"{label} pk={obj.pk}: missing timestamps in MongoDB, skipping."
                )
                continue

            self.stdout.write(
                f"{label} pk={obj.pk}: "
                f"created_at={created_at.isoformat()}, "
                f"updated_at={updated_at.isoformat()}"
            )
            if not dry_run:
                # Use QuerySet.update() — bypasses auto_now* at the SQL level.
                model_class.objects.filter(pk=obj.pk).update(
                    created_at=created_at,
                    updated_at=updated_at,
                )
            count += 1

        return count
