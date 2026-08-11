"""Server-only DeepSeek adapter over the OpenAI-compatible Chat Completions API.

Design rules (design §9.4):
- API Key is read ONLY from environment/settings; never appears in repr, log,
  public payload, or database.
- Uses ``response_format={"type":"json_object"}`` and requires JSON in the prompt.
- Handles empty content, finish_reason=length (truncation), malformed JSON,
  timeout, 429, and other HTTP errors with typed diagnostics.
- Supports a fake transport for CI (never calls the real API).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

ENV_API_KEY = "DEEPSEEK_API_KEY"
ENV_BASE_URL = "DEEPSEEK_BASE_URL"
ENV_MODEL = "DEEPSEEK_MODEL"
ENV_TIMEOUT_SEC = "DEEPSEEK_TIMEOUT_SEC"
ENV_MAX_TOKENS = "DEEPSEEK_MAX_TOKENS"

DEFAULT_BASE_URL = "https://api.deepseek.com"
# DeepSeek 官方 API 自 2026-07-24 起弃用 deepseek-chat；V4 Flash 的
# OpenAI-compatible 请求模型 ID 为 deepseek-v4-flash。
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_TIMEOUT_SEC = 90
DEFAULT_MAX_TOKENS = 4096

# Error codes
DEEPSEEK_NOT_CONFIGURED = "DEEPSEEK_NOT_CONFIGURED"
DEEPSEEK_TIMEOUT = "DEEPSEEK_TIMEOUT"
DEEPSEEK_RATE_LIMITED = "DEEPSEEK_RATE_LIMITED"
DEEPSEEK_HTTP_ERROR = "DEEPSEEK_HTTP_ERROR"
DEEPSEEK_EMPTY_RESPONSE = "DEEPSEEK_EMPTY_RESPONSE"
DEEPSEEK_TRUNCATED = "DEEPSEEK_TRUNCATED"
DEEPSEEK_MALFORMED_JSON = "DEEPSEEK_MALFORMED_JSON"


class HttpTransport(Protocol):
    """Provider-neutral HTTP transport protocol for testing."""

    def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str], timeout: float) -> httpx.Response:
        ...


@dataclass
class DeepSeekResult:
    """Typed result from a DeepSeek API call."""

    ok: bool
    content: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    usage_prompt_tokens: int | None = None
    usage_completion_tokens: int | None = None
    finish_reason: str | None = None


@dataclass
class DeepSeekAdapter:
    """OpenAI-compatible Chat Completions adapter for DeepSeek.

    The ``api_key`` is never included in ``repr()``, logs, or public payloads.
    Use ``from_env()`` to read configuration from environment variables.
    """

    api_key: str = field(repr=False)
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = float(DEFAULT_TIMEOUT_SEC)
    max_tokens: int = DEFAULT_MAX_TOKENS
    _transport: HttpTransport | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> "DeepSeekAdapter | None":
        """Create adapter from environment; return None if not configured."""
        api_key = os.environ.get(ENV_API_KEY, "").strip()
        if not api_key:
            return None
        return cls(
            api_key=api_key,
            base_url=os.environ.get(ENV_BASE_URL, DEFAULT_BASE_URL).rstrip("/"),
            model=os.environ.get(ENV_MODEL, DEFAULT_MODEL),
            timeout=float(os.environ.get(ENV_TIMEOUT_SEC, str(DEFAULT_TIMEOUT_SEC))),
            max_tokens=int(os.environ.get(ENV_MAX_TOKENS, str(DEFAULT_MAX_TOKENS))),
        )

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _do_post(self, url: str, payload: dict[str, Any]) -> httpx.Response:
        if self._transport is not None:
            return self._transport.post(
                url, json=payload, headers=self._headers, timeout=self.timeout,
            )
        with httpx.Client(timeout=self.timeout) as client:
            return client.post(url, json=payload, headers=self._headers)

    def chat_json(self, system_prompt: str, user_prompt: str) -> DeepSeekResult:
        """Send a JSON-mode chat completion request.

        Returns ``DeepSeekResult`` with ``ok=True`` and ``content`` on success,
        or ``ok=False`` and typed ``error_code`` on failure.
        """
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            # V4 defaults to thinking mode. This endpoint needs bounded-latency,
            # structured review output rather than exposed reasoning tokens.
            "thinking": {"type": "disabled"},
            "max_tokens": self.max_tokens,
        }

        try:
            resp = self._do_post(url, payload)
        except httpx.TimeoutException:
            return DeepSeekResult(ok=False, error_code=DEEPSEEK_TIMEOUT, error_message="请求超时")
        except httpx.HTTPError as exc:
            return DeepSeekResult(ok=False, error_code=DEEPSEEK_HTTP_ERROR, error_message="网络错误")

        if resp.status_code == 429:
            return DeepSeekResult(ok=False, error_code=DEEPSEEK_RATE_LIMITED, error_message="请求被限流")
        if resp.status_code != 200:
            return DeepSeekResult(
                ok=False,
                error_code=DEEPSEEK_HTTP_ERROR,
                error_message=f"HTTP {resp.status_code}",
            )

        try:
            body = resp.json()
        except Exception:
            return DeepSeekResult(ok=False, error_code=DEEPSEEK_MALFORMED_JSON, error_message="响应体非 JSON")

        choices = body.get("choices") or []
        if not choices:
            return DeepSeekResult(ok=False, error_code=DEEPSEEK_EMPTY_RESPONSE, error_message="无 choices")
        choice = choices[0]
        finish_reason = choice.get("finish_reason")
        content = choice.get("message", {}).get("content", "")

        if not content or not content.strip():
            return DeepSeekResult(ok=False, error_code=DEEPSEEK_EMPTY_RESPONSE, error_message="响应内容为空")

        if finish_reason == "length":
            return DeepSeekResult(
                ok=False,
                error_code=DEEPSEEK_TRUNCATED,
                error_message="响应被截断 (finish_reason=length)",
                finish_reason=finish_reason,
            )

        usage = body.get("usage", {})
        return DeepSeekResult(
            ok=True,
            content=content,
            usage_prompt_tokens=usage.get("prompt_tokens"),
            usage_completion_tokens=usage.get("completion_tokens"),
            finish_reason=finish_reason,
        )
