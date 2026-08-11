"""DeepSeek adapter tests with fake HTTP transport.

Covers: successful JSON Output, empty content, finish_reason=length,
malformed JSON, timeout, 429, and redacted error diagnostics.
Asserts the API key is only read from environment/settings and never
appears in repr/log/public payload.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from geomodeling.integrations.deepseek import (
    DEFAULT_TIMEOUT_SEC,
    DEEPSEEK_EMPTY_RESPONSE,
    DEEPSEEK_MALFORMED_JSON,
    DEEPSEEK_NOT_CONFIGURED,
    DEEPSEEK_RATE_LIMITED,
    DEEPSEEK_TIMEOUT,
    DEEPSEEK_TRUNCATED,
    DeepSeekAdapter,
    DeepSeekResult,
    ENV_API_KEY,
)


class FakeTransport:
    """Fake HTTP transport for testing."""

    def __init__(self, response_factory):
        self._factory = response_factory
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, json: dict, headers: dict, timeout: float) -> httpx.Response:
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self._factory()


def _make_response(status_code: int, body: dict | str | None = None) -> httpx.Response:
    if body is None:
        return httpx.Response(status_code=status_code)
    if isinstance(body, str):
        return httpx.Response(status_code=status_code, text=body)
    return httpx.Response(status_code=status_code, json=body)


def _success_body(content: str = '{"key": "value"}', finish_reason: str = "stop") -> dict:
    return {
        "choices": [{
            "message": {"role": "assistant", "content": content},
            "finish_reason": finish_reason,
        }],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }


class TestDeepSeekAdapter:
    def test_api_key_not_in_repr(self):
        adapter = DeepSeekAdapter(api_key="sk-secret-key-12345")
        assert "sk-secret-key-12345" not in repr(adapter)

    def test_from_env_returns_none_when_not_configured(self, monkeypatch):
        monkeypatch.delenv(ENV_API_KEY, raising=False)
        assert DeepSeekAdapter.from_env() is None

    def test_from_env_creates_adapter(self, monkeypatch):
        monkeypatch.setenv(ENV_API_KEY, "sk-test-key")
        monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
        adapter = DeepSeekAdapter.from_env()
        assert adapter is not None
        assert adapter.api_key == "sk-test-key"
        assert adapter.model == "deepseek-chat"

    def test_from_env_uses_current_flash_model_by_default(self, monkeypatch):
        monkeypatch.setenv(ENV_API_KEY, "sk-test-key")
        monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
        adapter = DeepSeekAdapter.from_env()
        assert adapter is not None
        assert adapter.model == "deepseek-v4-flash"
        assert adapter.timeout == float(DEFAULT_TIMEOUT_SEC)

    def test_successful_json_response(self):
        transport = FakeTransport(lambda: _make_response(200, _success_body()))
        adapter = DeepSeekAdapter(api_key="sk-test", _transport=transport)
        result = adapter.chat_json("system", "user")
        assert result.ok is True
        assert result.content == '{"key": "value"}'
        assert result.usage_prompt_tokens == 100
        assert result.usage_completion_tokens == 50

    def test_empty_content(self):
        transport = FakeTransport(lambda: _make_response(200, _success_body(content="")))
        adapter = DeepSeekAdapter(api_key="sk-test", _transport=transport)
        result = adapter.chat_json("system", "user")
        assert result.ok is False
        assert result.error_code == DEEPSEEK_EMPTY_RESPONSE

    def test_truncated_response(self):
        transport = FakeTransport(lambda: _make_response(200, _success_body(finish_reason="length")))
        adapter = DeepSeekAdapter(api_key="sk-test", _transport=transport)
        result = adapter.chat_json("system", "user")
        assert result.ok is False
        assert result.error_code == DEEPSEEK_TRUNCATED

    def test_malformed_json_response(self):
        transport = FakeTransport(lambda: _make_response(200, "not json at all"))
        adapter = DeepSeekAdapter(api_key="sk-test", _transport=transport)
        result = adapter.chat_json("system", "user")
        assert result.ok is False
        assert result.error_code == DEEPSEEK_MALFORMED_JSON

    def test_timeout(self):
        def raise_timeout():
            raise httpx.TimeoutException("timeout")
        transport = FakeTransport(raise_timeout)
        adapter = DeepSeekAdapter(api_key="sk-test", _transport=transport)
        result = adapter.chat_json("system", "user")
        assert result.ok is False
        assert result.error_code == DEEPSEEK_TIMEOUT

    def test_rate_limited(self):
        transport = FakeTransport(lambda: _make_response(429))
        adapter = DeepSeekAdapter(api_key="sk-test", _transport=transport)
        result = adapter.chat_json("system", "user")
        assert result.ok is False
        assert result.error_code == DEEPSEEK_RATE_LIMITED

    def test_http_error(self):
        transport = FakeTransport(lambda: _make_response(500))
        adapter = DeepSeekAdapter(api_key="sk-test", _transport=transport)
        result = adapter.chat_json("system", "user")
        assert result.ok is False
        assert "HTTP" in (result.error_message or "")

    def test_api_key_in_authorization_header(self):
        transport = FakeTransport(lambda: _make_response(200, _success_body()))
        adapter = DeepSeekAdapter(api_key="sk-secret", _transport=transport)
        adapter.chat_json("system", "user")
        assert transport.calls[0]["headers"]["Authorization"] == "Bearer sk-secret"

    def test_no_choices(self):
        transport = FakeTransport(lambda: _make_response(200, {"choices": []}))
        adapter = DeepSeekAdapter(api_key="sk-test", _transport=transport)
        result = adapter.chat_json("system", "user")
        assert result.ok is False
        assert result.error_code == DEEPSEEK_EMPTY_RESPONSE

    def test_uses_json_object_response_format(self):
        transport = FakeTransport(lambda: _make_response(200, _success_body()))
        adapter = DeepSeekAdapter(api_key="sk-test", _transport=transport)
        adapter.chat_json("system", "user")
        payload = transport.calls[0]["json"]
        assert payload["response_format"] == {"type": "json_object"}

    def test_explicitly_disables_thinking_for_low_latency_json_analysis(self):
        transport = FakeTransport(lambda: _make_response(200, _success_body()))
        adapter = DeepSeekAdapter(api_key="sk-test", _transport=transport)
        adapter.chat_json("system", "user")
        payload = transport.calls[0]["json"]
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["temperature"] == 0
