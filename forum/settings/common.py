"""
Common settings for forum app.
"""

from typing import Any


def plugin_settings(settings: Any) -> None:
    """
    Common settings for forum app
    """
    # Search backend
    if getattr(settings, "MEILISEARCH_ENABLED", False):
        settings.FORUM_SEARCH_BACKEND = getattr(
            settings,
            "FORUM_SEARCH_BACKEND",
            "forum.search.meilisearch.MeilisearchBackend",
        )
    else:
        settings.FORUM_SEARCH_BACKEND = getattr(
            settings, "FORUM_SEARCH_BACKEND", "forum.search.es.ElasticsearchBackend"
        )
        settings.FORUM_ELASTIC_SEARCH_CONFIG = getattr(
            settings, "FORUM_ELASTIC_SEARCH_CONFIG", [{"host": "elasticsearch"}]
        )

    # Unfortunately we can't copy settings from edx-platform because tutor patches have
    # not been applied yet
    settings.FORUM_MONGODB_DATABASE = getattr(
        settings, "FORUM_MONGODB_DATABASE", "cs_comments_service"
    )
    settings.FORUM_MONGODB_CLIENT_PARAMETERS = getattr(
        settings, "FORUM_MONGODB_CLIENT_PARAMETERS", {"host": "mongodb"}
    )

    # Enable forum service
    if "ENABLE_DISCUSSION_SERVICE" not in settings.FEATURES:
        settings.FEATURES["ENABLE_DISCUSSION_SERVICE"] = True

    # URL prefix must match the regex in the url_config of the plugin app
    settings.COMMENTS_SERVICE_URL = getattr(
        settings, "COMMENTS_SERVICE_URL", "http://localhost:8000/forum"
    )

    # Timezone-awareness is required for mysql fields
    settings.USE_TZ = getattr(settings, "USE_TZ", True)

    # AI Moderation settings
    settings.AI_MODERATION_API_URL = getattr(settings, "AI_MODERATION_API_URL", None)
    settings.AI_MODERATION_CLIENT_ID = getattr(
        settings, "AI_MODERATION_CLIENT_ID", None
    )
    settings.AI_MODERATION_SYSTEM_MESSAGE = getattr(
        settings, "AI_MODERATION_SYSTEM_MESSAGE", None
    )
    settings.AI_MODERATION_CONNECTION_TIMEOUT = getattr(
        settings, "AI_MODERATION_CONNECTION_TIMEOUT", 30
    )
    settings.AI_MODERATION_READ_TIMEOUT = getattr(
        settings, "AI_MODERATION_READ_TIMEOUT", 30
    )
    settings.AI_MODERATION_USER_ID = getattr(settings, "AI_MODERATION_USER_ID", None)
