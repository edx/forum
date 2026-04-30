"""
API Views for managing discussion bans.
"""

import logging
from typing import Any

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from forum.api.bans import ban_user, get_ban, get_banned_users, unban_user
from forum.backends.mysql.models import DiscussionBan
from forum.serializers.bans import (
    BannedUserResponseSerializer,
    BannedUsersListSerializer,
    BanUserSerializer,
    UnbanUserSerializer,
)
from forum.views.telemetry import (
    forum_error_type,
    set_custom_attribute,
    set_forum_trace_context,
    set_forum_trace_outcome,
)

User = get_user_model()
log = logging.getLogger(__name__)


def _get_request_value(data: Any, key: str) -> str:
    """Return request data value safely for telemetry context."""
    if not hasattr(data, "get"):
        return ""
    value = data.get(key)
    return str(value) if value is not None else ""


class BanUserAPIView(APIView):
    """
    API View to ban a user from discussions.

    Endpoint: POST /api/v2/users/bans

    Request Body:
        {
            "user_id": "123",
            "banned_by_id": "456",
            "scope": "course",  # or "organization"
            "course_id": "course-v1:edX+DemoX+Demo_Course",  # required for course scope
            "org_key": "edX",  # required for organization scope
            "reason": "Posting spam content"
        }

    Response:
        {
            "id": 1,
            "user": {"id": 123, "username": "learner", "email": "learner@example.com"},
            "course_id": "course-v1:edX+DemoX+Demo_Course",
            "org_key": "edX",
            "scope": "course",
            "reason": "Posting spam content",
            "is_active": true,
            "banned_at": "2024-01-15T10:30:00Z",
            "banned_by": {"id": 456, "username": "moderator"}
        }
    """

    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        """Ban a user from discussions."""
        request_data = request.data
        set_forum_trace_context(
            request,
            "moderation.ban_user",
            "user",
            entity_id=_get_request_value(request_data, "user_id"),
            course_id=_get_request_value(request_data, "course_id"),
            actor_id=_get_request_value(request_data, "banned_by_id"),
            data=request_data,
        )
        scope = _get_request_value(request_data, "scope")
        if scope:
            set_custom_attribute("forum.scope", scope)
        serializer = BanUserSerializer(data=request.data)

        if not serializer.is_valid():
            set_forum_trace_outcome(
                status.HTTP_400_BAD_REQUEST,
                "validation_error",
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            validated_data = serializer.validated_data.copy()
            # Convert user IDs to User objects
            user_id = validated_data.pop("user_id")
            banned_by_id = validated_data.pop("banned_by_id")
            user = User.objects.get(id=user_id)
            banned_by = User.objects.get(id=banned_by_id)

            ban_data = ban_user(user=user, banned_by=banned_by, **validated_data)
            set_custom_attribute("forum.entity_id", str(user_id))
            set_custom_attribute(
                "forum.course_id", str(ban_data.get("course_id") or "")
            )
            set_custom_attribute("forum.scope", str(ban_data.get("scope") or ""))
            set_forum_trace_outcome(status.HTTP_201_CREATED)
            return Response(ban_data, status=status.HTTP_201_CREATED)
        except (ValueError, TypeError) as e:
            set_forum_trace_outcome(
                status.HTTP_400_BAD_REQUEST,
                forum_error_type(e),
            )
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except User.DoesNotExist as error:
            set_forum_trace_outcome(
                status.HTTP_404_NOT_FOUND,
                forum_error_type(error),
            )
            return Response(
                {"error": "User not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            log.exception("Error banning user: %s", str(e))
            set_forum_trace_outcome(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                forum_error_type(e),
            )
            return Response(
                {"error": "Failed to ban user"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class UnbanUserAPIView(APIView):
    """
    API View to unban a user from discussions.

    Endpoint: POST /api/v2/users/bans/<ban_id>/unban

    Request Body:
        {
            "unbanned_by_id": "456",
            "course_id": "course-v1:edX+DemoX+Demo_Course",  # optional, for org-level ban exceptions
            "reason": "User appeal approved"
        }

    Response:
        {
            "status": "success",
            "message": "User learner unbanned successfully",
            "exception_created": false,
            "ban": {...},
            "exception": null
        }
    """

    permission_classes = (AllowAny,)

    def post(self, request: Request, ban_id: int) -> Response:
        """Unban a user from discussions."""
        request_data = request.data
        set_forum_trace_context(
            request,
            "moderation.unban_user",
            "user",
            course_id=_get_request_value(request_data, "course_id"),
            actor_id=_get_request_value(request_data, "unbanned_by_id"),
            data=request_data,
        )
        serializer = UnbanUserSerializer(data=request.data)

        if not serializer.is_valid():
            set_forum_trace_outcome(
                status.HTTP_400_BAD_REQUEST,
                "validation_error",
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            validated_data = serializer.validated_data.copy()
            # Convert unbanned_by_id to User object
            unbanned_by_id = validated_data.pop("unbanned_by_id")
            unbanned_by = User.objects.get(id=unbanned_by_id)

            unban_data = unban_user(
                ban_id=ban_id, unbanned_by=unbanned_by, **validated_data
            )
            ban_data = unban_data.get("ban") or {}
            user_data = ban_data.get("user") or {}
            set_custom_attribute("forum.entity_id", str(user_data.get("id", "")))
            set_custom_attribute(
                "forum.course_id", str(ban_data.get("course_id") or "")
            )
            set_custom_attribute("forum.scope", str(ban_data.get("scope") or ""))
            set_forum_trace_outcome(status.HTTP_200_OK)
            return Response(unban_data, status=status.HTTP_200_OK)
        except ValueError as e:
            if "not found" in str(e).lower():
                set_forum_trace_outcome(
                    status.HTTP_404_NOT_FOUND,
                    forum_error_type(e),
                )
                return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
            set_forum_trace_outcome(
                status.HTTP_400_BAD_REQUEST,
                forum_error_type(e),
            )
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except TypeError as e:
            set_forum_trace_outcome(
                status.HTTP_400_BAD_REQUEST,
                forum_error_type(e),
            )
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except DiscussionBan.DoesNotExist as error:
            set_forum_trace_outcome(
                status.HTTP_404_NOT_FOUND,
                forum_error_type(error),
            )
            return Response(
                {"error": f"Active ban with id {ban_id} not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except User.DoesNotExist as error:
            set_forum_trace_outcome(
                status.HTTP_404_NOT_FOUND,
                forum_error_type(error),
            )
            return Response(
                {"error": "Moderator user not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            log.exception("Error unbanning user: %s", str(e))
            set_forum_trace_outcome(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                forum_error_type(e),
            )
            return Response(
                {"error": "Failed to unban user"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class BannedUsersAPIView(APIView):
    """
    API View to list banned users.

    Endpoint: GET /api/v2/users/bans

    Query Parameters:
        - course_id (optional): Filter by course ID
        - org_key (optional): Filter by organization key
        - include_inactive (optional): Include inactive bans (default: false)

    Response:
        [
            {
                "id": 1,
                "user": {"id": 123, "username": "learner", "email": "learner@example.com"},
                "course_id": "course-v1:edX+DemoX+Demo_Course",
                "org_key": "edX",
                "scope": "course",
                "reason": "Posting spam content",
                "is_active": true,
                "banned_at": "2024-01-15T10:30:00Z",
                "banned_by": {"id": 456, "username": "moderator"},
                "unbanned_at": null,
                "unbanned_by": null
            }
        ]
    """

    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        """Get list of banned users."""
        request_params = request.query_params.dict()
        set_forum_trace_context(
            request,
            "moderation.list_banned_users",
            "user",
            course_id=request_params.get("course_id", ""),
            data=request_params,
        )
        if request_params.get("scope") is not None:
            set_custom_attribute("forum.scope", str(request_params.get("scope")))
        serializer = BannedUsersListSerializer(data=request.query_params)

        if not serializer.is_valid():
            set_forum_trace_outcome(
                status.HTTP_400_BAD_REQUEST,
                "validation_error",
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            banned_users = get_banned_users(**serializer.validated_data)
            response_serializer = BannedUserResponseSerializer(banned_users, many=True)
            set_forum_trace_outcome(status.HTTP_200_OK)
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        except (ValueError, TypeError) as e:
            set_forum_trace_outcome(
                status.HTTP_400_BAD_REQUEST,
                forum_error_type(e),
            )
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:  # pylint: disable=broad-exception-caught
            log.exception("Error fetching banned users: %s", str(e))
            set_forum_trace_outcome(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                forum_error_type(e),
            )
            return Response(
                {"error": "Failed to fetch banned users"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class BanDetailAPIView(APIView):
    """
    API View to get details of a specific ban.

    Endpoint: GET /api/v2/users/bans/<ban_id>

    Response:
        {
            "id": 1,
            "user": {"id": 123, "username": "learner", "email": "learner@example.com"},
            "course_id": "course-v1:edX+DemoX+Demo_Course",
            "org_key": "edX",
            "scope": "course",
            "reason": "Posting spam content",
            "is_active": true,
            "banned_at": "2024-01-15T10:30:00Z",
            "banned_by": {"id": 456, "username": "moderator"},
            "unbanned_at": null,
            "unbanned_by": null
        }
    """

    permission_classes = (AllowAny,)

    def get(self, request: Request, ban_id: int) -> Response:
        """Get details of a specific ban."""
        try:
            ban_data = get_ban(ban_id)
            if ban_data is None:
                return Response(
                    {"error": f"Ban with id {ban_id} not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            return Response(ban_data, status=status.HTTP_200_OK)
        except (ValueError, TypeError) as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:  # pylint: disable=broad-exception-caught
            log.exception("Error fetching ban details: %s", str(e))
            return Response(
                {"error": "Failed to fetch ban details"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
