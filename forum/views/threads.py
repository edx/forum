"""Forum Threads API Views."""

import logging
from typing import Any

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from forum.api.threads import (
    create_thread,
    delete_thread,
    get_thread,
    get_user_threads,
    update_thread,
)
from forum.utils import ForumV2RequestError, str_to_bool
from forum.views.telemetry import (
    forum_error_type,
    set_custom_attribute,
    set_forum_thread_context,
    set_forum_trace_context,
    set_forum_trace_outcome,
    set_forum_update_fields,
)

log = logging.getLogger(__name__)


class ThreadsAPIView(APIView):
    """
    API view to handle operations related to threads.

    This view uses the CommentThread model for database interactions and the ThreadSerializer
    for serializing and deserializing data.
    """

    permission_classes = (AllowAny,)

    def get(self, request: Request, thread_id: str) -> Response:
        """
        Retrieve a thread by its ID.

        Args:
            request: The HTTP request object.
            thread_id: The ID of the thread to retrieve.

        Returns:
            Response: A Response object containing the serialized thread data or an error message.
        """
        params = request.query_params.dict()
        set_forum_trace_context(
            request,
            "thread.get",
            "thread",
            entity_id=thread_id,
            course_id=params.get("course_id", ""),
            data=params,
        )
        try:
            data = get_thread(thread_id, params)
        except ForumV2RequestError as error:
            set_forum_trace_outcome(
                status.HTTP_400_BAD_REQUEST,
                forum_error_type(error),
            )
            return Response(
                {"error": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        set_forum_thread_context(data)
        set_forum_trace_outcome(status.HTTP_200_OK)
        return Response(data, status=status.HTTP_200_OK)

    def delete(self, request: Request, thread_id: str) -> Response:
        """
        Deletes a thread by its ID.

        Parameters:
            request (Request): The incoming request.
            thread_id: The ID of the thread to be deleted.
        Body:
            Empty.
        Response:
            The details of the thread that is deleted.
        """
        set_forum_trace_context(request, "thread.delete", "thread", entity_id=thread_id)
        try:
            serialized_data = delete_thread(thread_id)
        except ForumV2RequestError as error:
            set_forum_trace_outcome(
                status.HTTP_400_BAD_REQUEST,
                forum_error_type(error),
            )
            return Response(
                {"error": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        set_forum_thread_context(serialized_data)
        set_custom_attribute("forum.delete_mode", "soft")
        set_forum_trace_outcome(status.HTTP_200_OK)
        return Response(serialized_data, status=status.HTTP_200_OK)

    def put(self, request: Request, thread_id: str) -> Response:
        """
        Updates an existing thread.

        Parameters:
            request (Request): The incoming request.
            thread_id: The ID of the thread to be edited.
        Body:
            fields to be updated.
        Response:
            The details of the thread that is updated.
        """

        request_data = request.data
        set_forum_trace_context(
            request,
            "thread.update",
            "thread",
            entity_id=thread_id,
            data=request_data,
        )
        set_forum_update_fields(request_data)
        try:
            serialized_data = update_thread(thread_id, **request_data)
        except ForumV2RequestError as error:
            set_forum_trace_outcome(
                status.HTTP_400_BAD_REQUEST,
                forum_error_type(error),
            )
            return Response(
                {"error": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        set_forum_thread_context(serialized_data)
        set_forum_trace_outcome(status.HTTP_200_OK)
        return Response(serialized_data, status=status.HTTP_200_OK)


class CreateThreadAPIView(APIView):
    """
    API view to create a new thread.

    This view uses the CommentThread model for database interactions and the ThreadSerializer
    for serializing and deserializing data.
    """

    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        """
        Create a new thread.

        Parameters:
            request (Request): The incoming request.
        Body:
            fields to be added in a new thread.
        Response:
            The details of the thread that is created.
        """

        params = request.data
        set_forum_trace_context(
            request,
            "thread.create",
            "thread",
            data=params,
        )
        try:
            if params.get("anonymous"):
                params["anonymous"] = str_to_bool(params["anonymous"])
            if params.get("anonymous_to_peers"):
                params["anonymous_to_peers"] = str_to_bool(params["anonymous_to_peers"])
            serialized_data = create_thread(**params)
        except (TypeError, ForumV2RequestError) as error:
            set_forum_trace_outcome(
                status.HTTP_400_BAD_REQUEST,
                forum_error_type(error),
            )
            return Response(
                {"error": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        set_forum_thread_context(serialized_data)
        set_forum_trace_outcome(status.HTTP_200_OK)
        return Response(serialized_data, status=status.HTTP_200_OK)


class UserThreadsAPIView(APIView):
    """
    API View for getting all threads of a course.

    This view provides an endpoint for retrieving all threads based on course id.
    """

    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        """
        Retrieve a course's threads.

        Args:
            request (HttpRequest): The HTTP request object.

        Returns:
            Response: A Response object with the threads data.

        Raises:
            HTTP_400_BAD_REQUEST: If the user does not exist.
        """
        try:
            params: dict[str, Any] = request.GET.dict()
            serialized_data = get_user_threads(**params)
            return Response(serialized_data, status=status.HTTP_200_OK)
        except (TypeError, ValueError, ForumV2RequestError) as error:
            return Response(
                {"error": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )
