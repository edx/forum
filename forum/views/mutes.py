"""
Forum Mute / Unmute API Views.
"""

import logging
from typing import Any, Dict

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from opaque_keys.edx.keys import CourseKey

from forum.api.mutes import (
    get_all_muted_users_for_course,
    get_user_mute_status,
    mute_and_report_user,
    mute_user,
    unmute_user,
)
from forum.backends.mysql.models import DiscussionMute
from forum.serializers.mute import MuteAndReportInputSerializer
from forum.utils import ForumV2RequestError

log = logging.getLogger(__name__)


def _validate_scope(scope: str) -> Dict[str, Any]:
    """
    Validate mute scope parameter.

    Args:
        scope (str): The scope value to validate.

    Returns:
        Dict[str, Any]: Error response dict if invalid, empty dict if valid.
    """
    valid_scopes = [choice[0] for choice in DiscussionMute.Scope.choices]
    if scope not in valid_scopes:
        return {
            "error": f"Invalid scope '{scope}'. Must be one of: {', '.join(valid_scopes)}",
            "status": status.HTTP_400_BAD_REQUEST,
        }
    return {}


class MuteUserAPIView(APIView):
    """
    API View for muting users in discussions.

    Handles POST requests to mute a user.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, user_id: str, course_id: str) -> Response:
        """
        Mute a user in discussions.

        Parameters:
            request (Request): The incoming request.
            user_id (str): The ID of the user to mute.
            course_id (str): The course ID.

        Body:
            scope: Mute scope ('personal' or 'course')
            reason: Optional reason for muting

        Returns:
            Response: A response with the mute operation result.
        """
        try:
            # Derive muter_id from authenticated user
            muter_id = str(request.user.id) if hasattr(request.user, "id") else None
            if not muter_id:
                return Response(
                    {"error": "User must be authenticated"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            scope = request.data.get("scope", "personal")
            reason = request.data.get("reason", "")

            # Validate scope parameter
            scope_error = _validate_scope(scope)
            if scope_error:
                return Response(
                    {"error": scope_error["error"]},
                    status=scope_error["status"],
                )

            # Only privileged users can create course-wide mutes
            user_is_staff = getattr(request.user, "is_staff", False)
            if scope == "course" and not user_is_staff:
                return Response(
                    {"error": "Only privileged users can create course-wide mutes"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            result = mute_user(
                muted_user_id=user_id,
                muter_id=muter_id,
                course_id=course_id,
                scope=scope,
                reason=reason,
            )

            return Response(result, status=status.HTTP_200_OK)

        except ForumV2RequestError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:  # pylint: disable=broad-exception-caught
            log.error(f"Unexpected error in mute_user: {str(e)}")
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class UnmuteUserAPIView(APIView):
    """
    API View for unmuting users in discussions.

    Handles POST requests to unmute a user.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, user_id: str, course_id: str) -> Response:
        """
        Unmute a user in discussions.

        Parameters:
            request (Request): The incoming request.
            user_id (str): The ID of the user to unmute.
            course_id (str): The course ID.

        Body:
            muter_id: ID of the original user who muted this user (required for personal scope only)
            scope: Unmute scope ('personal' or 'course')

        Returns:
            Response: A response with the unmute operation result.
        """
        try:
            original_muter_id = request.data.get(
                "muter_id"
            )  # Who originally muted the user
            scope = request.data.get("scope", "personal")
            # Current user performing the unmute
            current_user_id = (
                str(request.user.id) if hasattr(request.user, "id") else None
            )

            if not current_user_id:
                return Response(
                    {"error": "User must be authenticated"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            # Validate scope parameter
            scope_error = _validate_scope(scope)
            if scope_error:
                return Response(
                    {"error": scope_error["error"]},
                    status=scope_error["status"],
                )

            # muter_id is required only for personal-scope unmutes
            if scope == "personal" and not original_muter_id:
                return Response(
                    {"error": "muter_id is required for personal-scope unmutes"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # For course-scope unmutes, forbid muter_id if provided
            if scope == "course" and original_muter_id:
                return Response(
                    {
                        "error": "muter_id should not be provided for course-scope unmutes"
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            result = unmute_user(
                muted_user_id=user_id,
                unmuted_by_id=current_user_id,  # Current user performing unmute
                course_id=course_id,
                scope=scope,
                muter_id=(
                    original_muter_id if scope == "personal" else None
                ),  # Only for personal mutes
            )

            return Response(result, status=status.HTTP_200_OK)

        except ForumV2RequestError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:  # pylint: disable=broad-exception-caught
            log.error(f"Unexpected error in unmute_user: {str(e)}")
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MuteAndReportUserAPIView(APIView):
    """
    API View for muting and reporting users in discussions.

    Handles POST requests to mute and report a user.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, user_id: str, course_id: str) -> Response:
        """
        Mute and report a user in discussions.

        Parameters:
            request (Request): The incoming request.
            user_id (str): The ID of the user to mute and report.
            course_id (str): The course ID.

        Body:
            scope: Mute scope ('personal' or 'course')
            reason: Reason for muting and reporting

        Returns:
            Response: A response with the mute and report operation result.
        """
        try:
            serializer = MuteAndReportInputSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            # Derive muter_id from authenticated user
            muter_id = str(request.user.id) if hasattr(request.user, "id") else None
            if not muter_id:
                return Response(
                    {"error": "User must be authenticated"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            scope = serializer.validated_data["scope"]
            reason = serializer.validated_data["reason"]

            # Only staff can create course-wide mutes
            user_is_staff = getattr(request.user, "is_staff", False)
            if scope == "course" and not user_is_staff:
                return Response(
                    {"error": "Only staff can create course-wide mutes"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            result = mute_and_report_user(
                muted_user_id=user_id,
                muter_id=muter_id,
                course_id=course_id,
                scope=scope,
                reason=reason,
            )

            return Response(result, status=status.HTTP_200_OK)

        except ForumV2RequestError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:  # pylint: disable=broad-exception-caught
            log.error(f"Unexpected error in mute_and_report_user: {str(e)}")
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class UserMuteStatusAPIView(APIView):
    """
    API View for getting user mute status.

    Handles GET requests to check if a user is muted.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, user_id: str, course_id: str) -> Response:
        """
        Get mute status for a user.

        Parameters:
            request (Request): The incoming request.
            user_id (str): The ID of the user to check.
            course_id (str): The course ID.

        Returns:
            Response: A response with the user's mute status.

        Note:
            viewer_id is always derived from the authenticated user.
            Any viewer_id in query params will be rejected if it doesn't match.
        """
        try:
            # Derive viewer_id from authenticated user
            viewer_id = str(request.user.id) if hasattr(request.user, "id") else None
            if not viewer_id:
                return Response(
                    {"error": "User must be authenticated"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            # Reject any attempt to override viewer_id via query params
            requested_viewer_id = request.query_params.get("viewer_id")
            if requested_viewer_id and requested_viewer_id != viewer_id:
                return Response(
                    {"error": "Cannot query mute status as a different user"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            result = get_user_mute_status(
                user_id=user_id,
                course_id=course_id,
                viewer_id=viewer_id,
            )

            return Response(result, status=status.HTTP_200_OK)

        except ForumV2RequestError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:  # pylint: disable=broad-exception-caught
            log.error(f"Unexpected error in get_user_mute_status: {str(e)}")
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class CourseMutedUsersAPIView(APIView):
    """
    API View for getting all muted users in a course.

    Handles GET requests to get course-wide muted users list.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, course_id: str) -> Response:
        """
        Get all muted users in a course.

        Parameters:
            request (Request): The incoming request.
            course_id (str): The course ID.

        Query Parameters:
            scope: Filter by scope ('personal', 'course', or 'all') - learners limited to 'personal'

        Returns:
            Response: A response with the course muted users list.
        """
        try:
            # Force requester_id to authenticated user
            requester_id = str(request.user.id) if hasattr(request.user, "id") else None
            if not requester_id:
                return Response(
                    {"error": "User must be authenticated"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            scope = request.query_params.get("scope", "all")

            # Validate scope parameter
            scope_error = _validate_scope(scope)
            if scope_error:
                return Response(
                    {"error": scope_error["error"]},
                    status=scope_error["status"],
                )

            # Use is_staff as the privilege indicator for forum service
            try:
                # Validate course_id format
                CourseKey.from_string(course_id)
                requester_is_privileged = getattr(request.user, "is_staff", False)
            except Exception:  # pylint: disable=broad-except
                # If we can't determine course key, use is_staff as fallback
                requester_is_privileged = getattr(request.user, "is_staff", False)

            # Learners can only view their own personal mutes
            # Privileged users can view course-wide mutes and all scopes
            if not requester_is_privileged:
                # For learners, force scope to "personal" and filter to their own mutes only
                scope = "personal"

            # Pass the requester's privilege status to the backend for filtering
            result = get_all_muted_users_for_course(
                course_id=course_id,
                requester_id=requester_id,
                scope=scope,
                requester_is_staff=requester_is_privileged,
            )

            return Response(result, status=status.HTTP_200_OK)

        except ForumV2RequestError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:  # pylint: disable=broad-exception-caught
            log.error(f"Unexpected error in get_all_muted_users_for_course: {str(e)}")
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
