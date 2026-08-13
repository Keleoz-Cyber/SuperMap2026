from __future__ import annotations

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from geomodeling.api.routes import ai_settings
from geomodeling.integrations.deepseek_credentials import (
    DeepSeekSettingsService,
    InMemoryCredentialStore,
)
from geomodeling.platform.errors import PlatformError, platform_error_handler


def make_client(handler) -> tuple[TestClient, InMemoryCredentialStore]:
    store = InMemoryCredentialStore()
    service = DeepSeekSettingsService(store=store, http_handler=handler)
    app = FastAPI()
    app.add_exception_handler(PlatformError, platform_error_handler)
    app.include_router(ai_settings.router)
    app.dependency_overrides[ai_settings.get_ai_settings_service] = lambda: service
    return TestClient(app), store


def test_settings_status_is_redacted_and_save_is_immediately_active():
    client, _ = make_client(lambda request: httpx.Response(200, json={"data": []}))

    assert client.get("/api/settings/ai").json()["configured"] is False
    response = client.post("/api/settings/ai", json={"api_key": "sk-user-secret"})

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["source"] == "windows_credential"
    assert "api_key" not in body
    assert "sk-user-secret" not in response.text


def test_connection_test_uses_supplied_secret_but_never_echoes_it():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers["Authorization"]
        return httpx.Response(200, json={"data": [{"id": "deepseek-v4-flash"}]})

    client, _ = make_client(handler)
    response = client.post("/api/settings/ai/test", json={"api_key": "sk-test-only"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert seen["authorization"] == "Bearer sk-test-only"
    assert "sk-test-only" not in response.text


def test_connection_test_maps_authentication_failure_without_upstream_body():
    client, _ = make_client(
        lambda request: httpx.Response(401, json={"error": {"message": "bad sk-leaked"}})
    )

    response = client.post("/api/settings/ai/test", json={"api_key": "sk-test-only"})

    assert response.status_code == 200
    assert response.json() == {
        "ok": False,
        "code": "DEEPSEEK_AUTH_FAILED",
        "message": "API Key 无效或已失效",
    }
    assert "sk-leaked" not in response.text


def test_clear_removes_credential():
    client, _ = make_client(lambda request: httpx.Response(200, json={"data": []}))
    client.post("/api/settings/ai", json={"api_key": "sk-user-secret"})

    response = client.delete("/api/settings/ai")

    assert response.status_code == 200
    assert response.json()["configured"] is False


def test_environment_managed_configuration_cannot_be_overwritten(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-secret")
    client, _ = make_client(lambda request: httpx.Response(200, json={"data": []}))

    response = client.post("/api/settings/ai", json={"api_key": "sk-user-secret"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AI_SETTINGS_ENV_MANAGED"
    assert "sk-env-secret" not in response.text


def test_invalid_provider_configuration_returns_typed_422_without_secret():
    client, _ = make_client(lambda request: httpx.Response(200, json={"data": []}))

    response = client.post(
        "/api/settings/ai",
        json={
            "api_key": "sk-invalid-secret",
            "base_url": "https://example.com",
            "model": "deepseek-v4-flash",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AI_SETTINGS_INVALID"
    assert "sk-invalid-secret" not in response.text
