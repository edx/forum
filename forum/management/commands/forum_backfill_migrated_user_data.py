"""Backfill user-level forum data missed by earlier MongoDB → MySQL migrations.

Migrations run before this fix selected users with ``{"course_stats.course_id":
<course>}``. MongoDB user documents that carry no ``course_stats`` entry for the
course — common for accounts predating that field — were invisible to both the
user pass and the read state pass, so four tables came out incomplete:

* ``forum_forumuser``   — user data
* ``forum_coursestat``  — course-level statistics
* ``forum_readstate``   — per-course read state
* ``forum_lastreadtime``— per-thread read timestamps

This command repairs those gaps for courses that have already been migrated. It
is deliberately self-contained: it shares no state with the migration command
and can be run at any time against a live MySQL backend.

Safety contract, in a stage/production environment where MySQL has been serving
traffic since the migration:

* **Create-only.** A row that already exists is never updated or deleted, so
  data written by the live site after the migration is never rolled back.
* **No duplicates.** Every table is checked for existing rows before writing,
  and the bulk inserts additionally use ``ignore_conflicts`` so a concurrent
  writer cannot produce a duplicate.
* **Re-runnable.** A second run over the same course writes nothing.
"""

import time
from datetime import datetime
from typing import Any, Iterable, TypeVar, cast

from django.contrib.auth.models import User  # pylint: disable=E5142
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Count, Max, Q
from pymongo.database import Database

from forum.models import (
    AbuseFlagger,
    Comment,
    CommentThread,
    CourseStat,
    ForumUser,
    HistoricalAbuseFlagger,
    LastReadTime,
    MongoContent,
    ReadState,
)
from forum.mongo import get_database
from forum.utils import make_aware

# Batch size for bulk_create calls.
DEFAULT_BATCH_SIZE = 500

# Chunk size for `IN (...)` lookups against large id sets.
ID_CHUNK_SIZE = 5000

T = TypeVar("T")

STAT_FIELDS = (
    "active_flags",
    "inactive_flags",
    "threads",
    "responses",
    "replies",
    "deleted_threads",
    "deleted_responses",
    "deleted_replies",
    "last_activity_at",
)

REPORT_FIELDS = (
    ("forum_users", "ForumUser rows created"),
    ("course_stats", "CourseStat rows created"),
    ("read_states", "ReadState rows created"),
    ("last_read_times", "LastReadTime rows created"),
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def to_int_id(value: Any) -> int | None:
    """Convert a user ID value to int; return None when it is not numeric."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def parse_mongo_datetime(value: Any) -> datetime | None:
    """Parse a MongoDB datetime (string or datetime) into an aware datetime."""
    if not value:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return make_aware(value)


def chunked(values: list[T], size: int = ID_CHUNK_SIZE) -> Iterable[list[T]]:
    """Yield *values* in chunks of at most *size* items."""
    for start in range(0, len(values), size):
        yield values[start : start + size]


# ---------------------------------------------------------------------------
# Working out who belongs to a course
# ---------------------------------------------------------------------------


def collect_course_user_ids(
    db: Database[dict[str, Any]], course_id: str
) -> set[int]:
    """
    Return every user ID associated with *course_id*, from MongoDB and MySQL.

    Neither ``course_stats`` nor ``read_states`` can be trusted to be present,
    so membership is collected from every place a user ID can appear:

    * user documents carrying course stats or read states for the course;
    * content in MongoDB — authors, voters, abuse flaggers, editors, and the
      users who deleted or closed an item;
    * subscriptions to the course's threads;
    * content already migrated into MySQL, for courses whose MongoDB data has
      since been deleted.
    """
    ids: set[int] = set()

    user_query = {
        "$or": [
            {"course_stats.course_id": course_id},
            {"read_states.course_id": course_id},
        ]
    }
    for doc in db.users.find(user_query, {"_id": 1}):
        uid = to_int_id(doc["_id"])
        if uid is not None:
            ids.add(uid)

    content_projection = {
        "author_id": 1,
        "deleted_by": 1,
        "closed_by_id": 1,
        "votes": 1,
        "abuse_flaggers": 1,
        "historical_abuse_flaggers": 1,
        "edit_history": 1,
    }
    for content in db.contents.find({"course_id": course_id}, content_projection):
        for field in ("author_id", "deleted_by", "closed_by_id"):
            uid = to_int_id(content.get(field))
            if uid is not None:
                ids.add(uid)
        for vote_type in ("up", "down"):
            for raw in content.get("votes", {}).get(vote_type, []):
                uid = to_int_id(raw)
                if uid is not None:
                    ids.add(uid)
        for field in ("abuse_flaggers", "historical_abuse_flaggers"):
            for raw in content.get(field, []):
                uid = to_int_id(raw)
                if uid is not None:
                    ids.add(uid)
        for edit in content.get("edit_history", []):
            uid = to_int_id(edit.get("author_id"))
            if uid is not None:
                ids.add(uid)

    for raw in db.subscriptions.distinct(
        "subscriber_id", {"source.course_id": course_id}
    ):
        uid = to_int_id(raw)
        if uid is not None:
            ids.add(uid)

    for model in (CommentThread, Comment):
        ids.update(
            uid
            for uid in model.objects.filter(course_id=course_id)
            .values_list("author_id", flat=True)
            .distinct()
            if uid is not None
        )

    return ids


def existing_django_user_ids(user_ids: set[int]) -> set[int]:
    """Filter *user_ids* down to accounts that exist in Django."""
    found: set[int] = set()
    for chunk in chunked(sorted(user_ids)):
        found.update(
            User.objects.filter(pk__in=chunk).values_list("pk", flat=True)
        )
    return found


# ---------------------------------------------------------------------------
# Course stats derived from migrated content
# ---------------------------------------------------------------------------


def flagged_object_counts_by_author(
    model: Any, content_type: ContentType, object_author: dict[int, int]
) -> dict[int, int]:
    """
    Count, per author, how many of their content objects carry a flag.

    Matches ``MySQLBackend.build_course_stats``, which groups flag rows by
    content object and counts the groups: the number of the author's items that
    are flagged, not the number of flags on them.
    """
    counts: dict[int, int] = {}
    for chunk in chunked(list(object_author.keys())):
        flagged = (
            model.objects.filter(content_type=content_type, content_object_id__in=chunk)
            .values_list("content_object_id", flat=True)
            .distinct()
        )
        for object_id in flagged:
            author_id = object_author.get(object_id)
            if author_id is not None:
                counts[author_id] = counts.get(author_id, 0) + 1
    return counts


def derive_course_stats(course_id: str, user_ids: set[int]) -> dict[int, dict[str, Any]]:
    """
    Derive per-user course stats for *course_id* from content already in MySQL.

    The bulk equivalent of ``MySQLBackend.build_course_stats``, which walks one
    user at a time. Used for users whose MongoDB document has no stats entry —
    the content that was migrated is then the only truthful source of numbers.

    Returns ``{user_id: {stat_field: value}}``, following the same convention as
    ``build_course_stats``: ``threads``/``responses``/``replies`` exclude
    deleted items, which are counted separately.
    """
    if not user_ids:
        return {}

    thread_filter = Q(course_id=course_id, author_id__in=user_ids)
    comment_filter = Q(course_id=course_id, author_id__in=user_ids)
    stats: dict[int, dict[str, Any]] = {}

    def entry_for(user_id: int) -> dict[str, Any]:
        return stats.setdefault(
            user_id,
            {
                "threads": 0,
                "responses": 0,
                "replies": 0,
                "deleted_threads": 0,
                "deleted_responses": 0,
                "deleted_replies": 0,
                "active_flags": 0,
                "inactive_flags": 0,
                "last_activity_at": None,
            },
        )

    def note_activity(entry: dict[str, Any], value: datetime | None) -> None:
        if value is None:
            return
        current = entry["last_activity_at"]
        if current is None or value > current:
            entry["last_activity_at"] = value

    thread_rows = (
        CommentThread.objects.filter(thread_filter)
        .values("author_id")
        .annotate(
            total=Count("pk"),
            deleted=Count("pk", filter=Q(is_deleted=True)),
            last_activity=Max("updated_at"),
        )
    )
    for row in thread_rows:
        author_id = row["author_id"]
        if author_id is None:
            continue
        entry = entry_for(author_id)
        entry["deleted_threads"] = row["deleted"]
        entry["threads"] = row["total"] - row["deleted"]
        note_activity(entry, row["last_activity"])

    comment_rows = (
        Comment.objects.filter(comment_filter)
        .values("author_id")
        .annotate(
            responses_total=Count("pk", filter=Q(parent__isnull=True)),
            responses_deleted=Count(
                "pk", filter=Q(parent__isnull=True, is_deleted=True)
            ),
            replies_total=Count("pk", filter=Q(parent__isnull=False)),
            replies_deleted=Count(
                "pk", filter=Q(parent__isnull=False, is_deleted=True)
            ),
            last_activity=Max("updated_at"),
        )
    )
    for row in comment_rows:
        author_id = row["author_id"]
        if author_id is None:
            continue
        entry = entry_for(author_id)
        entry["deleted_responses"] = row["responses_deleted"]
        entry["responses"] = row["responses_total"] - row["responses_deleted"]
        entry["deleted_replies"] = row["replies_deleted"]
        entry["replies"] = row["replies_total"] - row["replies_deleted"]
        note_activity(entry, row["last_activity"])

    if not stats:
        return {}

    thread_authors = dict(
        CommentThread.objects.filter(thread_filter).values_list("pk", "author_id")
    )
    comment_authors = dict(
        Comment.objects.filter(comment_filter).values_list("pk", "author_id")
    )
    thread_ct = ContentType.objects.get_for_model(CommentThread)
    comment_ct = ContentType.objects.get_for_model(Comment)

    for model, field in (
        (AbuseFlagger, "active_flags"),
        (HistoricalAbuseFlagger, "inactive_flags"),
    ):
        per_author = flagged_object_counts_by_author(model, thread_ct, thread_authors)
        for author_id, count in flagged_object_counts_by_author(
            model, comment_ct, comment_authors
        ).items():
            per_author[author_id] = per_author.get(author_id, 0) + count
        for author_id, count in per_author.items():
            if author_id in stats:
                stats[author_id][field] = count

    return stats


# ---------------------------------------------------------------------------
# Per-table backfills (create-only)
# ---------------------------------------------------------------------------


def backfill_forum_users(
    db: Database[dict[str, Any]],
    user_ids: set[int],
    batch_size: int,
    dry_run: bool,
) -> int:
    """Create ForumUser rows for users that have none. Never updates a row."""
    if not user_ids:
        return 0

    existing: set[int] = set()
    for chunk in chunked(sorted(user_ids)):
        existing.update(
            ForumUser.objects.filter(user_id__in=chunk).values_list(
                "user_id", flat=True
            )
        )
    missing = user_ids - existing
    if not missing or dry_run:
        return len(missing)

    sort_keys: dict[int, str] = {}
    for doc in db.users.find(
        {"_id": {"$in": [str(uid) for uid in missing]}},
        {"_id": 1, "default_sort_key": 1},
    ):
        uid = to_int_id(doc["_id"])
        if uid is not None and doc.get("default_sort_key"):
            sort_keys[uid] = doc["default_sort_key"]

    ForumUser.objects.bulk_create(
        [
            ForumUser(user_id=uid, default_sort_key=sort_keys.get(uid, "date"))
            for uid in sorted(missing)
        ],
        batch_size=batch_size,
        ignore_conflicts=True,
    )
    return len(missing)


def backfill_course_stats(
    db: Database[dict[str, Any]],
    course_id: str,
    user_ids: set[int],
    batch_size: int,
    dry_run: bool,
) -> int:
    """
    Create CourseStat rows for users that have none for *course_id*.

    Values come from the user's MongoDB ``course_stats`` entry when it has one,
    and otherwise from the content already migrated into MySQL. Users with
    neither — someone who only ever read threads — get no row, matching what
    MongoDB holds for them. Existing rows are never touched: the live site has
    been maintaining them since the migration.
    """
    if not user_ids:
        return 0

    existing: set[int] = set()
    for chunk in chunked(sorted(user_ids)):
        existing.update(
            CourseStat.objects.filter(
                user_id__in=chunk, course_id=course_id
            ).values_list("user_id", flat=True)
        )
    missing = user_ids - existing
    if not missing:
        return 0

    mongo_stats: dict[int, dict[str, Any]] = {}
    for doc in db.users.find(
        {"_id": {"$in": [str(uid) for uid in missing]}}, {"_id": 1, "course_stats": 1}
    ):
        uid = to_int_id(doc["_id"])
        if uid is None:
            continue
        for stat in doc.get("course_stats", []):
            if stat.get("course_id") == course_id:
                mongo_stats[uid] = stat
                break

    derived = derive_course_stats(course_id, missing)

    def values_for(uid: int) -> dict[str, Any]:
        """Prefer MongoDB's numbers, falling back to what the content implies."""
        stat = mongo_stats.get(uid)
        fallback = derived.get(uid, {})
        if stat is None:
            return {
                field: fallback.get(field, None if field == "last_activity_at" else 0)
                for field in STAT_FIELDS
            }
        values: dict[str, Any] = {}
        for field in STAT_FIELDS:
            if field == "last_activity_at":
                values[field] = parse_mongo_datetime(
                    stat.get("last_activity_at")
                ) or fallback.get("last_activity_at")
            else:
                values[field] = stat.get(field, fallback.get(field, 0))
        return values

    to_create = [
        CourseStat(user_id=uid, course_id=course_id, **values_for(uid))
        for uid in sorted(missing)
        if uid in mongo_stats or uid in derived
    ]
    if not to_create or dry_run:
        return len(to_create)

    CourseStat.objects.bulk_create(
        to_create, batch_size=batch_size, ignore_conflicts=True
    )
    return len(to_create)


def backfill_read_states(
    db: Database[dict[str, Any]],
    course_id: str,
    user_ids: set[int],
    batch_size: int,
    dry_run: bool,
) -> tuple[int, int]:
    """
    Create ReadState and LastReadTime rows missing for *course_id*.

    Existing last read times are left alone, never rewritten: the live site
    advances them as learners read, so MongoDB's value is likely to be the
    older of the two. Returns ``(read_states_created, last_read_times_created)``.
    """
    if not user_ids:
        return 0, 0

    # Read states live on the user document, keyed by course.
    per_user: dict[int, dict[str, Any]] = {}
    thread_mongo_ids: set[str] = set()
    for doc in db.users.find(
        {"read_states.course_id": course_id}, {"_id": 1, "read_states": 1}
    ):
        uid = to_int_id(doc["_id"])
        if uid is None or uid not in user_ids:
            continue
        last_read_times: dict[str, Any] = {}
        for read_state in doc.get("read_states", []):
            if read_state.get("course_id") != course_id:
                continue
            last_read_times.update(read_state.get("last_read_times", {}) or {})
        per_user[uid] = last_read_times
        thread_mongo_ids.update(last_read_times.keys())

    if not per_user:
        return 0, 0

    existing_states: dict[int, ReadState] = {}
    for chunk in chunked(sorted(per_user.keys())):
        existing_states.update(
            {
                cast(int, rs.user_id): rs  # type: ignore[attr-defined]
                for rs in ReadState.objects.filter(
                    user_id__in=chunk, course_id=course_id
                )
            }
        )
    missing_states = sorted(set(per_user.keys()) - set(existing_states.keys()))

    if dry_run:
        # Without writing the ReadState rows their last read times cannot be
        # attributed, so report the read states only.
        return len(missing_states), 0

    if missing_states:
        ReadState.objects.bulk_create(
            [
                ReadState(user_id=uid, course_id=course_id)
                for uid in missing_states
            ],
            batch_size=batch_size,
            ignore_conflicts=True,
        )
        for chunk in chunked(missing_states):
            existing_states.update(
                {
                    cast(int, rs.user_id): rs  # type: ignore[attr-defined]
                    for rs in ReadState.objects.filter(
                        user_id__in=chunk, course_id=course_id
                    )
                }
            )

    # Map MongoDB thread ids to migrated CommentThread primary keys.
    thread_pks: dict[str, int] = {}
    for chunk in chunked(sorted(thread_mongo_ids)):
        for mapping in MongoContent.objects.filter(mongo_id__in=chunk):
            if mapping.content_object_id:
                thread_pks[mapping.mongo_id] = mapping.content_object_id

    state_pks = [rs.pk for rs in existing_states.values()]
    existing_pairs: set[tuple[int, int]] = set()
    for chunk in chunked(state_pks):
        existing_pairs.update(
            LastReadTime.objects.filter(read_state_id__in=chunk).values_list(
                "read_state_id", "comment_thread_id"
            )
        )

    to_create: list[LastReadTime] = []
    seen: set[tuple[int, int]] = set(existing_pairs)
    for uid, last_read_times in per_user.items():
        read_state = existing_states.get(uid)
        if read_state is None:
            continue
        for mongo_thread_id, timestamp in last_read_times.items():
            thread_pk = thread_pks.get(str(mongo_thread_id))
            # No mapping means the thread was never migrated (deleted content
            # retained in the user document); nothing to point a row at.
            if not thread_pk:
                continue
            key = (read_state.pk, thread_pk)
            if key in seen:
                continue
            parsed = parse_mongo_datetime(timestamp)
            if parsed is None:
                continue
            to_create.append(
                LastReadTime(
                    read_state=read_state,
                    comment_thread_id=thread_pk,
                    timestamp=parsed,
                )
            )
            seen.add(key)

    if to_create:
        LastReadTime.objects.bulk_create(
            to_create, batch_size=batch_size, ignore_conflicts=True
        )
    return len(missing_states), len(to_create)


def backfill_course(
    db: Database[dict[str, Any]],
    course_id: str,
    batch_size: int,
    dry_run: bool,
) -> dict[str, int]:
    """Backfill all four tables for one course."""
    candidate_ids = collect_course_user_ids(db, course_id)
    user_ids = existing_django_user_ids(candidate_ids)

    forum_users = backfill_forum_users(db, user_ids, batch_size, dry_run)
    course_stats = backfill_course_stats(
        db, course_id, user_ids, batch_size, dry_run
    )
    read_states, last_read_times = backfill_read_states(
        db, course_id, user_ids, batch_size, dry_run
    )
    return {
        "forum_users": forum_users,
        "course_stats": course_stats,
        "read_states": read_states,
        "last_read_times": last_read_times,
    }


class Command(BaseCommand):
    """Backfill ForumUser, CourseStat, ReadState and LastReadTime rows."""

    help = (
        "Backfill user data, course stats and read states that earlier "
        "MongoDB to MySQL migrations skipped for users without course stats. "
        "Only missing rows are written; existing rows are never modified."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Add arguments to the command."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what is missing without writing to the database.",
        )
        parser.add_argument(
            "-b",
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            metavar="N",
            help=f"Bulk-insert batch size (default: {DEFAULT_BATCH_SIZE}).",
        )
        parser.add_argument(
            "courses", nargs="+", type=str, help="List of course IDs or `all`"
        )

    def handle(self, *args: str, **options: dict[str, Any]) -> None:
        """Handle the command."""
        db = get_database()

        dry_run = bool(options["dry_run"])
        batch_size = int(str(options["batch_size"]))
        if batch_size < 1:
            raise CommandError("--batch-size must be >= 1.")

        course_ids = list(cast(list[str], options["courses"]))
        if "all" in course_ids:
            course_ids = db.contents.distinct("course_id")

        if dry_run:
            self.stdout.write("DRY RUN — no changes will be written.")

        total = len(course_ids)
        totals = {key: 0 for key, _ in REPORT_FIELDS}
        failed: list[tuple[str, str]] = []

        for index, course_id in enumerate(course_ids, start=1):
            started = time.monotonic()
            try:
                result = backfill_course(db, course_id, batch_size, dry_run)
            except Exception as exc:  # pylint: disable=broad-except
                elapsed = time.monotonic() - started
                self.stderr.write(
                    self.style.ERROR(
                        f"[{index}/{total}] FAILED {course_id} "
                        f"after {elapsed:.1f}s: {exc}"
                    )
                )
                failed.append((course_id, str(exc)))
                continue

            elapsed = time.monotonic() - started
            for key in totals:
                totals[key] += result[key]
            summary = ", ".join(f"{key}={result[key]}" for key in totals)
            self.stdout.write(
                f"[{index}/{total}] OK {course_id} ({elapsed:.1f}s) {summary}"
            )

        self.stdout.write("")
        for key, label in REPORT_FIELDS:
            self.stdout.write(f"{label}: {totals[key]}")

        if failed:
            self.stderr.write(
                self.style.ERROR(f"\n{len(failed)} course(s) failed backfill:")
            )
            for course_id, err in failed:
                self.stderr.write(self.style.ERROR(f"  {course_id}: {err}"))
            raise CommandError(
                f"{len(failed)} course(s) failed backfill. See stderr for details."
            )

        self.stdout.write(self.style.SUCCESS("Backfill completed successfully"))
