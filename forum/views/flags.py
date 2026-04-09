"""Forum Flag API Views."""

from edx_django_utils.monitoring import set_custom_attribute
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from forum.api.flags import update_comment_flag, update_thread_flag
from forum.utils import ForumV2RequestError, str_to_bool


class CommentFlagAPIView(APIView):
    """
    API View for flagging/unflagging comments.

    Handles PUT requests to flag or unflag a comment.
    """

    permission_classes = (AllowAny,)

    def put(self, request: Request, comment_id: str, action: str) -> Response:
        """
        Flag or unflag a comment.

        Parameters:
        request (Request): The incoming request.
        comment_id (str): The ID of the comment to flag/unflag.
        action (str): The action to take (either "flag" or "unflag").

        Returns:
        Response: A response with the updated comment data.
        """
        set_custom_attribute("forum.operation", f"{action}_comment")
        set_custom_attribute("forum.comment_id", comment_id)
        set_custom_attribute("forum.action", action)

        request_data = request.data
        update_all = str_to_bool(request_data.get("all", False))
        user_id = request_data.get("user_id")
        if user_id:
            set_custom_attribute("forum.user_id", user_id)
        set_custom_attribute("forum.update_all", update_all)

        try:
            serializer_data = update_comment_flag(
                comment_id, action, user_id, update_all
            )
            return Response(serializer_data, status=status.HTTP_200_OK)
        except ForumV2RequestError as e:
            set_custom_attribute("forum.error_type", "ForumV2RequestError")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ThreadFlagAPIView(APIView):
    """
    API View for flagging/unflagging threads.

    Handles PUT requests to flag or unflag a thread.
    """

    permission_classes = (AllowAny,)

    def put(self, request: Request, thread_id: str, action: str) -> Response:
        """
        Flag or unflag a thread.

        Parameters:
        request (Request): The incoming request.
        thread_id (str): The ID of the thread to flag/unflag.
        action (str): The action to take (either "flag" or "unflag").

        Returns:
        Response: A response with the updated thread data.
        """
        set_custom_attribute("forum.operation", f"{action}_thread")
        set_custom_attribute("forum.thread_id", thread_id)
        set_custom_attribute("forum.action", action)

        request_data = request.data
        update_all = str_to_bool(request_data.get("all", False))
        user_id = request_data.get("user_id")
        if user_id:
            set_custom_attribute("forum.user_id", user_id)
        set_custom_attribute("forum.update_all", update_all)

        try:
            serializer_data = update_thread_flag(thread_id, action, user_id, update_all)
            return Response(serializer_data, status=status.HTTP_200_OK)
        except ForumV2RequestError as e:
            set_custom_attribute("forum.error_type", "ForumV2RequestError")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
