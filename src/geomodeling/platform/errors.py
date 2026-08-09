"""Stable platform errors with public-detail sanitization.

Public error payloads follow ``{"error": {"code", "message", "details"}}``.
``Path`` objects and absolute paths are stripped from public ``details``
(本机路径不回传浏览器); the full diagnostics stay in the server log.
"""

from __future__ import annotations

import logging
import re
from pathlib import PurePath
from typing import Any

logger = logging.getLogger("geomodeling.platform")

REDACTED_PATH = "<redacted-path>"

# Stable public error codes; API routes (Task 3+) reuse these.
CASE_NOT_FOUND = "CASE_NOT_FOUND"
DATASET_NOT_FOUND = "DATASET_NOT_FOUND"
EXPERIMENT_NOT_FOUND = "EXPERIMENT_NOT_FOUND"
RUN_NOT_FOUND = "RUN_NOT_FOUND"
CANDIDATE_NOT_FOUND = "CANDIDATE_NOT_FOUND"
DATASET_NOT_IN_CASE = "DATASET_NOT_IN_CASE"
EXPERIMENT_NOT_IN_CASE = "EXPERIMENT_NOT_IN_CASE"
CANDIDATE_NOT_IN_CASE = "CANDIDATE_NOT_IN_CASE"
INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"
RUN_NOT_RETRYABLE = "RUN_NOT_RETRYABLE"
RUN_ALREADY_ACTIVE = "RUN_ALREADY_ACTIVE"
CANDIDATE_NOT_SUCCEEDED = "CANDIDATE_NOT_SUCCEEDED"
DATASET_VERSION_CONFLICT = "DATASET_VERSION_CONFLICT"

# v0.7 微震 CSV 预置（builtin_preset 工作台身份）
PRESET_SOURCE_INVALID = "PRESET_SOURCE_INVALID"
PRESET_BASELINE_INVALID = "PRESET_BASELINE_INVALID"
PRESET_NOT_INITIALIZED = "PRESET_NOT_INITIALIZED"
# read_only 案例（预置官方案例）禁止产品面新增正式选择
READ_ONLY_CASE_FORMAL_SELECTION = "READ_ONLY_CASE_FORMAL_SELECTION"

# v0.8.0 电阻率散点预置迁移：旧 legacy/S3M 产品入口类型化退役（410）
LEGACY_RESISTIVITY_RETIRED = "LEGACY_RESISTIVITY_RETIRED"

# v0.6 专业建模状态（SQLite v5）
PROFESSIONAL_DIAGNOSIS_NOT_FOUND = "PROFESSIONAL_DIAGNOSIS_NOT_FOUND"
PROFESSIONAL_DIAGNOSIS_NOT_SUCCEEDED = "PROFESSIONAL_DIAGNOSIS_NOT_SUCCEEDED"
PROFESSIONAL_CONFIRMATION_NOT_FOUND = "PROFESSIONAL_CONFIRMATION_NOT_FOUND"
PROFESSIONAL_CONFIRMATION_CONFLICT = "PROFESSIONAL_CONFIRMATION_CONFLICT"
PROFESSIONAL_ARTIFACTS_NOT_FOUND = "PROFESSIONAL_ARTIFACTS_NOT_FOUND"
PROFESSIONAL_ARTIFACTS_CONFLICT = "PROFESSIONAL_ARTIFACTS_CONFLICT"
ANOMALY_EXTRACTION_NOT_FOUND = "ANOMALY_EXTRACTION_NOT_FOUND"
ANALYSIS_JOB_NOT_FOUND = "ANALYSIS_JOB_NOT_FOUND"
ANALYSIS_JOB_NOT_RETRYABLE = "ANALYSIS_JOB_NOT_RETRYABLE"
ANALYSIS_JOB_ALREADY_ACTIVE = "ANALYSIS_JOB_ALREADY_ACTIVE"

# v0.6.1 原生体渲染（wgs84_display_anchor_v1 显示坐标契约）
RENDER_DISPLAY_ANCHOR_INVALID = "RENDER_DISPLAY_ANCHOR_INVALID"
RENDER_COORDINATES_INVALID = "RENDER_COORDINATES_INVALID"

# v0.7.0 案例生命周期（第三批设计 §10）
CASE_DELETE_FORBIDDEN = "CASE_DELETE_FORBIDDEN"
CASE_HAS_INFLIGHT_WORK = "CASE_HAS_INFLIGHT_WORK"
CASE_TRASHED = "CASE_TRASHED"
CASE_PURGE_CONFIRMATION_MISMATCH = "CASE_PURGE_CONFIRMATION_MISMATCH"
CASE_PURGE_BLOCKED = "CASE_PURGE_BLOCKED"
CASE_PURGE_RECOVERY_REQUIRED = "CASE_PURGE_RECOVERY_REQUIRED"

# v0.7.0 数据准备恢复（第三批设计 §6）
DATA_PREPARATION_CORRUPT = "DATA_PREPARATION_CORRUPT"
DATASET_ABANDON_FORBIDDEN = "DATASET_ABANDON_FORBIDDEN"

# v0.8.0 第二批统计与空间分析中心（设计 §8）：分析摘要要求已验证数据版本
DATASET_NOT_VALIDATED = "DATASET_NOT_VALIDATED"

# v0.7.0 候选比较（第三批设计 §8）
COMPARISON_SELECTION_INVALID = "COMPARISON_SELECTION_INVALID"
COMPARISON_DATASET_MISMATCH = "COMPARISON_DATASET_MISMATCH"

# 绝对路径形态：POSIX ``/x``、根相对/UNC ``\x``/``\\srv``、Windows 盘符
# （含 ``C:secret`` 这类盘符相对路径，同样可能泄露目录结构）。
_ABS_PATH_TEXT_RE = re.compile(r"^(?:[\\/]|[A-Za-z]:)")


class PlatformError(Exception):
    """Domain error carrying a stable code, user message, and diagnostics."""

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        http_status: int = 400,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = details or {}
        self.http_status = http_status

    def public_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": sanitize_public_details(self.details),
            }
        }


def _is_absolute_path_text(text: str) -> bool:
    return bool(_ABS_PATH_TEXT_RE.match(text))


def sanitize_public_details(value: Any) -> Any:
    """递归脱敏：``PurePath`` 实例与绝对路径文本替换为占位符，其余原样保留。

    ``PurePath`` 兜底覆盖非 ``Path`` 子类（如 ``PurePosixPath``），避免
    不可 JSON 序列化的对象直达响应层造成 500。
    """

    if isinstance(value, PurePath):
        return REDACTED_PATH
    if isinstance(value, str):
        return REDACTED_PATH if _is_absolute_path_text(value) else value
    if isinstance(value, dict):
        return {key: sanitize_public_details(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_public_details(item) for item in value]
    return value


async def platform_error_handler(request: Any, exc: PlatformError) -> Any:
    """FastAPI exception handler：日志保留完整诊断，响应只含脱敏详情。

    ``fastapi`` 在这里惰性导入，保证 platform 层不依赖 api extra。
    """

    from fastapi.responses import JSONResponse

    logger.error(
        "platform error %s (%s): %s details=%r",
        exc.code,
        exc.http_status,
        exc.message,
        exc.details,
    )
    return JSONResponse(status_code=exc.http_status, content=exc.public_payload())
