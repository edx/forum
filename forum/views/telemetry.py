"""Telemetry helpers for native forum API views."""

from typing import Any, Optional

from django.core.exceptions import ObjectDoesNotExist
from rest_framework import status
from rest_framework.serializers import ValidationError

from forum.utils import ForumV2RequestError

try:
    from edx_django_utils.monitoring import (  # type: ignore[import-untyped]
        set_custom_attribute as _set_custom_attribute,
    )
except ImportError:  # pragma: no cover

    def _set_custom_attribute(*args: Any, **kwargs: Any) -> None:
        """No-op fallback when monitoring utils are unavailable."""
        return None


def set_custom_attribute(key: str, value: Any) -> None:
    """Set a Datadog custom attribute when monitoring is available."""
    _set_custom_attribute(key, value)


def _get_value(data: Optional[Any], key: str) -> str:
    """Return a string value from request/response data when available."""
    if not data or not hasattr(data, "get"):
        return ""
    value = data.get(key)
    return str(value) if value is not None else ""


def _get_actor_id(request: Any, data: Optional[Any] = None) -> str:
    """Return the best available actor id without changing request behavior."""
    actor_id = (
        _get_value(data, "user_id")
        or _get_value(data, "editing_user_id")
        or _get_value(data, "closing_user_id")
        or str(request.query_params.get("user_id", ""))
    )
    if actor_id:
        return actor_id
    return str(getattr(getattr(request, "user", None), "id", "") or "")


def set_forum_trace_context(
    request: Any,
    operation: str,
    entity_type: str,
    entity_id: str = "",
    course_id: str = "",
    actor_id: str = "",
    data: Optional[Any] = None,
) -> None:
    """Attach canonical request context for native forum API traces."""
    set_custom_attribute("forum.operation", operation)
    set_custom_attribute("forum.entity_type", entity_type)
    set_custom_attribute("forum.entity_id", str(entity_id or ""))
    set_custom_attribute(
        "forum.actor_id", str(actor_id or _get_actor_id(request, data))
    )
    set_custom_attribute(
        "forum.course_id", str(course_id or _get_value(data, "course_id"))
    )


def set_forum_thread_context(data: dict[str, Any]) -> None:
    """Attach thread-specific context after a native forum thread operation."""
    set_custom_attribute("forum.entity_id", _get_value(data, "id"))
    set_custom_attribute("forum.course_id", _get_value(data, "course_id"))
    set_custom_attribute(
        "forum.thread_type", _get_value(data, "thread_type") or _get_value(data, "type")
    )
    set_custom_attribute("forum.commentable_id", _get_value(data, "commentable_id"))
    if data.get("group_id") is not None:
        set_custom_attribute("forum.group_id", str(data.get("group_id")))


def set_forum_comment_context(data: dict[str, Any]) -> None:
    """Attach comment-specific context after a native forum comment operation."""
    set_custom_attribute("forum.entity_id", _get_value(data, "id"))
    set_custom_attribute("forum.course_id", _get_value(data, "course_id"))
    parent_id = _get_value(data, "parent_id")
    if parent_id:
        set_custom_attribute("forum.parent_comment_id", parent_id)


def set_forum_update_fields(data: Any) -> None:
    """Attach a stable comma-separated list of fields updated by a request."""
    if not hasattr(data, "items"):
        set_custom_attribute("forum.update_fields", "")
        return
    update_fields = sorted(key for key, value in data.items() if value is not None)
    set_custom_attribute("forum.update_fields", ",".join(update_fields))


def set_forum_trace_outcome(
    response_status: int, error_type: Optional[str] = None
) -> None:
    """Attach success/error outcome attributes for native forum API traces."""
    set_custom_attribute(
        "forum.result",
        "success" if int(response_status) < status.HTTP_400_BAD_REQUEST else "error",
    )
    set_custom_attribute("forum.http_status", str(response_status))
    if error_type:
        set_custom_attribute("forum.error_type", error_type)


def forum_error_type(exc: Exception) -> str:
    """Map native forum view failures to stable Datadog error types."""
    if isinstance(
        exc,
        (
            ForumV2RequestError,
            KeyError,
            ObjectDoesNotExist,
            TypeError,
            ValueError,
            ValidationError,
        ),
    ):
        return "validation_error"
    return "backend_error"
