"""Professional analysis executors, artifact writes and confirmations.

设计 §5.2/§5.3/§6/§7.1/§12/§17：持久化分析任务的执行体与不可变确认服务。

- 诊断：读 standardized.parquet → ``compute_empirical_variogram``（种子来自
  standardized SHA-256 与规范化配置）→ 全向 + 方向 bins 落 CSV → 每模型
  （球状/指数/高斯）``fit_variogram_evidence`` → ``suggest_anisotropy``。
  有效 bin 不足或拟合失败一律结构化失败，不静默改用旧固定 12-bin，也不
  把方向失败降级为全向成功。
- 异常提取：要求已物化成果（metadata 存在、grid 哈希登记）与已请求的不
  确定性层；按登记网格与不确定性工件计算，掩膜按 §12.1 复算并与诊断
  计数互证。
- 全部工件以「同级临时目录写齐 → 回读校验 → 计算 SHA-256 → 原子替换」
  落盘；失败逐步清理，清理异常只记日志，绝不覆盖原业务异常（与导出补偿
  同款模式）。成功只在 manifest 校验通过后提交数据库。
- 取消语义与插值 run 一致：内存事件 + 持久 ``cancel_requested`` 旗标；
  取消只影响当前任务，不改已有成功工件。
- 双候选比较（设计 §4.3/§13.3）：只读已登记工件（OOF parquet、
  fold_assignments、grid.npz、metadata.json），绝不重跑模型；兼容对在所
  选候选交集上重算指标差，不兼容只披露 mismatches，绝不显示指标差值。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import math
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import ValidationError, model_validator

from geomodeling.modeling.anomalies import (
    ANOMALY_UNCERTAINTY_UNAVAILABLE,
    AnomalyComponent,
    UncertaintyLayer,
    extract_anomalies,
)
from geomodeling.modeling.comparison import (
    CandidateComparison,
    align_oof_pair,
    comparison_fingerprint,
    grid_axes_identical,
    grid_difference_summary,
    pair_common_valid_mask,
    pair_metric_deltas,
    validation_fingerprint_from_assignments,
)
from geomodeling.modeling.directional_variogram import (
    EmpiricalBin,
    compute_empirical_variogram,
)
from geomodeling.modeling.professional_contracts import (
    AnomalyExtractionSpec,
    DirectionSpec,
    VariogramDiagnosticSpec,
)
from geomodeling.modeling.professional_diagnosis import (
    STATUS_SUPPORTED,
    STATUS_UNSUPPORTED_INSUFFICIENT_PAIRS,
    DirectionalFit,
    suggest_anisotropy,
)
from geomodeling.modeling.variogram import (
    MIN_FIT_BINS,
    MODELS,
    ManualVariogramParameters,
    fit_variogram_evidence,
)
from geomodeling.platform import tables
from geomodeling.platform.errors import (
    CANDIDATE_NOT_SUCCEEDED,
    PROFESSIONAL_DIAGNOSIS_NOT_SUCCEEDED,
    PlatformError,
)
from geomodeling.platform.repositories import (
    AnalysisJobRepository,
    AnomalyExtractionRepository,
    DatasetRepository,
    ProfessionalConfirmationRepository,
    ProfessionalDiagnosticRepository,
)
from geomodeling.platform.results import RESULT_NOT_MATERIALIZED, _load_candidate, load_grid
from geomodeling.platform.schemas import (
    AnalysisJobRecord,
    ContractModel,
    ProfessionalConfirmationRecord,
    SpatialValidationSpec,
)
from geomodeling.platform.tables import RunStatus

__all__ = [
    "ANALYSIS_JOB_KIND_UNKNOWN",
    "ANOMALY_ARTIFACT_WRITE_FAILED",
    "ANOMALY_INTERNAL_INCONSISTENT",
    "CANCEL_REQUESTED",
    "COMPARISON_EVIDENCE_INCOMPLETE",
    "COMPARISON_SAME_CANDIDATE",
    "DIAGNOSIS_ARTIFACT_WRITE_FAILED",
    "MANIFEST_VERIFICATION_FAILED",
    "PROFESSIONAL_CONFIG_INVALID",
    "PROFESSIONAL_CONFIRMATION_INVALID",
    "RUN_CANCELED",
    "anomaly_fingerprint",
    "canonical_anomaly_config",
    "canonical_variogram_config",
    "compare_candidates",
    "confirm_professional_diagnosis",
    "diagnosis_fingerprint",
    "execute_anomaly_extraction",
    "execute_professional_diagnosis",
    "fail_unknown_kind",
    "sha256_file",
    "verify_manifest",
]

logger = logging.getLogger("geomodeling.platform")

RUN_CANCELED = "RUN_CANCELED"
DIAGNOSIS_ARTIFACT_WRITE_FAILED = "DIAGNOSIS_ARTIFACT_WRITE_FAILED"
ANOMALY_ARTIFACT_WRITE_FAILED = "ANOMALY_ARTIFACT_WRITE_FAILED"
MANIFEST_VERIFICATION_FAILED = "MANIFEST_VERIFICATION_FAILED"
ANALYSIS_JOB_KIND_UNKNOWN = "ANALYSIS_JOB_KIND_UNKNOWN"
PROFESSIONAL_CONFIG_INVALID = "PROFESSIONAL_CONFIG_INVALID"
PROFESSIONAL_CONFIRMATION_INVALID = "PROFESSIONAL_CONFIRMATION_INVALID"
ANOMALY_INTERNAL_INCONSISTENT = "ANOMALY_INTERNAL_INCONSISTENT"
COMPARISON_SAME_CANDIDATE = "COMPARISON_SAME_CANDIDATE"
COMPARISON_EVIDENCE_INCOMPLETE = "COMPARISON_EVIDENCE_INCOMPLETE"

#: 取消意图的持久旗标键（与 worker.CANCEL_REQUESTED 同串，两处常量不互
#: 引以避免 worker ↔ professional 循环依赖）。
CANCEL_REQUESTED = "cancel_requested"


# ---------------------------------------------------------------------------
# 规范化配置与指纹
# ---------------------------------------------------------------------------


def canonical_variogram_config(config: dict[str, Any]) -> dict[str, Any]:
    """严格校验诊断请求配置（``{"variogram": ...}``），返回规范化形态。"""

    try:
        spec = VariogramDiagnosticSpec.model_validate((config or {}).get("variogram") or {})
    except ValidationError as exc:
        raise PlatformError(
            PROFESSIONAL_CONFIG_INVALID, "诊断配置非法", {"reason": str(exc)[:300]}
        ) from exc
    return {"variogram": spec.model_dump(mode="json")}


def canonical_anomaly_config(config: dict[str, Any]) -> dict[str, Any]:
    """严格校验异常提取配置（``AnomalyExtractionSpec`` 载荷），返回规范化形态。"""

    try:
        spec = AnomalyExtractionSpec.model_validate(config or {})
    except ValidationError as exc:
        raise PlatformError(
            PROFESSIONAL_CONFIG_INVALID, "异常提取配置非法", {"reason": str(exc)[:300]}
        ) from exc
    return spec.model_dump(mode="json")


def diagnosis_fingerprint(standardized_sha256: str, canonical_config: dict[str, Any]) -> str:
    """诊断指纹 = standardized SHA-256 + 规范化配置哈希（§5.1）。"""

    payload = {"standardized_sha256": standardized_sha256, "config": canonical_config}
    return hashlib.sha256(tables.dumps_canonical(payload).encode("utf-8")).hexdigest()


def anomaly_fingerprint(grid_sha256: str, canonical_config: dict[str, Any]) -> str:
    """异常指纹 = 成果网格哈希 + 配置哈希（§5.1）。"""

    payload = {"grid_sha256": grid_sha256, "config": canonical_config}
    return hashlib.sha256(tables.dumps_canonical(payload).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# 工件写入：同级临时目录写齐 → 回读校验 → 计算 SHA-256 → 原子替换
# ---------------------------------------------------------------------------


def _write_file(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")


def _format_csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value) if math.isfinite(value) else ""
    return str(value)


def _csv_bytes(fieldnames: list[str], rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({name: _format_csv_value(row.get(name)) for name in fieldnames})
    return buffer.getvalue().encode("utf-8")


def _npz_bytes(**arrays: Any) -> bytes:
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    return buffer.getvalue()


def _cleanup_failed_write(tmp_dir: Path, moved: list[Path], final_dir: Path) -> None:
    """失败逐步清理：已替换文件 → 临时目录 → 空最终目录。

    清理异常只记日志（含堆栈），绝不覆盖原业务异常（§5.3，与导出补偿
    同款模式）。
    """

    for path in moved:
        try:
            path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            logger.exception("professional artifact cleanup failed: %s", path)
    try:
        shutil.rmtree(tmp_dir)
    except Exception:  # noqa: BLE001
        logger.exception("professional artifact staging cleanup failed: %s", tmp_dir)
    try:
        if final_dir.exists() and not any(final_dir.iterdir()):
            final_dir.rmdir()
    except Exception:  # noqa: BLE001
        logger.exception("professional artifact dir cleanup failed: %s", final_dir)


def _write_artifact_dir(
    final_dir: Path, payloads: dict[str, bytes], *, error_code: str
) -> dict[str, dict[str, Any]]:
    """把 ``payloads`` 原子落入 ``final_dir``，返回逐文件 manifest 条目。"""

    final_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"{final_dir.name}-", dir=final_dir.parent))
    moved: list[Path] = []
    try:
        for name, data in payloads.items():
            _write_file(tmp_dir / name, data)
        entries: dict[str, dict[str, Any]] = {}
        for name, expected in payloads.items():
            blob = (tmp_dir / name).read_bytes()
            if blob != expected:
                raise PlatformError(
                    error_code, "专业工件回读校验失败", {"file": name}
                )
            entries[name] = {
                "file": name,
                "sha256": hashlib.sha256(blob).hexdigest(),
                "bytes": len(blob),
            }
        final_dir.mkdir(parents=True, exist_ok=True)
        for name in payloads:
            os.replace(tmp_dir / name, final_dir / name)
            moved.append(final_dir / name)
    except PlatformError:
        _cleanup_failed_write(tmp_dir, moved, final_dir)
        raise
    except Exception as exc:
        _cleanup_failed_write(tmp_dir, moved, final_dir)
        raise PlatformError(
            error_code, "专业工件写入失败", {"reason": str(exc)[:200]}
        ) from exc
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return entries


def _atomic_write_file(target: Path, data: bytes, *, error_code: str) -> None:
    """单文件原子写：同级临时文件 + 回读校验 + ``os.replace``。"""

    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{target.stem}-", suffix=target.suffix, dir=target.parent
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        _write_file(tmp_path, data)
        if tmp_path.read_bytes() != data:
            raise PlatformError(error_code, "专业工件回读校验失败", {"file": target.name})
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def verify_manifest(manifest: dict[str, Any]) -> bool:
    """重算 manifest 引用的每件工件的 SHA-256 与大小，全部匹配才返回 True。

    任何缺失、大小或哈希不匹配都以 ``MANIFEST_VERIFICATION_FAILED`` 结构化
    失败（§17：工件哈希不匹配必须结构化失败）。
    """

    artifacts = manifest.get("artifacts") if isinstance(manifest, dict) else None
    directory = manifest.get("directory") if isinstance(manifest, dict) else None
    if not isinstance(artifacts, dict) or not artifacts or not directory:
        raise PlatformError(
            MANIFEST_VERIFICATION_FAILED,
            "manifest 缺少 artifacts 或 directory",
            http_status=409,
        )
    base = Path(directory)
    for name, entry in artifacts.items():
        file_name = entry.get("file")
        expected_sha = entry.get("sha256")
        expected_bytes = entry.get("bytes")
        if not file_name or not isinstance(expected_sha, str) or not isinstance(expected_bytes, int):
            raise PlatformError(
                MANIFEST_VERIFICATION_FAILED,
                "manifest 工件条目不完整",
                {"artifact": name},
                http_status=409,
            )
        path = base / file_name
        if not path.is_file():
            raise PlatformError(
                MANIFEST_VERIFICATION_FAILED,
                "manifest 引用的工件不存在",
                {"artifact": name},
                http_status=409,
            )
        blob = path.read_bytes()
        if len(blob) != expected_bytes or hashlib.sha256(blob).hexdigest() != expected_sha:
            raise PlatformError(
                MANIFEST_VERIFICATION_FAILED,
                "工件哈希或大小不匹配",
                {"artifact": name},
                http_status=409,
            )
    return True


# ---------------------------------------------------------------------------
# 分析任务生命周期辅助
# ---------------------------------------------------------------------------


def _begin_job(runtime, job_id: str) -> bool:
    """queued→running；取消意图（持久旗标或已取消）优先，返回 False 表示已取消。

    running 视为崩遗领养（单 worker 串行，无并发驱动者），直接续跑。
    """

    with runtime.session() as session:
        repo = AnalysisJobRepository(session)
        current = repo.get(job_id)
        if current.status == RunStatus.CANCELED.value or current.progress.get(CANCEL_REQUESTED):
            if current.status != RunStatus.CANCELED.value:
                repo.cancel(job_id)
            return False
        if current.status == RunStatus.QUEUED.value:
            repo.mark_running(job_id)
        return True


def _persist_job_progress(runtime, job_id: str, progress: dict[str, Any]) -> None:
    """有界进度落库；取消旗标不被进度覆盖（durability）。"""

    with runtime.session() as session:
        row = session.get(tables.AnalysisJob, job_id)
        if row is None or row.status != RunStatus.RUNNING.value:
            return
        merged = dict(progress)
        existing = tables.loads_canonical(row.progress_json)
        if existing.get(CANCEL_REQUESTED):
            merged[CANCEL_REQUESTED] = True
        row.progress_json = tables.dumps_canonical(merged)
        session.commit()


def _job_error(exc: PlatformError) -> dict[str, Any]:
    return {"code": exc.code, "message": exc.message}


def _finish_job_failed(runtime, job_id: str, error: dict[str, Any]) -> None:
    with runtime.session() as session:
        try:
            AnalysisJobRepository(session).mark_failed(job_id, error=error)
        except PlatformError:
            logger.exception("analysis job %s 已处终态，失败结果不覆盖", job_id)


def _cancel_job(runtime, job_id: str) -> None:
    with runtime.session() as session:
        try:
            AnalysisJobRepository(session).cancel(job_id)
        except PlatformError:
            logger.exception("analysis job %s 已处终态，取消不覆盖", job_id)


def fail_unknown_kind(runtime, job: AnalysisJobRecord) -> None:
    """未知 ``job_kind`` 的防御分支：任务以结构化错误失败（§5.2 分派兜底）。"""

    error = {
        "code": ANALYSIS_JOB_KIND_UNKNOWN,
        "message": f"未知分析任务类型：{job.job_kind}",
    }
    with runtime.session() as session:
        repo = AnalysisJobRepository(session)
        try:
            repo.mark_running(job.id)
        except PlatformError:
            logger.exception("analysis job %s 已不在排队状态", job.id)
        try:
            repo.mark_failed(job.id, error=error)
        except PlatformError:
            logger.exception("analysis job %s 已处终态，失败结果不覆盖", job.id)


# ---------------------------------------------------------------------------
# 专业诊断执行体
# ---------------------------------------------------------------------------

_OMNI_FIELDS = [
    "bin_index",
    "lower_distance",
    "upper_distance",
    "center_distance",
    "mean_distance",
    "semivariance",
    "pair_count",
    "used_for_fit",
    "exclusion_reason",
]

_DIRECTION_FIELDS = [
    "direction_id",
    "azimuth_deg",
    "dip_deg",
    "azimuth_tolerance_deg",
    "dip_tolerance_deg",
    *_OMNI_FIELDS,
]


def _bin_row(index: int, bin_: EmpiricalBin) -> dict[str, Any]:
    return {
        "bin_index": index,
        "lower_distance": bin_.lower_distance,
        "upper_distance": bin_.upper_distance,
        "center_distance": bin_.center_distance,
        "mean_distance": bin_.mean_distance,
        "semivariance": bin_.semivariance,
        "pair_count": bin_.pair_count,
        "used_for_fit": bin_.used_for_fit,
        "exclusion_reason": bin_.exclusion_reason,
    }


def _direction_row(
    direction_id: str, direction: DirectionSpec, index: int, bin_: EmpiricalBin
) -> dict[str, Any]:
    return {
        "direction_id": direction_id,
        "azimuth_deg": float(direction.azimuth_deg),
        "dip_deg": float(direction.dip_deg) if direction.dip_deg is not None else None,
        "azimuth_tolerance_deg": float(direction.azimuth_tolerance_deg),
        "dip_tolerance_deg": (
            float(direction.dip_tolerance_deg)
            if direction.dip_tolerance_deg is not None
            else None
        ),
        **_bin_row(index, bin_),
    }


def execute_professional_diagnosis(
    runtime, job: AnalysisJobRecord, event: threading.Event
) -> None:
    """worker 入口：驱动专业诊断到终态。

    结构化失败（``PlatformError``）落库到诊断与任务；取消只取消任务；
    未捕获异常上交 worker 兜底（任务不得悬在 running）。
    """

    diagnosis_id = job.subject_id
    if not _begin_job(runtime, job.id):
        return
    try:
        _drive_professional_diagnosis(runtime, job, diagnosis_id, event)
    except PlatformError as exc:
        if exc.code == RUN_CANCELED:
            _cancel_job(runtime, job.id)
            return
        error = _job_error(exc)
        with runtime.session() as session:
            try:
                ProfessionalDiagnosticRepository(session).mark_failed(
                    diagnosis_id, error=error
                )
            except PlatformError:
                logger.exception("diagnosis %s 已处终态，失败结果不覆盖", diagnosis_id)
        _finish_job_failed(runtime, job.id, error)


def _drive_professional_diagnosis(
    runtime, job: AnalysisJobRecord, diagnosis_id: str, event: threading.Event
) -> None:
    with runtime.session() as session:
        diagnosis = ProfessionalDiagnosticRepository(session).get(diagnosis_id)
        dataset = DatasetRepository(session).get(diagnosis.dataset_version_id)

    if diagnosis.status == RunStatus.SUCCEEDED.value:
        # 采用既有成功（如任务在提交后崩遗重跑）：证据必须仍通过校验
        verify_manifest(diagnosis.manifest)
        with runtime.session() as session:
            AnalysisJobRepository(session).mark_succeeded(
                job.id, progress={"phase": "adopted_existing_success"}
            )
        return
    if diagnosis.status == RunStatus.FAILED.value:
        # 确定性重跑：同数据同配置的失败诊断以原结构化错误再失败
        stored = diagnosis.error or {}
        raise PlatformError(
            stored.get("code", "PROFESSIONAL_DIAGNOSIS_FAILED"),
            stored.get("message", "诊断已失败"),
            http_status=409,
        )
    if diagnosis.status == RunStatus.QUEUED.value:
        with runtime.session() as session:
            ProfessionalDiagnosticRepository(session).mark_running(diagnosis_id)
    # running 视为崩遗领养：直接续算（工件原子替换，重写无害）

    standardized = runtime.settings.standardized_dataset(dataset.case_id, dataset.id)
    if not standardized.is_file():
        raise PlatformError(
            "DATASET_NOT_FOUND",
            "标准化数据不存在",
            {"dataset_id": dataset.id},
            http_status=404,
        )
    standardized_sha256 = dataset.profile.get("standardized_sha256") or sha256_file(standardized)
    spec = VariogramDiagnosticSpec.model_validate(diagnosis.config["variogram"])
    frame = pd.read_parquet(standardized)
    valid = frame.loc[frame["is_numeric_valid"]].reset_index(drop=True)
    mapping = dataset.profile.get("mapping", {})
    coord_cols = ["x", "y"] + (["z"] if mapping.get("dimension") == "3d" else [])
    points = valid[coord_cols].to_numpy(dtype="float64")
    values = valid["value"].to_numpy(dtype="float64")

    total_bins = spec.lag_count * (1 + len(spec.directions))
    _persist_job_progress(
        runtime,
        job.id,
        {"phase": "empirical_variogram", "completed_bins": 0, "total_bins": total_bins},
    )
    empirical = compute_empirical_variogram(
        points, values, spec, data_sha256=standardized_sha256, cancel=event.is_set
    )
    if event.is_set():
        raise PlatformError(RUN_CANCELED, "任务已被取消", http_status=409)
    _persist_job_progress(
        runtime,
        job.id,
        {"phase": "fit_models", "completed_bins": total_bins, "total_bins": total_bins},
    )

    # 全向拟合：三模型全部拟合；任何失败都结构化失败（§17 禁止静默回退）
    models = [fit_variogram_evidence(empirical.omnidirectional, model) for model in MODELS]
    direction_fits: list[DirectionalFit] = []
    for index, directional_bins in enumerate(empirical.directional):
        direction = spec.directions[index]
        direction_id = f"d{index:03d}"
        used = [b for b in directional_bins if b.used_for_fit]
        if len(used) < MIN_FIT_BINS:
            # 点对不足的方向只披露、不参与比较（§6.3：不外推主方向）
            direction_fits.append(
                DirectionalFit(
                    direction_id=direction_id,
                    direction=direction,
                    status=STATUS_UNSUPPORTED_INSUFFICIENT_PAIRS,
                    fit=None,
                    used_pair_count=sum(b.pair_count for b in directional_bins),
                )
            )
            continue
        # supported 方向三模型全部拟合，取 weighted_sse 最优者参与候选比较
        fits = [fit_variogram_evidence(directional_bins, model) for model in MODELS]
        best = min(fits, key=lambda evidence: evidence.weighted_sse)
        direction_fits.append(
            DirectionalFit(
                direction_id=direction_id,
                direction=direction,
                status=STATUS_SUPPORTED,
                fit=best,
                used_pair_count=sum(b.pair_count for b in used),
            )
        )
    suggestion = suggest_anisotropy(direction_fits)

    if event.is_set():
        raise PlatformError(RUN_CANCELED, "任务已被取消", http_status=409)

    final_dir = runtime.settings.professional_diagnosis_dir(
        dataset.case_id, dataset.id, diagnosis_id
    )
    best_overall = min(models, key=lambda evidence: evidence.weighted_sse)
    metadata = {
        "diagnosis_id": diagnosis_id,
        "dataset_version_id": dataset.id,
        "fingerprint": diagnosis.fingerprint,
        "config": {"variogram": spec.model_dump(mode="json")},
        "standardized_sha256": standardized_sha256,
        "sampling": {
            "total_pair_count": empirical.sampling.total_pair_count,
            "used_pair_count": empirical.sampling.used_pair_count,
            "sampling_rate": empirical.sampling.sampling_rate,
            "sampled": empirical.sampling.sampled,
            "seed": empirical.sampling.seed,
        },
        "created_at": tables.utc_now_iso(),
    }
    directional_rows = [
        _direction_row(f"d{index:03d}", spec.directions[index], bin_index, bin_)
        for index, directional_bins in enumerate(empirical.directional)
        for bin_index, bin_ in enumerate(directional_bins)
    ]
    try:
        payloads = {
            "metadata.json": _json_bytes(metadata),
            "omnidirectional.csv": _csv_bytes(
                _OMNI_FIELDS,
                [_bin_row(index, bin_) for index, bin_ in enumerate(empirical.omnidirectional)],
            ),
            "directional.csv": _csv_bytes(_DIRECTION_FIELDS, directional_rows),
            "fitted_models.json": _json_bytes(
                {
                    "models": [m.model_dump(mode="json") for m in models],
                    "best_model": best_overall.model,
                    "parameter_origin": "automatic_candidate",
                }
            ),
            "anisotropy_candidates.json": _json_bytes(suggestion.model_dump(mode="json")),
        }
        entries = _write_artifact_dir(
            final_dir, payloads, error_code=DIAGNOSIS_ARTIFACT_WRITE_FAILED
        )
    except PlatformError:
        raise
    except Exception as exc:
        raise PlatformError(
            DIAGNOSIS_ARTIFACT_WRITE_FAILED,
            "诊断工件写入失败",
            {"reason": str(exc)[:200]},
        ) from exc

    artifact_names = {
        "metadata.json": "metadata",
        "omnidirectional.csv": "omnidirectional",
        "directional.csv": "directional",
        "fitted_models.json": "fitted_models",
        "anisotropy_candidates.json": "anisotropy_candidates",
    }
    manifest = {
        "version": 1,
        "diagnosis_id": diagnosis_id,
        "dataset_version_id": dataset.id,
        "fingerprint": diagnosis.fingerprint,
        "directory": str(final_dir),
        "artifacts": {artifact_names[name]: entry for name, entry in entries.items()},
        "summary": {
            "fitted_models": [m.model for m in models],
            "best_model": best_overall.model,
            "omni_used_bin_count": sum(
                1 for b in empirical.omnidirectional if b.used_for_fit
            ),
            "direction_count": len(spec.directions),
            "supported_direction_count": sum(
                1 for f in direction_fits if f.status == STATUS_SUPPORTED
            ),
            "skipped_direction_ids": list(suggestion.skipped_direction_ids),
            "candidate_ranks": [c.rank for c in suggestion.candidates],
            "warnings": list(suggestion.warnings),
        },
        "created_at": tables.utc_now_iso(),
    }
    _atomic_write_file(
        final_dir / "manifest.json",
        _json_bytes(manifest),
        error_code=DIAGNOSIS_ARTIFACT_WRITE_FAILED,
    )
    # 成功只在 manifest 校验通过后提交（§5.2）
    verify_manifest(manifest)
    with runtime.session() as session:
        ProfessionalDiagnosticRepository(session).mark_succeeded(
            diagnosis_id, manifest=manifest
        )
    with runtime.session() as session:
        AnalysisJobRepository(session).mark_succeeded(
            job.id,
            progress={
                "phase": "succeeded",
                "completed_bins": total_bins,
                "total_bins": total_bins,
            },
        )


# ---------------------------------------------------------------------------
# 不可变确认服务（§5.1/§6.4/§7.1）
# ---------------------------------------------------------------------------


class _AnisotropyConfirmation(ContractModel):
    """确认中的各向异性选择：「保持各向同性」与一组参数恰好其一（§7.1）。"""

    keep_isotropic: bool
    azimuth_deg: float | None = None
    dip_deg: float | None = None
    roll_deg: float | None = None
    major_minor_ratio: float | None = None
    major_vertical_ratio: float | None = None
    candidate_rank: int | None = None
    anisotropy_candidates_sha256: str | None = None

    @model_validator(mode="after")
    def _check_choice(self) -> "_AnisotropyConfirmation":
        if self.keep_isotropic:
            extras = (
                self.azimuth_deg,
                self.dip_deg,
                self.roll_deg,
                self.major_minor_ratio,
                self.major_vertical_ratio,
                self.candidate_rank,
                self.anisotropy_candidates_sha256,
            )
            if any(value is not None for value in extras):
                raise ValueError("保持各向同性时不得携带各向异性参数")
            return self
        for name in (
            "azimuth_deg",
            "major_minor_ratio",
            "candidate_rank",
            "anisotropy_candidates_sha256",
        ):
            if getattr(self, name) is None:
                raise ValueError(f"各向异性确认必须提供 {name}")
        for name in ("azimuth_deg", "dip_deg", "roll_deg", "major_minor_ratio", "major_vertical_ratio"):
            value = getattr(self, name)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{name} 必须为有限值")
        if not 0.0 <= float(self.azimuth_deg) < 180.0:
            raise ValueError("azimuth_deg 必须在 [0, 180) 内")
        if float(self.major_minor_ratio) <= 0.0:
            raise ValueError("major_minor_ratio 必须大于 0")
        if self.major_vertical_ratio is not None and float(self.major_vertical_ratio) <= 0.0:
            raise ValueError("major_vertical_ratio 必须大于 0")
        if int(self.candidate_rank) < 1:
            raise ValueError("candidate_rank 必须 ≥ 1")
        return self


class _ConfirmationConfig(ContractModel):
    """确认配置：模型类型、参数策略（自动候选证据引用 / 人工固定参数）与各向异性。"""

    model: Literal["spherical", "exponential", "gaussian"]
    parameter_strategy: Literal["automatic_candidate", "manual"]
    fitted_models_sha256: str | None = None
    manual_parameters: ManualVariogramParameters | None = None
    anisotropy: _AnisotropyConfirmation

    @model_validator(mode="after")
    def _check_strategy(self) -> "_ConfirmationConfig":
        if self.parameter_strategy == "automatic_candidate":
            if not self.fitted_models_sha256:
                raise ValueError("automatic_candidate 策略必须引用 fitted_models 证据")
            if self.manual_parameters is not None:
                raise ValueError("automatic_candidate 策略不接受人工固定参数")
        else:
            if self.manual_parameters is None:
                raise ValueError("manual 策略必须提供人工固定参数")
            if self.fitted_models_sha256 is not None:
                raise ValueError("manual 策略不引用自动拟合证据")
        return self


def _validate_manual_parameters(parameters: ManualVariogramParameters) -> None:
    """人工固定参数的有限性与范围校验（§6.4：标记为用户先验，同一失败通道）。"""

    nugget = float(parameters.nugget)
    sill = float(parameters.sill)
    range_ = float(parameters.range)
    for name, value in (("nugget", nugget), ("sill", sill), ("range", range_)):
        if not math.isfinite(value):
            raise PlatformError(
                PROFESSIONAL_CONFIRMATION_INVALID, f"人工变异函数参数必须为有限值：{name}"
            )
    if nugget < 0:
        raise PlatformError(PROFESSIONAL_CONFIRMATION_INVALID, "nugget 必须 ≥ 0")
    if sill <= nugget:
        raise PlatformError(
            PROFESSIONAL_CONFIRMATION_INVALID, "manual 模式要求 sill（总基台值）严格大于 nugget"
        )
    if range_ <= 0:
        raise PlatformError(PROFESSIONAL_CONFIRMATION_INVALID, "range 必须 > 0")


def confirm_professional_diagnosis(
    runtime, diagnosis_id: str, config: dict[str, Any], note: str
) -> ProfessionalConfirmationRecord:
    """为成功诊断插入一条不可变确认快照；永不更新既有快照（§5.1）。

    校验 manual/automatic 参数策略与证据引用：自动策略必须引用本诊断
    manifest 中的 fitted_models 证据哈希；人工固定参数标记 ``user_prior``；
    非各向同性确认必须引用 manifest 中存在的候选与证据哈希。IDW 不创建
    确认（服务层无 IDW 入口）。
    """

    with runtime.session() as session:
        diagnosis = ProfessionalDiagnosticRepository(session).get(diagnosis_id)
    if diagnosis.status != RunStatus.SUCCEEDED.value:
        raise PlatformError(
            PROFESSIONAL_DIAGNOSIS_NOT_SUCCEEDED,
            "只有成功诊断才能创建确认快照",
            {"diagnosis_id": diagnosis_id, "status": diagnosis.status},
            http_status=409,
        )
    if not note or not note.strip():
        raise PlatformError(PROFESSIONAL_CONFIRMATION_INVALID, "确认说明不能为空")
    try:
        parsed = _ConfirmationConfig.model_validate(config or {})
    except ValidationError as exc:
        raise PlatformError(
            PROFESSIONAL_CONFIRMATION_INVALID,
            "确认配置非法",
            {"reason": str(exc)[:300]},
        ) from exc

    artifacts = diagnosis.manifest.get("artifacts", {})
    summary = diagnosis.manifest.get("summary", {})
    if parsed.parameter_strategy == "automatic_candidate":
        expected = artifacts.get("fitted_models", {}).get("sha256")
        if parsed.fitted_models_sha256 != expected:
            raise PlatformError(
                PROFESSIONAL_CONFIRMATION_INVALID,
                "fitted_models 证据引用与诊断 manifest 不匹配",
                http_status=409,
            )
        if parsed.model not in summary.get("fitted_models", []):
            raise PlatformError(
                PROFESSIONAL_CONFIRMATION_INVALID,
                "确认模型不在诊断拟合证据中",
                {"model": parsed.model},
                http_status=409,
            )
    else:
        _validate_manual_parameters(parsed.manual_parameters)

    anisotropy = parsed.anisotropy
    if not anisotropy.keep_isotropic:
        expected = artifacts.get("anisotropy_candidates", {}).get("sha256")
        if anisotropy.anisotropy_candidates_sha256 != expected:
            raise PlatformError(
                PROFESSIONAL_CONFIRMATION_INVALID,
                "anisotropy_candidates 证据引用与诊断 manifest 不匹配",
                http_status=409,
            )
        if anisotropy.candidate_rank not in summary.get("candidate_ranks", []):
            raise PlatformError(
                PROFESSIONAL_CONFIRMATION_INVALID,
                "证据引用的候选不存在",
                {"candidate_rank": anisotropy.candidate_rank},
                http_status=409,
            )

    stored: dict[str, Any] = {
        "model": parsed.model,
        "parameter_strategy": parsed.parameter_strategy,
        "parameter_origin": (
            "automatic_candidate"
            if parsed.parameter_strategy == "automatic_candidate"
            else "manual_confirmed"
        ),
        "anisotropy": anisotropy.model_dump(mode="json"),
    }
    if parsed.parameter_strategy == "automatic_candidate":
        stored["fitted_models_sha256"] = parsed.fitted_models_sha256
    else:
        # 固定 nugget/sill/range 必须标记为用户先验（§6.4）
        stored["prior"] = "user_prior"
        stored["manual_parameters"] = parsed.manual_parameters.model_dump(mode="json")

    # 确认指纹 = 诊断 manifest 哈希 + 确认配置哈希（§5.1）
    manifest_sha256 = hashlib.sha256(
        tables.dumps_canonical(diagnosis.manifest).encode("utf-8")
    ).hexdigest()
    fingerprint = hashlib.sha256(
        tables.dumps_canonical(
            {"manifest_sha256": manifest_sha256, "config": stored}
        ).encode("utf-8")
    ).hexdigest()
    with runtime.session() as session:
        return ProfessionalConfirmationRepository(session).create(
            diagnosis_id, config=stored, fingerprint=fingerprint, note=note.strip()
        )


# ---------------------------------------------------------------------------
# 异常提取执行体
# ---------------------------------------------------------------------------

_COMPONENT_FIELDS = [
    "component_id",
    "support_node_count",
    "support_measure",
    "support_unit",
    "bounds",
    "centroid",
    "value_min",
    "value_max",
    "value_mean",
    "touches_grid_boundary",
    "empirical_error_scale_min",
    "empirical_error_scale_max",
    "empirical_error_scale_mean",
    "kriging_std_min",
    "kriging_std_max",
    "kriging_std_mean",
]


def execute_anomaly_extraction(
    runtime, job: AnalysisJobRecord, event: threading.Event
) -> None:
    """worker 入口：驱动异常提取到终态（语义与诊断执行体一致）。"""

    extraction_id = job.subject_id
    if not _begin_job(runtime, job.id):
        return
    try:
        _drive_anomaly_extraction(runtime, job, extraction_id, event)
    except PlatformError as exc:
        if exc.code == RUN_CANCELED:
            _cancel_job(runtime, job.id)
            return
        error = _job_error(exc)
        with runtime.session() as session:
            try:
                AnomalyExtractionRepository(session).mark_failed(extraction_id, error=error)
            except PlatformError:
                logger.exception("extraction %s 已处终态，失败结果不覆盖", extraction_id)
        _finish_job_failed(runtime, job.id, error)


def _load_uncertainty_layer(
    path: Path, name: str, gate: float | None
) -> UncertaintyLayer | None:
    """读取已登记的不确定性层；门槛已请求而层缺失时结构化失败（§12.1/§17）。"""

    if gate is None:
        return None
    if not path.is_file():
        raise PlatformError(
            ANOMALY_UNCERTAINTY_UNAVAILABLE,
            f"已请求 {name} 不确定性上限，但对应层不存在；不得忽略该门槛",
            {"layer": name},
            http_status=409,
        )
    with np.load(path) as bundle:
        return UncertaintyLayer(values=bundle["values"], is_nodata=bundle["is_nodata"])


def _eligible_mask(
    grid,
    spec: AnomalyExtractionSpec,
    empirical_layer: UncertaintyLayer | None,
    kriging_layer: UncertaintyLayer | None,
) -> np.ndarray:
    """按 §12.1 规则复算掩膜（``extract_anomalies`` 不返回掩膜，工件需要）。

    语义与 ``modeling.anomalies`` 逐条对应：NoData/非有限节点不进入；
    高值 ``>=`` / 低值 ``<=``（含等号）；不确定性层门槛内 NoData/非有限
    节点不进入。复算结果与提取诊断的 ``eligible_node_count`` 互证。
    """

    values = np.asarray(grid.values, dtype=np.float64)
    finite = np.isfinite(values)
    base = ~grid.is_nodata & finite
    if spec.direction == "high":
        mask = base & (values >= spec.threshold)
    else:
        mask = base & (values <= spec.threshold)
    for layer, gate in (
        (empirical_layer, spec.empirical_error_max),
        (kriging_layer, spec.kriging_std_max),
    ):
        if layer is None or gate is None:
            continue
        mask &= ~layer.is_nodata & np.isfinite(layer.values) & (layer.values <= gate)
    return mask


def _component_row(component: AnomalyComponent) -> dict[str, Any]:
    row = component.model_dump(mode="json")
    row["bounds"] = json.dumps(row["bounds"], ensure_ascii=False)
    row["centroid"] = json.dumps(row["centroid"], ensure_ascii=False)
    return row


def _drive_anomaly_extraction(
    runtime, job: AnalysisJobRecord, extraction_id: str, event: threading.Event
) -> None:
    with runtime.session() as session:
        extraction = AnomalyExtractionRepository(session).get(extraction_id)

    if extraction.status == "succeeded":
        # 采用既有成功：证据必须仍通过 manifest 校验
        verify_manifest(extraction.manifest)
        with runtime.session() as session:
            AnalysisJobRepository(session).mark_succeeded(
                job.id, progress={"phase": "adopted_existing_success"}
            )
        return
    if extraction.status == "failed":
        # 确定性重跑：同成果同配置的失败提取以原结构化错误再失败
        stored = extraction.error or {}
        raise PlatformError(
            stored.get("code", "ANOMALY_EXTRACTION_FAILED"),
            stored.get("message", "异常提取已失败"),
            http_status=409,
        )

    result_id = extraction.candidate_result_id
    grid = load_grid(runtime, result_id)  # RESULT_NOT_MATERIALIZED → 404
    spec = AnomalyExtractionSpec.model_validate(extraction.config)
    professional_dir = runtime.settings.professional_result_dir(result_id)
    empirical_layer = _load_uncertainty_layer(
        professional_dir / "empirical_error_scale.npz",
        "empirical_error_scale",
        spec.empirical_error_max,
    )
    kriging_layer = _load_uncertainty_layer(
        professional_dir / "kriging_standard_deviation.npz",
        "kriging_std",
        spec.kriging_std_max,
    )

    _persist_job_progress(runtime, job.id, {"phase": "extract_components"})
    outcome = extract_anomalies(
        axes=grid.axes,
        values=grid.values,
        is_nodata=grid.is_nodata,
        spec=spec,
        empirical_error_scale=empirical_layer,
        kriging_std=kriging_layer,
        cancel=event.is_set,
    )
    if event.is_set():
        raise PlatformError(RUN_CANCELED, "任务已被取消", http_status=409)
    mask = _eligible_mask(grid, spec, empirical_layer, kriging_layer)
    if int(mask.sum()) != outcome.diagnostics["eligible_node_count"]:
        raise PlatformError(
            ANOMALY_INTERNAL_INCONSISTENT,
            "掩膜复算与提取诊断不一致",
            {
                "recomputed": int(mask.sum()),
                "reported": outcome.diagnostics["eligible_node_count"],
            },
            http_status=409,
        )

    final_dir = runtime.settings.anomaly_extraction_dir(result_id, extraction_id)
    summary = {
        "extraction_id": extraction_id,
        "candidate_result_id": result_id,
        "fingerprint": extraction.fingerprint,
        "config": spec.model_dump(mode="json"),
        "grid_sha256": grid.metadata.get("grid_sha256"),
        "diagnostics": outcome.diagnostics,
        "created_at": tables.utc_now_iso(),
    }
    try:
        payloads = {
            "mask.npz": _npz_bytes(axes=np.array(grid.axes, dtype=object), mask=mask),
            "components.csv": _csv_bytes(
                _COMPONENT_FIELDS, [_component_row(c) for c in outcome.components]
            ),
            "summary.json": _json_bytes(summary),
        }
        entries = _write_artifact_dir(
            final_dir, payloads, error_code=ANOMALY_ARTIFACT_WRITE_FAILED
        )
    except PlatformError:
        raise
    except Exception as exc:
        raise PlatformError(
            ANOMALY_ARTIFACT_WRITE_FAILED,
            "异常工件写入失败",
            {"reason": str(exc)[:200]},
        ) from exc

    artifact_names = {
        "mask.npz": "mask",
        "components.csv": "components",
        "summary.json": "summary",
    }
    manifest = {
        "version": 1,
        "extraction_id": extraction_id,
        "candidate_result_id": result_id,
        "fingerprint": extraction.fingerprint,
        "directory": str(final_dir),
        "artifacts": {artifact_names[name]: entry for name, entry in entries.items()},
        "summary": {
            "component_count": len(outcome.components),
            "eligible_node_count": outcome.diagnostics["eligible_node_count"],
            "empirical_error_gated": outcome.diagnostics["empirical_error_gated"],
            "kriging_std_gated": outcome.diagnostics["kriging_std_gated"],
        },
        "created_at": tables.utc_now_iso(),
    }
    _atomic_write_file(
        final_dir / "manifest.json",
        _json_bytes(manifest),
        error_code=ANOMALY_ARTIFACT_WRITE_FAILED,
    )
    # 成功只在 manifest 校验通过后提交（§5.2）
    verify_manifest(manifest)
    with runtime.session() as session:
        AnomalyExtractionRepository(session).mark_succeeded(extraction_id, manifest=manifest)
    with runtime.session() as session:
        AnalysisJobRepository(session).mark_succeeded(
            job.id,
            progress={"phase": "succeeded", "component_count": len(outcome.components)},
        )


# ---------------------------------------------------------------------------
# 双候选比较服务（设计 §4.3/§13.3）：只读已登记工件，绝不重跑模型
# ---------------------------------------------------------------------------


def _comparison_context(runtime, result_id: str) -> dict[str, Any]:
    """读取候选的归属链、数据版本 profile 与已登记折证据（只读）。

    候选必须存在且为 succeeded；折证据（OOF / fold_assignments）缺失以
    ``COMPARISON_EVIDENCE_INCOMPLETE`` 结构化失败——没有登记证据就不比
    较，绝不现场重跑补齐。验证折分指纹从登记的 fold_assignments 工件重
    算（与 run 期定义逐位一致）。
    """

    candidate, _run, experiment = _load_candidate(runtime, result_id)
    if candidate.status != RunStatus.SUCCEEDED.value:
        raise PlatformError(
            CANDIDATE_NOT_SUCCEEDED,
            "只有成功候选才能参与比较",
            {"result_id": result_id, "status": candidate.status},
            http_status=409,
        )
    params = tables.loads_canonical(experiment.params_json)
    dataset_version_id = params["dataset_version_id"]
    with runtime.session() as session:
        dataset = session.get(tables.DatasetVersion, dataset_version_id)
    if dataset is None:
        raise PlatformError(
            "DATASET_NOT_FOUND",
            "候选所属数据版本缺失，归属链不完整",
            {"result_id": result_id, "dataset_version_id": dataset_version_id},
            http_status=409,
        )
    profile = tables.loads_canonical(dataset.profile_json)

    professional_dir = runtime.settings.professional_result_dir(result_id)
    oof_path = professional_dir / "out_of_fold_predictions.parquet"
    assignments_path = professional_dir / "fold_assignments.parquet"
    for evidence in (oof_path, assignments_path):
        if not evidence.is_file():
            raise PlatformError(
                COMPARISON_EVIDENCE_INCOMPLETE,
                "候选折证据不完整，无法比较",
                {"result_id": result_id, "artifact": evidence.name},
                http_status=409,
            )
    data_sha256 = profile.get("standardized_sha256") or sha256_file(
        runtime.settings.standardized_dataset(experiment.case_id, dataset_version_id)
    )
    validation = SpatialValidationSpec.model_validate(params.get("validation") or {})
    assignments = pd.read_parquet(assignments_path)
    mapping = profile.get("mapping", {})
    return {
        "candidate": candidate,
        "dataset_version_id": dataset_version_id,
        "value_name": mapping.get("value_name"),
        "value_unit": mapping.get("value_unit"),
        "oof": pd.read_parquet(oof_path),
        "validation_fingerprint": validation_fingerprint_from_assignments(
            assignments, validation=validation, data_sha256=data_sha256
        ),
    }


def compare_candidates(runtime, first_result_id: str, second_result_id: str) -> CandidateComparison:
    """比较两个成功候选，返回兼容判定与（兼容时）同口径指标差。

    兼容条件（全部满足才 compatible）：同一 ``dataset_version_id``、同一
    验证折分指纹、同一 OOF ``source_row`` 集合、同一值单位
    （value_name/value_unit 来自数据集 profile）。指标差只在所选候选的
    公共有效交集上重算（first − second），绝不复用各 run 预存的公共掩
    膜；交集为空视为不兼容（``common_valid_mask``）。不兼容仍可分别打
    开，但 ``metric_deltas``/``common_valid_count`` 一律 None。

    场差只在两候选网格轴完全一致且已物化时，于共同有效网格节点上给出
    有界摘要；否则 ``grid_difference_available=False`` 且不生成差值。
    同一候选（first == second）以 ``COMPARISON_SAME_CANDIDATE`` 结构化
    错误拒绝。归属解析（case → dataset → experiment → run → result 链
    路校验）留给 Task 17 API 层；本服务只校验两候选存在且为 succeeded。
    """

    if first_result_id == second_result_id:
        raise PlatformError(
            COMPARISON_SAME_CANDIDATE,
            "候选不能与自身比较",
            {"result_id": first_result_id},
            http_status=409,
        )
    first = _comparison_context(runtime, first_result_id)
    second = _comparison_context(runtime, second_result_id)

    mismatches: list[str] = []
    if first["dataset_version_id"] != second["dataset_version_id"]:
        mismatches.append("dataset_version_id")
    if (first["value_name"], first["value_unit"]) != (
        second["value_name"],
        second["value_unit"],
    ):
        mismatches.append("value_unit")
    if first["validation_fingerprint"] != second["validation_fingerprint"]:
        mismatches.append("validation_fingerprint")
    first_rows = sorted(int(row) for row in first["oof"]["source_row"].unique())
    second_rows = sorted(int(row) for row in second["oof"]["source_row"].unique())
    if first_rows != second_rows:
        mismatches.append("source_row")
    fingerprint = comparison_fingerprint(
        first["candidate"].fingerprint,
        second["candidate"].fingerprint,
        sorted(set(first_rows) & set(second_rows)),
    )

    common_valid_count: int | None = None
    metric_deltas: dict[str, float] | None = None
    if not mismatches:
        aligned_first, aligned_second = align_oof_pair(first["oof"], second["oof"])
        mask = pair_common_valid_mask(aligned_first, aligned_second)
        if not mask.any():
            # 公共有效集合为空：无任何同口径指标可展示，视为不兼容
            mismatches.append("common_valid_mask")
        else:
            common_valid_count, metric_deltas = pair_metric_deltas(
                aligned_first, aligned_second, mask
            )
    if mismatches:
        return CandidateComparison(
            first_result_id=first_result_id,
            second_result_id=second_result_id,
            compatible=False,
            mismatches=mismatches,
            common_valid_count=None,
            metric_deltas=None,
            grid_difference_available=False,
            grid_difference=None,
            comparison_fingerprint=fingerprint,
        )

    grid_difference = None
    try:
        first_grid = load_grid(runtime, first_result_id)
        second_grid = load_grid(runtime, second_result_id)
    except PlatformError as exc:
        if exc.code != RESULT_NOT_MATERIALIZED:
            raise
    else:
        if grid_axes_identical(first_grid.axes, second_grid.axes):
            grid_difference = grid_difference_summary(
                first_grid.values,
                first_grid.is_nodata,
                second_grid.values,
                second_grid.is_nodata,
            )
    return CandidateComparison(
        first_result_id=first_result_id,
        second_result_id=second_result_id,
        compatible=True,
        mismatches=[],
        common_valid_count=common_valid_count,
        metric_deltas=metric_deltas,
        grid_difference_available=grid_difference is not None,
        grid_difference=grid_difference,
        comparison_fingerprint=fingerprint,
    )
