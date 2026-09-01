"""
Serializer for the comment data.
"""

from typing import Any

from rest_framework import serializers

from forum.serializers.contents import ContentSerializer
from forum.serializers.custom_datetime import CustomDateTimeField
from forum.utils import prepare_comment_data_for_get_children


class EndorsementSerializer(serializers.Serializer[dict[str, Any]]):
    """
    Serializer for handling endorsement of a comment

    Attributes:
        user_id (str): The endorsement user id.
        time (datetime): The timestamp of when the user has endorsed the comment.
    """

    user_id = serializers.CharField()
    time = CustomDateTimeField()

    def create(self, validated_data: dict[str, Any]) -> Any:
        """Raise NotImplementedError"""
        raise NotImplementedError

    def update(self, instance: Any, validated_data: dict[str, Any]) -> Any:
        """Raise NotImplementedError"""
        raise NotImplementedError


class CommentSerializer(ContentSerializer):
    """
    Serializer for handling user comments on threads.

    Inherits from ContentSerializer.

    Attributes:
        endorsed (bool): Whether the comment is endorsed by an authority.
        depth (int): The depth of the comment in a nested comment structure.
        thread_id (str): The ID of the thread the comment belongs to.
        parent_id (str or None): The ID of the parent comment, if any.
        child_count (int): The number of child comments nested under this comment.
        sk (str or None): sk field, has ids data in it.
        endorsement: saves endorsement data.
    """

    endorsed = serializers.BooleanField(default=False)
    depth = serializers.IntegerField(default=0)
    thread_id = serializers.CharField(source="comment_thread_id")
    parent_id = serializers.CharField(default=None, allow_null=True)
    child_count = serializers.IntegerField(default=0)
    sk = serializers.CharField(default=None, required=False, allow_null=True)
    endorsement = EndorsementSerializer(default=None, required=False, allow_null=True)
    children = serializers.SerializerMethodField()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        exclude_fields = kwargs.pop("exclude_fields", None)
        self.backend = kwargs.pop("backend")
        super().__init__(*args, **kwargs)
        if exclude_fields:
            for field in exclude_fields:
                self.fields.pop(field, None)

    def get_children(self, obj: Any) -> list[dict[str, Any]]:
        """Get comments of a thread."""
        if not self.context.get("recursive", False):
            return []

        filter_kwargs: dict[str, Any] = {
            "parent_id": obj["_id"],
            "depth": 1,
            "sort": self.context.get("sort", -1),
        }
        if not self.context.get("show_deleted", False):
            filter_kwargs["is_deleted"] = False
        children = self.backend.get_comments(**filter_kwargs)
        children_data = prepare_comment_data_for_get_children(children)
        serializer = CommentSerializer(
            children_data,
            many=True,
            context={"recursive": False},
            exclude_fields=["sk"],
            backend=self.backend,
        )
        return list(serializer.data)

    def to_representation(self, instance: Any) -> dict[str, Any]:
        """Return comment representation."""
        comment = super().to_representation(instance)
        comment.pop("historical_abuse_flaggers")
        if comment["parent_id"] == "None":
            comment["parent_id"] = None
        return comment

    def create(self, validated_data: dict[str, Any]) -> Any:
        """Raise NotImplementedError"""
        raise NotImplementedError

    def update(self, instance: Any, validated_data: dict[str, Any]) -> Any:
        """Raise NotImplementedError"""
        raise NotImplementedError
