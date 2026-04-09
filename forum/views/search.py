"""
Search API Views
"""

from typing import Any

from edx_django_utils.monitoring import set_custom_attribute
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from forum.api.search import search_threads
from forum.constants import FORUM_DEFAULT_PAGE, FORUM_DEFAULT_PER_PAGE
from forum.utils import get_commentable_ids_from_params, get_group_ids_from_params


class SearchThreadsView(APIView):
    """
    A view that handles the search and retrieval of threads based on query parameters.

    This view provides a `GET` endpoint that allows searching for threads with various filtering,
    sorting, and pagination options. It also supports suggesting corrected search text if no results
    are found with the initial query.
    """

    permission_classes = (AllowAny,)

    def _validate_and_extract_params(self, request: Request) -> dict[str, Any]:
        """
        Validate and extract query parameters from the request.
        """
        data = request.query_params
        params: dict[str, Any] = {}

        # Required parameters
        text = data.get("text")
        if not text:
            raise ValueError("text is required")
        params["text"] = text

        # Sort key validation
        VALID_SORT_KEYS = ("activity", "comments", "date", "votes")
        sort_key = data.get("sort_key", "date")
        if sort_key not in VALID_SORT_KEYS:
            raise ValueError("invalid sort_key")
        params["sort_key"] = sort_key

        # Pagination handling
        page = data.get("page", FORUM_DEFAULT_PAGE)
        try:
            params["page"] = int(page)
        except ValueError as exc:
            raise ValueError("Invalid page value.") from exc

        per_page = data.get("per_page", FORUM_DEFAULT_PER_PAGE)
        try:
            params["per_page"] = int(per_page)
        except ValueError as exc:
            raise ValueError("Invalid per_page value.") from exc

        # Optional parameters with default values and type conversion
        params["context"] = data.get("context", "course")
        params["user_id"] = data.get("user_id", "")
        params["course_id"] = data.get("course_id", "")
        params["author_id"] = data.get("author_id")
        params["thread_type"] = data.get("thread_type")
        params["flagged"] = data.get("flagged", "false").lower() == "true"
        params["unread"] = data.get("unread", "false").lower() == "true"
        params["unanswered"] = data.get("unanswered", "false").lower() == "true"
        params["unresponded"] = data.get("unresponded", "false").lower() == "true"
        params["count_flagged"] = data.get("count_flagged", "false").lower() == "true"

        # Group IDs extraction
        params["group_ids"] = get_group_ids_from_params(data)

        params["commentable_ids"] = get_commentable_ids_from_params(data)

        return params

    def get(self, request: Request) -> Response:
        """
        Handle GET requests to search for threads based on query parameters.

        Args:
            request (Request): The Django request object containing query parameters.

        Returns:
            Response: A JSON response containing the search results, corrected text (if any), and total results.
        """
        set_custom_attribute("forum.operation", "search_threads")

        try:
            params: dict[str, Any] = self._validate_and_extract_params(request)
        except ValueError as error:
            set_custom_attribute("forum.error_type", "ValueError")
            set_custom_attribute("forum.error_message", str(error))
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        # Track search parameters
        set_custom_attribute("forum.search_text", params.get("text", ""))
        set_custom_attribute("forum.sort_key", params.get("sort_key", "date"))
        if params.get("course_id"):
            set_custom_attribute("forum.course_id", params["course_id"])
        if params.get("user_id"):
            set_custom_attribute("forum.user_id", params["user_id"])
        if params.get("author_id"):
            set_custom_attribute("forum.author_id", params["author_id"])
        if params.get("thread_type"):
            set_custom_attribute("forum.thread_type", params["thread_type"])
        set_custom_attribute("forum.flagged", params.get("flagged", False))
        set_custom_attribute("forum.unread", params.get("unread", False))
        set_custom_attribute("forum.unanswered", params.get("unanswered", False))
        set_custom_attribute("forum.page", str(params.get("page", 1)))
        set_custom_attribute("forum.per_page", str(params.get("per_page", 20)))

        search_threads_data = search_threads(**params)

        return Response(search_threads_data)
