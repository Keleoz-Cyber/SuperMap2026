"""Thin SuperMap iServer REST client used by the publishing adapter.

Design rules (docs/supermap-integration.md):
- The browser never holds iServer admin credentials; this client runs only
  inside the FastAPI backend.
- Every call degrades gracefully: when iServer is down the client reports
  ``ok=False`` and an error string instead of raising, so modeling evidence
  is never rewritten by a publishing failure.
- Credentials come from environment variables and are never committed:
  ``GEOMODELING_ISERVER_ADMIN_USER`` / ``GEOMODELING_ISERVER_ADMIN_PASSWORD``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

DEFAULT_BASE_URL = "http://localhost:8090/iserver"
ENV_BASE_URL = "GEOMODELING_ISERVER_URL"
ENV_ADMIN_USER = "GEOMODELING_ISERVER_ADMIN_USER"
ENV_ADMIN_PASSWORD = "GEOMODELING_ISERVER_ADMIN_PASSWORD"


@dataclass
class ClientResponse:
    """Non-throwing HTTP result wrapper."""

    ok: bool
    status_code: int | None
    data: Any = None
    error: str | None = None


@dataclass
class IServerClient:
    """Minimal iServer REST client with optional admin token support."""

    base_url: str = DEFAULT_BASE_URL
    timeout: float = 10.0
    admin_user: str | None = None
    admin_password: str | None = None
    _token: str | None = field(default=None, repr=False)
    _http: httpx.Client | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, timeout: float = 10.0) -> "IServerClient":
        return cls(
            base_url=os.environ.get(ENV_BASE_URL, DEFAULT_BASE_URL).rstrip("/"),
            timeout=timeout,
            admin_user=os.environ.get(ENV_ADMIN_USER) or None,
            admin_password=os.environ.get(ENV_ADMIN_PASSWORD) or None,
        )

    @property
    def http(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=self.timeout)
        return self._http

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None

    # ------------------------------------------------------------------ auth
    def acquire_token(self, expiration_minutes: int = 120) -> ClientResponse:
        """Request an admin token; requires configured admin credentials."""

        if not self.admin_user or not self.admin_password:
            return ClientResponse(False, None, error="admin credentials not configured")
        try:
            resp = self.http.post(
                f"{self.base_url}/services/security/tokens.rjson",
                json={
                    "userName": self.admin_user,
                    "password": self.admin_password,
                    "clientType": "REQUESTIP",
                    "expiration": expiration_minutes,
                },
                headers={"Content-Type": "application/json"},
            )
        except httpx.HTTPError as exc:  # connection refused, timeout, ...
            return ClientResponse(False, None, error=f"{type(exc).__name__}: {exc}")
        if resp.status_code != 200:
            return ClientResponse(False, resp.status_code, error=resp.text[:300])
        token = resp.text.strip().strip('"')
        if not token:
            return ClientResponse(False, resp.status_code, error="empty token")
        self._token = token
        return ClientResponse(True, resp.status_code, data=token)

    def _with_token(self, url: str) -> str:
        if self._token:
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}token={self._token}"
        return url

    # ------------------------------------------------------------------ http
    def get_json(self, path: str, *, use_token: bool = False) -> ClientResponse:
        """GET ``{base_url}/{path}`` and parse JSON without raising."""

        url = f"{self.base_url}/{path.lstrip('/')}"
        if use_token:
            if self._token is None:
                result = self.acquire_token()
                if not result.ok:
                    return ClientResponse(False, result.status_code, error=result.error)
            url = self._with_token(url)
        try:
            resp = self.http.get(url)
        except httpx.HTTPError as exc:
            return ClientResponse(False, None, error=f"{type(exc).__name__}: {exc}")
        if resp.status_code != 200:
            return ClientResponse(False, resp.status_code, error=resp.text[:300])
        try:
            return ClientResponse(True, resp.status_code, data=resp.json())
        except ValueError:
            return ClientResponse(False, resp.status_code, error="invalid JSON body")


def encode_segment(value: str) -> str:
    """URL-encode one path segment (dataset/scene names contain Chinese)."""

    return quote(value, safe="")
