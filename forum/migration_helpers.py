"""Migration commands helper methods."""

import logging
from datetime import datetime
from typing import Any

from django.contrib.auth.models import User  # pylint: disable=E5142
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import OutputWrapper
from django.utils import timezone
from pymongo.collection import Collection
from pymongo.database import Database

from forum.models import (
    AbuseFlagger,
    Comment,
    CommentThread,
    CourseStat,
    EditHistory,
    ForumUser,
    HistoricalAbuseFlagger,
    LastReadTime,
    MongoContent,
    ReadState,
    Subscription,
    UserVote,
)
from forum.utils import get_trunc_title, make_aware

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Batch size for all bulk_create / bulk_update operations.
# Tune this to balance memory use vs round-trip overhead.
# ---------------------------------------------------------------------------
BATCH_SIZE = 500


def get_user_or_none(user_id: Any) -> User | None:
    """Get a user by ID or return None if not found."""
    try:
        return User.objects.get(id=int(user_id))
    except User.DoesNotExist:
        return None


def parse_mongo_datetime(value: Any) -> datetime | None:
    """
    Parse a MongoDB datetime value to a timezone-aware datetime.

    MongoDB may return datetime as string or datetime object.
    This function handles both cases.
    """
    if not value:
        return None

    if isinstance(value, str):
        # Parse ISO format string, handle 'Z' suffix for UTC
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))

    return make_aware(value)


def get_all_course_ids(db: Database[dict[str, Any]]) -> list[str]:
    """Get all course IDs from MongoDB."""
    return db.contents.distinct("course_id")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_int_id(uid: Any) -> int | None:
    """Convert a user ID value to int; return None on failure."""
    try:
        return int(uid)
    except (ValueError, TypeError):
        return None


def _collect_all_user_ids(contents: list[dict[str, Any]]) -> set[int]:
    """Return the set of all integer user IDs referenced in *contents*."""
    ids: set[int] = set()
    for c in contents:
        for field in ("author_id", "deleted_by", "closed_by_id"):
            uid = _to_int_id(c.get(field))
            if uid is not None:
                ids.add(uid)
        for vote_type in ("up", "down"):
            for uid_str in c.get("votes", {}).get(vote_type, []):
                uid = _to_int_id(uid_str)
                if uid is not None:
                    ids.add(uid)
        for uid_str in c.get("abuse_flaggers", []):
            uid = _to_int_id(uid_str)
            if uid is not None:
                ids.add(uid)
        for uid_str in c.get("historical_abuse_flaggers", []):
            uid = _to_int_id(uid_str)
            if uid is not None:
                ids.add(uid)
        for edit in c.get("edit_history", []):
            uid = _to_int_id(edit.get("author_id"))
            if uid is not None:
                ids.add(uid)
    return ids


def _build_user_cache(user_ids: set[int]) -> dict[int, User]:
    """Fetch all requested users in one query; return a {pk: User} mapping."""
    if not user_ids:
        return {}
    return {u.pk: u for u in User.objects.filter(pk__in=user_ids)}


# ---------------------------------------------------------------------------
# migrate_users  (batch-optimised)
# ---------------------------------------------------------------------------

def migrate_users(db: Database[dict[str, Any]], course_id: str) -> None:
    """
    Migrate users from MongoDB to MySQL.

    Uses bulk_create / bulk_update instead of per-row get_or_create calls,
    reducing the number of SQL round-trips from O(N) to O(1).
    """
    all_mongo_users = list(db.users.find({"course_stats.course_id": course_id}))
    if not all_mongo_users:
        return

    # Build a numeric-uid → mongo-doc map, dropping unparsable IDs.
    uid_map: dict[int, dict[str, Any]] = {}
    for u in all_mongo_users:
        uid = _to_int_id(u["_id"])
        if uid is not None:
            uid_map[uid] = u

    if not uid_map:
        return

    # --- Single bulk fetch of all Django users for this course ---
    django_users = {u.pk: u for u in User.objects.filter(pk__in=uid_map.keys())}

    # --- ForumUser: create missing rows in one shot ---
    existing_fu_ids = set(
        ForumUser.objects.filter(user_id__in=django_users.keys()).values_list(
            "user_id", flat=True
        )
    )
    new_forum_users = [
        ForumUser(
            user_id=uid,
            default_sort_key=uid_map[uid].get("default_sort_key", "date"),
        )
        for uid in django_users
        if uid not in existing_fu_ids
    ]
    if new_forum_users:
        ForumUser.objects.bulk_create(
            new_forum_users, batch_size=BATCH_SIZE, ignore_conflicts=True
        )

    # --- CourseStat: bulk create new / bulk update existing ---
    existing_stats: dict[int, CourseStat] = {
        cs.user_id: cs
        for cs in CourseStat.objects.filter(
            user_id__in=django_users.keys(), course_id=course_id
        )
    }
    stat_update_fields = [
        "active_flags", "inactive_flags", "threads", "responses", "replies",
        "deleted_threads", "deleted_responses", "deleted_replies", "last_activity_at",
    ]
    stats_to_create: list[CourseStat] = []
    stats_to_update: list[CourseStat] = []

    for uid, mongo_user in uid_map.items():
        if uid not in django_users:
            continue
        for stat in mongo_user.get("course_stats", []):
            if stat.get("course_id") != course_id:
                continue
            last_activity_at = parse_mongo_datetime(stat.get("last_activity_at"))
            if uid in existing_stats:
                cs = existing_stats[uid]
                cs.active_flags = stat.get("active_flags", 0)
                cs.inactive_flags = stat.get("inactive_flags", 0)
                cs.threads = stat.get("threads", 0)
                cs.responses = stat.get("responses", 0)
                cs.replies = stat.get("replies", 0)
                cs.deleted_threads = stat.get("deleted_threads", 0)
                cs.deleted_responses = stat.get("deleted_responses", 0)
                cs.deleted_replies = stat.get("deleted_replies", 0)
                cs.last_activity_at = last_activity_at
                stats_to_update.append(cs)
            else:
                stats_to_create.append(
                    CourseStat(
                        user_id=uid,
                        course_id=course_id,
                        active_flags=stat.get("active_flags", 0),
                        inactive_flags=stat.get("inactive_flags", 0),
                        threads=stat.get("threads", 0),
                        responses=stat.get("responses", 0),
                        replies=stat.get("replies", 0),
                        deleted_threads=stat.get("deleted_threads", 0),
                        deleted_responses=stat.get("deleted_responses", 0),
                        deleted_replies=stat.get("deleted_replies", 0),
                        last_activity_at=last_activity_at,
                    )
                )

    if stats_to_create:
        CourseStat.objects.bulk_create(
            stats_to_create, batch_size=BATCH_SIZE, ignore_conflicts=True
        )
    if stats_to_update:
        CourseStat.objects.bulk_update(
            stats_to_update, stat_update_fields, batch_size=BATCH_SIZE
        )


# ---------------------------------------------------------------------------
# migrate_content  (batch-optimised)
# ---------------------------------------------------------------------------

def migrate_content(db: Database[dict[str, Any]], course_id: str) -> None:
    """
    Migrate threads and comments from MongoDB to MySQL.

    Strategy:
    1.  Fetch ALL content for the course in a single MongoDB query.
    2.  Build a user cache with a single Django query (eliminates the
        biggest N+1 problem: per-voter/flagger/editor user lookups).
    3.  Pre-fetch all existing MongoContent mappings in one query.
    4.  Bulk-create new threads, then top-level comments, then child
        comments (preserving the FK ordering requirement).
    5.  Bulk-create votes, edit history, and abuse flaggers.
    6.  Issue a SINGLE MongoDB ``$in`` query for all subscriptions
        instead of one query per content item.
    """
    contents = list(
        db.contents.find({"course_id": course_id}).sort("created_at", 1)
    )
    if not contents:
        return

    all_ids_str = [str(c["_id"]) for c in contents]

    # Pre-fetch all existing MongoContent rows (one query).
    mongo_cache: dict[str, MongoContent] = {
        mc.mongo_id: mc
        for mc in MongoContent.objects.filter(mongo_id__in=all_ids_str)
    }

    # Collect every user ID referenced anywhere; fetch them all at once.
    user_cache = _build_user_cache(_collect_all_user_ids(contents))

    # ContentType objects are cached by Django's framework after the first call.
    thread_ct = ContentType.objects.get_for_model(CommentThread)
    comment_ct = ContentType.objects.get_for_model(Comment)

    threads_data = [c for c in contents if c["_type"] == "CommentThread"]
    comments_data = [c for c in contents if c["_type"] == "Comment"]

    # --- Threads ---
    _bulk_migrate_threads(threads_data, mongo_cache, user_cache, thread_ct)
    _refresh_mongo_cache(mongo_cache, [str(t["_id"]) for t in threads_data])

    # --- Comments: top-level first, then children (parent must exist first) ---
    top_level = [
        c for c in comments_data
        if not c.get("parent_id") or str(c.get("parent_id")) == "None"
    ]
    child_comments = [
        c for c in comments_data
        if c.get("parent_id") and str(c.get("parent_id")) != "None"
    ]
    _bulk_migrate_comments(top_level, mongo_cache, user_cache, comment_ct)
    _refresh_mongo_cache(mongo_cache, [str(c["_id"]) for c in top_level])
    _bulk_migrate_comments(child_comments, mongo_cache, user_cache, comment_ct)
    _refresh_mongo_cache(mongo_cache, [str(c["_id"]) for c in child_comments])

    # --- Metadata: votes, edit history, flaggers ---
    _bulk_migrate_votes(contents, mongo_cache, user_cache, thread_ct, comment_ct)
    _bulk_migrate_edit_history(contents, mongo_cache, user_cache, thread_ct, comment_ct)
    _bulk_migrate_abuse_flaggers(contents, mongo_cache, user_cache, thread_ct, comment_ct)

    # --- Subscriptions: ONE MongoDB query for the entire course ---
    _bulk_migrate_subscriptions(db, all_ids_str, mongo_cache, user_cache)


def _refresh_mongo_cache(
    cache: dict[str, MongoContent], mongo_ids: list[str]
) -> None:
    """Update *cache* with freshly queried MongoContent rows for *mongo_ids*."""
    if not mongo_ids:
        return
    cache.update(
        {mc.mongo_id: mc for mc in MongoContent.objects.filter(mongo_id__in=mongo_ids)}
    )


def _bulk_migrate_threads(
    threads_data: list[dict[str, Any]],
    mongo_cache: dict[str, MongoContent],
    user_cache: dict[int, User],
    thread_ct: ContentType,
) -> None:
    """Bulk-create new threads and bulk-update existing ones."""
    if not threads_data:
        return

    new_data = [
        t for t in threads_data
        if not (mongo_cache.get(str(t["_id"])) and
                mongo_cache[str(t["_id"])].content_object_id)
    ]
    existing_data = [
        t for t in threads_data
        if mongo_cache.get(str(t["_id"])) and
        mongo_cache[str(t["_id"])].content_object_id
    ]

    # --- Create new threads in bulk ---
    if new_data:
        pairs: list[tuple[str, CommentThread]] = []
        for t in new_data:
            author = user_cache.get(_to_int_id(t.get("author_id")))  # type: ignore[arg-type]
            if not author:
                continue
            author_username = (
                t.get("author_username")
                or t.get("retired_username")
                or author.username
            )
            deleted_by = (
                user_cache.get(_to_int_id(t.get("deleted_by")))  # type: ignore[arg-type]
                if t.get("deleted_by") else None
            )
            closed_by = (
                user_cache.get(_to_int_id(t.get("closed_by_id")))  # type: ignore[arg-type]
                if t.get("closed_by_id") else None
            )
            pairs.append((
                str(t["_id"]),
                CommentThread(
                    author=author,
                    author_username=author_username,
                    retired_username=t.get("retired_username"),
                    course_id=t["course_id"],
                    title=get_trunc_title(t.get("title", "")),
                    body=t["body"],
                    thread_type=t.get("thread_type", "discussion"),
                    context=t.get("context", "course"),
                    anonymous=t.get("anonymous", False),
                    anonymous_to_peers=t.get("anonymous_to_peers", False),
                    closed=t.get("closed", False),
                    closed_by=closed_by,
                    close_reason_code=t.get("close_reason_code"),
                    pinned=t.get("pinned", False),
                    created_at=parse_mongo_datetime(t["created_at"]),
                    updated_at=parse_mongo_datetime(t["updated_at"]),
                    last_activity_at=parse_mongo_datetime(t["last_activity_at"]),
                    commentable_id=t.get("commentable_id"),
                    is_spam=t.get("is_spam", False),
                    is_deleted=t.get("is_deleted", False),
                    deleted_at=parse_mongo_datetime(t.get("deleted_at")),
                    deleted_by=deleted_by,
                    visible=t.get("visible", True),
                ),
            ))

        if pairs:
            mongo_ids, objs = zip(*pairs)
            # Django 4.1+ returns PKs from bulk_create on MySQL 8.0.19+.
            created = CommentThread.objects.bulk_create(list(objs), batch_size=BATCH_SIZE)
            mc_rows = [
                MongoContent(
                    mongo_id=mid,
                    content_type=thread_ct,
                    content_object_id=thread.pk,
                )
                for mid, thread in zip(mongo_ids, created)
                if thread.pk
            ]
            if mc_rows:
                MongoContent.objects.bulk_create(
                    mc_rows, batch_size=BATCH_SIZE, ignore_conflicts=True
                )

    # --- Update existing threads in bulk ---
    if existing_data:
        pks = [
            mongo_cache[str(t["_id"])].content_object_id
            for t in existing_data
            if str(t["_id"]) in mongo_cache
        ]
        thread_pk_map = {
            th.pk: th
            for th in CommentThread.objects.filter(pk__in=pks)
        }
        thread_update_fields = [
            "title", "body", "thread_type", "context", "anonymous",
            "anonymous_to_peers", "closed", "closed_by", "close_reason_code",
            "pinned", "updated_at", "last_activity_at", "commentable_id",
            "is_spam", "is_deleted", "deleted_at", "deleted_by", "visible",
        ]
        to_update: list[CommentThread] = []
        for t in existing_data:
            mc = mongo_cache.get(str(t["_id"]))
            if not mc:
                continue
            thread = thread_pk_map.get(mc.content_object_id)
            if not thread:
                continue
            deleted_by = (
                user_cache.get(_to_int_id(t.get("deleted_by")))  # type: ignore[arg-type]
                if t.get("deleted_by") else None
            )
            closed_by = (
                user_cache.get(_to_int_id(t.get("closed_by_id")))  # type: ignore[arg-type]
                if t.get("closed_by_id") else None
            )
            thread.title = get_trunc_title(t.get("title", ""))
            thread.body = t["body"]
            thread.thread_type = t.get("thread_type", "discussion")
            thread.context = t.get("context", "course")
            thread.anonymous = t.get("anonymous", False)
            thread.anonymous_to_peers = t.get("anonymous_to_peers", False)
            thread.closed = t.get("closed", False)
            thread.closed_by = closed_by  # type: ignore[assignment]
            thread.close_reason_code = t.get("close_reason_code")
            thread.pinned = t.get("pinned", False)
            thread.updated_at = parse_mongo_datetime(t["updated_at"])  # type: ignore[assignment]
            thread.last_activity_at = parse_mongo_datetime(t["last_activity_at"])
            thread.commentable_id = t.get("commentable_id")  # type: ignore[assignment]
            thread.is_spam = t.get("is_spam", False)
            thread.is_deleted = t.get("is_deleted", False)
            thread.deleted_at = parse_mongo_datetime(t.get("deleted_at"))
            thread.deleted_by = deleted_by  # type: ignore[assignment]
            thread.visible = t.get("visible", True)
            to_update.append(thread)
        if to_update:
            CommentThread.objects.bulk_update(
                to_update, thread_update_fields, batch_size=BATCH_SIZE
            )


def _bulk_migrate_comments(
    comments_data: list[dict[str, Any]],
    mongo_cache: dict[str, MongoContent],
    user_cache: dict[int, User],
    comment_ct: ContentType,
) -> None:
    """
    Bulk-create new comments and bulk-update existing ones.

    Must be called with top-level comments before child comments so that
    parent PKs are available in *mongo_cache* when children are processed.
    """
    if not comments_data:
        return

    new_data = [
        c for c in comments_data
        if not (mongo_cache.get(str(c["_id"])) and
                mongo_cache[str(c["_id"])].content_object_id)
    ]
    existing_data = [
        c for c in comments_data
        if mongo_cache.get(str(c["_id"])) and
        mongo_cache[str(c["_id"])].content_object_id
    ]

    # --- Create new comments in bulk ---
    if new_data:
        pairs: list[tuple[str, Comment]] = []
        for c in new_data:
            author = user_cache.get(_to_int_id(c.get("author_id")))  # type: ignore[arg-type]
            if not author:
                continue

            mongo_thread_id = str(c["comment_thread_id"])
            mc_thread = mongo_cache.get(mongo_thread_id)
            if not mc_thread or not mc_thread.content_object_id:
                logger.warning(
                    f"Thread mapping not found for comment {c.get('_id')} "
                    f"(mongo_thread_id={mongo_thread_id})"
                )
                continue

            parent_pk: int | None = None
            if c.get("parent_id") and str(c.get("parent_id")) != "None":
                mc_parent = mongo_cache.get(str(c["parent_id"]))
                if not mc_parent or not mc_parent.content_object_id:
                    logger.warning(
                        f"Parent mapping not found for comment {c.get('_id')} "
                        f"(parent_id={c['parent_id']})"
                    )
                    continue
                parent_pk = mc_parent.content_object_id

            author_username = (
                c.get("author_username")
                or c.get("retired_username")
                or author.username
            )
            deleted_by = (
                user_cache.get(_to_int_id(c.get("deleted_by")))  # type: ignore[arg-type]
                if c.get("deleted_by") else None
            )
            pairs.append((
                str(c["_id"]),
                Comment(
                    author=author,
                    author_username=author_username,
                    retired_username=c.get("retired_username"),
                    comment_thread_id=mc_thread.content_object_id,
                    parent_id=parent_pk,
                    course_id=c["course_id"],
                    body=c["body"],
                    anonymous=c.get("anonymous", False),
                    anonymous_to_peers=c.get("anonymous_to_peers", False),
                    endorsed=c.get("endorsed", False),
                    child_count=c.get("child_count", 0),
                    created_at=parse_mongo_datetime(c["created_at"]),
                    updated_at=parse_mongo_datetime(c["updated_at"]),
                    depth=1 if parent_pk else 0,
                    is_spam=c.get("is_spam", False),
                    is_deleted=c.get("is_deleted", False),
                    deleted_at=parse_mongo_datetime(c.get("deleted_at")),
                    deleted_by=deleted_by,
                    visible=c.get("visible", True),
                ),
            ))

        if pairs:
            mongo_ids, objs = zip(*pairs)
            created = Comment.objects.bulk_create(list(objs), batch_size=BATCH_SIZE)

            mc_rows = []
            sort_key_updates: list[Comment] = []
            for mid, comment in zip(mongo_ids, created):
                if not comment.pk:
                    continue
                mc_rows.append(
                    MongoContent(
                        mongo_id=mid,
                        content_type=comment_ct,
                        content_object_id=comment.pk,
                    )
                )
                # Set sort_key now that we have the PK.
                if comment.parent_id:
                    comment.sort_key = f"{comment.parent_id}-{comment.pk}"
                else:
                    comment.sort_key = f"{comment.pk}"
                sort_key_updates.append(comment)

            if mc_rows:
                MongoContent.objects.bulk_create(
                    mc_rows, batch_size=BATCH_SIZE, ignore_conflicts=True
                )
            if sort_key_updates:
                Comment.objects.bulk_update(
                    sort_key_updates, ["sort_key"], batch_size=BATCH_SIZE
                )

    # --- Update existing comments in bulk ---
    if existing_data:
        pks = [
            mongo_cache[str(c["_id"])].content_object_id
            for c in existing_data
            if str(c["_id"]) in mongo_cache
        ]
        comment_pk_map = {
            cm.pk: cm for cm in Comment.objects.filter(pk__in=pks)
        }
        comment_update_fields = [
            "body", "anonymous", "anonymous_to_peers", "endorsed", "child_count",
            "updated_at", "is_spam", "is_deleted", "deleted_at", "deleted_by", "visible",
        ]
        to_update: list[Comment] = []
        for c in existing_data:
            mc = mongo_cache.get(str(c["_id"]))
            if not mc:
                continue
            comment = comment_pk_map.get(mc.content_object_id)
            if not comment:
                continue
            deleted_by = (
                user_cache.get(_to_int_id(c.get("deleted_by")))  # type: ignore[arg-type]
                if c.get("deleted_by") else None
            )
            comment.body = c["body"]
            comment.anonymous = c.get("anonymous", False)
            comment.anonymous_to_peers = c.get("anonymous_to_peers", False)
            comment.endorsed = c.get("endorsed", False)
            comment.child_count = c.get("child_count", 0)
            comment.updated_at = parse_mongo_datetime(c["updated_at"])  # type: ignore[assignment]
            comment.is_spam = c.get("is_spam", False)
            comment.is_deleted = c.get("is_deleted", False)
            comment.deleted_at = parse_mongo_datetime(c.get("deleted_at"))
            comment.deleted_by = deleted_by  # type: ignore[assignment]
            comment.visible = c.get("visible", True)
            to_update.append(comment)
        if to_update:
            Comment.objects.bulk_update(
                to_update, comment_update_fields, batch_size=BATCH_SIZE
            )


def _bulk_migrate_votes(
    contents: list[dict[str, Any]],
    mongo_cache: dict[str, MongoContent],
    user_cache: dict[int, User],
    thread_ct: ContentType,
    comment_ct: ContentType,
) -> None:
    """Bulk-create missing UserVote rows for all content in one pass."""
    candidates: list[tuple[int, int, int, int]] = []  # (user_id, ct_id, obj_id, vote)
    for c in contents:
        mc = mongo_cache.get(str(c["_id"]))
        if not mc or not mc.content_object_id:
            continue
        ct = thread_ct if c["_type"] == "CommentThread" else comment_ct
        for vote_type in ("up", "down"):
            vote_val = 1 if vote_type == "up" else -1
            for uid_str in c.get("votes", {}).get(vote_type, []):
                uid = _to_int_id(uid_str)
                if uid is not None and uid in user_cache:
                    candidates.append((uid, ct.pk, mc.content_object_id, vote_val))

    if not candidates:
        return

    obj_ids = {obj_id for _, _, obj_id, _ in candidates}
    existing_keys = set(
        UserVote.objects.filter(content_object_id__in=obj_ids).values_list(
            "user_id", "content_type_id", "content_object_id"
        )
    )

    new_votes = [
        UserVote(
            user_id=uid,
            content_type_id=ct_id,
            content_object_id=obj_id,
            vote=vote_val,
        )
        for uid, ct_id, obj_id, vote_val in candidates
        if (uid, ct_id, obj_id) not in existing_keys
    ]
    if new_votes:
        UserVote.objects.bulk_create(
            new_votes, batch_size=BATCH_SIZE, ignore_conflicts=True
        )


def _bulk_migrate_edit_history(
    contents: list[dict[str, Any]],
    mongo_cache: dict[str, MongoContent],
    user_cache: dict[int, User],
    thread_ct: ContentType,
    comment_ct: ContentType,
) -> None:
    """Bulk-create missing EditHistory rows for all content in one pass."""
    obj_ids = [mc.content_object_id for mc in mongo_cache.values() if mc.content_object_id]
    existing_keys: set[tuple[int, int, Any, int]] = set(
        EditHistory.objects.filter(content_object_id__in=obj_ids).values_list(
            "content_object_id", "content_type_id", "created_at", "editor_id"
        )
    )

    to_create: list[EditHistory] = []
    for c in contents:
        mc = mongo_cache.get(str(c["_id"]))
        if not mc or not mc.content_object_id:
            continue
        ct = thread_ct if c["_type"] == "CommentThread" else comment_ct
        for edit in c.get("edit_history", []):
            editor = user_cache.get(_to_int_id(edit.get("author_id")))  # type: ignore[arg-type]
            if not editor:
                continue
            created_at = parse_mongo_datetime(edit["created_at"])
            key = (mc.content_object_id, ct.pk, created_at, editor.pk)
            if key not in existing_keys:
                to_create.append(
                    EditHistory(
                        content_object_id=mc.content_object_id,
                        content_type=ct,
                        created_at=created_at,
                        editor=editor,
                        original_body=edit["original_body"],
                        reason_code=edit["reason_code"],
                    )
                )
                existing_keys.add(key)  # avoid duplicates within the same batch

    if to_create:
        EditHistory.objects.bulk_create(
            to_create, batch_size=BATCH_SIZE, ignore_conflicts=True
        )


def _bulk_migrate_abuse_flaggers(
    contents: list[dict[str, Any]],
    mongo_cache: dict[str, MongoContent],
    user_cache: dict[int, User],
    thread_ct: ContentType,
    comment_ct: ContentType,
) -> None:
    """Bulk-create missing AbuseFlagger / HistoricalAbuseFlagger rows."""
    obj_ids = [mc.content_object_id for mc in mongo_cache.values() if mc.content_object_id]

    existing_af: set[tuple[int, int, int]] = set(
        AbuseFlagger.objects.filter(content_object_id__in=obj_ids).values_list(
            "user_id", "content_type_id", "content_object_id"
        )
    )
    existing_haf: set[tuple[int, int, int]] = set(
        HistoricalAbuseFlagger.objects.filter(content_object_id__in=obj_ids).values_list(
            "user_id", "content_type_id", "content_object_id"
        )
    )

    af_to_create: list[AbuseFlagger] = []
    haf_to_create: list[HistoricalAbuseFlagger] = []
    flagged_at = timezone.now()

    for c in contents:
        mc = mongo_cache.get(str(c["_id"]))
        if not mc or not mc.content_object_id:
            continue
        ct = thread_ct if c["_type"] == "CommentThread" else comment_ct

        for uid_str in c.get("abuse_flaggers", []):
            uid = _to_int_id(uid_str)
            if uid is not None and uid in user_cache:
                key = (uid, ct.pk, mc.content_object_id)
                if key not in existing_af:
                    af_to_create.append(
                        AbuseFlagger(
                            user_id=uid,
                            content_type=ct,
                            content_object_id=mc.content_object_id,
                            flagged_at=flagged_at,
                        )
                    )
                    existing_af.add(key)

        for uid_str in c.get("historical_abuse_flaggers", []):
            uid = _to_int_id(uid_str)
            if uid is not None and uid in user_cache:
                key = (uid, ct.pk, mc.content_object_id)
                if key not in existing_haf:
                    haf_to_create.append(
                        HistoricalAbuseFlagger(
                            user_id=uid,
                            content_type=ct,
                            content_object_id=mc.content_object_id,
                            flagged_at=flagged_at,
                        )
                    )
                    existing_haf.add(key)

    if af_to_create:
        AbuseFlagger.objects.bulk_create(
            af_to_create, batch_size=BATCH_SIZE, ignore_conflicts=True
        )
    if haf_to_create:
        HistoricalAbuseFlagger.objects.bulk_create(
            haf_to_create, batch_size=BATCH_SIZE, ignore_conflicts=True
        )


def _bulk_migrate_subscriptions(
    db: Database[dict[str, Any]],
    content_ids_str: list[str],
    mongo_cache: dict[str, MongoContent],
    user_cache: dict[int, User],
) -> None:
    """
    Migrate subscriptions for an entire course using a SINGLE MongoDB query.

    The original code fired one ``db.subscriptions.find()`` per content
    item.  This version fetches them all at once via ``$in``.
    """
    if not content_ids_str:
        return

    all_subs = list(
        db.subscriptions.find({"source_id": {"$in": content_ids_str}})
    )
    if not all_subs:
        return

    thread_ct = ContentType.objects.get_for_model(CommentThread)
    comment_ct = ContentType.objects.get_for_model(Comment)

    obj_ids = [mc.content_object_id for mc in mongo_cache.values() if mc.content_object_id]
    existing_sub_map: dict[tuple[int, int, int], Subscription] = {
        (s.subscriber_id, s.source_content_type_id, s.source_object_id): s
        for s in Subscription.objects.filter(source_object_id__in=obj_ids)
    }

    subs_to_create: list[Subscription] = []
    subs_to_update: list[Subscription] = []
    seen: set[tuple[int, int, int]] = set(existing_sub_map.keys())

    for sub in all_subs:
        uid = _to_int_id(sub.get("subscriber_id"))
        user = user_cache.get(uid) if uid is not None else None  # type: ignore[arg-type]
        if not user:
            continue
        mc = mongo_cache.get(str(sub.get("source_id", "")))
        if not mc or not mc.content_object_id:
            logger.warning(
                f"Skipping subscription for source {sub.get('source_id')}: mapping not found"
            )
            continue
        ct = thread_ct if sub.get("source_type") == "CommentThread" else comment_ct
        created_at = parse_mongo_datetime(sub.get("created_at")) or timezone.now()
        updated_at = parse_mongo_datetime(sub.get("updated_at")) or timezone.now()
        key = (user.pk, ct.pk, mc.content_object_id)

        if key in existing_sub_map:
            s = existing_sub_map[key]
            s.created_at = created_at  # type: ignore[assignment]
            s.updated_at = updated_at  # type: ignore[assignment]
            subs_to_update.append(s)
        elif key not in seen:
            subs_to_create.append(
                Subscription(
                    subscriber=user,
                    source_content_type=ct,
                    source_object_id=mc.content_object_id,
                    created_at=created_at,
                    updated_at=updated_at,
                )
            )
            seen.add(key)

    if subs_to_create:
        Subscription.objects.bulk_create(
            subs_to_create, batch_size=BATCH_SIZE, ignore_conflicts=True
        )
    if subs_to_update:
        Subscription.objects.bulk_update(
            subs_to_update, ["created_at", "updated_at"], batch_size=BATCH_SIZE
        )


# ---------------------------------------------------------------------------
# migrate_read_states  (batch-optimised)
# ---------------------------------------------------------------------------

def migrate_read_states(db: Database[dict[str, Any]], course_id: str) -> None:
    """
    Migrate read states from MongoDB to MySQL using bulk operations.

    Replaces the original per-row get_or_create / .save() loops with
    one bulk-create pass for ReadState and one for LastReadTime.
    """
    all_mongo_users = list(db.users.find({"course_stats.course_id": course_id}))
    if not all_mongo_users:
        return

    # Collect per-user read-state data and all referenced thread IDs.
    all_thread_ids: set[str] = set()
    user_read_data: list[tuple[int, list[dict[str, Any]]]] = []
    for user_data in all_mongo_users:
        uid = _to_int_id(user_data["_id"])
        if uid is None:
            continue
        relevant = [
            rs for rs in user_data.get("read_states", [])
            if rs.get("course_id") == course_id
        ]
        if relevant:
            user_read_data.append((uid, relevant))
            for rs in relevant:
                all_thread_ids.update(rs.get("last_read_times", {}).keys())

    if not user_read_data:
        return

    uids = {uid for uid, _ in user_read_data}
    django_users = {u.pk: u for u in User.objects.filter(pk__in=uids)}

    # Bulk-fetch all MongoContent for referenced thread IDs.
    mongo_thread_map: dict[str, int] = {}  # mongo_id → content_object_id
    for mc in MongoContent.objects.filter(mongo_id__in=all_thread_ids):
        if mc.content_object_id:
            mongo_thread_map[mc.mongo_id] = mc.content_object_id

    # Bulk get-or-create ReadState rows.
    existing_rs: dict[int, ReadState] = {
        rs.user_id: rs
        for rs in ReadState.objects.filter(
            user_id__in=django_users.keys(), course_id=course_id
        )
    }
    new_rs = [
        ReadState(user_id=uid, course_id=course_id)
        for uid, _ in user_read_data
        if uid in django_users and uid not in existing_rs
    ]
    if new_rs:
        ReadState.objects.bulk_create(
            new_rs, batch_size=BATCH_SIZE, ignore_conflicts=True
        )
        existing_rs.update(
            {
                rs.user_id: rs
                for rs in ReadState.objects.filter(
                    user_id__in=[r.user_id for r in new_rs],
                    course_id=course_id,
                )
            }
        )

    # Bulk get-or-create LastReadTime rows.
    rs_ids = [rs.pk for rs in existing_rs.values()]
    existing_lrt: dict[tuple[int, int], LastReadTime] = {
        (lrt.read_state_id, lrt.comment_thread_id): lrt
        for lrt in LastReadTime.objects.filter(read_state_id__in=rs_ids)
    }

    lrt_to_create: list[LastReadTime] = []
    lrt_to_update: list[LastReadTime] = []
    seen_keys: set[tuple[int, int]] = set(existing_lrt.keys())

    for uid, read_states in user_read_data:
        if uid not in django_users:
            continue
        rs = existing_rs.get(uid)
        if not rs:
            continue
        for read_state in read_states:
            for thread_id, timestamp in read_state.get("last_read_times", {}).items():
                thread_pk = mongo_thread_map.get(thread_id)
                # thread_pk may be None for deleted threads retained in MongoDB
                # read_states — skip silently (same behaviour as original code).
                if not thread_pk:
                    continue
                parsed_ts = parse_mongo_datetime(timestamp)
                key = (rs.pk, thread_pk)
                if key in existing_lrt:
                    lrt = existing_lrt[key]
                    lrt.timestamp = parsed_ts  # type: ignore[assignment]
                    lrt_to_update.append(lrt)
                elif key not in seen_keys:
                    lrt_to_create.append(
                        LastReadTime(
                            read_state=rs,
                            comment_thread_id=thread_pk,
                            timestamp=parsed_ts,
                        )
                    )
                    seen_keys.add(key)

    if lrt_to_create:
        LastReadTime.objects.bulk_create(
            lrt_to_create, batch_size=BATCH_SIZE, ignore_conflicts=True
        )
    if lrt_to_update:
        LastReadTime.objects.bulk_update(
            lrt_to_update, ["timestamp"], batch_size=BATCH_SIZE
        )


def delete_course_data(
    db: Database[dict[str, Any]],
    course_id: str,
    dry_run: bool,
    stdout: OutputWrapper,
) -> None:
    """Delete content (threads and comments)."""
    contents = db.contents.find({"course_id": course_id})
    for content in contents:
        subscriptions = (
            db.subscriptions.delete_many({"source_id": str(content["_id"])})
            if not dry_run
            else None
        )
    stdout.write(
        f"Subscription documents to be deleted: {subscriptions.deleted_count if subscriptions else 'N/A (dry run)'}"
    )

    content_result = (
        db.contents.delete_many({"course_id": course_id}) if not dry_run else None
    )
    stdout.write(
        f"Content documents to be deleted: {content_result.deleted_count if content_result else 'N/A (dry run)'}"
    )
    user_ids = db.users.distinct("_id", {"course_stats.course_id": course_id})

    for user_id in user_ids:
        if not dry_run:
            db.users.update_one(
                {"_id": user_id},
                {
                    "$pull": {
                        "course_stats": {"course_id": course_id},
                        "read_states": {"course_id": course_id},
                    }
                },
            )
            stdout.write(f"Updated user data for user ID: {user_id}")

    if not dry_run:
        db.users.update_many(
            {},
            {
                "$pull": {
                    "course_stats": {"course_id": course_id},
                    "read_states": {"course_id": course_id},
                }
            },
        )
        stdout.write("Cleaned up users collection")


def log_deletion(
    collection_name: str,
    result: Collection[dict[str, Any]],
    stdout: OutputWrapper,
) -> None:
    """Log the deletion of a collection."""
    stdout.write(f"Deleted {result.deleted_count} documents from {collection_name}")


# pylint: disable=import-error,import-outside-toplevel
def enable_mysql_backend_for_course(course_id: str) -> None:
    """Enable MySQL backend waffle flag for a course."""
    from opaque_keys.edx.keys import CourseKey
    from openedx.core.djangoapps.waffle_utils.models import (  # type: ignore[import-not-found]
        WaffleFlagCourseOverrideModel,
    )

    from forum.toggles import ENABLE_MYSQL_BACKEND

    course_key = CourseKey.from_string(course_id)
    WaffleFlagCourseOverrideModel.objects.create(
        course_id=course_key, waffle_flag=ENABLE_MYSQL_BACKEND.name, enabled=True
    )
