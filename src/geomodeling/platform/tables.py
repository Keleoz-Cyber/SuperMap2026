"""SQLAlchemy table definitions for the v0.4 platform database.

Conventions follow the v0.3 codebase: statuses are plain enum strings,
structured fields are stored as canonical JSON text
(``json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))``),
and timestamps are UTC ISO-8601 strings.

v5 增加专业建模状态表：诊断、不可变确认快照、按候选唯一的专业工件、
幂等异常提取与持久化分析任务（设计 §5.1）。
v6 增加 NetCDF 渲染资产状态表 render_assets（v0.6.1 设计 §2.2）。
v7 增加案例生命周期字段（lifecycle_state、trashed_at）和永久删除操作表
case_purge_operations（v0.7.0 第三批设计 §4）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def dumps_canonical(value: Any) -> str:
    """Serialize structured fields to canonical JSON text.

    Python's ``json`` defaults to ``allow_nan=True``, which emits ``NaN`` /
    ``Infinity`` literals that are invalid strict JSON. Callers (run metrics,
    quality reports, manifests, ...) must sanitize non-finite floats before
    persisting; this helper intentionally does not mask bad input.
    """

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def loads_canonical(raw: str) -> Any:
    return json.loads(raw)


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    INTERRUPTED = "interrupted"


RUN_INFLIGHT_STATUSES = frozenset({RunStatus.QUEUED.value, RunStatus.RUNNING.value})
RUN_TERMINAL_STATUSES = frozenset(
    {
        RunStatus.SUCCEEDED.value,
        RunStatus.FAILED.value,
        RunStatus.CANCELED.value,
        RunStatus.INTERRUPTED.value,
    }
)

ERROR_PROCESS_RESTARTED = "PROCESS_RESTARTED"


class CaseLifecycleState(str, Enum):
    ACTIVE = "active"
    TRASHED = "trashed"
    PURGING = "purging"


class PurgeOperationState(str, Enum):
    PREPARED = "prepared"
    QUARANTINED = "quarantined"
    COMMITTED = "committed"
    CLEANED = "cleaned"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class Base(DeclarativeBase):
    pass


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        Index("ix_cases_lifecycle_state", "lifecycle_state"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    case_type: Mapped[str] = mapped_column(String(64))
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    # v7: 案例生命周期状态（active/trashed/purging）和回收时间
    lifecycle_state: Mapped[str] = mapped_column(
        String(16), default=CaseLifecycleState.ACTIVE.value,
        server_default=CaseLifecycleState.ACTIVE.value,
    )
    trashed_at: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now_iso, onupdate=utc_now_iso)


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (
        # 版本号按案例单调递增；唯一约束把并发分配竞争收敛为可处理的冲突
        UniqueConstraint("case_id", "version", name="uq_dataset_versions_case_version"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    version: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    source_path: Mapped[str] = mapped_column(Text)
    standardized_path: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    profile_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)


class QualityReport(Base):
    __tablename__ = "quality_reports"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dataset_version_id: Mapped[str] = mapped_column(ForeignKey("dataset_versions.id"))
    status: Mapped[str] = mapped_column(String(32), default="unreviewed")
    report_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    name: Mapped[str] = mapped_column(String(256))
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now_iso, onupdate=utc_now_iso)


class Run(Base):
    __tablename__ = "runs"
    # 数据库层保证每个 experiment 最多一个 queued/running run（部分唯一索引）；
    # 应用层的计数预检只是友好错误，竞态由本约束兜底。
    __table_args__ = (
        Index(
            "ux_runs_experiment_inflight",
            "experiment_id",
            unique=True,
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"))
    status: Mapped[str] = mapped_column(String(32), default=RunStatus.QUEUED.value)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    retry_of_run_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("runs.id"), nullable=True, default=None
    )
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now_iso, onupdate=utc_now_iso)
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)


class CandidateResult(Base):
    __tablename__ = "candidate_results"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    category: Mapped[str] = mapped_column(String(32), default="preview")
    fingerprint: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="queued")
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    predictions_path: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    grid_path: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)


class FormalSelection(Base):
    __tablename__ = "formal_selections"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    candidate_result_id: Mapped[str] = mapped_column(ForeignKey("candidate_results.id"))
    selected_by: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    # v4 新增：导出必须归属具体成果；v3 既有行为 NULL（不可被发布复用）
    candidate_result_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("candidate_results.id"), nullable=True, default=None
    )
    package_path: Mapped[str] = mapped_column(Text)
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)


class Publication(Base):
    __tablename__ = "publications"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    export_id: Mapped[str] = mapped_column(ForeignKey("exports.id"))
    target: Mapped[str] = mapped_column(String(64), default="iserver")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now_iso, onupdate=utc_now_iso)


# ---------------------------------------------------------------------------
# v5: professional modeling state
# ---------------------------------------------------------------------------


class ProfessionalDiagnostic(Base):
    """数据集级专业诊断（半变异函数等），由 analysis_jobs 驱动状态。"""

    __tablename__ = "professional_diagnostics"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dataset_version_id: Mapped[str] = mapped_column(ForeignKey("dataset_versions.id"))
    status: Mapped[str] = mapped_column(String(32), default=RunStatus.QUEUED.value)
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    fingerprint: Mapped[str] = mapped_column(String(64), default="")
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now_iso, onupdate=utc_now_iso)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)


class ProfessionalConfirmation(Base):
    """一次性不可变确认快照；修改任何参数必须以新指纹创建新快照。IDW 不创建。"""

    __tablename__ = "professional_confirmations"
    __table_args__ = (
        # 同一诊断下同一配置指纹的确认是纯粹重复：数据库层拒绝；
        # 不同人工判断以不同指纹形成各自快照。
        UniqueConstraint(
            "diagnostic_id",
            "fingerprint",
            name="uq_professional_confirmations_diagnostic_fingerprint",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    diagnostic_id: Mapped[str] = mapped_column(ForeignKey("professional_diagnostics.id"))
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    fingerprint: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)


class ProfessionalResultArtifacts(Base):
    """一个候选的一套专业真相（折分/OOF/方差/经验误差工件）。"""

    __tablename__ = "professional_result_artifacts"
    __table_args__ = (
        # candidate_result_id 唯一：防止一个候选出现两套专业真相。
        UniqueConstraint(
            "candidate_result_id", name="uq_professional_result_artifacts_candidate"
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    candidate_result_id: Mapped[str] = mapped_column(ForeignKey("candidate_results.id"))
    # 可空；专业 Kriging 候选必填（由服务层校验）
    confirmation_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("professional_confirmations.id"), nullable=True, default=None
    )
    status: Mapped[str] = mapped_column(String(32), default="pending")
    capabilities_json: Mapped[str] = mapped_column(Text, default="{}")
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)


class AnomalyExtraction(Base):
    """成果网格上的异常提取；同成果同配置指纹幂等返回同一成功提取。"""

    __tablename__ = "anomaly_extractions"
    __table_args__ = (
        # 同一成果同一指纹最多一条成功提取（幂等返回的结构兜底）；
        # pending/failed 行不受限，失败后可按同指纹重新提取。
        Index(
            "ux_anomaly_extractions_succeeded_fingerprint",
            "candidate_result_id",
            "fingerprint",
            unique=True,
            sqlite_where=text("status = 'succeeded'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    candidate_result_id: Mapped[str] = mapped_column(ForeignKey("candidate_results.id"))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    fingerprint: Mapped[str] = mapped_column(String(64), default="")
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)


class AnalysisJob(Base):
    """持久化专业分析任务（诊断/异常提取）；长计算不在 FastAPI 请求中执行。"""

    __tablename__ = "analysis_jobs"
    # 数据库层保证同一 job_kind + subject_id 最多一个 queued/running 任务
    # （部分唯一索引）；应用层预检只是友好错误，竞态由本约束兜底。
    __table_args__ = (
        Index(
            "ux_analysis_jobs_subject_inflight",
            "job_kind",
            "subject_id",
            unique=True,
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_kind: Mapped[str] = mapped_column(String(32))
    # subject_id 是多态引用（诊断或异常提取），不建外键
    subject_type: Mapped[str] = mapped_column(String(64))
    subject_id: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default=RunStatus.QUEUED.value)
    retry_of_job_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("analysis_jobs.id"), nullable=True, default=None
    )
    progress_json: Mapped[str] = mapped_column(Text, default="{}")
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now_iso, onupdate=utc_now_iso)
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)


# ---------------------------------------------------------------------------
# v6: NetCDF render asset state
# ---------------------------------------------------------------------------


class RenderAsset(Base):
    """v0.6.1 NetCDF 渲染资产（设计 §2.2）。

    五元身份（source_kind, source_id, grid_sha256, renderer, format_version）
    唯一；状态机 creating→ready/failed（→interrupted 仅由启动恢复写入），
    全部迁移由仓储 compare-and-update 驱动。
    """

    __tablename__ = "render_assets"
    __table_args__ = (
        # 同一渲染源身份最多一行：唯一约束兜底并发 claim 竞态，
        # 撞约束方回滚后重读胜出者。
        UniqueConstraint(
            "source_kind",
            "source_id",
            "grid_sha256",
            "renderer",
            "format_version",
            name="uq_render_assets_source_identity",
        ),
        CheckConstraint(
            "status IN ('creating', 'ready', 'failed', 'interrupted')",
            name="ck_render_assets_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(128))
    # 可空：candidate_result 源挂既有候选；builtin_legacy 源为 NULL
    candidate_result_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("candidate_results.id"), nullable=True, default=None
    )
    renderer: Mapped[str] = mapped_column(String(64))
    format_version: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(32))
    grid_sha256: Mapped[str] = mapped_column(String(64))
    netcdf_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    # 服务端内部目录；公共 DTO 序列化永不暴露
    asset_dir: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now_iso, onupdate=utc_now_iso)


# ---------------------------------------------------------------------------
# v7: case lifecycle purge operations
# ---------------------------------------------------------------------------


class CasePurgeOperation(Base):
    """永久删除操作表（v0.7.0 第三批设计 §4.2）。

    崩溃恢复日志，不作为用户历史数据浏览功能。``case_id`` 不建外键，
    案例删除后仍保留回执。``manifest_json`` 只含相对路径和哈希；
    ``error_json`` 只含类型化失败码/消息，不含绝对路径。
    """

    __tablename__ = "case_purge_operations"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(128), index=True)
    state: Mapped[str] = mapped_column(String(32))
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    receipt_json: Mapped[str] = mapped_column(Text, default="{}")
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now_iso, onupdate=utc_now_iso)


# ---------------------------------------------------------------------------
# v8: AI analysis records
# ---------------------------------------------------------------------------


class AIAnalysisRecord(Base):
    """AI 辅助研判记录（v0.9.0 设计 §9.5）。

    显式 POST 生成、GET 只读最近。相同 evidence_hash + prompt_version +
    model + mode 默认复用；regenerate=true 才重新计费。不保存 API Key
    和模型隐藏推理内容。
    """

    __tablename__ = "ai_analysis_records"
    __table_args__ = (
        Index("ix_ai_analysis_result_id", "result_id"),
        UniqueConstraint(
            "result_id", "evidence_hash", "prompt_version", "model", "mode",
            name="uq_ai_analysis_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    result_id: Mapped[str] = mapped_column(String(128), ForeignKey("candidate_results.id"))
    grid_sha256: Mapped[str] = mapped_column(String(64))
    evidence_hash: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    review_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    usage_prompt_tokens: Mapped[int | None] = mapped_column(nullable=True, default=None)
    usage_completion_tokens: Mapped[int | None] = mapped_column(nullable=True, default=None)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True, default=None)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso)
