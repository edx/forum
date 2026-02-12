"""
Mongo Models
"""

from .comments import Comment
from .contents import BaseContents, Contents
from .subscriptions import Subscriptions
from .threads import CommentThread
from .users import Users

__all__ = [
    "BaseContents",
    "Comment",
    "Contents",
    "CommentThread",
    "Subscriptions",
    "Users",
    "MODEL_INDICES",
]

MODEL_INDICES: tuple[type[BaseContents], ...] = (CommentThread, Comment)
