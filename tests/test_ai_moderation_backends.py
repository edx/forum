"""Tests for the AI moderation backend interface and backend selection."""

# Fixtures are passed to tests by name, which pylint reads as shadowing; one
# applied only for its side effects reads as an unused argument.
# pylint: disable=redefined-outer-name,unused-argument

import os
import subprocess
import sys
from types import SimpleNamespace
from typing import Any, Dict, Generator, Optional
from unittest.mock import Mock, patch

import pytest
import requests
from django.conf import settings as django_settings
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from forum.ai_moderation.backends import BaseModerationBackend, HTTPModerationBackend
from forum.ai_moderation.backends.base import strip_code_fence
from forum.ai_moderation.backends.xpert import XPertModerationBackend
from forum.ai_moderation.defaults import (
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_READ_TIMEOUT,
    DEFAULT_SYSTEM_MESSAGE,
)
from forum.ai_moderation.service import AIModerationService
from forum.settings.common import plugin_settings

SPAM_PAYLOAD = (
    '{"classification": "spam_or_scam", "reasoning": "Spam detected", '
    '"confidence_score": 0.9}'
)

XPERT_BACKEND = "forum.ai_moderation.backends.xpert.XPertModerationBackend"


class StubProviderBackend(HTTPModerationBackend):
    """
    A provider backend written the way an Open edX operator would write one.

    It exists to prove the extension point works from outside forum: a class
    that subclasses HTTPModerationBackend, describes one provider's request and
    response, and is selected by dotted path. Its provider is imaginary -- a
    bearer-token JSON API answering ``{"verdict": {"text": "<classifier JSON>"}}``.
    """

    @property
    def api_key(self) -> Optional[str]:
        """Credential for the provider."""
        return getattr(django_settings, "AI_MODERATION_API_KEY", None)

    def classify(self, content: str) -> Optional[Dict[str, Any]]:
        """Classify content, returning the common moderation result."""
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response_data = self.post(
            {"prompt": self.system_message, "input": content}, headers
        )
        if response_data is None:
            return None

        return self.parse_moderation_payload(
            response_data.get("verdict", {}).get("text"), response_data
        )


@pytest.fixture
def xpert_settings() -> Generator[None, None, None]:
    """Configure the XPert backend."""
    with override_settings(
        AI_MODERATION_BACKEND=XPERT_BACKEND,
        AI_MODERATION_API_URL="http://xpert.example.com/v1/message",
        AI_MODERATION_CLIENT_ID="test-client-id",
        AI_MODERATION_SYSTEM_MESSAGE="classify this",
        AI_MODERATION_CONNECTION_TIMEOUT=0.5,
        AI_MODERATION_READ_TIMEOUT=20,
    ):
        yield


@pytest.fixture
def stub_provider_settings() -> Generator[None, None, None]:
    """Configure the out-of-tree stub provider backend."""
    with override_settings(
        AI_MODERATION_BACKEND=f"{StubProviderBackend.__module__}.StubProviderBackend",
        AI_MODERATION_API_URL="http://provider.example.com/v1/moderate",
        AI_MODERATION_API_KEY="test-api-key",
        AI_MODERATION_SYSTEM_MESSAGE="classify this",
        AI_MODERATION_CONNECTION_TIMEOUT=0.5,
        AI_MODERATION_READ_TIMEOUT=20,
    ):
        yield


def xpert_response(payload: str) -> Mock:
    """Build a mocked XPert response."""
    response = Mock()
    response.status_code = 200
    response.json.return_value = [{"content": payload}]
    return response


def stub_provider_response(payload: str) -> Mock:
    """Build a mocked response from the stub provider."""
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"verdict": {"text": payload}}
    return response


class TestBaseModerationBackend:
    """Tests for the backend interface itself."""

    def test_classify_is_not_implemented(self) -> None:
        """The interface carries no behaviour of its own."""
        with pytest.raises(NotImplementedError):
            BaseModerationBackend().classify("some content")

    def test_shipped_backend_implements_the_interface(self) -> None:
        """XPert is usable wherever a moderation backend is expected."""
        assert isinstance(XPertModerationBackend(), BaseModerationBackend)

    def test_http_base_reads_only_provider_neutral_settings(self) -> None:
        """
        The shared HTTP base has no opinion about credentials.

        Auth belongs to the subclass -- XPert puts a client_id in the body,
        another provider might send a bearer token or an x-api-key header.
        """
        assert not hasattr(HTTPModerationBackend, "api_key")

        with override_settings(
            AI_MODERATION_API_URL="http://provider.example.com",
            AI_MODERATION_SYSTEM_MESSAGE=None,
        ):
            backend = XPertModerationBackend()
            assert backend.api_url == "http://provider.example.com"
            assert backend.system_message == DEFAULT_SYSTEM_MESSAGE
            assert backend.timeout == (DEFAULT_CONNECTION_TIMEOUT, DEFAULT_READ_TIMEOUT)

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ('{"a": 1}', '{"a": 1}'),
            ('```json\n{"a": 1}\n```', '{"a": 1}'),
            ('```\n{"a": 1}\n```', '{"a": 1}'),
            ('  {"a": 1}  ', '{"a": 1}'),
        ],
    )
    def test_strip_code_fence(self, raw: str, expected: str) -> None:
        """Models routinely wrap their JSON answer in a Markdown fence."""
        assert strip_code_fence(raw) == expected


class TestPluginSettings:
    """
    Forum declares the AI moderation settings itself, through its plugin settings,
    so that no edx-platform change is needed to configure the feature.
    """

    def test_defaults_are_declared(self) -> None:
        """The settings a deployment must fill in are declared, and left empty."""
        site = SimpleNamespace(FEATURES={})
        plugin_settings(site)

        assert site.AI_MODERATION_SYSTEM_MESSAGE == DEFAULT_SYSTEM_MESSAGE
        assert site.AI_MODERATION_CONNECTION_TIMEOUT == DEFAULT_CONNECTION_TIMEOUT
        assert site.AI_MODERATION_READ_TIMEOUT == DEFAULT_READ_TIMEOUT

        # Nothing is guessed on a deployment's behalf -- least of all a provider.
        assert site.AI_MODERATION_BACKEND is None
        assert site.AI_MODERATION_API_URL is None
        assert site.AI_MODERATION_USER_ID is None

    def test_no_provider_specific_settings_are_declared(self) -> None:
        """
        Provider settings belong to the backend that reads them.

        Declaring, say, a bearer token here would bake one provider's auth
        scheme into the generic layer.
        """
        site = SimpleNamespace(FEATURES={})
        plugin_settings(site)

        assert not hasattr(site, "AI_MODERATION_API_KEY")
        assert not hasattr(site, "AI_MODERATION_MODEL")
        assert not hasattr(site, "AI_MODERATION_CLIENT_ID")

    def test_configured_values_are_never_overridden(self) -> None:
        """
        Plugin settings are applied after a deployment's own configuration is
        read, so a site that already chose XPert keeps it.
        """
        site = SimpleNamespace(
            FEATURES={},
            AI_MODERATION_BACKEND=XPERT_BACKEND,
            AI_MODERATION_API_URL="https://xpert.example.com/v1/message",
            AI_MODERATION_SYSTEM_MESSAGE="the deployed prompt",
            AI_MODERATION_CONNECTION_TIMEOUT=0.5,
            AI_MODERATION_READ_TIMEOUT=20,
            AI_MODERATION_USER_ID=758316,
        )
        plugin_settings(site)

        assert site.AI_MODERATION_BACKEND == XPERT_BACKEND
        assert site.AI_MODERATION_API_URL == "https://xpert.example.com/v1/message"
        assert site.AI_MODERATION_SYSTEM_MESSAGE == "the deployed prompt"
        assert site.AI_MODERATION_CONNECTION_TIMEOUT == 0.5
        assert site.AI_MODERATION_READ_TIMEOUT == 20
        assert site.AI_MODERATION_USER_ID == 758316

    def test_settings_module_imports_before_apps_are_ready(self) -> None:
        """
        Plugin settings are imported while Django settings are still being
        assembled, so nothing on that path may reach a Django model. A fresh
        interpreter is the only honest way to check: this process has long since
        imported the service.
        """
        result = subprocess.run(
            [sys.executable, "-c", "import forum.settings.common"],
            env={**os.environ, "DJANGO_SETTINGS_MODULE": "forum.settings.test"},
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr


class TestBackendSelection:
    """Tests for choosing a backend with AI_MODERATION_BACKEND."""

    def test_no_provider_is_shipped_by_default(self) -> None:
        """
        Forum defines the interface and no provider, so an unconfigured
        deployment is told exactly what to set.
        """
        service = AIModerationService()
        with override_settings(AI_MODERATION_BACKEND=None):
            with pytest.raises(ImproperlyConfigured) as excinfo:
                _ = service.moderation_backend

        assert "AI_MODERATION_BACKEND" in str(excinfo.value)
        assert "BaseModerationBackend" in str(excinfo.value)

    def test_configured_backend_is_loaded(self, xpert_settings: None) -> None:
        """The configured dotted path decides which provider is used."""
        service = AIModerationService()
        assert isinstance(service.moderation_backend, XPertModerationBackend)

    def test_out_of_tree_backend_is_loaded(self, stub_provider_settings: None) -> None:
        """A backend that does not ship with forum plugs in the same way."""
        service = AIModerationService()
        assert isinstance(service.moderation_backend, StubProviderBackend)

    def test_backend_is_reloaded_when_the_setting_changes(
        self, xpert_settings: None
    ) -> None:
        """The cached backend does not outlive the setting that chose it."""
        service = AIModerationService()
        assert isinstance(service.moderation_backend, XPertModerationBackend)

        with override_settings(
            AI_MODERATION_BACKEND=(
                f"{StubProviderBackend.__module__}.StubProviderBackend"
            )
        ):
            assert isinstance(service.moderation_backend, StubProviderBackend)

        assert isinstance(service.moderation_backend, XPertModerationBackend)

    def test_unimportable_backend_reports_a_clear_error(self) -> None:
        """A typo in AI_MODERATION_BACKEND says exactly what is wrong."""
        service = AIModerationService()
        with override_settings(AI_MODERATION_BACKEND="forum.nope.NoSuchBackend"):
            with pytest.raises(ImproperlyConfigured) as excinfo:
                _ = service.moderation_backend

        assert "AI_MODERATION_BACKEND" in str(excinfo.value)
        assert "forum.nope.NoSuchBackend" in str(excinfo.value)

    def test_backend_must_implement_the_interface(self) -> None:
        """Pointing the setting at some other class is a configuration error."""
        service = AIModerationService()
        with override_settings(
            AI_MODERATION_BACKEND="forum.ai_moderation.service.AIModerationService"
        ):
            with pytest.raises(ImproperlyConfigured) as excinfo:
                _ = service.moderation_backend

        assert "BaseModerationBackend" in str(excinfo.value)

    @pytest.mark.parametrize("backend_path", [None, "forum.nope.NoSuchBackend"])
    def test_misconfiguration_does_not_break_moderation(
        self, backend_path: Optional[str]
    ) -> None:
        """Unset or wrong, a configuration error is logged, not raised at the caller."""
        service = AIModerationService()
        classify = service._classify  # pylint: disable=protected-access
        with override_settings(AI_MODERATION_BACKEND=backend_path):
            assert classify("content") is None


class TestXPertModerationBackend:
    """Tests for the edX-specific XPert backend."""

    def test_request_format(self, xpert_settings: None) -> None:
        """XPert authorises on client_id and takes the prompt at the top level."""
        with patch(
            "requests.post", return_value=xpert_response(SPAM_PAYLOAD)
        ) as mock_post:
            XPertModerationBackend().classify("check me")

        args, kwargs = mock_post.call_args
        assert args[0] == "http://xpert.example.com/v1/message"
        assert "Authorization" not in kwargs["headers"]
        assert kwargs["timeout"] == (0.5, 20)
        assert kwargs["json"] == {
            "messages": [{"role": "user", "content": "check me"}],
            "client_id": "test-client-id",
            "system_message": "classify this",
        }

    def test_response_is_normalized(self, xpert_settings: None) -> None:
        """The first element's content holds the classifier JSON."""
        raw = xpert_response(SPAM_PAYLOAD)
        with patch("requests.post", return_value=raw):
            result = XPertModerationBackend().classify("check me")

        assert result is not None
        assert result["classification"] == "spam_or_scam"
        assert result["reasoning"] == "Spam detected"
        assert result["confidence_score"] == 0.9
        assert result["full_api_response"] == raw.json.return_value

    def test_default_system_message_is_used_when_unset(self) -> None:
        """Standing up a backend does not also mean writing a prompt."""
        with override_settings(
            AI_MODERATION_API_URL="http://xpert.example.com/v1/message",
            AI_MODERATION_SYSTEM_MESSAGE=None,
        ), patch(
            "requests.post", return_value=xpert_response(SPAM_PAYLOAD)
        ) as mock_post:
            XPertModerationBackend().classify("check me")

        assert mock_post.call_args.kwargs["json"]["system_message"] == (
            DEFAULT_SYSTEM_MESSAGE
        )

    def test_missing_api_url_is_a_configuration_error(self) -> None:
        """No endpoint means no request at all."""
        with override_settings(AI_MODERATION_API_URL=None), patch(
            "requests.post"
        ) as mock_post:
            assert XPertModerationBackend().classify("check me") is None

        mock_post.assert_not_called()

    @pytest.mark.parametrize(
        "body",
        [
            {},
            [],
            ["not a dict"],
            [{}],
            [{"content": "not json"}],
            [{"content": "[1, 2, 3]"}],
        ],
    )
    def test_unusable_responses_return_none(
        self, body: Any, xpert_settings: None
    ) -> None:
        """Anything that is not a parsable verdict fails closed."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = body

        with patch("requests.post", return_value=response):
            assert XPertModerationBackend().classify("check me") is None

    def test_request_failure_returns_none(self, xpert_settings: None) -> None:
        """A network failure degrades moderation instead of raising."""
        with patch("requests.post", side_effect=requests.ConnectionError("refused")):
            assert XPertModerationBackend().classify("check me") is None

    def test_timeout_returns_none(self, xpert_settings: None) -> None:
        """A slow classifier degrades moderation instead of raising."""
        with patch("requests.post", side_effect=requests.Timeout("too slow")):
            assert XPertModerationBackend().classify("check me") is None

    def test_http_error_returns_none(self, xpert_settings: None) -> None:
        """A non-2xx answer degrades moderation instead of raising."""
        failed = requests.Response()
        failed.status_code = 500
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError(
            "500", response=failed
        )

        with patch("requests.post", return_value=response):
            assert XPertModerationBackend().classify("check me") is None


class TestCustomProviderBackend:
    """
    Tests for what an operator gets from the shared HTTP base.

    These exercise StubProviderBackend, whose only provider-specific code is the
    request body, the auth header and where the verdict lives in the response.
    Everything else -- timeouts, error handling, fence stripping, normalization
    -- is inherited.
    """

    def test_request_format(self, stub_provider_settings: None) -> None:
        """The backend decides its own body and its own auth scheme."""
        with patch(
            "requests.post", return_value=stub_provider_response(SPAM_PAYLOAD)
        ) as mock_post:
            StubProviderBackend().classify("check me")

        args, kwargs = mock_post.call_args
        assert args[0] == "http://provider.example.com/v1/moderate"
        assert kwargs["headers"]["Authorization"] == "Bearer test-api-key"
        assert kwargs["timeout"] == (0.5, 20)
        assert kwargs["json"] == {"prompt": "classify this", "input": "check me"}

    def test_response_is_normalized(self, stub_provider_settings: None) -> None:
        """A verdict from anywhere in the response reaches the common result."""
        raw = stub_provider_response(SPAM_PAYLOAD)
        with patch("requests.post", return_value=raw):
            result = StubProviderBackend().classify("check me")

        assert result is not None
        assert result["classification"] == "spam_or_scam"
        assert result["reasoning"] == "Spam detected"
        assert result["confidence_score"] == 0.9
        assert result["full_api_response"] == raw.json.return_value

    def test_fenced_response_is_parsed(self, stub_provider_settings: None) -> None:
        """A JSON answer wrapped in a Markdown fence is still understood."""
        fenced = f"```json\n{SPAM_PAYLOAD}\n```"
        with patch("requests.post", return_value=stub_provider_response(fenced)):
            result = StubProviderBackend().classify("check me")

        assert result is not None
        assert result["classification"] == "spam_or_scam"

    def test_extra_keys_are_preserved(self, stub_provider_settings: None) -> None:
        """Anything else the classifier returned is kept for the audit log."""
        payload = '{"classification": "not_spam", "categories": ["none"]}'
        with patch("requests.post", return_value=stub_provider_response(payload)):
            result = StubProviderBackend().classify("check me")

        assert result is not None
        assert result["categories"] == ["none"]
        assert result["confidence_score"] is None

    def test_request_failure_returns_none(self, stub_provider_settings: None) -> None:
        """Error handling is inherited, not reimplemented per provider."""
        with patch("requests.post", side_effect=requests.ConnectionError("refused")):
            assert StubProviderBackend().classify("check me") is None
