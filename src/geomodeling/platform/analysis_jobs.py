"""Persistent analysis-job request services (design §5.2).

诊断与异常提取的请求入口：**先落库再入队**——subject 行与
``analysis_jobs`` 行在 ``JobWorker.enqueue_analysis`` 之前就已持久化；
同指纹成功幂等返回（不产生新任务）；重复在途请求 409
（``ANALYSIS_JOB_ALREADY_ACTIVE``）；崩遗的 queued/running subject 在
无活跃任务时被新请求领养续跑；重试产生新身份（``retry_of_job_id``）
并保留旧证据。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from geomodeling.modeling.anomalies import ANOMALY_UNCERTAINTY_UNAVAILABLE
from geomodeling.modeling.professional_contracts import AnomalyExtractionSpec
from geomodeling.platform.errors import (
    ANALYSIS_JOB_ALREADY_ACTIVE,
    PlatformError,
)
from geomodeling.platform.professional import (
    anomaly_fingerprint,
    canonical_anomaly_config,
    canonical_variogram_config,
    diagnosis_fingerprint,
    sha256_file,
)
from geomodeling.platform.repositories import (
    AnalysisJobRepository,
    AnomalyExtractionRepository,
    CandidateRepository,
    DatasetRepository,
    ProfessionalDiagnosticRepository,
)
from geomodeling.platform.results import RESULT_NOT_MATERIALIZED
from geomodeling.platform.schemas import (
    AnalysisJobRecord,
    AnomalyExtractionRecord,
    ProfessionalDiagnosticRecord,
)
from geomodeling.platform.tables import (
    AnomalyExtraction,
    ProfessionalDiagnostic,
    RunStatus,
)

__all__ = [
    "AnalysisRequest",
    "create_anomaly_extraction",
    "create_professional_diagnosis",
    "get_analysis_job",
    "get_anomaly_extraction",
    "get_professional_diagnosis",
    "retry_analysis_job",
]


@dataclass(frozen=True)
class AnalysisRequest:
    """一次分析请求的落库结果：subject 身份 + 任务身份。

    ``reused=True`` 表示命中同指纹既有成功（幂等返回），``job_id`` 为
    None（无新任务，调用方不得入队）。
    """

    id: str
    job_id: str | None
    reused: bool


# ---------------------------------------------------------------------------
# 专业诊断请求
# ---------------------------------------------------------------------------


def create_professional_diagnosis(
    runtime, dataset_id: str, config: dict[str, Any]
) -> AnalysisRequest:
    """创建专业诊断请求：诊断行与分析任务先落库，调用方再入队执行。

    同数据同配置指纹：已有成功诊断 → 幂等返回（``job_id=None``，不同确认
    快照不需要重新计算诊断，§5.1）；在途同指纹请求且任务活跃 → 409；在途
    subject 无活跃任务（崩遗）→ 领养续跑；否则新建诊断与任务。
    """

    canonical = canonical_variogram_config(config)
    with runtime.session() as session:
        dataset = DatasetRepository(session).get(dataset_id)
    standardized_sha256 = dataset.profile.get("standardized_sha256")
    if standardized_sha256 is None:
        standardized = runtime.settings.standardized_dataset(dataset.case_id, dataset.id)
        if not standardized.is_file():
            raise PlatformError(
                "DATASET_NOT_FOUND",
                "标准化数据不存在",
                {"dataset_id": dataset_id},
                http_status=404,
            )
        standardized_sha256 = sha256_file(standardized)
    fingerprint = diagnosis_fingerprint(standardized_sha256, canonical)

    with runtime.session() as session:
        existing = session.scalar(
            select(ProfessionalDiagnostic)
            .where(
                ProfessionalDiagnostic.dataset_version_id == dataset_id,
                ProfessionalDiagnostic.fingerprint == fingerprint,
                ProfessionalDiagnostic.status.in_(
                    [
                        RunStatus.QUEUED.value,
                        RunStatus.RUNNING.value,
                        RunStatus.SUCCEEDED.value,
                    ]
                ),
            )
            .order_by(ProfessionalDiagnostic.created_at.asc())
        )
        if existing is not None and existing.status == RunStatus.SUCCEEDED.value:
            return AnalysisRequest(id=existing.id, job_id=None, reused=True)
        jobs = AnalysisJobRepository(session)
        if existing is not None:
            active = jobs.find_active(
                job_kind="professional_diagnosis", subject_id=existing.id
            )
            if active is not None:
                raise PlatformError(
                    ANALYSIS_JOB_ALREADY_ACTIVE,
                    "该数据集已有排队或运行中的同配置诊断请求",
                    {"dataset_id": dataset_id, "diagnosis_id": existing.id},
                    http_status=409,
                )
            # 崩遗领养：在途 subject 无活跃任务，补一条新任务续跑
            job = jobs.create(
                job_kind="professional_diagnosis",
                subject_type="professional_diagnostic",
                subject_id=existing.id,
                request_fingerprint=fingerprint,
            )
            return AnalysisRequest(id=existing.id, job_id=job.id, reused=False)
        diagnosis = ProfessionalDiagnosticRepository(session).create(
            dataset_id, config=canonical, fingerprint=fingerprint
        )
        job = jobs.create(
            job_kind="professional_diagnosis",
            subject_type="professional_diagnostic",
            subject_id=diagnosis.id,
            request_fingerprint=fingerprint,
        )
        return AnalysisRequest(id=diagnosis.id, job_id=job.id, reused=False)


def get_professional_diagnosis(runtime, diagnosis_id: str) -> ProfessionalDiagnosticRecord:
    with runtime.session() as session:
        return ProfessionalDiagnosticRepository(session).get(diagnosis_id)


# ---------------------------------------------------------------------------
# 异常提取请求
# ---------------------------------------------------------------------------


def create_anomaly_extraction(
    runtime, result_id: str, config: dict[str, Any]
) -> AnalysisRequest:
    """创建异常提取请求：提取行与分析任务先落库，调用方再入队执行。

    要求已物化成果（metadata 存在、grid 哈希登记）与已请求的不确定性
    能力；缺失的不确定性层在请求期即结构化失败（不得忽略门槛）。同成果
    同配置指纹幂等返回既有成功；重复在途请求 409。
    """

    canonical = canonical_anomaly_config(config)
    with runtime.session() as session:
        CandidateRepository(session).get(result_id)  # CANDIDATE_NOT_FOUND → 404
    metadata_path = runtime.settings.result_grid(result_id).parent / "metadata.json"
    if not metadata_path.is_file():
        raise PlatformError(
            RESULT_NOT_MATERIALIZED,
            "成果尚未生成，请先调用 materialize",
            {"result_id": result_id},
            http_status=404,
        )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    grid_sha256 = metadata.get("grid_sha256")
    if not grid_sha256:
        raise PlatformError(
            RESULT_NOT_MATERIALIZED,
            "成果网格哈希未登记",
            {"result_id": result_id},
            http_status=404,
        )
    # 已请求的不确定性能力必须存在（§12.1/§17：不得忽略门槛）
    spec = AnomalyExtractionSpec.model_validate(canonical)
    professional_dir = runtime.settings.professional_result_dir(result_id)
    if spec.empirical_error_max is not None and not (
        professional_dir / "empirical_error_scale.npz"
    ).is_file():
        raise PlatformError(
            ANOMALY_UNCERTAINTY_UNAVAILABLE,
            "已请求 empirical_error_scale 不确定性上限，但对应层不存在；不得忽略该门槛",
            {"layer": "empirical_error_scale"},
            http_status=409,
        )
    if spec.kriging_std_max is not None and not (
        professional_dir / "kriging_standard_deviation.npz"
    ).is_file():
        raise PlatformError(
            ANOMALY_UNCERTAINTY_UNAVAILABLE,
            "已请求 kriging_std 不确定性上限，但对应层不存在；不得忽略该门槛",
            {"layer": "kriging_std"},
            http_status=409,
        )
    fingerprint = anomaly_fingerprint(grid_sha256, canonical)

    with runtime.session() as session:
        succeeded = session.scalar(
            select(AnomalyExtraction).where(
                AnomalyExtraction.candidate_result_id == result_id,
                AnomalyExtraction.fingerprint == fingerprint,
                AnomalyExtraction.status == "succeeded",
            )
        )
        if succeeded is not None:
            return AnalysisRequest(id=succeeded.id, job_id=None, reused=True)
        pending = session.scalar(
            select(AnomalyExtraction)
            .where(
                AnomalyExtraction.candidate_result_id == result_id,
                AnomalyExtraction.fingerprint == fingerprint,
                AnomalyExtraction.status == "pending",
            )
            .order_by(AnomalyExtraction.created_at.asc())
        )
        jobs = AnalysisJobRepository(session)
        if pending is not None:
            active = jobs.find_active(job_kind="anomaly_extraction", subject_id=pending.id)
            if active is not None:
                raise PlatformError(
                    ANALYSIS_JOB_ALREADY_ACTIVE,
                    "该成果已有排队或运行中的同配置异常提取请求",
                    {"result_id": result_id, "extraction_id": pending.id},
                    http_status=409,
                )
            # 崩遗领养：pending subject 无活跃任务，补一条新任务续跑
            job = jobs.create(
                job_kind="anomaly_extraction",
                subject_type="anomaly_extraction",
                subject_id=pending.id,
                request_fingerprint=fingerprint,
            )
            return AnalysisRequest(id=pending.id, job_id=job.id, reused=False)
        extraction = AnomalyExtractionRepository(session).create(
            result_id, config=canonical, fingerprint=fingerprint
        )
        job = jobs.create(
            job_kind="anomaly_extraction",
            subject_type="anomaly_extraction",
            subject_id=extraction.id,
            request_fingerprint=fingerprint,
        )
        return AnalysisRequest(id=extraction.id, job_id=job.id, reused=False)


def get_anomaly_extraction(runtime, extraction_id: str) -> AnomalyExtractionRecord:
    with runtime.session() as session:
        return AnomalyExtractionRepository(session).get(extraction_id)


# ---------------------------------------------------------------------------
# 任务读取与重试
# ---------------------------------------------------------------------------


def get_analysis_job(runtime, job_id: str) -> AnalysisJobRecord:
    with runtime.session() as session:
        return AnalysisJobRepository(session).get(job_id)


def retry_analysis_job(runtime, job_id: str) -> AnalysisJobRecord:
    """从 failed/canceled/interrupted 发起重试：新身份、``retry_of_job_id``

    引用原任务；原任务与 subject 的结构化证据全部保留（§5.2/§17）。
    """

    with runtime.session() as session:
        return AnalysisJobRepository(session).retry(job_id)
