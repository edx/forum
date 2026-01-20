"""MySQL backend for forum v2."""

from forum.backends.mysql.models import Content, CommentThread, Comment

MODEL_INDICES: tuple[type[Content], ...] = (CommentThread, Comment)
