"""Backfill author_username for threads/comments migrated before migration 0004.

This command only updates author_username and retired_username (for threads)
where those fields are currently NULL. All other fields are left untouched.
"""

from typing import Any

from bson import ObjectId
from django.core.management.base import BaseCommand, CommandParser

from forum.migration_helpers import get_user_or_none
from forum.models import Comment, CommentThread, MongoContent
from forum.mongo import get_database


class Command(BaseCommand):
    """Backfill author_username/retired_username for rows that lack it."""

    help = (
        "Backfill author_username (and retired_username) for CommentThreads and "
        "Comments that were migrated before migration 0004 added those fields."
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

        thread_count = self._backfill_threads(db, dry_run)
        comment_count = self._backfill_comments(db, dry_run)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Threads updated: {thread_count}, Comments updated: {comment_count}"
            )
        )

    def _resolve_username(
        self,
        mongo_doc: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        """
        Return (author_username, retired_username) using the same fallback logic
        as the main migration: MongoDB value → retired_username → current username.
        """
        author_username: str | None = mongo_doc.get("author_username")
        retired_username: str | None = mongo_doc.get("retired_username")

        if not author_username:
            if retired_username:
                author_username = retired_username
            else:
                author = get_user_or_none(mongo_doc.get("author_id"))
                if author:
                    author_username = author.username

        return author_username, retired_username

    def _backfill_threads(self, db: Any, dry_run: bool) -> int:
        """Backfill CommentThreads with NULL author_username."""
        null_threads = CommentThread.objects.filter(author_username__isnull=True)
        count = 0

        for thread in null_threads.iterator():
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

            author_username, retired_username = self._resolve_username(mongo_doc)
            if not author_username:
                self.stderr.write(
                    f"Could not resolve author_username for CommentThread pk={thread.pk}, skipping."
                )
                continue

            self.stdout.write(
                f"CommentThread pk={thread.pk}: author_username={author_username!r}, "
                f"retired_username={retired_username!r}"
            )
            if not dry_run:
                thread.author_username = author_username
                thread.retired_username = retired_username
                thread.save(update_fields=["author_username", "retired_username"])
            count += 1

        return count

    def _backfill_comments(self, db: Any, dry_run: bool) -> int:
        """Backfill Comments with NULL author_username."""
        null_comments = Comment.objects.filter(author_username__isnull=True)
        count = 0

        for comment in null_comments.iterator():
            mapping = MongoContent.objects.filter(
                content_object_id=comment.pk,
                content_type=comment.content_type,
            ).first()
            if not mapping:
                self.stderr.write(
                    f"No MongoContent mapping for Comment pk={comment.pk}, skipping."
                )
                continue

            mongo_doc = db.contents.find_one({"_id": ObjectId(mapping.mongo_id)})
            if not mongo_doc:
                self.stderr.write(
                    f"MongoDB document not found for mongo_id={mapping.mongo_id}, skipping."
                )
                continue

            author_username, retired_username = self._resolve_username(mongo_doc)
            if not author_username:
                self.stderr.write(
                    f"Could not resolve author_username for Comment pk={comment.pk}, skipping."
                )
                continue

            self.stdout.write(
                f"Comment pk={comment.pk}: author_username={author_username!r}"
            )
            if not dry_run:
                comment.author_username = author_username
                comment.retired_username = retired_username
                comment.save(update_fields=["author_username", "retired_username"])
            count += 1

        return count
