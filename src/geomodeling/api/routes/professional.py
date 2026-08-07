"""v0.6 professional analysis public API (设计 §14).

诊断/异常提取是长任务：请求先落库再入队（``worker.enqueue_analysis``），
响应 202 + 任务身份（job_id/subject_id/status），绝不在请求线程执行长计
算；同指纹成功幂等返回 200（``reused=true``，无新任务）。取消/重试与插值
run 同一合同：cancel 只变更当前分析任务（终态行完全不可变），retry 产生
新身份（``retry_of_job_id``）且从不改写原任务记录。

每条链都先经 repositories 解析归属（case → dataset → experiment → run →
result；diagnosis → dataset，extraction → candidate）再读文件。公共响应全
部经过 ``platform.public_dto`` 白名单/递归清理：工件只暴露逻辑名、行数、
大小与 SHA-256，manifest 内部的服务器 ``directory`` 绝对路径绝不外传。

大表（变异函数 bins / OOF 残差 / 连通区）行数上限内联 + ``decimate`` 抽
稀，完整工件走 ``/api/professional-artifacts/{artifact_id}/download``：
只接受「类别:subject:逻辑名」三段式已登记身份，路径从 manifest 白名单
（登记目录 + 纯基名 file）解析并逐件校验哈希，绝不拼接客户端输入。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field

from geomodeling.api.deps import get_platform_runtime
from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.analysis_jobs import (
    create_anomaly_extraction,
    create_professional_diagnosis,
    get_analysis_job,
    get_anomaly_extraction,
    get_professional_diagnosis,
    retry_analysis_job,
)
from geomodeling.platform.errors import (
    PROFESSIONAL_ARTIFACTS_NOT_FOUND,
    PROFESSIONAL_DIAGNOSIS_NOT_SUCCEEDED,
    PlatformError,
)
from geomodeling.platform.professional import (
    MANIFEST_VERIFICATION_FAILED,
    compare_candidates,
    confirm_professional_diagnosis,
)
from geomodeling.platform.public_dto import (
    public_analysis_job,
    public_anomaly_extraction,
    public_comparison,
    public_confirmation,
    public_fold_evidence,
    public_professional_diagnosis,
    public_professional_result,
    public_residuals,
    public_variogram_evidence,
)
from geomodeling.platform.repositories import (
    AnalysisJobRepository,
    DatasetRepository,
    require_active_dataset,
    require_active_candidate,
)
from geomodeling.platform.results import CANDIDATE_NOT_SUCCEEDED, _load_candidate, preview
from geomodeling.platform.schemas import ContractModel, ProfessionalDiagnosisRequest
from geomodeling.platform.candidate_comparisons import CandidateComparisonRequest
from geomodeling.platform.tables import AnalysisJob, RunStatus

router = APIRouter(tags=["v0.6-professional"])

ANALYSIS_JOB_NOT_CANCELABLE = "ANALYSIS_JOB_NOT_CANCELABLE"
PROFESSIONAL_ARTIFACT_NOT_FOUND = "PROFESSIONAL_ARTIFACT_NOT_FOUND"
COMPARISON_NOT_FOUND = "COMPARISON_NOT_FOUND"
DATASET_NOT_VALIDATED = "DATASET_NOT_VALIDATED"

# 大表内联行数硬上限（decimate 之外的第二道闸，与微震诊断点同一范式）
MAX_VARIOGRAM_ROWS = 2_000
MAX_RESIDUAL_ROWS = 5_000
MAX_COMPONENT_ROWS = 500
MAX_FOLD_GROUPS = 200

_ARTIFACT_MEDIA_TYPES = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".parquet": "application/octet-stream",
    ".npz": "application/octet-stream",
}

# 比较登记身份 = comparison_fingerprint（64 位十六进制）
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


def _worker(request: Request):
    return getattr(request.app.state, "job_worker", None)


def _artifact_url(kind: str, subject_id: str, logical_name: str) -> str:
    return f"/api/professional-artifacts/{kind}:{subject_id}:{logical_name}/download"


# ---------------------------------------------------------------------------
# 专业诊断
# ---------------------------------------------------------------------------


@router.post("/api/datasets/{dataset_id}/professional-diagnostics")
def request_professional_diagnosis(
    dataset_id: str,
    request_body: ProfessionalDiagnosisRequest,
    request: Request,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> JSONResponse:
    """创建专业诊断请求：202 + 任务身份；同指纹成功幂等返回 200。"""

    require_active_dataset(runtime, dataset_id)
    with runtime.session() as session:
        dv = session.get(tables.DatasetVersion, dataset_id)
        if dv is None or dv.status != "validated":
            raise PlatformError(
                DATASET_NOT_VALIDATED,
                "只有已校验（validated）的数据集才能发起专业诊断",
                {"dataset_id": dataset_id, "status": dv.status if dv else None},
                http_status=409,
            )
    record = create_professional_diagnosis(
        runtime, dataset_id, request_body.model_dump(mode="json")
    )
    # 先读 subject 状态再入队：响应身份不受 worker 并发翻转影响（确定性）
    subject = get_professional_diagnosis(runtime, record.id)
    body = {
        "diagnosis_id": record.id,
        "job_id": record.job_id,
        "status": getattr(subject.status, "value", subject.status),
        "reused": record.reused,
    }
    if record.job_id is not None:
        worker = _worker(request)
        if worker is not None:
            worker.enqueue_analysis(record.job_id)
    return JSONResponse(status_code=200 if record.reused else 202, content=body)


@router.get("/api/datasets/{dataset_id}/professional-diagnostics")
def list_professional_diagnostics(
    dataset_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """List diagnostics for a dataset, newest-first, with job summary and view URL."""

    require_active_dataset(runtime, dataset_id)
    from geomodeling.platform.repositories import (
        ProfessionalDiagnosticRepository,
        AnalysisJobRepository,
        _analysis_job_record,
    )
    from geomodeling.platform.public_dto import public_professional_diagnosis, public_analysis_job
    from sqlalchemy import select as sa_select

    with runtime.session() as session:
        diagnoses = ProfessionalDiagnosticRepository(session).list_for_dataset(dataset_id)
        items = []
        for diag in diagnoses:
            job_record = None
            job_row = session.scalar(
                sa_select(AnalysisJob)
                .where(
                    AnalysisJob.subject_id == diag.id,
                    AnalysisJob.job_kind == "professional_diagnosis",
                )
                .order_by(AnalysisJob.created_at.desc())
                .limit(1)
            )
            if job_row is not None:
                job_record = _analysis_job_record(job_row)
            items.append({
                "diagnosis": public_professional_diagnosis(diag),
                "job": public_analysis_job(job_record) if job_record else None,
                "url": f"/datasets/{dataset_id}/professional-diagnosis?diagnosis={diag.id}",
            })
    return {"dataset_id": dataset_id, "diagnostics": items}


@router.get("/api/professional-confirmations/{confirmation_id}")
def get_professional_confirmation(
    confirmation_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """Read a confirmation snapshot with diagnosis/dataset/case identity."""

    from geomodeling.platform.repositories import (
        ProfessionalConfirmationRepository,
        ProfessionalDiagnosticRepository,
        DatasetRepository,
        CaseRepository,
    )
    from geomodeling.platform.public_dto import public_confirmation, public_professional_diagnosis
    from geomodeling.platform.errors import PROFESSIONAL_DIAGNOSIS_NOT_SUCCEEDED

    with runtime.session() as session:
        conf_repo = ProfessionalConfirmationRepository(session)
        confirmation = conf_repo.get(confirmation_id)
        diag_repo = ProfessionalDiagnosticRepository(session)
        diagnosis = diag_repo.get(confirmation.diagnostic_id)
        dataset = DatasetRepository(session).get(diagnosis.dataset_version_id)
        case = CaseRepository(session).get_active(dataset.case_id)

        return {
            "confirmation": public_confirmation(confirmation),
            "diagnosis_id": diagnosis.id,
            "diagnosis_status": getattr(diagnosis.status, "value", diagnosis.status),
            "dataset_id": dataset.id,
            "case_id": case.id,
            "fingerprint": confirmation.fingerprint,
            "config_summary": confirmation.config,
        }


def _load_succeeded_diagnosis(runtime: PlatformRuntime, diagnosis_id: str):
    """解析诊断与归属数据版本；非 succeeded 诊断 409（证据只在成功态公开）。"""

    record = get_professional_diagnosis(runtime, diagnosis_id)
    require_active_dataset(runtime, record.dataset_version_id)
    if record.status != RunStatus.SUCCEEDED.value:
        raise PlatformError(
            PROFESSIONAL_DIAGNOSIS_NOT_SUCCEEDED,
            "只有成功诊断才能公开变异函数证据",
            {"diagnosis_id": diagnosis_id, "status": record.status},
            http_status=409,
        )
    return record


@router.get("/api/professional-diagnostics/{diagnosis_id}")
def get_professional_diagnosis_dto(
    diagnosis_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """诊断状态、指纹、manifest 摘要（逻辑工件名/大小/SHA-256）与错误。"""

    record = get_professional_diagnosis(runtime, diagnosis_id)
    require_active_dataset(runtime, record.dataset_version_id)
    return public_professional_diagnosis(record)


def _bounded_rows(frame: pd.DataFrame, decimate: int, cap: int) -> dict[str, Any]:
    """有界内联：decimate 抽稀 + 硬上限；NaN→null、numpy→原生 JSON 类型。"""

    total = len(frame)
    stride = max(decimate, math.ceil(total / cap) if total else 1)
    view = frame.iloc[::stride]
    return {
        "total": total,
        "returned": len(view),
        "decimate": stride,
        "rows": json.loads(view.to_json(orient="records")),
    }


def _read_csv_artifact(manifest: dict[str, Any], logical_name: str) -> pd.DataFrame:
    entry = (manifest.get("artifacts") or {}).get(logical_name) or {}
    return pd.read_csv(Path(manifest["directory"]) / entry["file"], encoding="utf-8")


def _read_json_artifact(manifest: dict[str, Any], logical_name: str) -> Any:
    entry = (manifest.get("artifacts") or {}).get(logical_name) or {}
    return json.loads((Path(manifest["directory"]) / entry["file"]).read_text(encoding="utf-8"))


def _bool_column(frame: pd.DataFrame, name: str) -> None:
    """CSV 中的 true/false 文本列还原为布尔（就地）。"""

    if name in frame.columns and frame[name].dtype == object:
        frame[name] = frame[name].map({"true": True, "false": False})


@router.get("/api/professional-diagnostics/{diagnosis_id}/variogram")
def get_diagnosis_variogram(
    diagnosis_id: str,
    decimate: int = Query(1, ge=1, le=1000),
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """全向 + 方向经验半变异函数 bins（行数上限内联，完整工件走下载）。"""

    record = _load_succeeded_diagnosis(runtime, diagnosis_id)
    manifest = record.manifest
    omni = _read_csv_artifact(manifest, "omnidirectional")
    directional = _read_csv_artifact(manifest, "directional")
    for frame in (omni, directional):
        _bool_column(frame, "used_for_fit")
    metadata = _read_json_artifact(manifest, "metadata")
    return public_variogram_evidence(
        diagnosis_id,
        omnidirectional=_bounded_rows(omni, decimate, MAX_VARIOGRAM_ROWS),
        directional=_bounded_rows(directional, decimate, MAX_VARIOGRAM_ROWS),
        fitted_models=_read_json_artifact(manifest, "fitted_models"),
        anisotropy_candidates=_read_json_artifact(manifest, "anisotropy_candidates"),
        sampling=metadata.get("sampling") or {},
        downloads={
            "omnidirectional": _artifact_url("diagnosis", diagnosis_id, "omnidirectional"),
            "directional": _artifact_url("diagnosis", diagnosis_id, "directional"),
            "fitted_models": _artifact_url("diagnosis", diagnosis_id, "fitted_models"),
            "anisotropy_candidates": _artifact_url(
                "diagnosis", diagnosis_id, "anisotropy_candidates"
            ),
        },
    )


class ConfirmationBody(ContractModel):
    """确认请求体：模型类型、参数策略（自动候选证据引用/人工固定参数）与各向异性。

    与服务层 ``_ConfirmationConfig`` 同一载荷形状；严格校验在服务层执行，
    ``note`` 必填（§5.1/§7.1）。
    """

    model: Literal["spherical", "exponential", "gaussian"]
    parameter_strategy: Literal["automatic_candidate", "manual"]
    fitted_models_sha256: str | None = None
    manual_parameters: dict[str, Any] | None = None
    anisotropy: dict[str, Any] = Field(default_factory=dict)
    note: str = Field(min_length=1, max_length=2000)


@router.post("/api/professional-diagnostics/{diagnosis_id}/confirm", status_code=201)
def confirm_diagnosis(
    diagnosis_id: str,
    request_body: ConfirmationBody,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """为成功诊断创建不可变确认快照（201）；非 succeeded 诊断 409。"""

    _diag = get_professional_diagnosis(runtime, diagnosis_id)
    require_active_dataset(runtime, _diag.dataset_version_id)
    record = confirm_professional_diagnosis(
        runtime,
        diagnosis_id,
        request_body.model_dump(mode="json", exclude={"note"}),
        request_body.note,
    )
    return public_confirmation(record)


# ---------------------------------------------------------------------------
# 分析任务生命周期（与插值 run 同一合同）
# ---------------------------------------------------------------------------


@router.get("/api/analysis-jobs/{job_id}")
def get_analysis_job_dto(
    job_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    return public_analysis_job(get_analysis_job(runtime, job_id))


@router.post("/api/analysis-jobs/{job_id}/cancel")
def cancel_analysis_job(
    job_id: str,
    request: Request,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """取消分析任务：queued 原子转 canceled；running 写取消旗标协作退出。

    取消只影响当前任务——终态行完全不可变，subject 行与既有成功工件不改写。
    """

    with runtime.session() as session:
        repo = AnalysisJobRepository(session)
        record = repo.get(job_id)
        if record.status in tables.RUN_TERMINAL_STATUSES:
            raise PlatformError(
                ANALYSIS_JOB_NOT_CANCELABLE,
                "终态分析任务不能取消（已成功/失败/取消/中断的任务不可再变更）",
                {"job_id": job_id, "status": record.status},
                http_status=409,
            )
        if record.status == "queued":
            record = repo.cancel(job_id)
        else:
            worker = _worker(request)
            if worker is not None:
                worker.cancel_analysis(job_id)
            record = repo.get(job_id)
    return public_analysis_job(record)


@router.post("/api/analysis-jobs/{job_id}/retry", status_code=201)
def retry_analysis_job_route(
    job_id: str,
    request: Request,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """从 failed/canceled/interrupted 重试：新身份 + ``retry_of_job_id``，原记录不改写。"""

    record = retry_analysis_job(runtime, job_id)
    worker = _worker(request)
    if worker is not None:
        worker.enqueue_analysis(record.id)
    return public_analysis_job(record)


# ---------------------------------------------------------------------------
# 成果专业证据
# ---------------------------------------------------------------------------


def _load_succeeded_candidate(runtime: PlatformRuntime, result_id: str):
    """归属链（result → run → experiment）+ succeeded 门禁。"""

    candidate, run, experiment = _load_candidate(runtime, result_id)
    if candidate.status != "succeeded":
        raise PlatformError(
            CANDIDATE_NOT_SUCCEEDED,
            "只有成功候选才能公开专业证据",
            {"result_id": result_id, "status": candidate.status},
            http_status=409,
        )
    return candidate, run, experiment


@router.get("/api/results/{result_id}/professional")
def get_professional_result(
    result_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """成果专业证据：capabilities、参数出处与已登记 manifest 摘要。

    legacy 候选（无专业工件集合）明确返回
    ``{"available": false, "reason": "LEGACY_RESULT_NOT_COMPUTED"}``，
    绝不伪造零值指标或能力。
    """

    require_active_candidate(runtime, result_id)
    candidate, _run, experiment = _load_succeeded_candidate(runtime, result_id)
    params = tables.loads_canonical(experiment.params_json)
    algorithm = params["algorithm"]
    with runtime.session() as session:
        artifacts_row = (
            session.query(tables.ProfessionalResultArtifacts)
            .filter(tables.ProfessionalResultArtifacts.candidate_result_id == result_id)
            .one_or_none()
        )
    if artifacts_row is None:
        if params.get("professional") is None:
            return public_professional_result(
                result_id,
                algorithm=algorithm,
                confirmation_id=None,
                capabilities=None,
                parameter_provenance=None,
                manifest=None,
            )
        raise PlatformError(
            PROFESSIONAL_ARTIFACTS_NOT_FOUND,
            "专业候选缺少工件集合，证据不完整",
            {"result_id": result_id},
            http_status=404,
        )
    manifest = (
        tables.loads_canonical(artifacts_row.manifest_json) if artifacts_row.manifest_json else {}
    )
    # 参数出处住在物化期 metadata.json（已登记工件）；未物化时为 None
    provenance = None
    metadata_path = runtime.settings.professional_result_dir(result_id) / "metadata.json"
    if metadata_path.is_file():
        provenance = json.loads(metadata_path.read_text(encoding="utf-8")).get(
            "parameter_provenance"
        )
    return public_professional_result(
        result_id,
        algorithm=algorithm,
        confirmation_id=artifacts_row.confirmation_id,
        capabilities=(
            tables.loads_canonical(artifacts_row.capabilities_json)
            if artifacts_row.capabilities_json
            else {}
        ),
        parameter_provenance=provenance,
        manifest=manifest or None,
    )


@router.get("/api/results/{result_id}/folds")
def get_result_folds(
    result_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """折分证据：折数、逐折训练/验证计数、空间组身份、泄漏检查与逐折指标（有界）。"""

    require_active_candidate(runtime, result_id)
    candidate, _run, _experiment = _load_succeeded_candidate(runtime, result_id)
    assignments_path = (
        runtime.settings.professional_result_dir(result_id) / "fold_assignments.parquet"
    )
    if not assignments_path.is_file():
        raise PlatformError(
            PROFESSIONAL_ARTIFACT_NOT_FOUND,
            "折分证据未登记，成果证据不完整",
            {"result_id": result_id, "artifact": "fold_assignments"},
            http_status=404,
        )
    assignments = pd.read_parquet(assignments_path)
    metrics = tables.loads_canonical(candidate.metrics_json) if candidate.metrics_json else {}
    fold_metrics = {
        int(entry["fold"]): {"rmse": entry.get("rmse"), "valid_count": entry.get("valid_count")}
        for entry in metrics.get("fold_metrics") or []
    }
    folds: list[dict[str, Any]] = []
    for fold_index, group in assignments.groupby("fold_index"):
        validation = group[group["role"] == "validation"]
        groups = sorted(int(key) for key in validation["group_key"].unique())
        folds.append(
            {
                "fold_index": int(fold_index),
                "training_count": int((group["role"] == "training").sum()),
                "validation_count": int(len(validation)),
                "validation_groups": groups[:MAX_FOLD_GROUPS],
                "group_count": len(groups),
                "leakage_detected": bool(group["leakage_detected"].any()),
                "metrics": fold_metrics.get(int(fold_index)),
            }
        )
    folds.sort(key=lambda fold: fold["fold_index"])
    return public_fold_evidence(
        result_id,
        fold_count=len(folds),
        leakage_detected=bool(assignments["leakage_detected"].any()),
        folds=folds,
        download_url=_artifact_url("result", result_id, "fold_assignments"),
    )


@router.get("/api/results/{result_id}/residuals")
def get_result_residuals(
    result_id: str,
    decimate: int = Query(1, ge=1, le=1000),
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """OOF 残差表：行数上限内联 + decimate 抽稀；完整 parquet 走白名单下载。"""

    require_active_candidate(runtime, result_id)
    _load_succeeded_candidate(runtime, result_id)
    oof_path = (
        runtime.settings.professional_result_dir(result_id) / "out_of_fold_predictions.parquet"
    )
    if not oof_path.is_file():
        raise PlatformError(
            PROFESSIONAL_ARTIFACT_NOT_FOUND,
            "折外残差证据未登记，成果证据不完整",
            {"result_id": result_id, "artifact": "out_of_fold_predictions"},
            http_status=404,
        )
    frame = pd.read_parquet(oof_path)
    total = len(frame)
    stride = max(decimate, math.ceil(total / MAX_RESIDUAL_ROWS) if total else 1)
    view = frame.iloc[::stride]
    column_names = [
        "source_row",
        "fold_index",
        "x",
        "y",
        "z",
        "observed",
        "predicted",
        "residual",
        "absolute_error",
        "squared_error",
        "is_nodata",
    ]
    columns = {
        name: json.loads(view[name].to_json(orient="values")) for name in column_names
    }
    return public_residuals(
        result_id,
        total=total,
        returned=len(view),
        decimate=stride,
        columns=columns,
        download_url=_artifact_url("result", result_id, "out_of_fold_predictions"),
    )


@router.get("/api/results/{result_id}/uncertainty/{kind}")
def get_result_uncertainty(
    result_id: str,
    kind: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """不确定性层有界抽稀预览：kind=empirical_error|kriging_std。

    能力不适用（IDW 请求 kriging_std）409；层未物化 404；绝不返回 0 场。
    """

    require_active_candidate(runtime, result_id)
    return preview(runtime, result_id, layer=kind)


# ---------------------------------------------------------------------------
# 异常提取
# ---------------------------------------------------------------------------


@router.post("/api/results/{result_id}/anomaly-extractions")
def request_anomaly_extraction(
    result_id: str,
    request: Request,
    config: dict[str, Any] = Body(default_factory=dict),
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> JSONResponse:
    """创建异常提取请求：202 + 任务身份；同成果同配置成功幂等返回 200。"""

    require_active_candidate(runtime, result_id)
    record = create_anomaly_extraction(runtime, result_id, config)
    # 先读 subject 状态再入队：响应身份不受 worker 并发翻转影响（确定性）
    subject = get_anomaly_extraction(runtime, record.id)
    body = {
        "extraction_id": record.id,
        "job_id": record.job_id,
        "status": subject.status,
        "reused": record.reused,
    }
    if record.job_id is not None:
        worker = _worker(request)
        if worker is not None:
            worker.enqueue_analysis(record.job_id)
    return JSONResponse(status_code=200 if record.reused else 202, content=body)


@router.get("/api/anomaly-extractions/{extraction_id}")
def get_anomaly_extraction_dto(
    extraction_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """提取状态、配置、manifest 摘要与有界 components 预览。"""

    record = get_anomaly_extraction(runtime, extraction_id)
    require_active_candidate(runtime, record.candidate_result_id)
    _load_candidate(runtime, record.candidate_result_id)  # 归属链核验
    components = None
    if record.status == "succeeded" and record.manifest:
        frame = _read_csv_artifact(record.manifest, "components")
        view = frame.head(MAX_COMPONENT_ROWS)
        rows = json.loads(view.to_json(orient="records"))
        for row in rows:
            for key in ("bounds", "centroid"):
                value = row.get(key)
                if isinstance(value, str):
                    row[key] = json.loads(value)
        components = {"total": len(frame), "returned": len(view), "rows": rows}
    return public_anomaly_extraction(record, components=components)


# ---------------------------------------------------------------------------
# 双候选比较（fingerprint 幂等登记/查询）
# ---------------------------------------------------------------------------


class ComparisonBody(ContractModel):
    first_result_id: str = Field(min_length=1, max_length=128)
    second_result_id: str = Field(min_length=1, max_length=128)


def _comparison_registry_path(runtime: PlatformRuntime, fingerprint: str) -> Path:
    """比较登记文件：指纹即身份，只含公开 DTO（绝不写服务器路径）。"""

    return runtime.settings.data_dir / "comparisons" / f"{fingerprint}.json"


def _register_comparison(runtime: PlatformRuntime, dto: dict[str, Any]) -> None:
    """原子登记比较结论：同级临时文件 + 回读校验 + ``os.replace``（幂等）。"""

    path = _comparison_registry_path(runtime, dto["comparison_fingerprint"])
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dto, ensure_ascii=False, sort_keys=True).encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(
        prefix="comparison-", suffix=".json", dir=path.parent
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.write_bytes(payload)
        if tmp_path.read_bytes() != payload:
            raise PlatformError(
                "COMPARISON_REGISTRY_WRITE_FAILED", "比较登记回读校验失败", http_status=409
            )
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


@router.post("/api/professional-comparisons", status_code=201)
def create_comparison(
    request_body: ComparisonBody,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """比较两个成功候选（只读已登记工件）；结论以 comparison_fingerprint 登记。"""

    require_active_candidate(runtime, request_body.first_result_id)
    require_active_candidate(runtime, request_body.second_result_id)
    comparison = compare_candidates(
        runtime, request_body.first_result_id, request_body.second_result_id
    )
    dto = public_comparison(comparison)
    _register_comparison(runtime, dto)
    return dto


@router.get("/api/professional-comparisons/{comparison_id}")
def get_comparison(
    comparison_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """按 comparison_fingerprint 幂等查询已登记比较结论。"""

    if not _FINGERPRINT_RE.match(comparison_id):
        raise PlatformError(
            COMPARISON_NOT_FOUND,
            "比较不存在",
            {"comparison_id": comparison_id},
            http_status=404,
        )
    path = _comparison_registry_path(runtime, comparison_id)
    if not path.is_file():
        raise PlatformError(
            COMPARISON_NOT_FOUND,
            "比较不存在",
            {"comparison_id": comparison_id},
            http_status=404,
        )
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 白名单工件下载
# ---------------------------------------------------------------------------


def _artifact_not_found(message: str, **details: Any) -> PlatformError:
    return PlatformError(PROFESSIONAL_ARTIFACT_NOT_FOUND, message, details, http_status=404)


def _subject_manifest(runtime: PlatformRuntime, kind: str, subject_id: str) -> dict[str, Any]:
    """按已登记身份类别解析 subject manifest；一切未知身份统一 404。"""

    try:
        if kind == "diagnosis":
            record = get_professional_diagnosis(runtime, subject_id)
            with runtime.session() as session:
                DatasetRepository(session).get(record.dataset_version_id)
            if record.status == RunStatus.SUCCEEDED.value and record.manifest:
                return record.manifest
            raise _artifact_not_found(
                "工件未登记（诊断尚未成功）", artifact_kind=kind, subject_id=subject_id
            )
        if kind == "result":
            _load_candidate(runtime, subject_id)
            with runtime.session() as session:
                artifacts_row = (
                    session.query(tables.ProfessionalResultArtifacts)
                    .filter(tables.ProfessionalResultArtifacts.candidate_result_id == subject_id)
                    .one_or_none()
                )
            if artifacts_row is not None and artifacts_row.manifest_json:
                return tables.loads_canonical(artifacts_row.manifest_json)
            raise _artifact_not_found(
                "工件未登记（成果无专业工件集合）", artifact_kind=kind, subject_id=subject_id
            )
        if kind == "extraction":
            record = get_anomaly_extraction(runtime, subject_id)
            _load_candidate(runtime, record.candidate_result_id)
            if record.status == "succeeded" and record.manifest:
                return record.manifest
            raise _artifact_not_found(
                "工件未登记（提取尚未成功）", artifact_kind=kind, subject_id=subject_id
            )
    except PlatformError as exc:
        # 未知身份（诊断/成果/提取不存在）统一为工件 404，不泄露存在性差异
        if exc.http_status == 404:
            raise _artifact_not_found(
                "专业工件身份未登记", artifact_kind=kind, subject_id=subject_id
            ) from exc
        raise
    raise _artifact_not_found("未知工件类别", artifact_kind=kind, subject_id=subject_id)


@router.get("/api/professional-artifacts/{artifact_id}/download")
def download_professional_artifact(
    artifact_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> FileResponse:
    """下载已登记工件：「类别:subject:逻辑名」三段式身份，路径从 manifest 白名单解析。

    逻辑名必须是 manifest 已登记工件键，登记 file 必须是纯基名；逐件校验
    大小与 SHA-256（fail-closed），绝不拼接客户端输入。
    """

    parts = artifact_id.split(":")
    if len(parts) != 3:
        raise _artifact_not_found("工件身份须为「类别:subject:逻辑名」", artifact_id=artifact_id)
    kind, subject_id, logical_name = parts
    manifest = _subject_manifest(runtime, kind, subject_id)
    entry = (manifest.get("artifacts") or {}).get(logical_name)
    if not isinstance(entry, dict):
        raise _artifact_not_found(
            "逻辑工件名未登记", artifact_kind=kind, subject_id=subject_id, artifact=logical_name
        )
    file_name = entry.get("file")
    directory = manifest.get("directory")
    if (
        not isinstance(file_name, str)
        or not file_name
        or file_name != Path(file_name).name
        or not isinstance(directory, str)
        or not directory
    ):
        raise _artifact_not_found(
            "工件登记条目无效", artifact_kind=kind, subject_id=subject_id, artifact=logical_name
        )
    path = Path(directory) / file_name
    if not path.is_file():
        raise _artifact_not_found(
            "登记的工件文件缺失", artifact_kind=kind, subject_id=subject_id, artifact=logical_name
        )
    blob = path.read_bytes()
    if len(blob) != entry.get("bytes") or hashlib.sha256(blob).hexdigest() != entry.get("sha256"):
        raise PlatformError(
            MANIFEST_VERIFICATION_FAILED,
            "工件哈希或大小不匹配",
            {"artifact": logical_name},
            http_status=409,
        )
    media_type = _ARTIFACT_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, filename=file_name)


# ---------------------------------------------------------------------------
# v0.7.0 batch 3: candidate catalog and multi-candidate comparison (§8)
# ---------------------------------------------------------------------------


@router.get("/api/datasets/{dataset_id}/comparison-candidates")
def list_comparison_candidates(
    dataset_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """List comparable candidates across experiments for a dataset version."""

    require_active_dataset(runtime, dataset_id)
    from geomodeling.platform.candidate_comparisons import candidate_catalog

    return candidate_catalog(runtime, dataset_id)


@router.post("/api/candidate-comparisons")
def compare_candidates_route(
    request_body: CandidateComparisonRequest,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """Compare 2-4 candidates deterministically without persistence.

    Uses Pydantic body validation: invalid selections return 422, never 500.
    """

    from geomodeling.platform.candidate_comparisons import compare_candidates_multi

    for cid in request_body.candidate_result_ids:
        require_active_candidate(runtime, cid)
    result = compare_candidates_multi(runtime, request_body.candidate_result_ids)
    return result.model_dump(mode="json")
