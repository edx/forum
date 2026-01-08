"""
Forum Mute / Unmute API Views.
"""

import logging
from typing import Any

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from forum.models import (
    DiscussionMute,
    DiscussionMuteException,
    ModerationAuditLog,
)
from forum.serializers.mute import (
    MuteInputSerializer,
    UnmuteInputSerializer,
    UserMuteStatusSerializer, CourseMutedUsersSerializer,
)
from forum.utils import ForumV2RequestError
from forum.api.mutes import (
    mute_user,
    unmute_user,
    mute_and_report_user,
    get_user_mute_status,
    get_all_muted_users_for_course,
)

log = logging.getLogger(__name__)



class MuteUserAPIView(APIView):
    """
    API View for muting users in discussions.
    
    Handles POST requests to mute a user.
    """
    
    permission_classes = (AllowAny,)
    
    def post(self, request: Request, user_id: str, course_id: str) -> Response:
        """
        Mute a user in discussions.
        
        Parameters:
            request (Request): The incoming request.
            user_id (str): The ID of the user to mute.
            course_id (str): The course ID.
            
        Body:
            muter_id: ID of user performing the mute
            scope: Mute scope ('personal' or 'course')
            reason: Optional reason for muting
            
        Returns:
            Response: A response with the mute operation result.
        """
        try:
            muter_id = request.data.get("muter_id")
            scope = request.data.get("scope", "personal")
            reason = request.data.get("reason", "")
            
            if not muter_id:
                return Response(
                    {"error": "muter_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            
            result = mute_user(
                muted_user_id=user_id,
                muted_by_id=muter_id,
                course_id=course_id,
                scope=scope,
                reason=reason,
            )
            
            return Response(result, status=status.HTTP_200_OK)
        
        except ForumV2RequestError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            log.error(f"Unexpected error in mute_user: {str(e)}")
            return Response(
                {"error": "Internal server error"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UnmuteUserAPIView(APIView):
    """
    API View for unmuting users in discussions.
    
    Handles POST requests to unmute a user.
    """
    
    permission_classes = (AllowAny,)
    
    def post(self, request: Request, user_id: str, course_id: str) -> Response:
        """
        Unmute a user in discussions.
        
        Parameters:
            request (Request): The incoming request.
            user_id (str): The ID of the user to unmute.
            course_id (str): The course ID.
            
        Body:
            muter_id: ID of user performing the unmute
            scope: Unmute scope ('personal' or 'course')
            muted_by_id: Optional - for personal scope unmutes
            
        Returns:
            Response: A response with the unmute operation result.
        """
        try:
            muter_id = request.data.get("muter_id")
            scope = request.data.get("scope", "personal")
            muted_by_id = request.data.get("muted_by_id")
            
            if not muter_id:
                return Response(
                    {"error": "moderator_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            
            result = unmute_user(
                muted_user_id=user_id,
                unmuted_by_id=moderator_id,
                course_id=course_id,
                scope=scope,
                muted_by_id=muted_by_id,
            )
            
            return Response(result, status=status.HTTP_200_OK)
        
        except ForumV2RequestError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            log.error(f"Unexpected error in unmute_user: {str(e)}")
            return Response(
                {"error": "Internal server error"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class MuteAndReportUserAPIView(APIView):
    """
    API View for muting and reporting users in discussions.
    
    Handles POST requests to mute and report a user.
    """
    
    permission_classes = (AllowAny,)
    
    def post(self, request: Request, user_id: str, course_id: str) -> Response:
        """
        Mute and report a user in discussions.
        
        Parameters:
            request (Request): The incoming request.
            user_id (str): The ID of the user to mute and report.
            course_id (str): The course ID.
            
        Body:
            muter_id: ID of user performing the action
            scope: Mute scope ('personal' or 'course')
            reason: Reason for muting and reporting
            
        Returns:
            Response: A response with the mute and report operation result.
        """
        try:
            muter_id = request.data.get("muter_id")
            scope = request.data.get("scope", "personal")
            reason = request.data.get("reason", "")
            
            if not muter_id:
                return Response(
                    {"error": "muter_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            
            result = mute_and_report_user(
                muted_user_id=user_id,
                muted_by_id=moderator_id,
                course_id=course_id,
                scope=scope,
                reason=reason,
            )
            
            return Response(result, status=status.HTTP_200_OK)
        
        except ForumV2RequestError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            log.error(f"Unexpected error in mute_and_report_user: {str(e)}")
            return Response(
                {"error": "Internal server error"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UserMuteStatusAPIView(APIView):
    """
    API View for getting user mute status.
    
    Handles GET requests to check if a user is muted.
    """
    
    permission_classes = (AllowAny,)
    
    def get(self, request: Request, user_id: str, course_id: str) -> Response:
        """
        Get mute status for a user.
        
        Parameters:
            request (Request): The incoming request.
            user_id (str): The ID of the user to check.
            course_id (str): The course ID.
            
        Query Parameters:
            viewer_id: ID of the user checking the status
            
        Returns:
            Response: A response with the user's mute status.
        """
        try:
            viewer_id = request.query_params.get("viewer_id")
            
            if not viewer_id:
                return Response(
                    {"error": "viewer_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            
            result = get_user_mute_status(
                user_id=user_id,
                course_id=course_id,
                viewer_id=viewer_id,
            )
            
            return Response(result, status=status.HTTP_200_OK)
        
        except ForumV2RequestError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            log.error(f"Unexpected error in get_user_mute_status: {str(e)}")
            return Response(
                {"error": "Internal server error"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class CourseMutedUsersAPIView(APIView):
    """
    API View for getting all muted users in a course.
    
    Handles GET requests to get course-wide muted users list.
    """
    
    permission_classes = (AllowAny,)
    
    def get(self, request: Request, course_id: str) -> Response:
        """
        Get all muted users in a course.
        
        Parameters:
            request (Request): The incoming request.
            course_id (str): The course ID.
            
        Query Parameters:
            muter_id: ID of user requesting the list
            scope: Filter by scope ('personal', 'course', or 'all')
            requester_id: Optional ID of requesting user
            
        Returns:
            Response: A response with the course muted users list.
        """
        try:
            requester_id = request.query_params.get("requester_id")
            scope = request.query_params.get("scope", "all")
            
            result = get_all_muted_users_for_course(
                course_id=course_id,
                requester_id=requester_id,
                scope=scope,
            )
            
            return Response(result, status=status.HTTP_200_OK)
        
        except ForumV2RequestError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            log.error(f"Unexpected error in get_all_muted_users_for_course: {str(e)}")
            return Response(
                {"error": "Internal server error"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
