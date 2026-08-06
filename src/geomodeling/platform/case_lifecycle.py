"""Case lifecycle service: ownership, eligibility, trash, and restore.

The service resolves the complete ownership graph from persisted relationships
(never from browser data), enforces deletion eligibility and inflight-work
checks, and performs atomic lifecycle transitions.

v0.7.0 第三批设计 §5：只有持久化 Case 且 ``workspace_kind == "user_upload"``
且 ``read_only is not True`` 的案例可删除。适配器层内置身份（resistivity、
gas、microseismic）在 Case 查找前即拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from geomodeling.platform.errors import (
    CASE_DELETE_FORBIDDEN,
    CASE_HAS_INFLIGHT_WORK,
    CASE_NOT_FOUND,
    CASE_PURGE_BLOCKED,
    PlatformError,
)
from geomodeling.platform.repositories import (
    CaseRepository,
    _case_record,
)
from geomodeling.platform.tables import (
    AnalysisJob,
    AnomalyExtraction,
    CandidateResult,
    Case,
    CaseLifecycleState,
    DatasetVersion,
    Experiment,
    Export,
    ProfessionalConfirmation,
    ProfessionalDiagnostic,
    RenderAsset,
    Run,
    RunStatus,
    utc_now_iso,
)

# Adapter-only builtin IDs: these never have a persisted Case row and are
# forbidden from lifecycle operations before database lookup.
_ADAPTER_BUILTIN_CASE_IDS = frozenset({"resistivity", "gas", "microseismic"})

_RUN_INFLIGHT = frozenset({RunStatus.QUEUED.value, RunStatus.RUNNING.value})


@dataclass(frozen=True)
class CaseOwnership:
    """Complete typed ownership graph resolved from persisted relationships."""

    case_id: str
    dataset_ids: tuple[str, ...]
    experiment_ids: tuple[str, ...]
    run_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    diagnosis_ids: tuple[str, ...]
    confirmation_ids: tuple[str, ...]
    extraction_ids: tuple[str, ...]
    export_ids: tuple[str, ...]


class CaseLifecycleService:
    """Domain service for case trash, restore, and ownership resolution."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    # ------------------------------------------------------------------
    # Ownership resolution
    # ------------------------------------------------------------------

    def ownership(self, case_id: str) -> CaseOwnership:
        """Resolve the complete typed ownership graph from persisted rows."""

        with self._runtime.session() as session:
            self._assert_not_adapter_builtin(case_id)
            case = self._get_case_row(session, case_id)

            dataset_ids = tuple(
                session.scalars(
                    select(DatasetVersion.id)
                    .where(DatasetVersion.case_id == case_id)
                    .order_by(DatasetVersion.version.asc())
                ).all()
            )

            experiment_ids = tuple(
                session.scalars(
                    select(Experiment.id)
                    .where(Experiment.case_id == case_id)
                    .order_by(Experiment.created_at.asc())
                ).all()
            )

            run_ids = (
                tuple(
                    session.scalars(
                        select(Run.id)
                        .where(Run.experiment_id.in_(experiment_ids))
                        .order_by(Run.created_at.asc())
                    ).all()
                )
                if experiment_ids
                else ()
            )

            candidate_ids = (
                tuple(
                    session.scalars(
                        select(CandidateResult.id)
                        .where(CandidateResult.run_id.in_(run_ids))
                        .order_by(CandidateResult.created_at.asc())
                    ).all()
                )
                if run_ids
                else ()
            )

            diagnosis_ids = (
                tuple(
                    session.scalars(
                        select(ProfessionalDiagnostic.id)
                        .where(ProfessionalDiagnostic.dataset_version_id.in_(dataset_ids))
                        .order_by(ProfessionalDiagnostic.created_at.asc())
                    ).all()
                )
                if dataset_ids
                else ()
            )

            confirmation_ids = (
                tuple(
                    session.scalars(
                        select(ProfessionalConfirmation.id)
                        .where(ProfessionalConfirmation.diagnostic_id.in_(diagnosis_ids))
                        .order_by(ProfessionalConfirmation.created_at.asc())
                    ).all()
                )
                if diagnosis_ids
                else ()
            )

            extraction_ids = (
                tuple(
                    session.scalars(
                        select(AnomalyExtraction.id)
                        .where(AnomalyExtraction.candidate_result_id.in_(candidate_ids))
                        .order_by(AnomalyExtraction.created_at.asc())
                    ).all()
                )
                if candidate_ids
                else ()
            )

            export_ids = tuple(
                session.scalars(
                    select(Export.id)
                    .where(Export.case_id == case_id)
                    .order_by(Export.created_at.asc())
                ).all()
            )

            return CaseOwnership(
                case_id=case_id,
                dataset_ids=dataset_ids,
                experiment_ids=experiment_ids,
                run_ids=run_ids,
                candidate_ids=candidate_ids,
                diagnosis_ids=diagnosis_ids,
                confirmation_ids=confirmation_ids,
                extraction_ids=extraction_ids,
                export_ids=export_ids,
            )

    # ------------------------------------------------------------------
    # Inflight detection
    # ------------------------------------------------------------------

    def assert_no_inflight(self, ownership: CaseOwnership) -> None:
        """Raise CASE_HAS_INFLIGHT_WORK if any owned task is non-terminal."""

        with self._runtime.session() as session:
            if ownership.run_ids:
                active_runs = session.scalar(
                    select(Run.id)
                    .where(
                        Run.id.in_(ownership.run_ids),
                        Run.status.in_(sorted(_RUN_INFLIGHT)),
                    )
                    .limit(1)
                )
                if active_runs is not None:
                    raise PlatformError(
                        CASE_HAS_INFLIGHT_WORK,
                        "案例存在排队或运行中的建模任务",
                        {"case_id": ownership.case_id, "run_id": active_runs},
                        http_status=409,
                    )

            diag_subject_ids = ownership.diagnosis_ids
            ext_subject_ids = ownership.extraction_ids
            subject_ids = diag_subject_ids + ext_subject_ids
            if subject_ids:
                active_jobs = session.scalar(
                    select(AnalysisJob.id)
                    .where(
                        AnalysisJob.subject_id.in_(subject_ids),
                        AnalysisJob.status.in_(sorted(_RUN_INFLIGHT)),
                    )
                    .limit(1)
                )
                if active_jobs is not None:
                    raise PlatformError(
                        CASE_HAS_INFLIGHT_WORK,
                        "案例存在排队或运行中的分析任务",
                        {"case_id": ownership.case_id, "job_id": active_jobs},
                        http_status=409,
                    )

            if ownership.candidate_ids:
                creating_asset = session.scalar(
                    select(RenderAsset.id)
                    .where(
                        RenderAsset.candidate_result_id.in_(ownership.candidate_ids),
                        RenderAsset.status == "creating",
                    )
                    .limit(1)
                )
                if creating_asset is not None:
                    raise PlatformError(
                        CASE_HAS_INFLIGHT_WORK,
                        "案例存在正在创建的渲染资产",
                        {"case_id": ownership.case_id, "asset_id": creating_asset},
                        http_status=409,
                    )

    # ------------------------------------------------------------------
    # Trash and restore
    # ------------------------------------------------------------------

    def trash(self, case_id: str) -> Any:
        """Atomically transition an active user-upload case to trashed."""

        self._assert_not_adapter_builtin(case_id)
        with self._runtime.session() as session:
            row = self._get_case_row(session, case_id)
            self._assert_deletable(row)

            if row.lifecycle_state == CaseLifecycleState.TRASHED.value:
                return _case_record(row)

            if row.lifecycle_state != CaseLifecycleState.ACTIVE.value:
                raise PlatformError(
                    CASE_PURGE_BLOCKED,
                    "案例正在清理",
                    {"case_id": case_id},
                    http_status=409,
                )

            ownership = self.ownership(case_id)
            self.assert_no_inflight(ownership)

            row.lifecycle_state = CaseLifecycleState.TRASHED.value
            row.trashed_at = utc_now_iso()
            session.commit()
            return _case_record(row)

    def restore(self, case_id: str) -> Any:
        """Atomically transition a trashed case back to active."""

        self._assert_not_adapter_builtin(case_id)
        with self._runtime.session() as session:
            row = self._get_case_row(session, case_id)
            self._assert_deletable(row)

            if row.lifecycle_state == CaseLifecycleState.ACTIVE.value:
                return _case_record(row)

            if row.lifecycle_state != CaseLifecycleState.TRASHED.value:
                raise PlatformError(
                    CASE_PURGE_BLOCKED,
                    "案例正在清理，无法恢复",
                    {"case_id": case_id},
                    http_status=409,
                )

            row.lifecycle_state = CaseLifecycleState.ACTIVE.value
            row.trashed_at = None
            session.commit()
            return _case_record(row)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_not_adapter_builtin(case_id: str) -> None:
        if case_id in _ADAPTER_BUILTIN_CASE_IDS:
            raise PlatformError(
                CASE_DELETE_FORBIDDEN,
                "内置案例不可删除",
                {"case_id": case_id},
                http_status=409,
            )

    @staticmethod
    def _get_case_row(session: Session, case_id: str) -> Case:
        row = session.get(Case, case_id)
        if row is None:
            raise PlatformError(
                CASE_NOT_FOUND,
                "案例不存在",
                {"case_id": case_id},
                http_status=404,
            )
        return row

    @staticmethod
    def _assert_deletable(row: Case) -> None:
        from geomodeling.platform.tables import loads_canonical

        config = loads_canonical(row.config_json)
        workspace_kind = config.get("workspace_kind", "user_upload")
        is_read_only = config.get("read_only") is True

        if workspace_kind != "user_upload" or is_read_only:
            raise PlatformError(
                CASE_DELETE_FORBIDDEN,
                "内置案例不可删除",
                {"case_id": row.id, "workspace_kind": workspace_kind},
                http_status=409,
            )
