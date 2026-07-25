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
    RUN_ALREADY_ACTIVE,
    RUN_NOT_FOUND,
    RUN_NOT_RETRYABLE,
    PlatformError,
)
from geomodeling.platform.schemas import (
    CandidateResultRecord,
    CaseCreateRequest,
    CaseRecord,
    DatasetStatus,
    DatasetVersionRecord,
    ExperimentCreateRequest,
    ExperimentRecord,
    FormalSelectionRecord,
    FormalSelectionRequest,
    RunRecord,
)
from geomodeling.platform.tables import (
    CandidateResult,
    Case,
    DatasetVersion,
    Experiment,
    FormalSelection,
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

    def create(self, case_id: str, request: ExperimentCreateRequest) -> ExperimentRecord:
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
        """只有成功 run 产出的候选可以设为正式模型，且必须属于本案例。

        ownership（404）先于 run 状态（409）检查：跨案例探测候选时
        一律得到 404，不泄露候选存在性及其任务状态。
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
