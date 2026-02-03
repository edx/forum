"""
Forum Mute/Unmute Serializers.
"""

from typing import Any, Dict

from rest_framework import serializers

from forum.models import DiscussionMute, DiscussionMuteException


class MuteInputSerializer(serializers.Serializer[Dict[str, Any]]):
    """Serializer for mute input data."""

    muter_id = serializers.CharField(
        required=True, help_text="ID of user performing the mute action"
    )
    scope = serializers.ChoiceField(
        choices=DiscussionMute.Scope.choices,
        default=DiscussionMute.Scope.PERSONAL,
        help_text="Scope of the mute (personal or course-wide)",
    )
    reason = serializers.CharField(
        required=False, allow_blank=True, help_text="Optional reason for muting"
    )

    def create(self, validated_data: Dict[str, Any]) -> Any:
        """Not used for input serializers."""
        raise NotImplementedError("Input serializers do not support create operations")

    def update(self, instance: Any, validated_data: Dict[str, Any]) -> Any:
        """Not used for input serializers."""
        raise NotImplementedError("Input serializers do not support update operations")


class UnmuteInputSerializer(serializers.Serializer[Dict[str, Any]]):
    """Serializer for unmute input data."""

    unmuted_by_id = serializers.CharField(
        required=True, help_text="ID of user performing the unmute action"
    )
    scope = serializers.ChoiceField(
        choices=DiscussionMute.Scope.choices,
        default=DiscussionMute.Scope.PERSONAL,
        help_text="Scope of the unmute (personal or course-wide)",
    )
    muter_id = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Original muter ID (for personal scope unmutes)",
    )

    def create(self, validated_data: Dict[str, Any]) -> Any:
        """Not used for input serializers."""
        raise NotImplementedError("Input serializers do not support create operations")

    def update(self, instance: Any, validated_data: Dict[str, Any]) -> Any:
        """Not used for input serializers."""
        raise NotImplementedError("Input serializers do not support update operations")


class MuteAndReportInputSerializer(serializers.Serializer[Dict[str, Any]]):
    """Serializer for mute and report input data."""

    muter_id = serializers.CharField(
        required=True, help_text="ID of user performing the mute and report action"
    )
    scope = serializers.ChoiceField(
        choices=DiscussionMute.Scope.choices,
        default=DiscussionMute.Scope.PERSONAL,
        help_text="Scope of the mute (personal or course-wide)",
    )
    reason = serializers.CharField(
        required=True,
        help_text="Reason for muting and reporting (required for reports)",
    )

    def create(self, validated_data: Dict[str, Any]) -> Any:
        """Not used for input serializers."""
        raise NotImplementedError("Input serializers do not support create operations")

    def update(self, instance: Any, validated_data: Dict[str, Any]) -> Any:
        """Not used for input serializers."""
        raise NotImplementedError("Input serializers do not support update operations")


class UserMuteStatusSerializer(serializers.Serializer[Dict[str, Any]]):
    """Serializer for user mute status response."""

    user_id = serializers.CharField(help_text="ID of the user being checked")
    course_id = serializers.CharField(help_text="Course ID")
    is_muted = serializers.BooleanField(help_text="Whether the user is muted")
    mute_scope = serializers.CharField(
        allow_null=True,
        help_text="Scope of active mute (personal/course/null if not muted)",
    )
    muter_id = serializers.CharField(
        allow_null=True, help_text="ID of user who muted this user (for personal mutes)"
    )
    muted_by_username = serializers.CharField(
        allow_null=True, help_text="Username of user who muted this user"
    )
    muted_at = serializers.DateTimeField(
        allow_null=True, help_text="When the user was muted"
    )
    reason = serializers.CharField(allow_null=True, help_text="Reason for muting")
    has_exception = serializers.BooleanField(
        default=False, help_text="Whether viewer has an exception for course-wide mutes"
    )

    def create(self, validated_data: Dict[str, Any]) -> Any:
        """Not used for response serializers."""
        raise NotImplementedError(
            "Response serializers do not support create operations"
        )

    def update(self, instance: Any, validated_data: Dict[str, Any]) -> Any:
        """Not used for response serializers."""
        raise NotImplementedError(
            "Response serializers do not support update operations"
        )


class MutedUserSerializer(serializers.Serializer[Dict[str, Any]]):
    """Serializer for a muted user entry."""

    user_id = serializers.CharField(help_text="ID of the muted user")
    username = serializers.CharField(help_text="Username of the muted user")
    muter_id = serializers.CharField(help_text="ID of user who performed the mute")
    muted_by_username = serializers.CharField(
        help_text="Username of user who performed the mute"
    )
    scope = serializers.CharField(help_text="Mute scope (personal or course)")
    reason = serializers.CharField(help_text="Reason for muting")
    muted_at = serializers.DateTimeField(help_text="When the user was muted")
    is_active = serializers.BooleanField(
        help_text="Whether the mute is currently active"
    )

    def create(self, validated_data: Dict[str, Any]) -> Any:
        """Not used for response serializers."""
        raise NotImplementedError(
            "Response serializers do not support create operations"
        )

    def update(self, instance: Any, validated_data: Dict[str, Any]) -> Any:
        """Not used for response serializers."""
        raise NotImplementedError(
            "Response serializers do not support update operations"
        )


class CourseMutedUsersSerializer(serializers.Serializer[Dict[str, Any]]):
    """Serializer for course-wide muted users list response."""

    course_id = serializers.CharField(help_text="Course ID")
    requester_id = serializers.CharField(
        allow_null=True, help_text="ID of user requesting the list"
    )
    scope_filter = serializers.CharField(help_text="Applied scope filter")
    total_count = serializers.IntegerField(help_text="Total number of muted users")
    muted_users = MutedUserSerializer(many=True, help_text="List of muted users")

    def create(self, validated_data: Dict[str, Any]) -> Any:
        """Not used for response serializers."""
        raise NotImplementedError(
            "Response serializers do not support create operations"
        )

    def update(self, instance: Any, validated_data: Dict[str, Any]) -> Any:
        """Not used for response serializers."""
        raise NotImplementedError(
            "Response serializers do not support update operations"
        )


class DiscussionMuteSerializer(serializers.ModelSerializer[DiscussionMute]):
    """Serializer for DiscussionMute model."""

    muted_user_id = serializers.CharField(source="muted_user.pk", read_only=True)
    muted_user_username = serializers.CharField(
        source="muted_user.username", read_only=True
    )
    muter_id = serializers.CharField(source="muted_by.pk", read_only=True)
    muted_by_username = serializers.CharField(
        source="muted_by.username", read_only=True
    )
    unmuted_by_id = serializers.CharField(
        source="unmuted_by.pk", read_only=True, allow_null=True
    )
    unmuted_by_username = serializers.CharField(
        source="unmuted_by.username", read_only=True, allow_null=True
    )

    class Meta:
        model = DiscussionMute
        fields = [
            "id",
            "muted_user_id",
            "muted_user_username",
            "muter_id",
            "muted_by_username",
            "unmuted_by_id",
            "unmuted_by_username",
            "course_id",
            "scope",
            "reason",
            "is_active",
            "created",
            "modified",
            "muted_at",
            "unmuted_at",
        ]
        read_only_fields = ["id", "created", "modified", "muted_at", "unmuted_at"]


class DiscussionMuteExceptionSerializer(
    serializers.ModelSerializer[DiscussionMuteException]
):
    """Serializer for DiscussionMuteException model."""

    muted_user_id = serializers.CharField(source="muted_user.pk", read_only=True)
    muted_user_username = serializers.CharField(
        source="muted_user.username", read_only=True
    )
    exception_user_id = serializers.CharField(
        source="exception_user.pk", read_only=True
    )
    exception_user_username = serializers.CharField(
        source="exception_user.username", read_only=True
    )

    class Meta:
        model = DiscussionMuteException
        fields = [
            "id",
            "muted_user_id",
            "muted_user_username",
            "exception_user_id",
            "exception_user_username",
            "course_id",
            "created",
            "modified",
        ]
        read_only_fields = ["id", "created", "modified"]
