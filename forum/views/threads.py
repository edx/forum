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
    get_thread,
    get_user_threads,
    update_thread,
)
from forum.utils import ForumV2RequestError, str_to_bool

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
        try:
            params = request.query_params.dict()
            data = get_thread(thread_id, params)
        except ForumV2RequestError as error:
            return Response(
                {"error": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(data, status=status.HTTP_200_OK)

    def delete(self, request: Request, thread_id: str) -> Response:
        """
        Soft deletes a thread by its ID.

        Parameters:
            request (Request): The incoming request.
            thread_id: The ID of the thread to be deleted.
        Body:
            Empty.
        Response:
            The details of the thread that is deleted.
        """
        try:
            # Use soft delete instead of hard delete
            from forum.api.threads import soft_delete_thread
            user_id = request.data.get('user_id') or getattr(request.user, 'id', None)
            course_id = request.data.get('course_id')
            serialized_data = soft_delete_thread(thread_id, user_id, course_id)
            return Response(serialized_data, status=status.HTTP_200_OK)
        except ForumV2RequestError as error:
            return Response(
                {"error": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

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

        try:
            serialized_data = update_thread(thread_id, **request.data)
            return Response(serialized_data, status=status.HTTP_200_OK)
        except ForumV2RequestError as error:
            return Response(
                {"error": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )


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

        try:
            params = request.data
            if params.get("anonymous"):
                params["anonymous"] = str_to_bool(params["anonymous"])
            if params.get("anonymous_to_peers"):
                params["anonymous_to_peers"] = str_to_bool(params["anonymous_to_peers"])
            serialized_data = create_thread(**params)
            return Response(serialized_data, status=status.HTTP_200_OK)
        except (TypeError, ForumV2RequestError) as error:
            return Response(
                {"error": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )


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


class SoftDeleteThreadAPIView(APIView):
    """API view for soft delete operations on threads."""

    permission_classes = (AllowAny,)

    def post(self, request: Request, thread_id: str) -> Response:
        """
        Soft delete a thread.

        Args:
            request: The HTTP request object.
            thread_id: The ID of the thread to soft delete.

        Returns:
            Response: A Response object containing the updated thread data or an error message.
        """
        try:
            user_id = request.data.get("user_id")
            if not user_id:
                return Response(
                    {"error": "user_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            course_id = request.data.get("course_id")
            from forum.api.threads import soft_delete_thread
            data = soft_delete_thread(thread_id, user_id, course_id)
            return Response(data, status=status.HTTP_200_OK)
        except ForumV2RequestError as error:
            return Response(
                {"error": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def delete(self, request: Request, thread_id: str) -> Response:
        """
        Restore a soft deleted thread.

        Args:
            request: The HTTP request object.
            thread_id: The ID of the thread to restore.

        Returns:
            Response: A Response object containing the restored thread data or an error message.
        """
        try:
            course_id = request.GET.get("course_id")
            from forum.api.threads import restore_thread
            data = restore_thread(thread_id, course_id)
            return Response(data, status=status.HTTP_200_OK)
        except ForumV2RequestError as error:
            return Response(
                {"error": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )


class BulkSoftDeleteThreadsAPIView(APIView):
    """API view for bulk soft delete operations on threads."""

    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        """
        Bulk soft delete threads.

        Args:
            request: The HTTP request object containing thread_ids and user_id.

        Returns:
            Response: A Response object containing operation results.
        """
        try:
            thread_ids = request.data.get("thread_ids", [])
            user_id = request.data.get("user_id")
            course_id = request.data.get("course_id")

            if not thread_ids:
                return Response(
                    {"error": "thread_ids list is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not user_id:
                return Response(
                    {"error": "user_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            from forum.api.threads import bulk_soft_delete_threads
            data = bulk_soft_delete_threads(thread_ids, user_id, course_id)
            return Response(data, status=status.HTTP_200_OK)
        except ForumV2RequestError as error:
            return Response(
                {"error": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def delete(self, request: Request) -> Response:
        """
        Bulk restore soft deleted threads.

        Args:
            request: The HTTP request object containing thread_ids.

        Returns:
            Response: A Response object containing operation results.
        """
        try:
            thread_ids = request.data.get("thread_ids", [])
            course_id = request.data.get("course_id")

            if not thread_ids:
                return Response(
                    {"error": "thread_ids list is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            from forum.api.threads import bulk_restore_threads
            data = bulk_restore_threads(thread_ids, course_id)
            return Response(data, status=status.HTTP_200_OK)
        except ForumV2RequestError as error:
            return Response(
                {"error": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )


class DeletedThreadsAPIView(APIView):
    """API view for retrieving soft deleted threads."""

    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        """
        Get soft deleted threads for a course.

        Args:
            request: The HTTP request object.

        Returns:
            Response: A Response object containing the deleted threads data.
        """
        try:
            params = request.query_params.dict()
            course_id = params.get("course_id")
            
            if not course_id:
                return Response(
                    {"error": "course_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            from forum.api.threads import get_deleted_threads
            data = get_deleted_threads(
                course_id=course_id,
                user_id=params.get("user_id"),
                resp_skip=int(params.get("resp_skip", 0)),
                resp_limit=int(params.get("resp_limit")) if params.get("resp_limit") else None,
                sort_key=params.get("sort_key"),
            )
            return Response(data, status=status.HTTP_200_OK)
        except (ValueError, ForumV2RequestError) as error:
            return Response(
                {"error": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )
