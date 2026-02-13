"""MySQL models for forum v2."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from django.contrib.auth.models import User  # pylint: disable=E5142
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from forum.utils import validate_upvote_or_downvote


class ForumUser(models.Model):
    """Forum user model."""

    class Meta:
        app_label = "forum"

    user: models.OneToOneField[User, User] = models.OneToOneField(
        User, related_name="forum", on_delete=models.CASCADE
    )
    default_sort_key: models.CharField[str, str] = models.CharField(
        max_length=25, default="date"
    )

    def to_dict(self, course_id: Optional[str] = None) -> dict[str, Any]:
        """Return a dictionary representation of the model."""
        course_stats = CourseStat.objects.filter(user=self.user)
        read_states = ReadState.objects.filter(user=self.user)

        if course_id:
            course_stat = course_stats.filter(course_id=course_id).first()
        else:
            course_stat = None

        return {
            "_id": self.user.pk,
            "default_sort_key": self.default_sort_key,
            "external_id": self.user.pk,
            "username": self.user.username,
            "email": self.user.email,
            "course_stats": (
                course_stat.to_dict()
                if course_stat
                else [stat.to_dict() for stat in course_stats]
            ),
            "read_states": [state.to_dict() for state in read_states],
        }


class CourseStat(models.Model):
    """Course stats model."""

    course_id: models.CharField[str, str] = models.CharField(max_length=255)
    active_flags: models.IntegerField[int, int] = models.IntegerField(default=0)
    inactive_flags: models.IntegerField[int, int] = models.IntegerField(default=0)
    threads: models.IntegerField[int, int] = models.IntegerField(default=0)
    responses: models.IntegerField[int, int] = models.IntegerField(default=0)
    replies: models.IntegerField[int, int] = models.IntegerField(default=0)
    deleted_threads: models.IntegerField[int, int] = models.IntegerField(default=0)
    deleted_responses: models.IntegerField[int, int] = models.IntegerField(default=0)
    deleted_replies: models.IntegerField[int, int] = models.IntegerField(default=0)
    last_activity_at: models.DateTimeField[Optional[datetime], datetime] = (
        models.DateTimeField(default=None, null=True, blank=True)
    )
    user: models.ForeignKey[User, User] = models.ForeignKey(
        User, related_name="course_stats", on_delete=models.CASCADE
    )

    def to_dict(self) -> dict[str, Any]:
        """Return a dictionary representation of the model."""
        return {
            "_id": str(self.pk),
            "active_flags": self.active_flags,
            "inactive_flags": self.inactive_flags,
            "threads": self.threads,
            "responses": self.responses,
            "replies": self.replies,
            "deleted_threads": self.deleted_threads,
            "deleted_responses": self.deleted_responses,
            "deleted_replies": self.deleted_replies,
            "deleted_count": self.deleted_threads
            + self.deleted_responses
            + self.deleted_replies,
            "course_id": self.course_id,
            "last_activity_at": self.last_activity_at,
        }

    class Meta:
        app_label = "forum"
        unique_together = ("user", "course_id")


class Content(models.Model):
    """Content model."""

    index_name = ""

    author: models.ForeignKey[User, User] = models.ForeignKey(
        User, on_delete=models.CASCADE
    )
    author_username: models.CharField[Optional[str], str] = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Username at time of posting, preserved for historical accuracy",
    )
    retired_username: models.CharField[Optional[str], str] = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Username to display if author account was retired",
    )
    course_id: models.CharField[str, str] = models.CharField(max_length=255)
    body: models.TextField[str, str] = models.TextField()
    visible: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    endorsed: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    anonymous: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    anonymous_to_peers: models.BooleanField[bool, bool] = models.BooleanField(
        default=False
    )
    group_id: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(
        null=True
    )
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        auto_now_add=True
    )
    updated_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        auto_now=True
    )
    is_spam: models.BooleanField[bool, bool] = models.BooleanField(
        default=False,
        help_text="Whether this content has been identified as spam by AI moderation",
    )
    is_deleted: models.BooleanField[bool, bool] = models.BooleanField(
        default=False,
        help_text="Whether this content has been soft deleted",
    )
    deleted_at: models.DateTimeField[Optional[datetime], datetime] = (
        models.DateTimeField(
            null=True,
            blank=True,
            help_text="When this content was soft deleted",
        )
    )
    deleted_by: models.ForeignKey[User, User] = models.ForeignKey(
        User,
        related_name="deleted_%(class)s",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="User who soft deleted this content",
    )
    uservote = GenericRelation(
        "UserVote",
        object_id_field="content_object_id",
        content_type_field="content_type",
    )

    @property
    def type(self) -> str:
        """Return the type of content as str."""
        return self._meta.object_name or ""

    @property
    def content_type(self) -> ContentType:
        """Return the type of content."""
        return ContentType.objects.get_for_model(self)

    @property
    def abuse_flaggers(self) -> list[int]:
        """Return a list of users who have flagged the content for abuse."""
        return list(
            AbuseFlagger.objects.filter(
                content_object_id=self.pk, content_type=self.content_type
            ).values_list("user_id", flat=True)
        )

    @property
    def historical_abuse_flaggers(self) -> list[int]:
        """Return a list of users who have historically flagged the content for abuse."""
        return list(
            HistoricalAbuseFlagger.objects.filter(
                content_object_id=self.pk, content_type=self.content_type
            ).values_list("user_id", flat=True)
        )

    @property
    def edit_history(self) -> QuerySet[EditHistory]:
        """Return a list of edit history for the content."""
        return EditHistory.objects.filter(
            content_object_id=self.pk, content_type=self.content_type
        )

    @property
    def votes(self) -> models.QuerySet[UserVote]:
        """Get all user vote query for content."""
        return UserVote.objects.filter(
            content_object_id=self.pk,
            content_type=self.content_type,
        )

    @property
    def get_votes(self) -> dict[str, Any]:
        """Get all user votes for content."""
        votes: dict[str, Any] = {
            "up": [],
            "down": [],
            "up_count": 0,
            "down_count": 0,
            "count": 0,
            "point": 0,
        }
        for vote in self.votes:
            if vote.vote == 1:
                votes["up"].append(vote.user.pk)
                votes["up_count"] += 1
            elif vote.vote == -1:
                votes["down"].append(vote.user.pk)
                votes["down_count"] += 1
            votes["point"] = votes["up_count"] - votes["down_count"]
            votes["count"] = votes["count"]
        return votes

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Set author_username on creation if not already set."""
        if not self.pk and not self.author_username:
            # On creation, store the current username
            if self.retired_username:
                self.author_username = self.retired_username
            elif self.author:
                self.author_username = self.author.username
        super().save(*args, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        """Return a dictionary representation of the content."""
        raise NotImplementedError

    class Meta:
        app_label = "forum"
        abstract = True


class CommentThread(Content):
    """Comment thread model."""

    index_name = "comment_threads"

    THREAD_TYPE_CHOICES = [
        ("question", "Question"),
        ("discussion", "Discussion"),
    ]

    CONTEXT_CHOICES = [
        ("course", "Course"),
        ("standalone", "Standalone"),
    ]

    title: models.CharField[str, str] = models.CharField(max_length=1024)
    thread_type: models.CharField[str, str] = models.CharField(
        max_length=50, choices=THREAD_TYPE_CHOICES, default="discussion"
    )
    context: models.CharField[str, str] = models.CharField(
        max_length=50, choices=CONTEXT_CHOICES, default="course"
    )
    closed: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    pinned: models.BooleanField[Optional[bool], bool] = models.BooleanField(
        null=True, blank=True
    )
    last_activity_at: models.DateTimeField[Optional[datetime], datetime] = (
        models.DateTimeField(null=True, blank=True)
    )
    close_reason_code: models.CharField[Optional[str], str] = models.CharField(
        max_length=255, null=True, blank=True
    )
    closed_by: models.ForeignKey[User, User] = models.ForeignKey(
        User,
        related_name="threads_closed",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    commentable_id: models.CharField[str, str] = models.CharField(
        max_length=255,
        default=None,
        blank=True,
        null=True,
    )

    @property
    def comment_count(self) -> int:
        """Return the number of comments in the thread (excluding deleted)."""
        return Comment.objects.filter(comment_thread=self, is_deleted=False).count()

    @classmethod
    def get(cls, thread_id: str) -> CommentThread:
        """Get a comment thread model instance."""
        return cls.objects.get(pk=int(thread_id))

    def to_dict(self) -> dict[str, Any]:
        """Return a dictionary representation of the model."""
        edit_history = []
        for edit in self.edit_history.all():
            edit_history.append(
                {
                    "_id": str(edit.pk),
                    "original_body": edit.original_body,
                    "reason_code": edit.reason_code,
                    "editor_username": edit.editor.username,
                    "author_id": edit.editor.pk,
                    "created_at": edit.created_at,
                }
            )

        return {
            "_id": str(self.pk),
            "votes": self.get_votes,
            "visible": self.visible,
            "abuse_flaggers": [str(flagger) for flagger in self.abuse_flaggers],
            "historical_abuse_flaggers": [
                str(flagger) for flagger in self.historical_abuse_flaggers
            ],
            "thread_type": self.thread_type,
            "_type": "CommentThread",
            "commentable_id": self.commentable_id,
            "context": self.context,
            "comment_count": self.comment_count,
            "at_position_list": [],
            "pinned": self.pinned if self.pinned else False,
            "title": self.title,
            "body": self.body,
            "course_id": self.course_id,
            "anonymous": self.anonymous,
            "anonymous_to_peers": self.anonymous_to_peers,
            "closed": self.closed,
            "closed_by_id": str(self.closed_by.pk) if self.closed_by else None,
            "close_reason_code": self.close_reason_code,
            "author_id": str(self.author.pk),
            "author_username": self.author_username
            or self.retired_username
            or self.author.username,
            "updated_at": self.updated_at,
            "created_at": self.created_at,
            "last_activity_at": self.last_activity_at,
            "edit_history": edit_history,
            "group_id": self.group_id,
            "is_spam": self.is_spam,
            "is_deleted": self.is_deleted,
            "deleted_at": self.deleted_at,
            "deleted_by": str(self.deleted_by.pk) if self.deleted_by else None,
        }

    def doc_to_hash(self) -> dict[str, Any]:
        """
        Converts the CommentThread model instance to a dictionary representation for Elasticsearch.
        """
        return {
            "id": str(self.pk),
            "title": self.title,
            "body": self.body,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_activity_at": (
                self.last_activity_at.isoformat() if self.last_activity_at else None
            ),
            "comment_count": self.comment_count,
            "votes_point": self.get_votes.get("point"),
            "context": self.context,
            "course_id": self.course_id,
            "commentable_id": self.commentable_id,
            "author_id": str(self.author.pk),
            "group_id": self.group_id,
            "thread_id": str(self.pk),
        }

    class Meta:
        app_label = "forum"
        indexes = [
            models.Index(fields=["context"]),
            models.Index(fields=["author"]),
            models.Index(fields=["author", "course_id"]),
            models.Index(fields=["course_id", "anonymous", "anonymous_to_peers"]),
            models.Index(
                fields=["author", "course_id", "anonymous", "anonymous_to_peers"]
            ),
            models.Index(fields=["is_spam"]),
            models.Index(fields=["course_id", "is_spam"]),
            models.Index(fields=["author", "course_id", "is_spam"]),
        ]


class Comment(Content):
    """Comment model class"""

    index_name = "comments"

    endorsement: models.JSONField[dict[str, Any], dict[str, Any]] = models.JSONField(
        default=dict
    )
    sort_key: models.CharField[Optional[str], str] = models.CharField(
        max_length=255, null=True, blank=True
    )
    child_count: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(
        default=0
    )
    retired_username: models.CharField[Optional[str], str] = models.CharField(
        max_length=255, null=True, blank=True
    )
    comment_thread: models.ForeignKey[CommentThread, CommentThread] = models.ForeignKey(
        CommentThread, on_delete=models.CASCADE
    )
    parent: models.ForeignKey[Comment, Comment] = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True
    )
    depth: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(
        default=0
    )

    def get_sort_key(self) -> str:
        """Get the sort key for the comment"""
        if self.parent:
            return f"{self.parent.pk}-{self.pk}"
        return str(self.pk)

    @staticmethod
    def get_list(**kwargs: Any) -> list[dict[str, Any]]:
        """
        Retrieves a list of all comments in the database based on provided filters.

        Args:
            kwargs: The filter arguments.

        Returns:
            A list of comments.
        """
        sort = kwargs.pop("sort", None)
        resp_skip = kwargs.pop("resp_skip", 0)
        resp_limit = kwargs.pop("resp_limit", None)
        comments = Comment.objects.filter(**kwargs)
        result = []
        if sort:
            if sort == 1:
                result = sorted(
                    comments, key=lambda x: (x.sort_key is None, x.sort_key or "")
                )
            elif sort == -1:
                result = sorted(
                    comments,
                    key=lambda x: (x.sort_key is None, x.sort_key or ""),
                    reverse=True,
                )

        paginated_comments = result or list(comments)

        # Apply pagination if resp_limit is provided
        if resp_limit is not None:
            resp_end = resp_skip + resp_limit
            paginated_comments = result[resp_skip:resp_end]
        elif resp_skip:  # If resp_limit is None but resp_skip is provided
            paginated_comments = result[resp_skip:]

        return [content.to_dict() for content in paginated_comments]

    @staticmethod
    def get_list_total_count(**kwargs: Any) -> int:
        """
        Retrieves the total count of comments in the database based on provided filters.

        Args:
            kwargs: The filter arguments to apply when counting comments.

        Returns:
            The total number of comments matching the provided filters.
        """
        kwargs.pop("sort", None)
        kwargs.pop("resp_skip", 0)
        kwargs.pop("resp_limit", None)
        return Comment.objects.filter(**kwargs).count()

    def get_parent_ids(self) -> list[str]:
        """Return a list of all parent IDs of a comment."""
        parent_ids = []
        current_comment = self
        while current_comment.parent:
            parent_ids.append(str(current_comment.parent.pk))
            current_comment = current_comment.parent
        return parent_ids

    def to_dict(self) -> dict[str, Any]:
        """Return a dictionary representation of the model."""
        edit_history = []
        for edit in self.edit_history.all():
            edit_history.append(
                {
                    "_id": str(edit.pk),
                    "original_body": edit.original_body,
                    "reason_code": edit.reason_code,
                    "editor_username": edit.editor.username,
                    "author_id": edit.editor.pk,
                    "created_at": edit.created_at,
                }
            )

        endorsement = {
            "user_id": self.endorsement.get("user_id") if self.endorsement else None,
            "time": self.endorsement.get("time") if self.endorsement else None,
        }

        data = {
            "_id": str(self.pk),
            "votes": self.get_votes,
            "visible": self.visible,
            "abuse_flaggers": [str(flagger) for flagger in self.abuse_flaggers],
            "historical_abuse_flaggers": [
                str(flagger) for flagger in self.historical_abuse_flaggers
            ],
            "parent_ids": self.get_parent_ids(),
            "parent_id": str(self.parent.pk) if self.parent else "None",
            "at_position_list": [],
            "body": self.body,
            "course_id": self.course_id,
            "_type": "Comment",
            "endorsed": self.endorsed,
            "anonymous": self.anonymous,
            "anonymous_to_peers": self.anonymous_to_peers,
            "author_id": str(self.author.pk),
            "comment_thread_id": str(self.comment_thread.pk),
            "child_count": self.child_count,
            "author_username": self.author_username
            or self.retired_username
            or self.author.username,
            "sk": str(self.pk),
            "updated_at": self.updated_at,
            "created_at": self.created_at,
            "endorsement": endorsement if self.endorsement else None,
            "is_spam": self.is_spam,
            "is_deleted": self.is_deleted,
            "deleted_at": self.deleted_at,
            "deleted_by": str(self.deleted_by.pk) if self.deleted_by else None,
        }
        if edit_history:
            data["edit_history"] = edit_history

        return data

    @classmethod
    def get(cls, comment_id: str) -> Comment:
        """Get a comment model instance."""
        return cls.objects.get(pk=int(comment_id))

    def doc_to_hash(self) -> dict[str, Any]:
        """
        Converts the Comment model instance to a dictionary representation for Elasticsearch.
        """
        return {
            "body": self.body,
            "course_id": self.course_id,
            "comment_thread_id": self.comment_thread.pk,
            "commentable_id": None,
            "group_id": self.group_id,
            "context": "course",
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "title": None,
        }

    class Meta:
        app_label = "forum"
        indexes = [
            models.Index(fields=["author", "course_id"]),
            models.Index(fields=["comment_thread", "author", "created_at"]),
            models.Index(fields=["comment_thread", "endorsed"]),
            models.Index(fields=["course_id", "parent", "endorsed"]),
            models.Index(fields=["course_id", "anonymous", "anonymous_to_peers"]),
            models.Index(
                fields=["author", "course_id", "anonymous", "anonymous_to_peers"]
            ),
            models.Index(fields=["is_spam"]),
            models.Index(fields=["course_id", "is_spam"]),
            models.Index(fields=["author", "course_id", "is_spam"]),
        ]


class EditHistory(models.Model):
    """Edit history model class"""

    DISCUSSION_MODERATION_EDIT_REASON_CODES = [
        ("grammar-spelling", _("Has grammar / spelling issues")),
        ("needs-clarity", _("Content needs clarity")),
        ("academic-integrity", _("Has academic integrity concern")),
        ("inappropriate-language", _("Has inappropriate language")),
        ("format-change", _("Formatting changes needed")),
        ("post-type-change", _("Post type needs change")),
        ("contains-pii", _("Contains personally identifiable information")),
        ("violates-guidelines", _("Violates community guidelines")),
    ]

    reason_code: models.CharField[Optional[str], str] = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        choices=DISCUSSION_MODERATION_EDIT_REASON_CODES,
    )
    original_body: models.TextField[str, str] = models.TextField()
    editor: models.ForeignKey[User, User] = models.ForeignKey(
        User, on_delete=models.CASCADE
    )
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        auto_now_add=True
    )
    content_type: models.ForeignKey[ContentType] = models.ForeignKey(
        ContentType, on_delete=models.CASCADE
    )
    content_object_id: models.PositiveIntegerField[int, int] = (
        models.PositiveIntegerField()
    )
    content: GenericForeignKey = GenericForeignKey("content_type", "content_object_id")

    class Meta:
        app_label = "forum"
        indexes = [
            models.Index(fields=["editor"]),
            models.Index(fields=["content_type", "content_object_id"]),
            models.Index(fields=["created_at"]),
        ]


class AbuseFlagger(models.Model):
    """Abuse flagger model class"""

    content_type: models.ForeignKey[ContentType] = models.ForeignKey(
        ContentType, on_delete=models.CASCADE
    )
    content_object_id: models.PositiveIntegerField[int, int] = (
        models.PositiveIntegerField()
    )
    content: GenericForeignKey = GenericForeignKey("content_type", "content_object_id")
    user: models.ForeignKey[User, User] = models.ForeignKey(
        User, on_delete=models.CASCADE
    )
    flagged_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        default=timezone.now
    )

    class Meta:
        app_label = "forum"
        unique_together = ("user", "content_type", "content_object_id")
        indexes = [
            models.Index(fields=["content_type", "content_object_id"]),
            models.Index(fields=["user", "content_type", "content_object_id"]),
        ]


class HistoricalAbuseFlagger(models.Model):
    """Historical abuse flagger model class"""

    content_type: models.ForeignKey[ContentType] = models.ForeignKey(
        ContentType, on_delete=models.CASCADE
    )
    content_object_id: models.PositiveIntegerField[int, int] = (
        models.PositiveIntegerField()
    )
    content: GenericForeignKey = GenericForeignKey("content_type", "content_object_id")
    user: models.ForeignKey[User, User] = models.ForeignKey(
        User, on_delete=models.CASCADE
    )
    flagged_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        default=timezone.now
    )

    class Meta:
        app_label = "forum"
        unique_together = ("user", "content_type", "content_object_id")
        indexes = [
            models.Index(fields=["content_type", "content_object_id"]),
            models.Index(fields=["user", "content_type", "content_object_id"]),
        ]


class ReadState(models.Model):
    """Read state model."""

    course_id: models.CharField[str, str] = models.CharField(max_length=255)
    user: models.ForeignKey[User, User] = models.ForeignKey(
        User, related_name="read_states", on_delete=models.CASCADE
    )
    last_read_times: models.QuerySet[LastReadTime]

    def to_dict(self) -> dict[str, Any]:
        """Return a dictionary representation of the model."""
        last_read_times = {}
        for last_read_time in self.last_read_times.all():
            last_read_times[str(last_read_time.comment_thread.pk)] = (
                last_read_time.timestamp
            )
        return {
            "_id": str(self.pk),
            "last_read_times": last_read_times,
            "course_id": self.course_id,
        }

    class Meta:
        app_label = "forum"
        unique_together = ("course_id", "user")
        indexes = [
            models.Index(fields=["user", "course_id"]),
        ]


class LastReadTime(models.Model):
    """Last read time model."""

    read_state: models.ForeignKey[ReadState] = models.ForeignKey(
        ReadState, related_name="last_read_times", on_delete=models.CASCADE
    )
    comment_thread: models.ForeignKey[CommentThread, CommentThread] = models.ForeignKey(
        CommentThread, on_delete=models.CASCADE
    )
    timestamp: models.DateTimeField[datetime, datetime] = models.DateTimeField()

    class Meta:
        app_label = "forum"
        unique_together = ("read_state", "comment_thread")
        indexes = [
            models.Index(fields=["read_state", "timestamp"]),
            models.Index(fields=["comment_thread"]),
        ]


class UserVote(models.Model):
    """User votes model class"""

    user: models.ForeignKey[User, User] = models.ForeignKey(
        User, on_delete=models.CASCADE
    )
    content_type: models.ForeignKey[ContentType] = models.ForeignKey(
        ContentType, on_delete=models.CASCADE
    )
    content_object_id: models.PositiveIntegerField[int, int] = (
        models.PositiveIntegerField()
    )
    content: GenericForeignKey = GenericForeignKey("content_type", "content_object_id")
    vote: models.IntegerField[int, int] = models.IntegerField(
        validators=[validate_upvote_or_downvote]
    )

    class Meta:
        app_label = "forum"
        unique_together = ("user", "content_type", "content_object_id")
        indexes = [
            models.Index(fields=["vote"]),
            models.Index(fields=["user", "vote"]),
            models.Index(fields=["content_type", "content_object_id"]),
        ]


class Subscription(models.Model):
    """Subscription model class"""

    subscriber: models.ForeignKey[User, User] = models.ForeignKey(
        User, on_delete=models.CASCADE
    )
    source_content_type: models.ForeignKey[ContentType, ContentType] = (
        models.ForeignKey(ContentType, on_delete=models.CASCADE)
    )
    source_object_id: models.PositiveIntegerField[int, int] = (
        models.PositiveIntegerField()
    )
    source: GenericForeignKey = GenericForeignKey(
        "source_content_type", "source_object_id"
    )
    created_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        auto_now_add=True
    )
    updated_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        auto_now=True
    )

    def to_dict(self) -> dict[str, Any]:
        """Return a dictionary representation of the model."""
        return {
            "_id": str(self.pk),
            "subscriber_id": str(self.subscriber.pk),
            "source_id": str(self.source_object_id),
            "source_type": self.source_content_type.model,
            "updated_at": self.updated_at,
            "created_at": self.created_at,
        }

    class Meta:
        app_label = "forum"
        unique_together = ("subscriber", "source_content_type", "source_object_id")
        indexes = [
            models.Index(fields=["subscriber"]),
            models.Index(
                fields=["subscriber", "source_object_id", "source_content_type"]
            ),
            models.Index(fields=["subscriber", "source_content_type"]),
            models.Index(fields=["source_object_id", "source_content_type"]),
        ]


class MongoContent(models.Model):
    """MongoContent model class."""

    content_type: models.ForeignKey[ContentType] = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True
    )
    content_object_id: models.PositiveIntegerField[int, int] = (
        models.PositiveIntegerField(null=True)
    )
    content: GenericForeignKey = GenericForeignKey("content_type", "content_object_id")
    mongo_id: models.CharField[str, str] = models.CharField(max_length=50, unique=True)

    class Meta:
        app_label = "forum"


class ModerationAuditLog(models.Model):
    """Audit log for AI moderation decisions on spam content."""

    # Available actions that can be taken on spam content
    ACTION_CHOICES = [
        ("flagged", "Content Flagged"),
        ("soft_deleted", "Content Soft Deleted"),
        ("no_action", "No Action Taken"),
        ("mute", "Mute"),
        ("unmute", "Unmute"),
        ("mute_and_report", "Mute and Report"),
    ]

    # Only spam classifications since we don't store non-spam entries
    CLASSIFICATION_CHOICES = [
        ("spam", "Spam"),
        ("spam_or_scam", "Spam or Scam"),
    ]

    timestamp: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        default=timezone.now, help_text="When the moderation decision was made"
    )
    body: models.TextField[str, str] = models.TextField(
        help_text="The content body that was moderated"
    )
    classifier_output: models.JSONField[dict[str, Any], dict[str, Any]] = (
        models.JSONField(help_text="Full output from the AI classifier")
    )
    reasoning: models.TextField[str, str] = models.TextField(
        help_text="AI reasoning for the decision"
    )
    classification: models.CharField[str, str] = models.CharField(
        max_length=20,
        choices=CLASSIFICATION_CHOICES,
        help_text="AI classification result",
    )
    actions_taken: models.JSONField[list[str], list[str]] = models.JSONField(
        default=list,
        help_text="List of actions taken based on moderation (e.g., ['flagged', 'soft_deleted'])",
    )
    confidence_score: models.FloatField[Optional[float], float] = models.FloatField(
        null=True, blank=True, help_text="AI confidence score if available"
    )
    moderator_override: models.BooleanField[bool, bool] = models.BooleanField(
        default=False, help_text="Whether a human moderator overrode the AI decision"
    )
    override_reason: models.TextField[Optional[str], str] = models.TextField(
        blank=True, null=True, help_text="Reason for moderator override"
    )
    moderator: models.ForeignKey[User, User] = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="moderation_actions",
        help_text="Human moderator who made override",
    )
    original_author: models.ForeignKey[User, User] = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="moderated_content",
        help_text="Original author of the moderated content",
    )

    course_id: models.CharField[str, str] = models.CharField(
        max_length=255,
        blank=True,
        help_text="Course where the moderation action was performed",
    )
    scope: models.CharField[str, str] = models.CharField(
        max_length=10,
        blank=True,
        help_text="Scope of mute action (personal or course)",
    )
    reason: models.TextField[str, str] = models.TextField(
        blank=True,
        help_text="Optional reason for mute/unmute action",
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional metadata for mute moderation",
    )

    def to_dict(self) -> dict[str, Any]:
        """Return a dictionary representation of the model."""
        return {
            "_id": str(self.pk),
            "timestamp": self.timestamp.isoformat(),
            "body": self.body,
            "classifier_output": self.classifier_output,
            "reasoning": self.reasoning,
            "classification": self.classification,
            "actions_taken": self.actions_taken,
            "confidence_score": self.confidence_score,
            "moderator_override": self.moderator_override,
            "override_reason": self.override_reason,
            "moderator_id": str(self.moderator.pk) if self.moderator else None,
            "moderator_username": self.moderator.username if self.moderator else None,
            "original_author_id": str(self.original_author.pk),
            "original_author_username": self.original_author.username,
        }

    class Meta:
        app_label = "forum"
        verbose_name = "Moderation Audit Log"
        verbose_name_plural = "Moderation Audit Logs"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["timestamp"]),
            models.Index(fields=["classification"]),
            models.Index(fields=["original_author"]),
            models.Index(fields=["moderator"]),
            models.Index(fields=["course_id"]),
        ]


class DiscussionMuteRecord(models.Model):
    """
    Tracks muted users in discussions.
    A mute can be personal or course-wide.
    """

    class Scope(models.TextChoices):
        PERSONAL = "personal", "Personal"
        COURSE = "course", "Course-wide"

    muted_user: models.ForeignKey[User, User] = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="forum_muted_by_users",
        help_text="User being muted",
        db_index=True,
    )
    muted_by: models.ForeignKey[User, User] = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="forum_muted_users",
        help_text="User performing the mute",
        db_index=True,
    )
    unmuted_by: models.ForeignKey[User, User] = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="forum_mute_unactions",
        help_text="User who performed the unmute action",
    )
    course_id: models.CharField[str, str] = models.CharField(
        max_length=255, db_index=True, help_text="Course in which mute applies"
    )
    scope: models.CharField[str, str] = models.CharField(
        max_length=10,
        choices=Scope.choices,
        default=Scope.PERSONAL,
        help_text="Scope of the mute (personal or course-wide)",
        db_index=True,
    )
    reason: models.TextField[str, str] = models.TextField(
        blank=True, help_text="Optional reason for muting"
    )
    is_active: models.BooleanField[bool, bool] = models.BooleanField(
        default=True, help_text="Whether the mute is currently active"
    )

    created: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        auto_now_add=True
    )
    modified: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        auto_now=True
    )
    muted_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        auto_now_add=True
    )
    unmuted_at: models.DateTimeField[Optional[datetime], datetime] = (
        models.DateTimeField(null=True, blank=True)
    )

    class Meta:
        app_label = "forum"
        db_table = "forum_discussion_user_mute"
        constraints = [
            # Only one active personal mute per (muted_by → muted_user) in a course
            models.UniqueConstraint(
                fields=["muted_user", "muted_by", "course_id", "scope"],
                condition=models.Q(is_active=True, scope="personal"),
                name="forum_unique_active_personal_mute",
            ),
            # Only one active course-wide mute per user per course
            models.UniqueConstraint(
                fields=["muted_user", "course_id"],
                condition=models.Q(is_active=True, scope="course"),
                name="forum_unique_active_course_mute",
            ),
        ]

        indexes = [
            models.Index(fields=["muted_user", "course_id", "is_active"]),
            models.Index(fields=["muted_by", "course_id", "scope"]),
            models.Index(fields=["scope", "course_id", "is_active"]),
        ]

    def to_dict(self) -> dict[str, Any]:
        """Return a dictionary representation of the model."""
        return {
            "_id": str(self.pk),
            "muted_user_id": str(self.muted_user.pk),
            "muted_user_username": self.muted_user.username,
            "muter_id": str(self.muted_by.pk),
            "muted_by_username": self.muted_by.username,
            "unmuted_by_id": str(self.unmuted_by.pk) if self.unmuted_by else None,
            "unmuted_by_username": (
                self.unmuted_by.username if self.unmuted_by else None
            ),
            "course_id": self.course_id,
            "scope": self.scope,
            "reason": self.reason,
            "is_active": self.is_active,
            "created": self.created.isoformat() if self.created else None,
            "modified": self.modified.isoformat() if self.modified else None,
            "muted_at": self.muted_at.isoformat() if self.muted_at else None,
            "unmuted_at": self.unmuted_at.isoformat() if self.unmuted_at else None,
        }

    def clean(self) -> None:
        """Additional validation for mute records."""

        # Mutes cannot be self-applied
        if self.muted_by == self.muted_user:
            raise ValidationError("Users cannot mute themselves.")

    def __str__(self) -> str:
        return f"{self.muted_by} muted {self.muted_user} in {self.course_id} ({self.scope})"


class DiscussionMuteException(models.Model):
    """
    Per-user exception for course-wide mutes.
    Allows a specific user to unmute someone while the rest of the course remains muted.
    """

    muted_user: models.ForeignKey[User, User] = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="forum_mute_exceptions_for",
        help_text="User who is globally muted in this course",
        db_index=True,
    )
    exception_user: models.ForeignKey[User, User] = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="forum_mute_exceptions",
        help_text="User who unmuted the muted_user for themselves",
        db_index=True,
    )
    course_id: models.CharField[str, str] = models.CharField(
        max_length=255,
        help_text="Course where the exception applies",
        db_index=True,
    )
    created: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        auto_now_add=True
    )
    modified: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        app_label = "forum"
        db_table = "forum_discussion_mute_exception"
        unique_together = [["muted_user", "exception_user", "course_id"]]
        indexes = [
            models.Index(fields=["muted_user", "course_id"]),
            models.Index(fields=["exception_user", "course_id"]),
        ]

    def to_dict(self) -> dict[str, Any]:
        """Return a dictionary representation of the model."""
        return {
            "_id": str(self.pk),
            "muted_user_id": str(self.muted_user.pk),
            "muted_user_username": self.muted_user.username,
            "exception_user_id": str(self.exception_user.pk),
            "exception_user_username": self.exception_user.username,
            "course_id": self.course_id,
            "created": self.created.isoformat() if self.created else None,
            "modified": self.modified.isoformat() if self.modified else None,
        }

    def clean(self) -> None:
        """Ensure exception is only created if a course-wide mute is active."""

        has_coursewide_mute = DiscussionMuteRecord.objects.filter(
            muted_user=self.muted_user,
            course_id=self.course_id,
            scope=DiscussionMuteRecord.Scope.COURSE,
            is_active=True,
        ).exists()

        if not has_coursewide_mute:
            raise ValidationError(
                "Exception can only be created for an active course-wide mute."
            )
