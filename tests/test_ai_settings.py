from __future__ import annotations

import json

import pytest

from geomodeling.integrations.deepseek_credentials import (
    DeepSeekCredentialConfig,
    DeepSeekSettingsService,
    InMemoryCredentialStore,
)


def _config(key: str = "sk-test-secret") -> DeepSeekCredentialConfig:
    return DeepSeekCredentialConfig(api_key=key)


def test_status_never_returns_api_key(monkeypatch):
    store = InMemoryCredentialStore()
    store.write(_config())
    service = DeepSeekSettingsService(store=store)

    status = service.status().model_dump(mode="json")

    assert status["configured"] is True
    assert status["source"] == "windows_credential"
    assert status["editable"] is True
    assert "api_key" not in status
    assert "sk-test-secret" not in json.dumps(status)


def test_environment_configuration_has_priority_and_is_read_only(monkeypatch):
    store = InMemoryCredentialStore()
    store.write(_config("sk-stored"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-secret")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    service = DeepSeekSettingsService(store=store)

    resolved = service.resolve()
    status = service.status()

    assert resolved is not None
    assert resolved.secret_value() == "sk-env-secret"
    assert status.source == "environment"
    assert status.model == "deepseek-v4-pro"
    assert status.editable is False


def test_environment_override_preserves_legacy_custom_endpoint_and_model(monkeypatch):
    """管理员环境变量保持 v0.9.1 既有能力；网页保存仍只准官方地址。"""

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-secret")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://deepseek-proxy.example/v1/")
    monkeypatch.setenv("DEEPSEEK_MODEL", "organization-deepseek-alias")

    resolved = DeepSeekSettingsService(store=InMemoryCredentialStore()).resolve()

    assert resolved is not None
    assert resolved.base_url == "https://deepseek-proxy.example/v1"
    assert resolved.model == "organization-deepseek-alias"


def test_write_read_and_clear_credential(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    store = InMemoryCredentialStore()
    service = DeepSeekSettingsService(store=store)

    service.save(_config())
    assert service.resolve().secret_value() == "sk-test-secret"

    service.clear()
    assert service.resolve() is None
    assert service.status().configured is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"api_key": "   "},
        {"api_key": "sk-test", "base_url": "http://api.deepseek.com"},
        {"api_key": "sk-test", "base_url": "https://example.com"},
        {"api_key": "sk-test", "model": "not-a-deepseek-model"},
        {"api_key": "sk-test", "timeout_sec": 0},
        {"api_key": "sk-test", "max_tokens": 0},
    ],
)
def test_invalid_user_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        DeepSeekCredentialConfig(**kwargs)


def test_in_memory_store_repr_does_not_expose_secret():
    store = InMemoryCredentialStore()
    store.write(_config())
    assert "sk-test-secret" not in repr(store)
