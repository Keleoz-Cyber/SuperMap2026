"""Local-only DeepSeek settings endpoints with redacted public responses."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, SecretStr
from pydantic import ValidationError

from geomodeling.integrations.deepseek_credentials import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SEC,
    DeepSeekCredentialConfig,
    DeepSeekSettingsService,
    get_default_deepseek_settings_service,
)
from geomodeling.platform.errors import PlatformError

router = APIRouter(prefix="/api/settings/ai", tags=["ai-settings"])


class AISettingsInput(BaseModel):
    api_key: SecretStr
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_sec: float = Field(default=float(DEFAULT_TIMEOUT_SEC), gt=0, le=600)
    max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, ge=1, le=384_000)

    def private_config(self) -> DeepSeekCredentialConfig:
        try:
            return DeepSeekCredentialConfig(**self.model_dump())
        except ValidationError as exc:
            raise PlatformError("AI_SETTINGS_INVALID", "AI 服务配置无效", http_status=422) from exc


class AISettingsTestInput(BaseModel):
    api_key: SecretStr | None = None
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_sec: float = Field(default=float(DEFAULT_TIMEOUT_SEC), gt=0, le=600)
    max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, ge=1, le=384_000)

    def optional_config(self) -> DeepSeekCredentialConfig | None:
        if self.api_key is None or not self.api_key.get_secret_value().strip():
            return None
        try:
            return DeepSeekCredentialConfig(**self.model_dump())
        except ValidationError as exc:
            raise PlatformError("AI_SETTINGS_INVALID", "AI 服务配置无效", http_status=422) from exc


def get_ai_settings_service() -> DeepSeekSettingsService:
    return get_default_deepseek_settings_service()


def _status(service: DeepSeekSettingsService) -> dict:
    return service.status().model_dump(mode="json")


@router.get("")
def read_ai_settings(service: DeepSeekSettingsService = Depends(get_ai_settings_service)) -> dict:
    return _status(service)


@router.post("")
def save_ai_settings(payload: AISettingsInput, service: DeepSeekSettingsService = Depends(get_ai_settings_service)) -> dict:
    if service.status().source == "environment":
        raise PlatformError("AI_SETTINGS_ENV_MANAGED", "当前配置由环境变量管理，网页不能覆盖", http_status=409)
    try:
        service.save(payload.private_config())
    except OSError:
        raise PlatformError("AI_CREDENTIAL_STORE_UNAVAILABLE", "系统安全凭据存储不可用，配置未保存", http_status=503)
    return _status(service)


@router.post("/test")
def test_ai_settings(payload: AISettingsTestInput, service: DeepSeekSettingsService = Depends(get_ai_settings_service)) -> dict:
    result = service.test(payload.optional_config())
    return {"ok": result.ok, "code": result.code, "message": result.message}


@router.delete("")
def clear_ai_settings(service: DeepSeekSettingsService = Depends(get_ai_settings_service)) -> dict:
    if service.status().source == "environment":
        raise PlatformError("AI_SETTINGS_ENV_MANAGED", "当前配置由环境变量管理，网页不能删除", http_status=409)
    try:
        service.clear()
    except OSError:
        raise PlatformError("AI_CREDENTIAL_STORE_UNAVAILABLE", "系统安全凭据存储不可用，配置未清除", http_status=503)
    return _status(service)
