"""Whitelist DTOs for public API responses.

内部记录（repositories 返回的 pydantic record）允许携带服务器路径；
任何跨出 API 边界的响应必须经过这里的白名单序列化。自由形态嵌套数据
（profile/evidence/manifest）无法穷尽键名，采用“键名黑名单 + 绝对路径
值检测”的递归清理，双保险。
"""

from __future__ import annotations

import re
from typing import Any

from geomodeling.platform.schemas import CaseRecord, DatasetVersionRecord

# 绝不外传的内部路径键名（出现在任意深度都删除）
PATH_KEYS = frozenset(
    {"source_path", "standardized_path", "grid_path", "package_path", "predictions_path"}
)

# 绝对路径形态：Windows 盘符（含 C:secret 盘符相对）、UNC、串首 POSIX、用户目录
_ABS_VALUE_RE = re.compile(r"^(?:[A-Za-z]:[\\/]?|\\\\|/|~[\\/])")

REDACTED = "<redacted-path>"


def scrub_nested(value: Any) -> Any:
    """递归清理嵌套数据：路径键删除，绝对路径形态字符串值替换为占位符。"""

    if isinstance(value, dict):
        return {
            key: scrub_nested(item)
            for key, item in value.items()
            if key not in PATH_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [scrub_nested(item) for item in value]
    if isinstance(value, str) and _ABS_VALUE_RE.match(value) and not value.startswith("/api/"):
        # /api/... 为面向浏览器的下载 URL，属于允许的公开形态
        return REDACTED
    return value


def public_dataset(record: DatasetVersionRecord) -> dict[str, Any]:
    """数据集公开 DTO：白名单字段 + 递归清理后的 profile。"""

    return {
        "id": record.id,
        "case_id": record.case_id,
        "version": record.version,
        "status": getattr(record.status, "value", record.status),
        "created_at": record.created_at,
        "profile": scrub_nested(record.profile),
    }


def public_derivation(record: DatasetVersionRecord, report: dict[str, Any]) -> dict[str, Any]:
    """微震派生证据公开 DTO（v0.5）：白名单字段 + 递归清理后的报告摘要。

    ``report`` 是内部 ``derivation_report.json`` 的自由形态内容，未来键会
    扩张，因此每个取值都过 ``scrub_nested``；工件只给逻辑名（报告自带的
    file/rows/sha256），绝不给服务器路径。分线计数由 profile 的来源清单
    摘要聚合得到，同样不含路径。
    """

    profile = record.profile
    source_files = scrub_nested(profile.get("source_files") or [])
    line_counts: dict[str, int] = {}
    for entry in source_files:
        line_id = entry.get("line_id") if isinstance(entry, dict) else None
        if line_id:
            line_counts[line_id] = line_counts.get(line_id, 0) + int(entry.get("source_record_count") or 0)
    return {
        "dataset_id": record.id,
        "case_id": record.case_id,
        "status": getattr(record.status, "value", record.status),
        "source_kind": profile.get("source_kind"),
        "rule_version": report.get("rule_version"),
        "adapter_version": report.get("adapter_version"),
        "aggregation_method": report.get("aggregation_method"),
        "layer_counts": scrub_nested(report.get("layer_counts") or {}),
        "line_counts": line_counts,
        "three_sigma": scrub_nested(report.get("three_sigma") or {}),
        "aggregation": scrub_nested(report.get("aggregation") or {}),
        "coordinates": scrub_nested(report.get("coordinates") or {}),
        "golden": scrub_nested(report.get("golden") or {}),
        "validation_passed": report.get("validation_passed"),
        "downstream_gates": scrub_nested(report.get("downstream_gates") or {}),
        "source_files": source_files,
        "artifacts": scrub_nested(report.get("artifacts") or {}),
    }


def public_case(record: CaseRecord) -> dict[str, Any]:
    """案例公开 DTO（config 同样递归清理，防未来键扩张）。"""

    return {
        "id": record.id,
        "name": record.name,
        "case_type": record.case_type,
        "config": scrub_nested(record.config),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
