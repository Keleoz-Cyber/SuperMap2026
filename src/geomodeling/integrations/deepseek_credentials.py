"""DeepSeek configuration resolved from environment or the operating-system keyring.

The API key never enters SQLite, project files, browser storage, logs, exports,
or public DTOs.  Environment variables are an administrator/development
override; Windows Credential Manager and macOS Keychain are user configuration paths.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Callable, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from geomodeling.integrations.deepseek import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SEC,
    ENV_API_KEY,
    ENV_BASE_URL,
    ENV_MAX_TOKENS,
    ENV_MODEL,
    ENV_TIMEOUT_SEC,
)

CREDENTIAL_TARGET = "GeoModelingPlatform/DeepSeek"
CREDENTIAL_USERNAME = "DeepSeek API"
# V4 是产品界面提供的当前模型；两个旧别名仍由 DeepSeek 官方兼容，保留
# 给环境变量管理员与既有自动化，避免配置功能造成回归。
ALLOWED_MODELS = {
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "deepseek-chat",
    "deepseek-reasoner",
}


class DeepSeekCredentialConfig(BaseModel):
    """Private provider configuration; ``api_key`` is redacted by Pydantic."""

    model_config = ConfigDict(frozen=True)

    api_key: SecretStr
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_sec: float = Field(default=float(DEFAULT_TIMEOUT_SEC), gt=0, le=600)
    max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, ge=1, le=384_000)

    @field_validator("api_key")
    @classmethod
    def validate_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("API Key 不能为空")
        return SecretStr(value.get_secret_value().strip())

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if normalized != DEFAULT_BASE_URL:
            raise ValueError("当前版本只允许 DeepSeek 官方 HTTPS 地址")
        return normalized

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if value not in ALLOWED_MODELS:
            raise ValueError("不支持的 DeepSeek 模型")
        return value

    def secret_value(self) -> str:
        return self.api_key.get_secret_value()

    @classmethod
    def from_environment(cls) -> "DeepSeekCredentialConfig | None":
        """Read the administrator override without consulting persistent storage.

        v0.9.1 已允许管理员通过环境变量指定代理地址与组织内模型别名。
        这里保留该兼容能力；严格的官方地址/模型白名单只约束网页保存路径。
        """

        key = os.environ.get(ENV_API_KEY, "").strip()
        if not key:
            return None
        return cls.model_construct(
            api_key=SecretStr(key),
            base_url=os.environ.get(ENV_BASE_URL, DEFAULT_BASE_URL).strip().rstrip("/"),
            model=os.environ.get(ENV_MODEL, DEFAULT_MODEL).strip(),
            timeout_sec=float(os.environ.get(ENV_TIMEOUT_SEC, DEFAULT_TIMEOUT_SEC)),
            max_tokens=int(os.environ.get(ENV_MAX_TOKENS, DEFAULT_MAX_TOKENS)),
        )


CredentialSource = Literal["environment", "windows_credential", "macos_keychain", "none"]


class DeepSeekSettingsStatus(BaseModel):
    configured: bool
    source: CredentialSource
    editable: bool
    storage_available: bool
    base_url: str
    model: str
    timeout_sec: float
    max_tokens: int


class CredentialStore(Protocol):
    available: bool
    source: Literal["windows_credential", "macos_keychain"]

    def read(self) -> DeepSeekCredentialConfig | None: ...
    def write(self, config: DeepSeekCredentialConfig) -> None: ...
    def clear(self) -> None: ...


@dataclass
class InMemoryCredentialStore:
    """Injectable test store; repr intentionally excludes its secret value."""

    available: bool = True
    source: Literal["windows_credential", "macos_keychain"] = "windows_credential"
    _config: DeepSeekCredentialConfig | None = field(default=None, repr=False)

    def read(self) -> DeepSeekCredentialConfig | None:
        return self._config

    def write(self, config: DeepSeekCredentialConfig) -> None:
        self._config = config

    def clear(self) -> None:
        self._config = None


if os.name == "nt":
    class _CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", wintypes.LPVOID),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    _PCREDENTIALW = ctypes.POINTER(_CREDENTIALW)


class WindowsCredentialStore:
    """Minimal WinCred wrapper using the current user's Generic Credentials."""

    available = os.name == "nt"
    source: Literal["windows_credential"] = "windows_credential"
    _TYPE_GENERIC = 1
    _PERSIST_LOCAL_MACHINE = 2
    _ERROR_NOT_FOUND = 1168

    def _advapi(self):
        if not self.available:
            raise OSError("Windows 凭据管理器仅在 Windows 可用")
        library = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        library.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
        library.CredWriteW.restype = wintypes.BOOL
        library.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_PCREDENTIALW)]
        library.CredReadW.restype = wintypes.BOOL
        library.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        library.CredDeleteW.restype = wintypes.BOOL
        library.CredFree.argtypes = [wintypes.LPVOID]
        library.CredFree.restype = None
        return library

    def read(self) -> DeepSeekCredentialConfig | None:
        advapi = self._advapi()
        pointer = _PCREDENTIALW()
        if not advapi.CredReadW(CREDENTIAL_TARGET, self._TYPE_GENERIC, 0, ctypes.byref(pointer)):
            error = ctypes.get_last_error()
            if error == self._ERROR_NOT_FOUND:
                return None
            raise ctypes.WinError(error)
        try:
            credential = pointer.contents
            raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return DeepSeekCredentialConfig.model_validate_json(raw.decode("utf-8"))
        finally:
            advapi.CredFree(pointer)

    def write(self, config: DeepSeekCredentialConfig) -> None:
        advapi = self._advapi()
        payload = json.dumps(
            {
                "api_key": config.secret_value(),
                "base_url": config.base_url,
                "model": config.model,
                "timeout_sec": config.timeout_sec,
                "max_tokens": config.max_tokens,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        blob = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
        credential = _CREDENTIALW()
        credential.Type = self._TYPE_GENERIC
        credential.TargetName = CREDENTIAL_TARGET
        credential.CredentialBlobSize = len(payload)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = self._PERSIST_LOCAL_MACHINE
        credential.UserName = CREDENTIAL_USERNAME
        if not advapi.CredWriteW(ctypes.byref(credential), 0):
            raise ctypes.WinError(ctypes.get_last_error())

    def clear(self) -> None:
        advapi = self._advapi()
        if advapi.CredDeleteW(CREDENTIAL_TARGET, self._TYPE_GENERIC, 0):
            return
        error = ctypes.get_last_error()
        if error != self._ERROR_NOT_FOUND:
            raise ctypes.WinError(error)


class KeyringBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


@dataclass
class MacOSKeychainStore:
    """Store the private JSON payload in the current user's macOS Keychain."""

    backend: KeyringBackend | None = field(default=None, repr=False)
    source: Literal["macos_keychain"] = field(default="macos_keychain", init=False)

    def _keyring(self) -> KeyringBackend:
        if self.backend is not None:
            return self.backend
        try:
            import keyring
        except ImportError as exc:
            raise OSError("macOS 钥匙串组件不可用") from exc
        return keyring

    @property
    def available(self) -> bool:
        if self.backend is not None:
            return True
        if sys.platform != "darwin":
            return False
        try:
            import keyring

            return float(keyring.get_keyring().priority) > 0
        except (ImportError, RuntimeError, TypeError, ValueError):
            return False

    def read(self) -> DeepSeekCredentialConfig | None:
        if not self.available:
            raise OSError("macOS 钥匙串不可用")
        try:
            raw = self._keyring().get_password(CREDENTIAL_TARGET, CREDENTIAL_USERNAME)
        except Exception as exc:
            raise OSError("无法读取 macOS 钥匙串") from exc
        if raw is None:
            return None
        try:
            return DeepSeekCredentialConfig.model_validate_json(raw)
        except ValueError as exc:
            raise OSError("macOS 钥匙串中的 AI 配置无效") from exc

    def write(self, config: DeepSeekCredentialConfig) -> None:
        if not self.available:
            raise OSError("macOS 钥匙串不可用")
        payload = json.dumps(
            {
                "api_key": config.secret_value(),
                "base_url": config.base_url,
                "model": config.model,
                "timeout_sec": config.timeout_sec,
                "max_tokens": config.max_tokens,
            },
            separators=(",", ":"),
        )
        try:
            self._keyring().set_password(CREDENTIAL_TARGET, CREDENTIAL_USERNAME, payload)
        except Exception as exc:
            raise OSError("无法写入 macOS 钥匙串") from exc

    def clear(self) -> None:
        if not self.available:
            raise OSError("macOS 钥匙串不可用")
        keyring_backend = self._keyring()
        try:
            if keyring_backend.get_password(CREDENTIAL_TARGET, CREDENTIAL_USERNAME) is not None:
                keyring_backend.delete_password(CREDENTIAL_TARGET, CREDENTIAL_USERNAME)
        except Exception as exc:
            raise OSError("无法清除 macOS 钥匙串") from exc


def default_credential_store(*, platform_name: str | None = None) -> CredentialStore:
    resolved = platform_name or sys.platform
    if resolved == "win32":
        return WindowsCredentialStore()
    if resolved == "darwin":
        return MacOSKeychainStore()
    return InMemoryCredentialStore(available=False)


@dataclass
class DeepSeekConnectionResult:
    ok: bool
    code: str
    message: str


class DeepSeekSettingsService:
    def __init__(
        self,
        store: CredentialStore | None = None,
        http_handler: Callable[[httpx.Request], httpx.Response] | None = None,
    ) -> None:
        self.store = store or default_credential_store()
        self._http_handler = http_handler

    @staticmethod
    def _from_environment() -> DeepSeekCredentialConfig | None:
        return DeepSeekCredentialConfig.from_environment()

    def resolve(self) -> DeepSeekCredentialConfig | None:
        environment = self._from_environment()
        if environment is not None:
            return environment
        if not self.store.available:
            return None
        return self.store.read()

    def status(self) -> DeepSeekSettingsStatus:
        environment = self._from_environment()
        stored = None if environment is not None or not self.store.available else self.store.read()
        resolved = environment or stored
        return DeepSeekSettingsStatus(
            configured=resolved is not None,
            source="environment" if environment else self.store.source if stored else "none",
            editable=environment is None and self.store.available,
            storage_available=self.store.available,
            base_url=resolved.base_url if resolved else DEFAULT_BASE_URL,
            model=resolved.model if resolved else DEFAULT_MODEL,
            timeout_sec=resolved.timeout_sec if resolved else float(DEFAULT_TIMEOUT_SEC),
            max_tokens=resolved.max_tokens if resolved else DEFAULT_MAX_TOKENS,
        )

    def save(self, config: DeepSeekCredentialConfig) -> None:
        if not self.store.available:
            raise OSError("系统安全凭据存储不可用")
        self.store.write(config)

    def clear(self) -> None:
        if not self.store.available:
            raise OSError("系统安全凭据存储不可用")
        self.store.clear()

    def test(self, config: DeepSeekCredentialConfig | None = None) -> DeepSeekConnectionResult:
        resolved = config or self.resolve()
        if resolved is None:
            return DeepSeekConnectionResult(False, "DEEPSEEK_NOT_CONFIGURED", "尚未配置 API Key")
        transport = httpx.MockTransport(self._http_handler) if self._http_handler else None
        try:
            with httpx.Client(transport=transport, timeout=resolved.timeout_sec) as client:
                response = client.get(
                    f"{resolved.base_url}/models",
                    headers={"Authorization": f"Bearer {resolved.secret_value()}"},
                )
        except httpx.TimeoutException:
            return DeepSeekConnectionResult(False, "DEEPSEEK_TIMEOUT", "连接 DeepSeek 超时")
        except httpx.HTTPError:
            return DeepSeekConnectionResult(False, "DEEPSEEK_NETWORK_ERROR", "无法连接 DeepSeek 服务")
        if response.status_code in (401, 403):
            return DeepSeekConnectionResult(False, "DEEPSEEK_AUTH_FAILED", "API Key 无效或已失效")
        if response.status_code == 402:
            return DeepSeekConnectionResult(False, "DEEPSEEK_BALANCE_INSUFFICIENT", "账户余额不足")
        if response.status_code == 429:
            return DeepSeekConnectionResult(False, "DEEPSEEK_RATE_LIMITED", "请求受到限流，请稍后重试")
        if response.status_code != 200:
            return DeepSeekConnectionResult(False, "DEEPSEEK_HTTP_ERROR", f"DeepSeek 服务返回 HTTP {response.status_code}")
        return DeepSeekConnectionResult(True, "DEEPSEEK_AVAILABLE", "连接成功，API Key 可用")


_default_service: DeepSeekSettingsService | None = None


def get_default_deepseek_settings_service() -> DeepSeekSettingsService:
    global _default_service
    if _default_service is None:
        _default_service = DeepSeekSettingsService()
    return _default_service
