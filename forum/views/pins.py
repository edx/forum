"""Forum Pin/Unpin thread API Views."""

import logging
from typing import Any

from edx_django_utils.monitoring import set_custom_attribute
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from forum.api import pin_thread, unpin_thread
from forum.utils import ForumV2RequestError

log = logging.getLogger(__name__)


class PinThreadAPIView(APIView):
    """
    API View to Pin thread.
    Handles PUT requests to pin a thread.
    """

    permission_classes = (AllowAny,)

    def put(self, request: Request, thread_id: str) -> Response:
        """
        Pins a thread.
        Parameters:
            request (Request): The incoming request.
            thread_id (str): The ID of the thread to pin.
        Body:
            user_id: requesting user's id
        Response:
            A response with the updated thread data.
        """
        set_custom_attribute("forum.operation", "pin_thread")
        set_custom_attribute("forum.thread_id", thread_id)

        user_id = request.data.get("user_id", "")
        if user_id:
            set_custom_attribute("forum.user_id", user_id)

        try:
            thread_data: dict[str, Any] = pin_thread(user_id, thread_id)
        except ForumV2RequestError as e:
            set_custom_attribute("forum.error_type", "ForumV2RequestError")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(thread_data, status=status.HTTP_200_OK)


class UnpinThreadAPIView(APIView):
    """
    API View to Unpin a thread.
    Handles PUT requests to unpin a thread.
    """

    permission_classes = (AllowAny,)

    def put(self, request: Request, thread_id: str) -> Response:
        """
        Unpins a thread.
        Parameters:
            request (Request): The incoming request.
            thread_id (str): The ID of the thread to unpin.
        Body:
            user_id: requesting user's id
        Response:
            A response with the updated thread data.
        """
        set_custom_attribute("forum.operation", "unpin_thread")
        set_custom_attribute("forum.thread_id", thread_id)

        user_id = request.data.get("user_id", "")
        if user_id:
            set_custom_attribute("forum.user_id", user_id)

        try:
            thread_data: dict[str, Any] = unpin_thread(user_id, thread_id)
        except ForumV2RequestError as e:
            set_custom_attribute("forum.error_type", "ForumV2RequestError")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(thread_data, status=status.HTTP_200_OK)
