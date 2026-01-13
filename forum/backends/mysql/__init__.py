"""MySQL backend for forum v2."""

from forum.backends.mysql.models import Comment, CommentThread, Content

MODEL_INDICES: tuple[type[Content], ...] = (CommentThread, Comment)
