"""Repositories for the v0.4 platform: the only ORM boundary.

Every repository accepts a SQLAlchemy ``Session`` and returns Pydantic
domain records from ``schemas.py`` — ORM rows never leak across this
boundary. Status transitions are explicit module-level tables enforced
with compare-and-update statements, so cancel/retry cannot race with
worker completion. Structured fields are persisted with
``tables.dumps_canonical``.
"""

from __future__ import annotations

import uuid
from typing import Any, Iterable

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from geomodeling.platform import tables
from geomodeling.platform.errors import (
    ANALYSIS_JOB_ALREADY_ACTIVE,
    ANALYSIS_JOB_NOT_FOUND,
    ANALYSIS_JOB_NOT_RETRYABLE,
    ANOMALY_EXTRACTION_NOT_FOUND,
    CANDIDATE_NOT_FOUND,
    CANDIDATE_NOT_IN_CASE,
    CANDIDATE_NOT_SUCCEEDED,
    CASE_NOT_FOUND,
    DATASET_NOT_FOUND,
    DATASET_NOT_IN_CASE,
    DATASET_VERSION_CONFLICT,
    EXPERIMENT_NOT_FOUND,
    EXPERIMENT_NOT_IN_CASE,
    INVALID_STATUS_TRANSITION,
    PROFESSIONAL_ARTIFACTS_CONFLICT,
    PROFESSIONAL_ARTIFACTS_NOT_FOUND,
    PROFESSIONAL_CONFIRMATION_CONFLICT,
    PROFESSIONAL_CONFIRMATION_NOT_FOUND,
    PROFESSIONAL_DIAGNOSIS_NOT_FOUND,
    PROFESSIONAL_DIAGNOSIS_NOT_SUCCEEDED,
    RUN_ALREADY_ACTIVE,
    RUN_NOT_FOUND,
    RUN_NOT_RETRYABLE,
    PlatformError,
)
from geomodeling.platform.render_contracts import RenderGridSource
from geomodeling.platform.schemas import (
    FORMAT_VERSION,
    RENDERER,
    STATUS_CREATING,
    STATUS_FAILED,
    STATUS_READY,
    AnalysisJobRecord,
    AnomalyExtractionRecord,
    CandidateResultRecord,
    CaseCreateRequest,
    CaseRecord,
    DatasetStatus,
    DatasetVersionRecord,
    ExperimentCreateRequest,
    ExperimentRecord,
    FormalSelectionRecord,
    FormalSelectionRequest,
    ProfessionalConfirmationRecord,
    ProfessionalDiagnosticRecord,
    ProfessionalResultArtifactsRecord,
    RenderAssetRecord,
    RunRecord,
    render_asset_id,
)
from geomodeling.platform.tables import (
    AnalysisJob,
    AnomalyExtraction,
    CandidateResult,
    Case,
    DatasetVersion,
    Experiment,
    FormalSelection,
    ProfessionalConfirmation,
    ProfessionalDiagnostic,
    ProfessionalResultArtifacts,
    RenderAsset,
    Run,
    RunStatus,
)

# ---------------------------------------------------------------------------
# Explicit status transition tables
# ---------------------------------------------------------------------------

# 数据集生命周期：uploaded→mapped→validated，或 uploaded→blocked→mapped→validated。
# validated 为终态；重新映射通过产生新 DatasetVersion 完成，不回退状态。
DATASET_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    DatasetStatus.UPLOADED.value: frozenset(
        {DatasetStatus.MAPPED.value, DatasetStatus.BLOCKED.value}
    ),
    DatasetStatus.MAPPED.value: frozenset(
        {DatasetStatus.VALIDATED.value, DatasetStatus.BLOCKED.value}
    ),
    DatasetStatus.BLOCKED.value: frozenset({DatasetStatus.MAPPED.value}),
    DatasetStatus.VALIDATED.value: frozenset(),
}

# 仅 failed/canceled/interrupted 可重试；重试产生新 run（retry_of_run_id），
# 不覆盖原记录。queued/running 不可重试。
RUN_RETRYABLE_STATUSES = frozenset(
    {RunStatus.FAILED.value, RunStatus.CANCELED.value, RunStatus.INTERRUPTED.value}
)

# 取消只允许从在途状态发起；终态 run 不可取消。
RUN_CANCELABLE_STATUSES = frozenset({RunStatus.QUEUED.value, RunStatus.RUNNING.value})


def _new_id() -> str:
    """Server-generated lowercase UUID; display names never become ids."""

    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# ORM row -> Pydantic record converters
# ---------------------------------------------------------------------------


def _case_record(row: Case) -> CaseRecord:
    return CaseRecord(
        id=row.id,
        name=row.name,
        case_type=row.case_type,
        config=tables.loads_canonical(row.config_json),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _dataset_record(row: DatasetVersion) -> DatasetVersionRecord:
    return DatasetVersionRecord(
        id=row.id,
        case_id=row.case_id,
        version=row.version,
        status=row.status,
        source_path=row.source_path,
        standardized_path=row.standardized_path,
        profile=tables.loads_canonical(row.profile_json),
        created_at=row.created_at,
    )


def _experiment_record(row: Experiment) -> ExperimentRecord:
    return ExperimentRecord(
        id=row.id,
        case_id=row.case_id,
        name=row.name,
        params=tables.loads_canonical(row.params_json),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _run_record(row: Run) -> RunRecord:
    return RunRecord(
        id=row.id,
        experiment_id=row.experiment_id,
        status=row.status,
        error_code=row.error_code,
        metrics=tables.loads_canonical(row.metrics_json),
        retry_of_run_id=row.retry_of_run_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def _candidate_record(row: CandidateResult) -> CandidateResultRecord:
    return CandidateResultRecord(
        id=row.id,
        run_id=row.run_id,
        category=row.category,
        grid_path=row.grid_path,
        metrics=tables.loads_canonical(row.metrics_json),
        created_at=row.created_at,
    )


def _formal_selection_record(row: FormalSelection) -> FormalSelectionRecord:
    return FormalSelectionRecord(
        id=row.id,
        case_id=row.case_id,
        candidate_result_id=row.candidate_result_id,
        selected_by=row.selected_by,
        note=row.note,
        created_at=row.created_at,
    )


# ---------------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------------


class CaseRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create(self, request: CaseCreateRequest) -> CaseRecord:
        row = Case(
            id=_new_id(),
            name=request.name,
            case_type=request.case_type,
            config_json=tables.dumps_canonical(request.config),
        )
        self._s.add(row)
        self._s.commit()
        return _case_record(row)

    def get(self, case_id: str) -> CaseRecord:
        row = self._s.get(Case, case_id)
        if row is None:
            raise PlatformError(
                CASE_NOT_FOUND, "案例不存在", {"case_id": case_id}, http_status=404
            )
        return _case_record(row)

    def list_all(self) -> list[CaseRecord]:
        rows = self._s.query(Case).order_by(Case.created_at.asc()).all()
        return [_case_record(row) for row in rows]


class DatasetRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def _allocate_version(self, case_id: str) -> int:
        current_max = self._s.scalar(
            select(func.max(DatasetVersion.version)).where(DatasetVersion.case_id == case_id)
        )
        return (current_max or 0) + 1

    def create_version(
        self, case_id: str, *, source_path: str, profile: dict[str, Any] | None = None
    ) -> DatasetVersionRecord:
        """分配下一个版本号并入库。

        ``(case_id, version)`` 唯一约束兜底并发竞争：两个写者抢到同一
        版本号时，后提交者得到 409（客户端可重试），而不是 500。
        """

        if self._s.get(Case, case_id) is None:
            raise PlatformError(
                CASE_NOT_FOUND, "案例不存在", {"case_id": case_id}, http_status=404
            )
        version = self._allocate_version(case_id)
        row = DatasetVersion(
            id=_new_id(),
            case_id=case_id,
            version=version,
            status=DatasetStatus.UPLOADED.value,
            source_path=source_path,
            profile_json=tables.dumps_canonical(profile or {}),
        )
        self._s.add(row)
        try:
            self._s.commit()
        except IntegrityError:
            self._s.rollback()
            raise PlatformError(
                DATASET_VERSION_CONFLICT,
                "数据版本号分配冲突，请重试",
                {"case_id": case_id, "version": version},
                http_status=409,
            ) from None
        return _dataset_record(row)

    def _get_row(self, dataset_id: str) -> DatasetVersion:
        row = self._s.get(DatasetVersion, dataset_id)
        if row is None:
            raise PlatformError(
                DATASET_NOT_FOUND, "数据集不存在", {"dataset_id": dataset_id}, http_status=404
            )
        return row

    def get(self, dataset_id: str) -> DatasetVersionRecord:
        return _dataset_record(self._get_row(dataset_id))

    def get_for_case(self, case_id: str, dataset_id: str) -> DatasetVersionRecord:
        row = self._get_row(dataset_id)
        if row.case_id != case_id:
            raise PlatformError(
                DATASET_NOT_IN_CASE,
                "数据集不属于该案例",
                {"dataset_id": dataset_id, "case_id": case_id},
                http_status=404,
            )
        return _dataset_record(row)

    def list_for_case(self, case_id: str) -> list[DatasetVersionRecord]:
        rows = (
            self._s.query(DatasetVersion)
            .filter(DatasetVersion.case_id == case_id)
            .order_by(DatasetVersion.version.asc())
            .all()
        )
        return [_dataset_record(row) for row in rows]

    def transition_status(
        self, dataset_id: str, target: DatasetStatus | str
    ) -> DatasetVersionRecord:
        """Compare-and-update 状态迁移；跳步与并发改写都被拒绝。"""

        target_value = DatasetStatus(target).value
        row = self._get_row(dataset_id)
        current = row.status
        allowed = DATASET_STATUS_TRANSITIONS.get(current, frozenset())
        if target_value not in allowed:
            raise PlatformError(
                INVALID_STATUS_TRANSITION,
                f"数据集状态不允许从 {current} 迁移到 {target_value}",
                {
                    "dataset_id": dataset_id,
                    "current": current,
                    "target": target_value,
                    "allowed": sorted(allowed),
                },
                http_status=409,
            )
        result = self._s.execute(
            update(DatasetVersion)
            .where(DatasetVersion.id == dataset_id, DatasetVersion.status == current)
            .values(status=target_value)
        )
        if result.rowcount != 1:  # 并发改写：重读后报告
            self._s.rollback()
            actual = self._get_row(dataset_id).status
            raise PlatformError(
                INVALID_STATUS_TRANSITION,
                "数据集状态已被并发修改",
                {"dataset_id": dataset_id, "expected": current, "actual": actual},
                http_status=409,
            )
        self._s.commit()
        return self.get(dataset_id)


class ExperimentRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create(
        self,
        case_id: str,
        request: ExperimentCreateRequest,
        *,
        professional: dict[str, Any] | None = None,
    ) -> ExperimentRecord:
        if request.case_id != case_id:
            raise PlatformError(
                EXPERIMENT_NOT_IN_CASE,
                "实验案例与路径案例不一致",
                {"case_id": case_id, "request_case_id": request.case_id},
                http_status=404,
            )
        if self._s.get(Case, case_id) is None:
            raise PlatformError(
                CASE_NOT_FOUND, "案例不存在", {"case_id": case_id}, http_status=404
            )
        # 数据版本必须属于本案例（ownership）
        DatasetRepository(self._s).get_for_case(case_id, request.dataset_version_id)
        params = {
            "algorithm": request.algorithm,
            "dataset_version_id": request.dataset_version_id,
            "search_mode": request.search_mode,
            "validation": request.validation.model_dump(mode="json"),
            "grid": request.grid.model_dump(mode="json") if request.grid is not None else None,
            "parameters": request.parameters,
        }
        if professional is not None:
            # v0.6：规范化专业上下文随实验参数落库；legacy 实验不写该键，
            # params_json 与 v0.5 逐位一致。
            params["professional"] = professional
        row = Experiment(
            id=_new_id(),
            case_id=case_id,
            name=request.name,
            params_json=tables.dumps_canonical(params),
        )
        self._s.add(row)
        self._s.commit()
        return _experiment_record(row)

    def _get_row(self, experiment_id: str) -> Experiment:
        row = self._s.get(Experiment, experiment_id)
        if row is None:
            raise PlatformError(
                EXPERIMENT_NOT_FOUND,
                "实验不存在",
                {"experiment_id": experiment_id},
                http_status=404,
            )
        return row

    def get(self, experiment_id: str) -> ExperimentRecord:
        return _experiment_record(self._get_row(experiment_id))

    def get_for_case(self, case_id: str, experiment_id: str) -> ExperimentRecord:
        row = self._get_row(experiment_id)
        if row.case_id != case_id:
            raise PlatformError(
                EXPERIMENT_NOT_IN_CASE,
                "实验不属于该案例",
                {"experiment_id": experiment_id, "case_id": case_id},
                http_status=404,
            )
        return _experiment_record(row)


class RunRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create(self, experiment_id: str) -> RunRecord:
        if self._s.get(Experiment, experiment_id) is None:
            raise PlatformError(
                EXPERIMENT_NOT_FOUND,
                "实验不存在",
                {"experiment_id": experiment_id},
                http_status=404,
            )
        row = Run(id=_new_id(), experiment_id=experiment_id, status=RunStatus.QUEUED.value)
        self._s.add(row)
        try:
            self._s.commit()
        except IntegrityError as exc:
            self._s.rollback()
            # 在途部分唯一索引兜底：并发创建撞约束 → 409
            raise PlatformError(
                RUN_ALREADY_ACTIVE,
                "该实验已有排队或运行中的任务",
                {"experiment_id": experiment_id},
                http_status=409,
            ) from exc
        return _run_record(row)

    def _get_row(self, run_id: str) -> Run:
        row = self._s.get(Run, run_id)
        if row is None:
            raise PlatformError(
                RUN_NOT_FOUND, "任务不存在", {"run_id": run_id}, http_status=404
            )
        return row

    def get(self, run_id: str) -> RunRecord:
        return _run_record(self._get_row(run_id))

    def _cas_transition(
        self,
        run_id: str,
        *,
        expected: Iterable[str],
        values: dict[str, Any],
        message: str,
    ) -> RunRecord:
        """原子比较并更新；不匹配时不覆盖现状，抛 409。"""

        expected_set = frozenset(expected)
        values.setdefault("updated_at", tables.utc_now_iso())
        result = self._s.execute(
            update(Run)
            .where(Run.id == run_id, Run.status.in_(sorted(expected_set)))
            .values(**values)
        )
        if result.rowcount != 1:
            self._s.rollback()
            actual = self._get_row(run_id).status  # RUN_NOT_FOUND if absent
            raise PlatformError(
                INVALID_STATUS_TRANSITION,
                message,
                {
                    "run_id": run_id,
                    "expected": sorted(expected_set),
                    "actual": actual,
                },
                http_status=409,
            )
        self._s.commit()
        return self.get(run_id)

    def mark_running(self, run_id: str) -> RunRecord:
        return self._cas_transition(
            run_id,
            expected={RunStatus.QUEUED.value},
            values={
                "status": RunStatus.RUNNING.value,
                "started_at": tables.utc_now_iso(),
            },
            message="只有排队中的任务可以启动",
        )

    def mark_succeeded(self, run_id: str, *, metrics: dict[str, Any]) -> RunRecord:
        return self._cas_transition(
            run_id,
            expected={RunStatus.RUNNING.value},
            values={
                "status": RunStatus.SUCCEEDED.value,
                "metrics_json": tables.dumps_canonical(metrics),
                "finished_at": tables.utc_now_iso(),
            },
            message="任务已不在运行中，完成结果不会覆盖当前状态",
        )

    def mark_failed(self, run_id: str, *, error_code: str, metrics: dict[str, Any] | None = None) -> RunRecord:
        values: dict[str, Any] = {
            "status": RunStatus.FAILED.value,
            "error_code": error_code,
            "finished_at": tables.utc_now_iso(),
        }
        if metrics is not None:
            values["metrics_json"] = tables.dumps_canonical(metrics)
        return self._cas_transition(
            run_id,
            expected={RunStatus.RUNNING.value},
            values=values,
            message="任务已不在运行中，失败结果不会覆盖当前状态",
        )

    def cancel(self, run_id: str) -> RunRecord:
        return self._cas_transition(
            run_id,
            expected=RUN_CANCELABLE_STATUSES,
            values={
                "status": RunStatus.CANCELED.value,
                "finished_at": tables.utc_now_iso(),
            },
            message="只有排队或运行中的任务可以取消",
        )

    def retry(self, run_id: str) -> RunRecord:
        """从 failed/canceled/interrupted 发起重试，产生引用原 run 的新 queued run。"""

        row = self._get_row(run_id)
        if row.status not in RUN_RETRYABLE_STATUSES:
            raise PlatformError(
                RUN_NOT_RETRYABLE,
                f"状态为 {row.status} 的任务不能重试",
                {"run_id": run_id, "status": row.status},
                http_status=409,
            )
        active = self._s.scalar(
            select(func.count(Run.id)).where(
                Run.experiment_id == row.experiment_id,
                Run.status.in_(sorted(tables.RUN_INFLIGHT_STATUSES)),
            )
        )
        if active:
            raise PlatformError(
                RUN_ALREADY_ACTIVE,
                "该实验已有排队或运行中的任务，不能重复重试",
                {"run_id": run_id, "experiment_id": row.experiment_id},
                http_status=409,
            )
        new_row = Run(
            id=_new_id(),
            experiment_id=row.experiment_id,
            status=RunStatus.QUEUED.value,
            retry_of_run_id=row.id,
        )
        self._s.add(new_row)
        try:
            self._s.commit()
        except IntegrityError as exc:
            self._s.rollback()
            raise PlatformError(
                RUN_ALREADY_ACTIVE,
                "该实验已有排队或运行中的任务，不能重复重试",
                {"run_id": run_id, "experiment_id": row.experiment_id},
                http_status=409,
            ) from exc
        return _run_record(new_row)


class CandidateRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create(
        self,
        run_id: str,
        *,
        metrics: dict[str, Any],
        category: str = "preview",
        grid_path: str | None = None,
    ) -> CandidateResultRecord:
        if self._s.get(Run, run_id) is None:
            raise PlatformError(
                RUN_NOT_FOUND, "任务不存在", {"run_id": run_id}, http_status=404
            )
        row = CandidateResult(
            id=_new_id(),
            run_id=run_id,
            category=category,
            grid_path=grid_path,
            metrics_json=tables.dumps_canonical(metrics),
        )
        self._s.add(row)
        self._s.commit()
        return _candidate_record(row)

    def _get_row(self, candidate_id: str) -> CandidateResult:
        row = self._s.get(CandidateResult, candidate_id)
        if row is None:
            raise PlatformError(
                CANDIDATE_NOT_FOUND,
                "候选结果不存在",
                {"candidate_result_id": candidate_id},
                http_status=404,
            )
        return row

    def get(self, candidate_id: str) -> CandidateResultRecord:
        return _candidate_record(self._get_row(candidate_id))


class FormalSelectionRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def select(self, case_id: str, request: FormalSelectionRequest) -> FormalSelectionRecord:
        """只有成功 run 产出的成功候选可以设为正式模型，且必须属于本案例。

        ownership（404）先于 run 状态（409）检查：跨案例探测候选时
        一律得到 404，不泄露候选存在性及其任务状态。run 与 candidate
        状态都必须为 succeeded：成功 run 里失败的候选同样拒绝。
        """

        candidate = CandidateRepository(self._s)._get_row(request.candidate_result_id)
        run = RunRepository(self._s)._get_row(candidate.run_id)
        experiment = ExperimentRepository(self._s)._get_row(run.experiment_id)
        if experiment.case_id != case_id:
            raise PlatformError(
                CANDIDATE_NOT_IN_CASE,
                "候选结果不属于该案例",
                {"candidate_result_id": candidate.id, "case_id": case_id},
                http_status=404,
            )
        if run.status != RunStatus.SUCCEEDED.value:
            raise PlatformError(
                CANDIDATE_NOT_SUCCEEDED,
                "只有成功任务产出的候选才能设为正式模型",
                {
                    "candidate_result_id": candidate.id,
                    "run_id": run.id,
                    "run_status": run.status,
                },
                http_status=409,
            )
        if candidate.status != RunStatus.SUCCEEDED.value:
            raise PlatformError(
                CANDIDATE_NOT_SUCCEEDED,
                "只有成功候选才能设为正式模型",
                {
                    "candidate_result_id": candidate.id,
                    "run_id": run.id,
                    "candidate_status": candidate.status,
                },
                http_status=409,
            )
        row = FormalSelection(
            id=_new_id(),
            case_id=case_id,
            candidate_result_id=candidate.id,
            selected_by=request.selected_by,
            note=request.note,
        )
        self._s.add(row)
        self._s.commit()
        return _formal_selection_record(row)


# ---------------------------------------------------------------------------
# v0.6 professional modeling repositories (SQLite v5)
# ---------------------------------------------------------------------------

# 诊断生命周期：queued→running→succeeded/failed；interrupted 由重启恢复写入。
DIAGNOSIS_INFLIGHT_STATUSES = frozenset({RunStatus.QUEUED.value, RunStatus.RUNNING.value})

# 专业工件与异常提取生命周期：pending→succeeded/failed（终态不可再迁移）。
ARTIFACT_INFLIGHT_STATUS = "pending"


def _professional_diagnostic_record(row: ProfessionalDiagnostic) -> ProfessionalDiagnosticRecord:
    return ProfessionalDiagnosticRecord(
        id=row.id,
        dataset_version_id=row.dataset_version_id,
        status=row.status,
        config=tables.loads_canonical(row.config_json),
        fingerprint=row.fingerprint,
        manifest=tables.loads_canonical(row.manifest_json),
        error=tables.loads_canonical(row.error_json) if row.error_json is not None else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
        finished_at=row.finished_at,
    )


def _professional_confirmation_record(
    row: ProfessionalConfirmation,
) -> ProfessionalConfirmationRecord:
    return ProfessionalConfirmationRecord(
        id=row.id,
        diagnostic_id=row.diagnostic_id,
        config=tables.loads_canonical(row.config_json),
        fingerprint=row.fingerprint,
        note=row.note,
        created_at=row.created_at,
    )


def _professional_result_artifacts_record(
    row: ProfessionalResultArtifacts,
) -> ProfessionalResultArtifactsRecord:
    return ProfessionalResultArtifactsRecord(
        id=row.id,
        candidate_result_id=row.candidate_result_id,
        confirmation_id=row.confirmation_id,
        status=row.status,
        capabilities=tables.loads_canonical(row.capabilities_json),
        manifest=tables.loads_canonical(row.manifest_json),
        created_at=row.created_at,
    )


def _anomaly_extraction_record(row: AnomalyExtraction) -> AnomalyExtractionRecord:
    return AnomalyExtractionRecord(
        id=row.id,
        candidate_result_id=row.candidate_result_id,
        status=row.status,
        config=tables.loads_canonical(row.config_json),
        fingerprint=row.fingerprint,
        manifest=tables.loads_canonical(row.manifest_json),
        error=tables.loads_canonical(row.error_json) if row.error_json is not None else None,
        created_at=row.created_at,
    )


def _analysis_job_record(row: AnalysisJob) -> AnalysisJobRecord:
    return AnalysisJobRecord(
        id=row.id,
        job_kind=row.job_kind,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        request_fingerprint=row.request_fingerprint,
        status=row.status,
        retry_of_job_id=row.retry_of_job_id,
        progress=tables.loads_canonical(row.progress_json),
        error=tables.loads_canonical(row.error_json) if row.error_json is not None else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


class ProfessionalDiagnosticRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create(
        self,
        dataset_version_id: str,
        *,
        config: dict[str, Any],
        fingerprint: str,
    ) -> ProfessionalDiagnosticRecord:
        if self._s.get(DatasetVersion, dataset_version_id) is None:
            raise PlatformError(
                DATASET_NOT_FOUND,
                "数据集不存在",
                {"dataset_id": dataset_version_id},
                http_status=404,
            )
        row = ProfessionalDiagnostic(
            id=_new_id(),
            dataset_version_id=dataset_version_id,
            status=RunStatus.QUEUED.value,
            config_json=tables.dumps_canonical(config),
            fingerprint=fingerprint,
        )
        self._s.add(row)
        self._s.commit()
        return _professional_diagnostic_record(row)

    def _get_row(self, diagnosis_id: str) -> ProfessionalDiagnostic:
        row = self._s.get(ProfessionalDiagnostic, diagnosis_id)
        if row is None:
            raise PlatformError(
                PROFESSIONAL_DIAGNOSIS_NOT_FOUND,
                "专业诊断不存在",
                {"diagnosis_id": diagnosis_id},
                http_status=404,
            )
        return row

    def get(self, diagnosis_id: str) -> ProfessionalDiagnosticRecord:
        return _professional_diagnostic_record(self._get_row(diagnosis_id))

    def _cas_transition(
        self,
        diagnosis_id: str,
        *,
        expected: Iterable[str],
        values: dict[str, Any],
        message: str,
    ) -> ProfessionalDiagnosticRecord:
        """原子比较并更新；不匹配时不覆盖现状，抛 409。"""

        expected_set = frozenset(expected)
        values.setdefault("updated_at", tables.utc_now_iso())
        result = self._s.execute(
            update(ProfessionalDiagnostic)
            .where(
                ProfessionalDiagnostic.id == diagnosis_id,
                ProfessionalDiagnostic.status.in_(sorted(expected_set)),
            )
            .values(**values)
        )
        if result.rowcount != 1:
            self._s.rollback()
            actual = self._get_row(diagnosis_id).status  # 404 if absent
            raise PlatformError(
                INVALID_STATUS_TRANSITION,
                message,
                {
                    "diagnosis_id": diagnosis_id,
                    "expected": sorted(expected_set),
                    "actual": actual,
                },
                http_status=409,
            )
        self._s.commit()
        return self.get(diagnosis_id)

    def mark_running(self, diagnosis_id: str) -> ProfessionalDiagnosticRecord:
        return self._cas_transition(
            diagnosis_id,
            expected={RunStatus.QUEUED.value},
            values={"status": RunStatus.RUNNING.value},
            message="只有排队中的诊断可以启动",
        )

    def mark_succeeded(
        self, diagnosis_id: str, *, manifest: dict[str, Any]
    ) -> ProfessionalDiagnosticRecord:
        return self._cas_transition(
            diagnosis_id,
            expected={RunStatus.RUNNING.value},
            values={
                "status": RunStatus.SUCCEEDED.value,
                "manifest_json": tables.dumps_canonical(manifest),
                "finished_at": tables.utc_now_iso(),
            },
            message="诊断已不在运行中，完成结果不会覆盖当前状态",
        )

    def mark_failed(
        self, diagnosis_id: str, *, error: dict[str, Any]
    ) -> ProfessionalDiagnosticRecord:
        return self._cas_transition(
            diagnosis_id,
            expected={RunStatus.RUNNING.value},
            values={
                "status": RunStatus.FAILED.value,
                "error_json": tables.dumps_canonical(error),
                "finished_at": tables.utc_now_iso(),
            },
            message="诊断已不在运行中，失败结果不会覆盖当前状态",
        )


class ProfessionalConfirmationRepository:
    """一次性不可变确认快照：只有 create/get/list，没有任何更新入口。"""

    def __init__(self, session: Session) -> None:
        self._s = session

    def create(
        self,
        diagnostic_id: str,
        *,
        config: dict[str, Any],
        fingerprint: str,
        note: str,
    ) -> ProfessionalConfirmationRecord:
        """为成功诊断创建确认快照；同一配置指纹的重复确认被拒绝。

        一个诊断可以产生多个不同指纹的快照用于比较不同人工判断；修改
        任何参数都必须以新指纹创建新快照，既有快照永不被更新。
        """

        diagnostic = ProfessionalDiagnosticRepository(self._s)._get_row(diagnostic_id)
        if diagnostic.status != RunStatus.SUCCEEDED.value:
            raise PlatformError(
                PROFESSIONAL_DIAGNOSIS_NOT_SUCCEEDED,
                "只有成功诊断才能创建确认快照",
                {"diagnostic_id": diagnostic_id, "status": diagnostic.status},
                http_status=409,
            )
        row = ProfessionalConfirmation(
            id=_new_id(),
            diagnostic_id=diagnostic_id,
            config_json=tables.dumps_canonical(config),
            fingerprint=fingerprint,
            note=note,
        )
        self._s.add(row)
        try:
            self._s.commit()
        except IntegrityError as exc:
            self._s.rollback()
            # (diagnostic_id, fingerprint) 唯一约束兜底：重复快照 → 409
            raise PlatformError(
                PROFESSIONAL_CONFIRMATION_CONFLICT,
                "同一配置指纹的确认快照已存在，修改参数必须创建新快照",
                {"diagnostic_id": diagnostic_id, "fingerprint": fingerprint},
                http_status=409,
            ) from exc
        return _professional_confirmation_record(row)

    def _get_row(self, confirmation_id: str) -> ProfessionalConfirmation:
        row = self._s.get(ProfessionalConfirmation, confirmation_id)
        if row is None:
            raise PlatformError(
                PROFESSIONAL_CONFIRMATION_NOT_FOUND,
                "专业确认快照不存在",
                {"confirmation_id": confirmation_id},
                http_status=404,
            )
        return row

    def get(self, confirmation_id: str) -> ProfessionalConfirmationRecord:
        return _professional_confirmation_record(self._get_row(confirmation_id))

    def list_for_diagnostic(self, diagnostic_id: str) -> list[ProfessionalConfirmationRecord]:
        rows = (
            self._s.query(ProfessionalConfirmation)
            .filter(ProfessionalConfirmation.diagnostic_id == diagnostic_id)
            .order_by(ProfessionalConfirmation.created_at.asc())
            .all()
        )
        return [_professional_confirmation_record(row) for row in rows]


class ProfessionalResultArtifactsRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create(
        self,
        candidate_result_id: str,
        *,
        confirmation_id: str | None,
        capabilities: dict[str, Any],
    ) -> ProfessionalResultArtifactsRecord:
        CandidateRepository(self._s)._get_row(candidate_result_id)
        if confirmation_id is not None:
            ProfessionalConfirmationRepository(self._s)._get_row(confirmation_id)
        row = ProfessionalResultArtifacts(
            id=_new_id(),
            candidate_result_id=candidate_result_id,
            confirmation_id=confirmation_id,
            status=ARTIFACT_INFLIGHT_STATUS,
            capabilities_json=tables.dumps_canonical(capabilities),
        )
        self._s.add(row)
        try:
            self._s.commit()
        except IntegrityError as exc:
            self._s.rollback()
            # candidate_result_id 唯一约束兜底：一个候选只有一套专业真相
            raise PlatformError(
                PROFESSIONAL_ARTIFACTS_CONFLICT,
                "该候选已存在专业工件集合",
                {"candidate_result_id": candidate_result_id},
                http_status=409,
            ) from exc
        return _professional_result_artifacts_record(row)

    def _get_row(self, artifacts_id: str) -> ProfessionalResultArtifacts:
        row = self._s.get(ProfessionalResultArtifacts, artifacts_id)
        if row is None:
            raise PlatformError(
                PROFESSIONAL_ARTIFACTS_NOT_FOUND,
                "专业工件集合不存在",
                {"artifacts_id": artifacts_id},
                http_status=404,
            )
        return row

    def get(self, artifacts_id: str) -> ProfessionalResultArtifactsRecord:
        return _professional_result_artifacts_record(self._get_row(artifacts_id))

    def get_for_candidate(self, candidate_result_id: str) -> ProfessionalResultArtifactsRecord:
        row = self._s.scalar(
            select(ProfessionalResultArtifacts).where(
                ProfessionalResultArtifacts.candidate_result_id == candidate_result_id
            )
        )
        if row is None:
            raise PlatformError(
                PROFESSIONAL_ARTIFACTS_NOT_FOUND,
                "该候选没有专业工件集合",
                {"candidate_result_id": candidate_result_id},
                http_status=404,
            )
        return _professional_result_artifacts_record(row)

    def _cas_transition(
        self,
        artifacts_id: str,
        *,
        values: dict[str, Any],
        message: str,
    ) -> ProfessionalResultArtifactsRecord:
        result = self._s.execute(
            update(ProfessionalResultArtifacts)
            .where(
                ProfessionalResultArtifacts.id == artifacts_id,
                ProfessionalResultArtifacts.status == ARTIFACT_INFLIGHT_STATUS,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            self._s.rollback()
            actual = self._get_row(artifacts_id).status  # 404 if absent
            raise PlatformError(
                INVALID_STATUS_TRANSITION,
                message,
                {"artifacts_id": artifacts_id, "expected": [ARTIFACT_INFLIGHT_STATUS], "actual": actual},
                http_status=409,
            )
        self._s.commit()
        return self.get(artifacts_id)

    def mark_succeeded(
        self, artifacts_id: str, *, manifest: dict[str, Any]
    ) -> ProfessionalResultArtifactsRecord:
        return self._cas_transition(
            artifacts_id,
            values={"status": "succeeded", "manifest_json": tables.dumps_canonical(manifest)},
            message="工件集合已不在待处理状态，完成结果不会覆盖当前状态",
        )

    def mark_failed(self, artifacts_id: str) -> ProfessionalResultArtifactsRecord:
        return self._cas_transition(
            artifacts_id,
            values={"status": "failed"},
            message="工件集合已不在待处理状态，失败结果不会覆盖当前状态",
        )


class AnomalyExtractionRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create(
        self,
        candidate_result_id: str,
        *,
        config: dict[str, Any],
        fingerprint: str,
    ) -> AnomalyExtractionRecord:
        """创建异常提取；同成果同配置指纹幂等返回既有成功提取。

        幂等只认成功提取：pending/failed 行不短路，失败后可按同指纹
        重新提取；成功指纹由部分唯一索引兜底，最多一条。
        """

        CandidateRepository(self._s)._get_row(candidate_result_id)
        existing = self._s.scalar(
            select(AnomalyExtraction).where(
                AnomalyExtraction.candidate_result_id == candidate_result_id,
                AnomalyExtraction.fingerprint == fingerprint,
                AnomalyExtraction.status == "succeeded",
            )
        )
        if existing is not None:
            return _anomaly_extraction_record(existing)
        row = AnomalyExtraction(
            id=_new_id(),
            candidate_result_id=candidate_result_id,
            status=ARTIFACT_INFLIGHT_STATUS,
            config_json=tables.dumps_canonical(config),
            fingerprint=fingerprint,
        )
        self._s.add(row)
        self._s.commit()
        return _anomaly_extraction_record(row)

    def _get_row(self, extraction_id: str) -> AnomalyExtraction:
        row = self._s.get(AnomalyExtraction, extraction_id)
        if row is None:
            raise PlatformError(
                ANOMALY_EXTRACTION_NOT_FOUND,
                "异常提取不存在",
                {"extraction_id": extraction_id},
                http_status=404,
            )
        return row

    def get(self, extraction_id: str) -> AnomalyExtractionRecord:
        return _anomaly_extraction_record(self._get_row(extraction_id))

    def _cas_transition(
        self,
        extraction_id: str,
        *,
        values: dict[str, Any],
        message: str,
    ) -> AnomalyExtractionRecord:
        result = self._s.execute(
            update(AnomalyExtraction)
            .where(
                AnomalyExtraction.id == extraction_id,
                AnomalyExtraction.status == ARTIFACT_INFLIGHT_STATUS,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            self._s.rollback()
            actual = self._get_row(extraction_id).status  # 404 if absent
            raise PlatformError(
                INVALID_STATUS_TRANSITION,
                message,
                {"extraction_id": extraction_id, "expected": [ARTIFACT_INFLIGHT_STATUS], "actual": actual},
                http_status=409,
            )
        self._s.commit()
        return self.get(extraction_id)

    def mark_succeeded(
        self, extraction_id: str, *, manifest: dict[str, Any]
    ) -> AnomalyExtractionRecord:
        return self._cas_transition(
            extraction_id,
            values={"status": "succeeded", "manifest_json": tables.dumps_canonical(manifest)},
            message="异常提取已不在待处理状态，完成结果不会覆盖当前状态",
        )

    def mark_failed(
        self, extraction_id: str, *, error: dict[str, Any]
    ) -> AnomalyExtractionRecord:
        return self._cas_transition(
            extraction_id,
            values={"status": "failed", "error_json": tables.dumps_canonical(error)},
            message="异常提取已不在待处理状态，失败结果不会覆盖当前状态",
        )


class AnalysisJobRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create(
        self,
        *,
        job_kind: str,
        subject_type: str,
        subject_id: str,
        request_fingerprint: str,
    ) -> AnalysisJobRecord:
        row = AnalysisJob(
            id=_new_id(),
            job_kind=job_kind,
            subject_type=subject_type,
            subject_id=subject_id,
            request_fingerprint=request_fingerprint,
            status=RunStatus.QUEUED.value,
        )
        self._s.add(row)
        try:
            self._s.commit()
        except IntegrityError as exc:
            self._s.rollback()
            # 在途部分唯一索引兜底：并发创建撞约束 → 409
            raise PlatformError(
                ANALYSIS_JOB_ALREADY_ACTIVE,
                "该对象已有排队或运行中的同类分析任务",
                {"job_kind": job_kind, "subject_id": subject_id},
                http_status=409,
            ) from exc
        return _analysis_job_record(row)

    def _get_row(self, job_id: str) -> AnalysisJob:
        row = self._s.get(AnalysisJob, job_id)
        if row is None:
            raise PlatformError(
                ANALYSIS_JOB_NOT_FOUND,
                "分析任务不存在",
                {"job_id": job_id},
                http_status=404,
            )
        return row

    def get(self, job_id: str) -> AnalysisJobRecord:
        return _analysis_job_record(self._get_row(job_id))

    def find_active(self, *, job_kind: str, subject_id: str) -> AnalysisJobRecord | None:
        row = self._s.scalar(
            select(AnalysisJob).where(
                AnalysisJob.job_kind == job_kind,
                AnalysisJob.subject_id == subject_id,
                AnalysisJob.status.in_(sorted(tables.RUN_INFLIGHT_STATUSES)),
            )
        )
        return None if row is None else _analysis_job_record(row)

    def _cas_transition(
        self,
        job_id: str,
        *,
        expected: Iterable[str],
        values: dict[str, Any],
        message: str,
    ) -> AnalysisJobRecord:
        """原子比较并更新；不匹配时不覆盖现状，抛 409。"""

        expected_set = frozenset(expected)
        values.setdefault("updated_at", tables.utc_now_iso())
        result = self._s.execute(
            update(AnalysisJob)
            .where(AnalysisJob.id == job_id, AnalysisJob.status.in_(sorted(expected_set)))
            .values(**values)
        )
        if result.rowcount != 1:
            self._s.rollback()
            actual = self._get_row(job_id).status  # ANALYSIS_JOB_NOT_FOUND if absent
            raise PlatformError(
                INVALID_STATUS_TRANSITION,
                message,
                {"job_id": job_id, "expected": sorted(expected_set), "actual": actual},
                http_status=409,
            )
        self._s.commit()
        return self.get(job_id)

    def mark_running(self, job_id: str) -> AnalysisJobRecord:
        return self._cas_transition(
            job_id,
            expected={RunStatus.QUEUED.value},
            values={
                "status": RunStatus.RUNNING.value,
                "started_at": tables.utc_now_iso(),
            },
            message="只有排队中的分析任务可以启动",
        )

    def mark_succeeded(
        self, job_id: str, *, progress: dict[str, Any] | None = None
    ) -> AnalysisJobRecord:
        values: dict[str, Any] = {
            "status": RunStatus.SUCCEEDED.value,
            "finished_at": tables.utc_now_iso(),
        }
        if progress is not None:
            values["progress_json"] = tables.dumps_canonical(progress)
        return self._cas_transition(
            job_id,
            expected={RunStatus.RUNNING.value},
            values=values,
            message="分析任务已不在运行中，完成结果不会覆盖当前状态",
        )

    def mark_failed(self, job_id: str, *, error: dict[str, Any]) -> AnalysisJobRecord:
        return self._cas_transition(
            job_id,
            expected={RunStatus.RUNNING.value},
            values={
                "status": RunStatus.FAILED.value,
                "error_json": tables.dumps_canonical(error),
                "finished_at": tables.utc_now_iso(),
            },
            message="分析任务已不在运行中，失败结果不会覆盖当前状态",
        )

    def cancel(self, job_id: str) -> AnalysisJobRecord:
        return self._cas_transition(
            job_id,
            expected=RUN_CANCELABLE_STATUSES,
            values={
                "status": RunStatus.CANCELED.value,
                "finished_at": tables.utc_now_iso(),
            },
            message="只有排队或运行中的分析任务可以取消",
        )

    def retry(self, job_id: str) -> AnalysisJobRecord:
        """从 failed/canceled/interrupted 发起重试，产生引用原任务的新 queued 任务。"""

        row = self._get_row(job_id)
        if row.status not in RUN_RETRYABLE_STATUSES:
            raise PlatformError(
                ANALYSIS_JOB_NOT_RETRYABLE,
                f"状态为 {row.status} 的分析任务不能重试",
                {"job_id": job_id, "status": row.status},
                http_status=409,
            )
        if self.find_active(job_kind=row.job_kind, subject_id=row.subject_id) is not None:
            raise PlatformError(
                ANALYSIS_JOB_ALREADY_ACTIVE,
                "该对象已有排队或运行中的同类分析任务，不能重复重试",
                {"job_id": job_id, "job_kind": row.job_kind, "subject_id": row.subject_id},
                http_status=409,
            )
        new_row = AnalysisJob(
            id=_new_id(),
            job_kind=row.job_kind,
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            request_fingerprint=row.request_fingerprint,
            status=RunStatus.QUEUED.value,
            retry_of_job_id=row.id,
        )
        self._s.add(new_row)
        try:
            self._s.commit()
        except IntegrityError as exc:
            self._s.rollback()
            raise PlatformError(
                ANALYSIS_JOB_ALREADY_ACTIVE,
                "该对象已有排队或运行中的同类分析任务，不能重复重试",
                {"job_id": job_id, "job_kind": row.job_kind, "subject_id": row.subject_id},
                http_status=409,
            ) from exc
        return _analysis_job_record(new_row)


# ---------------------------------------------------------------------------
# v0.6.1 render asset repository (SQLite v6)
# ---------------------------------------------------------------------------


def _render_asset_record(row: RenderAsset) -> RenderAssetRecord:
    """ORM 行 → 公共 DTO；``asset_dir`` 等内部列在此边界被截断。

    相对 URL 仅在 ready 状态暴露（文件 GET 要求 ready 行，设计 §2.3）。
    """

    ready = row.status == STATUS_READY
    return RenderAssetRecord(
        id=row.id,
        source_kind=row.source_kind,
        source_id=row.source_id,
        renderer=row.renderer,
        status=row.status,
        grid_sha256=row.grid_sha256,
        netcdf_sha256=row.netcdf_sha256 if ready else None,
        manifest_url=f"/api/render-assets/{row.id}/manifest" if ready else None,
        netcdf_url=f"/api/render-assets/{row.id}/volume.nc" if ready else None,
        error=tables.loads_canonical(row.error_json) if row.error_json is not None else None,
    )


class RenderAssetRepository:
    """NetCDF 渲染资产状态机：五元身份幂等，全部迁移为 compare-and-update。"""

    def __init__(self, session: Session) -> None:
        self._s = session

    def _get_row(self, asset_id: str) -> RenderAsset:
        row = self._s.get(RenderAsset, asset_id)
        if row is None:
            raise PlatformError(
                "RENDER_ASSET_NOT_FOUND",
                "渲染资产不存在",
                {"asset_id": asset_id},
                http_status=404,
            )
        return row

    def _get_by_identity(self, source: RenderGridSource) -> RenderAsset | None:
        return self._s.scalar(
            select(RenderAsset).where(
                RenderAsset.source_kind == source.source_kind,
                RenderAsset.source_id == source.source_id,
                RenderAsset.grid_sha256 == source.grid_sha256,
                RenderAsset.renderer == RENDERER,
                RenderAsset.format_version == FORMAT_VERSION,
            )
        )

    def claim(
        self, source: RenderGridSource, *, retry_failed: bool
    ) -> tuple[RenderAssetRecord, bool]:
        """认领 source 的创建权，返回 ``(record, created)``。

        - 无行：插入 creating 行（created=True）；并发插入撞五列唯一约束时
          回滚并重读胜出者（created=False），绝不覆盖既有行。
        - creating：他方正持有创建权，原样返回（created=False）。
        - ready：幂等复用（created=False）；ready→creating 被禁止，
          ``retry_failed=True`` 也不会把 ready 行翻回。
        - failed/interrupted：仅 ``retry_failed=True`` 时以 CAS 翻回
          creating（created=True），否则原样返回持久化的失败/中断。
        """

        row = self._get_by_identity(source)
        if row is None:
            row = RenderAsset(
                id=render_asset_id(
                    source_kind=source.source_kind,
                    source_id=source.source_id,
                    grid_sha256=source.grid_sha256,
                ),
                source_kind=source.source_kind,
                source_id=source.source_id,
                candidate_result_id=(
                    source.source_id if source.source_kind == "candidate_result" else None
                ),
                renderer=RENDERER,
                format_version=FORMAT_VERSION,
                status=STATUS_CREATING,
                grid_sha256=source.grid_sha256,
            )
            self._s.add(row)
            try:
                self._s.commit()
            except IntegrityError:
                self._s.rollback()
                winner = self._get_by_identity(source)
                if winner is None:
                    # 非唯一性竞态（如候选外键违例）：不伪装成竞态，原样抛出
                    raise
                return _render_asset_record(winner), False
            return _render_asset_record(row), True
        if row.status in (STATUS_CREATING, STATUS_READY):
            return _render_asset_record(row), False
        if not retry_failed:
            return _render_asset_record(row), False
        # failed/interrupted → creating：以读到的状态为比较条件原子翻转，
        # 并清除失败残留，避免过期身份随重试存活。
        result = self._s.execute(
            update(RenderAsset)
            .where(RenderAsset.id == row.id, RenderAsset.status == row.status)
            .values(
                status=STATUS_CREATING,
                error_json=None,
                netcdf_sha256=None,
                asset_dir=None,
                manifest_json="{}",
                updated_at=tables.utc_now_iso(),
            )
        )
        if result.rowcount != 1:
            # 并发改写：回滚重读现状，由调用方按当前状态处理
            self._s.rollback()
            return _render_asset_record(self._get_row(row.id)), False
        self._s.commit()
        return _render_asset_record(self._get_row(row.id)), True

    def _cas_transition(
        self,
        asset_id: str,
        *,
        values: dict[str, Any],
        message: str,
    ) -> RenderAssetRecord:
        """仅 creating 可迁移的原子比较并更新；不匹配时不覆盖现状，抛 409。"""

        values.setdefault("updated_at", tables.utc_now_iso())
        result = self._s.execute(
            update(RenderAsset)
            .where(RenderAsset.id == asset_id, RenderAsset.status == STATUS_CREATING)
            .values(**values)
        )
        if result.rowcount != 1:
            self._s.rollback()
            actual = self._get_row(asset_id).status  # RENDER_ASSET_NOT_FOUND if absent
            raise PlatformError(
                INVALID_STATUS_TRANSITION,
                message,
                {"asset_id": asset_id, "expected": [STATUS_CREATING], "actual": actual},
                http_status=409,
            )
        self._s.commit()
        return _render_asset_record(self._get_row(asset_id))

    def mark_ready(
        self,
        asset_id: str,
        *,
        netcdf_sha256: str,
        asset_dir: str,
        manifest: dict[str, Any],
    ) -> RenderAssetRecord:
        return self._cas_transition(
            asset_id,
            values={
                "status": STATUS_READY,
                "netcdf_sha256": netcdf_sha256,
                "asset_dir": asset_dir,
                "manifest_json": tables.dumps_canonical(manifest),
                "error_json": None,
            },
            message="渲染资产已不在创建中，就绪结果不会覆盖当前状态",
        )

    def mark_failed(
        self,
        asset_id: str,
        *,
        code: str,
        message: str,
        details: dict[str, Any],
    ) -> RenderAssetRecord:
        return self._cas_transition(
            asset_id,
            values={
                "status": STATUS_FAILED,
                "error_json": tables.dumps_canonical(
                    {"code": code, "message": message, "details": details}
                ),
            },
            message="渲染资产已不在创建中，失败结果不会覆盖当前状态",
        )

    def get_for_source(self, source_kind: str, source_id: str) -> RenderAssetRecord:
        """返回该源最新的渲染资产；从未创建过时 404。"""

        row = self._s.scalar(
            select(RenderAsset)
            .where(
                RenderAsset.source_kind == source_kind,
                RenderAsset.source_id == source_id,
            )
            .order_by(RenderAsset.created_at.desc())
            .limit(1)
        )
        if row is None:
            raise PlatformError(
                "RENDER_ASSET_NOT_FOUND",
                "该渲染源尚未创建渲染资产",
                {"source_kind": source_kind, "source_id": source_id},
                http_status=404,
            )
        return _render_asset_record(row)

    def get_ready(self, asset_id: str) -> RenderAssetRecord:
        """文件下发前的就绪门禁：只有 ready 行可以读文件。"""

        row = self._get_row(asset_id)
        if row.status != STATUS_READY:
            raise PlatformError(
                "RENDER_ASSET_NOT_READY",
                "渲染资产尚未就绪",
                {"asset_id": asset_id, "status": row.status},
                http_status=409,
            )
        return _render_asset_record(row)
