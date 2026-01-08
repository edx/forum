"""
Serializers for discussion ban operations.
"""

# mypy: ignore-errors

from rest_framework import serializers


class BanUserSerializer(serializers.Serializer):
    """
    Serializer for banning a user from discussions.
    """

    user_id = serializers.CharField(required=True, help_text="ID of the user to ban")

    def create(self, validated_data):
        """Not implemented - use API function instead."""
        raise NotImplementedError("Use ban_user() API function instead")

    def update(self, instance, validated_data):
        """Not implemented - bans are created, not updated."""
        raise NotImplementedError("Bans cannot be updated")

    banned_by_id = serializers.CharField(
        required=True, help_text="ID of the moderator performing the ban"
    )
    course_id = serializers.CharField(
        required=False, allow_null=True, help_text="Course ID for course-level bans"
    )
    org_key = serializers.CharField(
        required=False, allow_null=True, help_text="Organization key for org-level bans"
    )
    scope = serializers.ChoiceField(
        choices=["course", "organization"],
        default="course",
        help_text="Ban scope: 'course' or 'organization'",
    )
    reason = serializers.CharField(
        required=False, allow_blank=True, help_text="Reason for the ban (optional)"
    )

    def validate(self, attrs):
        """Validate that required fields are present based on scope."""
        scope = attrs.get("scope", "course")

        if scope == "course" and not attrs.get("course_id"):
            raise serializers.ValidationError(
                {"course_id": "course_id is required for course-level bans"}
            )

        if scope == "organization" and not attrs.get("org_key"):
            raise serializers.ValidationError(
                {"org_key": "org_key is required for organization-level bans"}
            )

        return attrs


class UnbanUserSerializer(serializers.Serializer):
    """
    Serializer for unbanning a user from discussions.
    """

    unbanned_by_id = serializers.CharField(
        required=True, help_text="ID of the moderator performing the unban"
    )

    def create(self, validated_data):
        """Not implemented - use API function instead."""
        raise NotImplementedError("Use unban_user() API function instead")

    def update(self, instance, validated_data):
        """Not implemented - use API function instead."""
        raise NotImplementedError("Use unban_user() API function instead")

    course_id = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Course ID for creating an exception to org-level ban",
    )
    reason = serializers.CharField(
        required=False, allow_blank=True, help_text="Reason for unbanning (optional)"
    )


class BannedUserResponseSerializer(serializers.Serializer):
    """
    Serializer for banned user data in responses (read-only).
    """

    id = serializers.IntegerField(read_only=True)

    def create(self, validated_data):
        """Not implemented - read-only serializer."""
        raise NotImplementedError("Read-only serializer")

    def update(self, instance, validated_data):
        """Not implemented - read-only serializer."""
        raise NotImplementedError("Read-only serializer")

    user = serializers.DictField(read_only=True)
    course_id = serializers.CharField(read_only=True, allow_null=True)
    org_key = serializers.CharField(read_only=True, allow_null=True)
    scope = serializers.CharField(read_only=True)
    reason = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    banned_at = serializers.DateTimeField(read_only=True, allow_null=True)
    banned_by = serializers.DictField(read_only=True, allow_null=True)
    unbanned_at = serializers.DateTimeField(read_only=True, allow_null=True)
    unbanned_by = serializers.DictField(read_only=True, allow_null=True)


class BannedUsersListSerializer(serializers.Serializer):
    """
    Serializer for listing banned users with filtering options (read-only).
    """

    course_id = serializers.CharField(
        required=False, allow_null=True, help_text="Filter by course ID"
    )
    org_key = serializers.CharField(
        required=False, allow_null=True, help_text="Filter by organization key"
    )
    include_inactive = serializers.BooleanField(
        default=False, help_text="Include inactive (unbanned) users"
    )

    def create(self, validated_data):
        """Not implemented - read-only serializer."""
        raise NotImplementedError("Read-only serializer")

    def update(self, instance, validated_data):
        """Not implemented - read-only serializer."""
        raise NotImplementedError("Read-only serializer")


class UnbanResponseSerializer(serializers.Serializer):
    """
    Serializer for unban operation response (read-only).
    """

    status = serializers.CharField(read_only=True)

    def create(self, validated_data):
        """Not implemented - read-only serializer."""
        raise NotImplementedError("Read-only serializer")

    def update(self, instance, validated_data):
        """Not implemented - read-only serializer."""
        raise NotImplementedError("Read-only serializer")

    message = serializers.CharField(read_only=True)
    exception_created = serializers.BooleanField(read_only=True)
    ban = BannedUserResponseSerializer(read_only=True)
    exception = serializers.DictField(read_only=True, allow_null=True)
