"""Whitelist DTOs for public API responses.

内部记录（repositories 返回的 pydantic record）允许携带服务器路径；
任何跨出 API 边界的响应必须经过这里的白名单序列化。自由形态嵌套数据
（profile/evidence/manifest）无法穷尽键名，采用“键名黑名单 + 绝对路径
值检测”的递归清理，双保险。
"""

from __future__ import annotations

import re
from typing import Any

from geomodeling.platform.schemas import (
    AnalysisJobRecord,
    AnomalyExtractionRecord,
    CaseRecord,
    DatasetVersionRecord,
    ProfessionalConfirmationRecord,
    ProfessionalDiagnosticRecord,
)

# 绝不外传的内部路径键名（出现在任意深度都删除）；``directory`` 是内部
# manifest 的服务器目录绝对路径，公共出口一律剔除。
PATH_KEYS = frozenset(
    {
        "source_path",
        "standardized_path",
        "grid_path",
        "package_path",
        "predictions_path",
        "directory",
    }
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


# ---------------------------------------------------------------------------
# v0.6 专业分析白名单 DTO（Task 17，设计 §14）
#
# 只暴露逻辑身份：工件逻辑名、行数、大小与 SHA-256。内部 manifest 的
# ``directory`` 绝对路径绝不外传（``PATH_KEYS`` 黑名单 + 工件条目白名单
# 双保险）；自由形态的自由键（config/progress/summary/provenance）递归清理。
# ---------------------------------------------------------------------------

#: legacy 候选的专业能力占位响应原因（绝不伪造零值指标或能力）。
LEGACY_RESULT_NOT_COMPUTED = "LEGACY_RESULT_NOT_COMPUTED"


def _status_value(status: Any) -> Any:
    return getattr(status, "value", status)


def public_manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    """公开 manifest 摘要：工件只给逻辑名 + file/sha256/bytes，剔除服务器目录。

    工件条目逐字段白名单（不接受 manifest 里未来新增的任何字段）；其余
    自由形态段落（summary/capabilities/config/materialization）递归清理。
    """

    artifacts = manifest.get("artifacts") or {}
    body: dict[str, Any] = {
        "version": manifest.get("version"),
        "fingerprint": manifest.get("fingerprint"),
        "artifacts": {
            name: {
                "file": entry.get("file"),
                "sha256": entry.get("sha256"),
                "bytes": entry.get("bytes"),
            }
            for name, entry in artifacts.items()
            if isinstance(entry, dict)
        },
        "created_at": manifest.get("created_at"),
    }
    for key in ("summary", "capabilities", "config", "materialization"):
        if key in manifest:
            body[key] = scrub_nested(manifest[key])
    return body


def public_professional_diagnosis(record: ProfessionalDiagnosticRecord) -> dict[str, Any]:
    """专业诊断公开 DTO：状态、指纹、manifest 摘要与结构化错误。"""

    return {
        "id": record.id,
        "dataset_version_id": record.dataset_version_id,
        "status": _status_value(record.status),
        "fingerprint": record.fingerprint,
        "config": scrub_nested(record.config),
        "manifest": public_manifest_summary(record.manifest) if record.manifest else None,
        "error": scrub_nested(record.error) if record.error else None,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "finished_at": record.finished_at,
    }


def public_analysis_job(record: AnalysisJobRecord) -> dict[str, Any]:
    """分析任务公开 DTO：任务身份、状态、有界进度与结构化错误。"""

    return {
        "id": record.id,
        "job_kind": record.job_kind,
        "subject_type": record.subject_type,
        "subject_id": record.subject_id,
        "request_fingerprint": record.request_fingerprint,
        "status": _status_value(record.status),
        "retry_of_job_id": record.retry_of_job_id,
        "progress": scrub_nested(record.progress),
        "error": scrub_nested(record.error) if record.error else None,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
    }


def public_confirmation(record: ProfessionalConfirmationRecord) -> dict[str, Any]:
    """不可变确认快照公开 DTO：身份、指纹、说明与规范化配置（递归清理）。"""

    return {
        "id": record.id,
        "diagnostic_id": record.diagnostic_id,
        "fingerprint": record.fingerprint,
        "note": record.note,
        "config": scrub_nested(record.config),
        "created_at": record.created_at,
    }


def public_professional_result(
    result_id: str,
    *,
    algorithm: str,
    confirmation_id: str | None,
    capabilities: dict[str, Any] | None,
    parameter_provenance: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    """成果专业证据公开 DTO：capabilities、参数出处与 manifest 摘要。

    legacy 候选（无专业工件登记）明确返回
    ``{"available": false, "reason": "LEGACY_RESULT_NOT_COMPUTED"}``，
    绝不伪造零值指标或能力。
    """

    if manifest is None:
        return {
            "result_id": result_id,
            "available": False,
            "reason": LEGACY_RESULT_NOT_COMPUTED,
            "algorithm": algorithm,
        }
    return {
        "result_id": result_id,
        "available": True,
        "algorithm": algorithm,
        "confirmation_id": confirmation_id,
        "capabilities": scrub_nested(capabilities or {}),
        "parameter_provenance": scrub_nested(parameter_provenance) if parameter_provenance else None,
        "manifest": public_manifest_summary(manifest),
    }


def public_fold_evidence(
    result_id: str,
    *,
    fold_count: int,
    leakage_detected: bool,
    folds: list[dict[str, Any]],
    download_url: str,
) -> dict[str, Any]:
    """折分证据公开 DTO：折数、逐折训练/验证计数、空间组身份、泄漏检查与逐折指标。"""

    return scrub_nested(
        {
            "result_id": result_id,
            "fold_count": fold_count,
            "leakage_detected": leakage_detected,
            "folds": folds,
            "download_url": download_url,
        }
    )


def public_residuals(
    result_id: str,
    *,
    total: int,
    returned: int,
    decimate: int,
    columns: dict[str, list[Any]],
    download_url: str,
) -> dict[str, Any]:
    """OOF 残差公开 DTO：行数上限内联（抽稀后）+ 白名单下载 URL。"""

    return scrub_nested(
        {
            "result_id": result_id,
            "total": total,
            "returned": returned,
            "decimate": decimate,
            **columns,
            "download_url": download_url,
        }
    )


def public_variogram_evidence(
    diagnosis_id: str,
    *,
    omnidirectional: dict[str, Any],
    directional: dict[str, Any],
    fitted_models: dict[str, Any],
    anisotropy_candidates: dict[str, Any],
    sampling: dict[str, Any],
    downloads: dict[str, Any],
) -> dict[str, Any]:
    """变异函数证据公开 DTO：全向 + 方向 bins（有界内联）与拟合/候选摘要。"""

    return scrub_nested(
        {
            "diagnosis_id": diagnosis_id,
            "omnidirectional": omnidirectional,
            "directional": directional,
            "fitted_models": fitted_models,
            "anisotropy_candidates": anisotropy_candidates,
            "sampling": sampling,
            "downloads": downloads,
        }
    )


def public_anomaly_extraction(
    record: AnomalyExtractionRecord, *, components: dict[str, Any] | None = None
) -> dict[str, Any]:
    """异常提取公开 DTO：状态、配置、manifest 摘要与有界 components 预览。"""

    return {
        "id": record.id,
        "candidate_result_id": record.candidate_result_id,
        "status": record.status,
        "fingerprint": record.fingerprint,
        "config": scrub_nested(record.config),
        "manifest": public_manifest_summary(record.manifest) if record.manifest else None,
        "error": scrub_nested(record.error) if record.error else None,
        "components": scrub_nested(components) if components is not None else None,
        "created_at": record.created_at,
    }


def public_comparison(comparison: Any) -> dict[str, Any]:
    """双候选比较公开 DTO（``CandidateComparison`` 契约模型，递归清理兜底）。"""

    return scrub_nested(comparison.model_dump(mode="json"))
