"""
Forum Mute / Unmute API Views.
"""

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from forum.api.mutes import (
    get_all_muted_users_for_course,
    get_user_mute_status,
    mute_and_report_user,
    mute_user,
    unmute_user,
)
from forum.backends.mysql.models import DiscussionMuteRecord
from forum.serializers.mute import (
    MuteAndReportInputSerializer,
    MuteInputSerializer,
    UnmuteInputSerializer,
    UserMuteStatusSerializer,
    CourseMutedUsersSerializer,
)
from forum.utils import ForumV2RequestError

log = logging.getLogger(__name__)


def _user_has_privileges(user: object) -> bool:
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True
    return (
        hasattr(user, "role_set")
        and user.role_set.exists()
        or hasattr(user, "courseaccessrole_set")
        and user.courseaccessrole_set.exists()
    )


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

            # Use serializer for validation
            data = request.data.copy()
            data["muter_id"] = muter_id
            serializer = MuteInputSerializer(data=data)
            serializer.is_valid(raise_exception=True)

            scope = serializer.validated_data["scope"]
            reason = serializer.validated_data["reason"]

            # Mute and report feature is only for regular learners
            is_privileged = _user_has_privileges(request.user)
            if is_privileged:
                return Response(
                    {
                        "error": (
                            "Mute and report feature is only available to regular learners, "
                            "not staff or privileged users"
                        )
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

            result = mute_user(
                muted_user_id=user_id,
                muter_id=muter_id,
                course_id=course_id,
                scope=scope,
                reason=reason,
                requester_is_privileged=is_privileged,
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
            # Current user performing the unmute
            current_user_id = (
                str(request.user.id) if hasattr(request.user, "id") else None
            )

            if not current_user_id:
                return Response(
                    {"error": "User must be authenticated"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            # Use serializer for validation
            data = request.data.copy()
            data["unmuted_by_id"] = current_user_id
            serializer = UnmuteInputSerializer(data=data)
            serializer.is_valid(raise_exception=True)

            original_muter_id = serializer.validated_data.get("muter_id")
            scope = serializer.validated_data["scope"]

            is_privileged = _user_has_privileges(request.user)

            # muter_id is required only for personal-scope unmutes
            if scope == "personal":
                if not original_muter_id:
                    return Response(
                        {"error": "muter_id is required for personal-scope unmutes"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Only the original muter can unmute a personal mute
                if str(original_muter_id) != str(current_user_id):
                    return Response(
                        {
                            "error": "Only the original muter can unmute a personal mute."
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )
            elif scope == "course":
                # Only privileged users can unmute course-wide mutes
                if not is_privileged:
                    return Response(
                        {
                            "error": "Only privileged users can unmute course-wide mutes."
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )

            result = unmute_user(
                muted_user_id=user_id,
                unmuted_by_id=current_user_id,
                course_id=course_id,
                scope=scope,
                muter_id=(original_muter_id if scope == "personal" else None),
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

            # Serialize the response
            serializer = UserMuteStatusSerializer(data=result)
            serializer.is_valid(raise_exception=True)

            return Response(serializer.validated_data, status=status.HTTP_200_OK)

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
            # Validate scope (accept 'all' as a special value for this endpoint)
            valid_scopes = [choice[0] for choice in DiscussionMuteRecord.Scope.choices] + [
                "all"
            ]
            if scope not in valid_scopes:
                return Response(
                    {
                        "error": f"Invalid scope '{scope}'. Must be one of: {valid_scopes}"
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Prevent learners from viewing course-wide mutes
            requester_is_privileged = _user_has_privileges(request.user)

            # Learners can only view their own personal mutes
            if not requester_is_privileged:
                scope = "personal"

            # Pass the requester's privilege status to the backend for filtering
            result = get_all_muted_users_for_course(
                course_id=course_id,
                requester_id=requester_id,
                scope=scope,
                requester_is_privileged=requester_is_privileged,
            )

            # Serialize the response
            serializer = CourseMutedUsersSerializer(data=result)
            serializer.is_valid(raise_exception=True)

            return Response(serializer.validated_data, status=status.HTTP_200_OK)

        except ForumV2RequestError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:  # pylint: disable=broad-exception-caught
            log.error(f"Unexpected error in get_all_muted_users_for_course: {str(e)}")
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
