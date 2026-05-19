"""Backfill closed_by and close_reason_code for threads missing those values.

This command targets CommentThread rows where closed=True but closed_by is NULL
(i.e. threads that were migrated before the migration script read these fields
from MongoDB). Only closed_by and close_reason_code are updated — all other
fields are left untouched.
"""

from typing import Any

from bson import ObjectId
from django.core.management.base import BaseCommand, CommandParser

from forum.migration_helpers import get_user_or_none
from forum.models import CommentThread, MongoContent
from forum.mongo import get_database


class Command(BaseCommand):
    """Backfill closed_by and close_reason_code for CommentThreads that lack them."""

    help = (
        "Backfill closed_by and close_reason_code for closed CommentThreads "
        "that were migrated before the migration script handled those fields."
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

        # Target threads that are closed but have no closed_by recorded
        null_closed_by_threads = CommentThread.objects.filter(
            closed=True,
            closed_by__isnull=True,
        )
        count = 0

        for thread in null_closed_by_threads.iterator():
            mapping = MongoContent.objects.filter(
                content_object_id=thread.pk,
                content_type=thread.content_type,
            ).first()
            if not mapping:
                self.stderr.write(
                    f"No MongoContent mapping for CommentThread pk={thread.pk}, skipping."
                )
                continue

            mongo_doc = db.contents.find_one({"_id": ObjectId(mapping.mongo_id)})
            if not mongo_doc:
                self.stderr.write(
                    f"MongoDB document not found for mongo_id={mapping.mongo_id}, skipping."
                )
                continue

            closed_by_id = mongo_doc.get("closed_by_id")
            close_reason_code = mongo_doc.get("close_reason_code")

            if not closed_by_id:
                # Thread is closed in MySQL but MongoDB has no closed_by_id —
                # nothing to backfill, skip silently.
                continue

            closed_by = get_user_or_none(closed_by_id)
            if not closed_by:
                self.stderr.write(
                    f"User closed_by_id={closed_by_id} not found in MySQL for "
                    f"CommentThread pk={thread.pk}, skipping."
                )
                continue

            self.stdout.write(
                f"CommentThread pk={thread.pk}: "
                f"closed_by={closed_by.username!r}, "
                f"close_reason_code={close_reason_code!r}"
            )
            if not dry_run:
                thread.closed_by = closed_by
                thread.close_reason_code = close_reason_code
                thread.save(update_fields=["closed_by_id", "close_reason_code"])
            count += 1

        self.stdout.write(self.style.SUCCESS(f"Done. CommentThreads updated: {count}"))
