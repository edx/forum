"""
Tests for listing a course's threads with the MySQL backend.

These cover the cost of the list as well as its contents: the work for one page
must not grow with the size of the course or with the votes on each thread.
"""

from datetime import timedelta
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.models.signals import post_init
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from forum.backends.mysql.api import MySQLBackend as backend
from forum.backends.mysql.models import (
    Comment,
    CommentThread,
    LastReadTime,
    ReadState,
    UserVote,
)
from forum.serializers.thread import ThreadSerializer

User = get_user_model()

COURSE_ID = "course-v1:edX+ThreadList+2026"

pytestmark = pytest.mark.django_db


def make_thread(
    author: Any,
    title: str,
    last_activity_at: Any,
    comments: int = 0,
    pinned: bool = False,
) -> CommentThread:
    """Create a thread in the test course, with `comments` comments by its author."""
    thread = CommentThread.objects.create(
        author=author,
        course_id=COURSE_ID,
        title=title,
        body=f"Body of {title}",
        last_activity_at=last_activity_at,
        pinned=pinned,
    )
    for index in range(comments):
        Comment.objects.create(
            author=author,
            course_id=COURSE_ID,
            body=f"Comment {index} on {title}",
            comment_thread=thread,
        )
    return thread


def vote(thread: CommentThread, voters: list[Any], value: int) -> None:
    """Add a vote of `value` (1 up, -1 down) on the thread from each voter."""
    content_type = ContentType.objects.get_for_model(CommentThread)
    for voter in voters:
        UserVote.objects.create(
            user=voter,
            content_type=content_type,
            content_object_id=thread.pk,
            vote=value,
        )


def upvote(thread: CommentThread, voters: list[Any]) -> None:
    """Add an up vote on the thread from each voter."""
    vote(thread, voters, 1)


def list_threads(
    user: Any,
    sort_key: str = "activity",
    page: int = 1,
    per_page: int = 3,
    **params: Any,
) -> dict[str, Any]:
    """List the course's threads the way the "All posts" view does."""
    thread_ids = [
        thread["_id"]
        for thread in backend.get_filtered_threads(
            backend.get_user_thread_filter(COURSE_ID), ids_only=True
        )
    ]
    return backend.get_threads(
        {
            "course_id": COURSE_ID,
            "sort_key": sort_key,
            "page": page,
            "per_page": per_page,
            **params,
        },
        str(user.pk),
        ThreadSerializer,
        thread_ids,
    )


def titles(result: dict[str, Any]) -> list[str]:
    """Return the titles of the listed threads, in order."""
    return [thread["title"] for thread in result["collection"]]


def mark_read(user: Any, thread: CommentThread, read_at: Any) -> None:
    """Record that the user read the thread at `read_at`."""
    read_state, _ = ReadState.objects.get_or_create(user=user, course_id=COURSE_ID)
    LastReadTime.objects.create(
        read_state=read_state, comment_thread=thread, timestamp=read_at
    )


class CommentThreadLoads:
    """Count the CommentThread rows Django builds into model instances."""

    def __init__(self) -> None:
        self.count = 0

    def __enter__(self) -> "CommentThreadLoads":
        post_init.connect(self._on_init, sender=CommentThread)
        return self

    def __exit__(self, *exc_info: Any) -> None:
        post_init.disconnect(self._on_init, sender=CommentThread)

    def _on_init(self, **kwargs: Any) -> None:
        self.count += 1


def test_list_work_does_not_grow_with_the_course() -> None:
    """
    Listing a page loads the same number of threads however big the course is.

    Before LP-1549 the backend loaded every thread twice (once for the ids and once
    with vote and comment joins) and sliced the page out in Python, so a large
    course took ~45 seconds to open.
    """
    author = User.objects.create(username="author")
    now = timezone.now()
    for index in range(10):
        make_thread(author, f"Thread {index}", now - timedelta(minutes=index))

    with CommentThreadLoads() as small_course:
        list_threads(author, per_page=3)

    for index in range(10, 40):
        make_thread(author, f"Thread {index}", now - timedelta(minutes=index))

    with CommentThreadLoads() as large_course:
        result = list_threads(author, per_page=3)

    assert titles(result) == ["Thread 0", "Thread 1", "Thread 2"]
    assert result["thread_count"] == 40
    assert large_course.count == small_course.count


def test_list_query_count_does_not_grow_with_votes() -> None:
    """The number of queries for a page is the same however many votes it has."""
    author = User.objects.create(username="author")
    voters = [User.objects.create(username=f"voter{index}") for index in range(6)]
    now = timezone.now()
    threads = [
        make_thread(author, f"Thread {index}", now - timedelta(minutes=index), 2)
        for index in range(3)
    ]
    for thread in threads:
        upvote(thread, voters[:1])

    with CaptureQueriesContext(connection) as few_votes:
        list_threads(author)

    for thread in threads:
        upvote(thread, voters[1:])

    with CaptureQueriesContext(connection) as many_votes:
        result = list_threads(author)

    assert [thread["votes"]["up_count"] for thread in result["collection"]] == [6] * 3
    assert len(many_votes) == len(few_votes)


def test_pages_follow_the_sort_order() -> None:
    """Pinned threads come first, then most recent activity, page by page."""
    author = User.objects.create(username="author")
    now = timezone.now()
    for index in range(6):
        make_thread(author, f"Thread {index}", now - timedelta(hours=index))
    make_thread(author, "Pinned", now - timedelta(days=30), pinned=True)

    pages = [list_threads(author, page=page, per_page=3) for page in (1, 2, 3)]

    assert [titles(page) for page in pages] == [
        ["Pinned", "Thread 0", "Thread 1"],
        ["Thread 2", "Thread 3", "Thread 4"],
        ["Thread 5"],
    ]
    assert all(page["thread_count"] == 7 for page in pages)
    assert all(page["num_pages"] == 3 for page in pages)


@pytest.mark.parametrize("sort_key", ["activity", "votes", "not-a-sort-key"])
def test_threads_with_identical_sort_values_are_not_repeated_across_pages(
    sort_key: str,
) -> None:
    """Exact ties, or an unknown sort key, must still give each thread one page."""
    author = User.objects.create(username="author")
    same_time = timezone.now()
    created = {
        make_thread(author, f"Thread {index}", same_time).title for index in range(7)
    }

    listed = [
        title
        for page in (1, 2, 3)
        for title in titles(
            list_threads(author, sort_key=sort_key, page=page, per_page=3)
        )
    ]

    assert sorted(listed) == sorted(created)


def test_sort_by_comments() -> None:
    """The comments sort orders threads by how many comments they have."""
    author = User.objects.create(username="author")
    now = timezone.now()
    make_thread(author, "No comments", now)
    make_thread(author, "Three comments", now - timedelta(days=2), comments=3)
    make_thread(author, "One comment", now - timedelta(days=1), comments=1)

    assert titles(list_threads(author, sort_key="comments")) == [
        "Three comments",
        "One comment",
        "No comments",
    ]


def test_sort_by_votes_uses_the_vote_total() -> None:
    """
    The votes sort orders threads by up votes minus down votes.

    Threads are created oldest first, so a sort that only knew "has votes" would
    fall back to newest first and put "One up vote" above "Three up votes".
    """
    author = User.objects.create(username="author")
    voters = [User.objects.create(username=f"voter{index}") for index in range(3)]
    now = timezone.now()
    vote(make_thread(author, "Three up votes", now), voters, 1)
    vote(make_thread(author, "One up vote", now), voters[:1], 1)
    make_thread(author, "Not voted", now)
    vote(make_thread(author, "One down vote", now), voters[:1], -1)

    assert titles(list_threads(author, sort_key="votes", per_page=10)) == [
        "Three up votes",
        "One up vote",
        "Not voted",
        "One down vote",
    ]


def test_endorsed_questions_are_marked_in_the_list() -> None:
    """A thread with an endorsed response is listed as endorsed."""
    author = User.objects.create(username="author")
    now = timezone.now()
    answered = make_thread(author, "Answered", now)
    make_thread(author, "Unanswered", now - timedelta(minutes=1), comments=1)
    Comment.objects.create(
        author=author,
        course_id=COURSE_ID,
        body="The answer",
        comment_thread=answered,
        endorsed=True,
    )

    endorsed = {
        thread["title"]: thread["endorsed"]
        for thread in list_threads(author)["collection"]
    }

    assert endorsed == {"Answered": True, "Unanswered": False}


def test_read_state_in_the_list() -> None:
    """Each listed thread reports whether the user has read it and what is new."""
    reader = User.objects.create(username="reader")
    other = User.objects.create(username="other")
    now = timezone.now()
    read = make_thread(other, "Read", now - timedelta(hours=3), comments=2)
    changed = make_thread(other, "Changed since read", now - timedelta(hours=1))
    make_thread(other, "Never read", now - timedelta(hours=2), comments=2)

    # Read after its comments were written (their created_at is the real "now").
    mark_read(reader, read, timezone.now())
    mark_read(reader, changed, now - timedelta(hours=2))
    Comment.objects.create(
        author=other,
        course_id=COURSE_ID,
        body="New since the reader looked",
        comment_thread=changed,
    )

    states = {
        thread["title"]: (thread["read"], thread["unread_comments_count"])
        for thread in list_threads(reader)["collection"]
    }

    assert states == {
        "Read": (True, 0),
        "Changed since read": (False, 1),
        "Never read": (False, 2),
    }


def test_unread_filter() -> None:
    """
    The unread filter leaves out threads read since their last activity, page by page.

    Read since its last activity: "Read". Read before it: "Changed since read".
    """
    reader = User.objects.create(username="reader")
    other = User.objects.create(username="other")
    now = timezone.now()
    make_thread(other, "Unread 1", now - timedelta(hours=1))
    read = make_thread(other, "Read", now - timedelta(hours=2))
    changed = make_thread(other, "Changed since read", now - timedelta(hours=3))
    make_thread(other, "Unread 2", now - timedelta(hours=4))
    mark_read(reader, read, now)
    mark_read(reader, changed, now - timedelta(hours=5))

    pages = [
        list_threads(reader, unread=True, page=page, per_page=2) for page in (1, 2)
    ]

    assert [titles(page) for page in pages] == [
        ["Unread 1", "Changed since read"],
        ["Unread 2"],
    ]
    assert [thread["read"] for page in pages for thread in page["collection"]] == [
        False
    ] * 3


def test_unresponded_filter() -> None:
    """The unresponded filter lists only threads with no comments at all."""
    author = User.objects.create(username="author")
    now = timezone.now()
    make_thread(author, "Answered", now, comments=1)
    make_thread(author, "Unanswered", now - timedelta(hours=1))
    deleted_only = make_thread(author, "Only a deleted comment", now)
    Comment.objects.create(
        author=author,
        course_id=COURSE_ID,
        body="Deleted",
        comment_thread=deleted_only,
        is_deleted=True,
    )

    assert titles(list_threads(author, unresponded=True)) == ["Unanswered"]


def test_list_without_a_user_has_no_read_state() -> None:
    """Without a requesting user the read fields are left empty."""
    author = User.objects.create(username="author")
    make_thread(author, "Thread", timezone.now(), comments=1)

    thread_ids = [
        thread["_id"]
        for thread in backend.get_filtered_threads(
            backend.get_user_thread_filter(COURSE_ID), ids_only=True
        )
    ]
    result = backend.get_threads(
        {"course_id": COURSE_ID, "sort_key": "activity"},
        "",
        ThreadSerializer,
        thread_ids,
    )

    assert result["collection"][0]["read"] is None
    assert result["collection"][0]["unread_comments_count"] is None
