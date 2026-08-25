"""
AI moderation backend for the edX XPert classifier.

This backend is edX specific: it exists so that the deployment which already
runs against XPert keeps doing so now that AI moderation itself is provider
agnostic. It is also the worked example of what a provider backend looks like --
see ``docs/how-tos/configure_ai_moderation.rst`` for writing your own.

XPert's dialect: it authorises on a ``client_id`` carried in the request body
rather than an ``Authorization`` header, it takes the prompt as a top level
``system_message``, and it answers with a list whose first element holds the
classifier JSON.
"""

import logging
from typing import Any, Dict, Optional

from django.conf import settings

from forum.ai_moderation.backends.base import HTTPModerationBackend

log = logging.getLogger(__name__)


class XPertModerationBackend(HTTPModerationBackend):
    """
    Classify content with the edX XPert API.

    Configured with::

        AI_MODERATION_API_URL      # e.g. https://xpert-api-services.../v1/message
        AI_MODERATION_CLIENT_ID
        AI_MODERATION_SYSTEM_MESSAGE
        AI_MODERATION_CONNECTION_TIMEOUT
        AI_MODERATION_READ_TIMEOUT
    """

    @property
    def client_id(self) -> Optional[str]:
        """XPert client the request is billed and authorised against."""
        return getattr(settings, "AI_MODERATION_CLIENT_ID", None)

    def classify(self, content: str) -> Optional[Dict[str, Any]]:
        """Classify content, returning the common moderation result."""
        headers = {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json",
            "user-agent": "Mozilla/5.0 (compatible; edX-Forum-AI-Moderation/1.0)",
        }

        payload: Dict[str, Any] = {
            "messages": [{"role": "user", "content": content}],
            "client_id": self.client_id,
            "system_message": self.system_message,
        }

        response_data = self.post(payload, headers)
        if response_data is None:
            return None

        message_content = self._extract_message_content(response_data)
        if message_content is None:
            return None

        return self.parse_moderation_payload(message_content, response_data)

    def _extract_message_content(self, response_data: Any) -> Optional[Any]:
        """Pull the classifier answer out of an XPert response."""
        if not isinstance(response_data, list):
            log.error(
                f"Expected list response from XPert API, got {type(response_data)}"
            )
            return None

        if len(response_data) == 0:
            log.error("Empty response list from XPert API")
            return None

        if not isinstance(response_data[0], dict):
            log.error(f"Expected dict in response list, got {type(response_data[0])}")
            return None

        return response_data[0].get("content", "")
