"""Case lifecycle service: ownership, eligibility, trash, and restore.

The service resolves the complete ownership graph from persisted relationships
(never from browser data), enforces deletion eligibility and inflight-work
checks, and performs atomic lifecycle transitions.

v0.7.0 第三批设计 §5：只有持久化 Case 且 ``workspace_kind == "user_upload"``
且 ``read_only is not True`` 的案例可删除。适配器层内置身份（resistivity、
gas、microseismic）在 Case 查找前即拒绝。
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from geomodeling.platform.errors import (
    CASE_DELETE_FORBIDDEN,
    CASE_HAS_INFLIGHT_WORK,
    CASE_NOT_FOUND,
    CASE_PURGE_BLOCKED,
    CASE_PURGE_CONFIRMATION_MISMATCH,
    PlatformError,
)
from geomodeling.platform.repositories import (
    CaseRepository,
    _case_record,
)
from geomodeling.platform.schemas import (
    CasePurgeManifest,
    PurgeFileMove,
)
from geomodeling.platform.tables import (
    AnalysisJob,
    AnomalyExtraction,
    CandidateResult,
    Case,
    CaseLifecycleState,
    CasePurgeOperation,
    DatasetVersion,
    Experiment,
    Export,
    FormalSelection,
    ProfessionalConfirmation,
    ProfessionalDiagnostic,
    ProfessionalResultArtifacts,
    Publication,
    QualityReport,
    RenderAsset,
    Run,
    RunStatus,
    loads_canonical,
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
    # Permanent purge with quarantine
    # ------------------------------------------------------------------

    def purge(
        self,
        case_id: str,
        *,
        confirmation_name: str,
        failpoint: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Permanently purge a trashed case through quarantine.

        1. Require trashed state and exact name confirmation.
        2. Build manifest from persisted ownership graph.
        3. Move files to quarantine directory.
        4. Delete all rows in dependency order inside one transaction.
        5. Clean quarantine after successful commit.

        Any failure before commit restores quarantined files and records
        ``rolled_back``.  After commit, recovery completes cleanup.
        """

        self._assert_not_adapter_builtin(case_id)

        with self._runtime.session() as session:
            row = self._get_case_row(session, case_id)
            self._assert_deletable(row)

            if row.lifecycle_state != CaseLifecycleState.TRASHED.value:
                raise PlatformError(
                    CASE_PURGE_BLOCKED,
                    "案例未在回收站，无法永久删除",
                    {"case_id": case_id, "lifecycle_state": row.lifecycle_state},
                    http_status=409,
                )

            if confirmation_name != row.name:
                raise PlatformError(
                    CASE_PURGE_CONFIRMATION_MISMATCH,
                    "确认名称与案例名称不匹配",
                    {"case_id": case_id},
                    http_status=422,
                )

            ownership = self.ownership(case_id)
            self.assert_no_inflight(ownership)

            manifest = self._build_manifest(session, case_id, ownership)

            operation_id = str(uuid.uuid4())
            op = CasePurgeOperation(
                id=operation_id,
                case_id=case_id,
                state="prepared",
                manifest_json=json.dumps(manifest.model_dump(), ensure_ascii=False,
                                         sort_keys=True, separators=(",", ":")),
            )
            session.add(op)
            session.commit()

        if failpoint:
            failpoint("after_prepared")

        quarantine_dir = self._runtime.settings.purge_quarantine_dir / operation_id

        try:
            file_moves = self._move_files_to_quarantine_v2(manifest, quarantine_dir)

            with self._runtime.session() as session:
                op_row = session.get(CasePurgeOperation, operation_id)
                op_row.state = "quarantined"
                session.commit()

            if failpoint:
                failpoint("after_quarantined")

            with self._runtime.session() as session:
                self._delete_rows(session, case_id, ownership)
                op_row = session.get(CasePurgeOperation, operation_id)
                op_row.state = "committed"
                op_row.receipt_json = json.dumps(
                    {"deleted": True, "committed_at": utc_now_iso()},
                    ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                )
                session.commit()

        except Exception:
            if quarantine_dir.exists():
                self._restore_files_from_quarantine_v2(manifest, quarantine_dir)
            with self._runtime.session() as session:
                op_row = session.get(CasePurgeOperation, operation_id)
                if op_row is not None and op_row.state not in ("committed", "cleaned"):
                    op_row.state = "rolled_back"
                    op_row.error_json = json.dumps(
                        {"code": "PURGE_ROLLBACK", "message": "文件已恢复"},
                        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                    )
                    session.commit()
            raise

        if failpoint:
            failpoint("after_committed")

        if quarantine_dir.exists():
            import shutil
            shutil.rmtree(quarantine_dir, ignore_errors=True)

        with self._runtime.session() as session:
            op_row = session.get(CasePurgeOperation, operation_id)
            op_row.state = "cleaned"
            session.commit()

        return {"operation_id": operation_id, "state": "cleaned"}

    # ------------------------------------------------------------------
    # Manifest building
    # ------------------------------------------------------------------

    def _build_manifest(
        self, session: Session, case_id: str, ownership: CaseOwnership,
    ) -> CasePurgeManifest:
        """Build typed manifest with relative paths and file hashes."""

        settings = self._runtime.settings
        roots = {
            "uploads": settings.uploads_dir,
            "datasets": settings.datasets_dir,
            "experiments": settings.experiments_dir,
            "results": settings.results_dir,
            "exports": settings.exports_dir,
            "render_assets": settings.render_assets_dir,
            "comparisons": settings.comparisons_dir,
        }

        raw_files: list[tuple[str, Path]] = []

        for did in ownership.dataset_ids:
            dv = session.get(DatasetVersion, did)
            if dv and dv.source_path:
                raw_files.append(("uploads", Path(dv.source_path)))
            if dv and dv.standardized_path:
                raw_files.append(("datasets", Path(dv.standardized_path)))
            for diag_id in ownership.diagnosis_ids:
                diag = session.get(ProfessionalDiagnostic, diag_id)
                if diag:
                    diag_dir = settings.professional_diagnosis_dir(
                        case_id, did, diag_id,
                    )
                    if diag_dir.exists():
                        for f in diag_dir.rglob("*"):
                            if f.is_file() and not f.is_symlink():
                                raw_files.append(("datasets", f))

        for cid in ownership.candidate_ids:
            cand = session.get(CandidateResult, cid)
            if cand and cand.grid_path:
                raw_files.append(("results", Path(cand.grid_path)))
            if cand and cand.predictions_path:
                raw_files.append(("results", Path(cand.predictions_path)))

            prof_dir = settings.professional_result_dir(cid)
            if prof_dir.exists():
                for f in prof_dir.rglob("*"):
                    if f.is_file() and not f.is_symlink():
                        raw_files.append(("results", f))

            for ext_id in ownership.extraction_ids:
                ext = session.get(AnomalyExtraction, ext_id)
                if ext:
                    ext_dir = settings.anomaly_extraction_dir(cid, ext_id)
                    if ext_dir.exists():
                        for f in ext_dir.rglob("*"):
                            if f.is_file() and not f.is_symlink():
                                raw_files.append(("results", f))

        for eid in ownership.export_ids:
            exp = session.get(Export, eid)
            if exp and exp.package_path:
                raw_files.append(("exports", Path(exp.package_path)))

        for ra in session.scalars(
            select(RenderAsset).where(
                RenderAsset.candidate_result_id.in_(ownership.candidate_ids)
            )
        ).all():
            if ra.asset_dir:
                ad = Path(ra.asset_dir)
                if ad.exists():
                    for f in ad.rglob("*"):
                        if f.is_file() and not f.is_symlink():
                            raw_files.append(("render_assets", f))

        comp_files = self._collect_comparison_files(
            session, settings.comparisons_dir, set(ownership.candidate_ids),
        )
        for cf in comp_files:
            raw_files.append(("comparisons", cf))

        file_moves: list[PurgeFileMove] = []
        seen: set[Path] = set()
        for root_name, file_path in raw_files:
            if file_path in seen:
                continue
            seen.add(file_path)
            move = self._validate_and_serialize_file(file_path, root_name, roots[root_name])
            file_moves.append(move)

        row_ids = {
            "datasets": list(ownership.dataset_ids),
            "experiments": list(ownership.experiment_ids),
            "runs": list(ownership.run_ids),
            "candidates": list(ownership.candidate_ids),
            "diagnostics": list(ownership.diagnosis_ids),
            "confirmations": list(ownership.confirmation_ids),
            "extractions": list(ownership.extraction_ids),
            "exports": list(ownership.export_ids),
        }

        return CasePurgeManifest(
            case_id=case_id,
            row_ids=row_ids,
            files=file_moves,
        )

    def _collect_comparison_files(
        self, session: Session, comp_dir: Path, candidate_ids: set[str],
    ) -> list[Path]:
        """Collect comparison registry JSON files owned by the case."""

        if not comp_dir.exists():
            return []
        result: list[Path] = []
        for f in comp_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                raise PlatformError(
                    CASE_PURGE_BLOCKED,
                    "比较登记文件损坏",
                    {"file": f.name},
                    http_status=409,
                )
            first_id = data.get("first_result_id")
            second_id = data.get("second_result_id")
            if first_id is None or second_id is None:
                continue
            if first_id in candidate_ids and second_id in candidate_ids:
                result.append(f)
            elif first_id in candidate_ids or second_id in candidate_ids:
                raise PlatformError(
                    CASE_PURGE_BLOCKED,
                    "比较登记文件跨案例引用",
                    {"file": f.name},
                    http_status=409,
                )
        return result

    @staticmethod
    def _validate_and_serialize_file(
        file_path: Path, root_name: str, root_dir: Path,
    ) -> PurgeFileMove:
        """Validate path containment and compute hash."""

        resolved = file_path.resolve(strict=True)
        root_resolved = root_dir.resolve()
        if not str(resolved).startswith(str(root_resolved)):
            raise PlatformError(
                CASE_PURGE_BLOCKED,
                "文件不在受控根目录内",
                {"root": root_name},
                http_status=409,
            )
        if file_path.is_symlink():
            raise PlatformError(
                CASE_PURGE_BLOCKED,
                "文件是符号链接",
                {"root": root_name},
                http_status=409,
            )
        rel = resolved.relative_to(root_resolved).as_posix()
        content = resolved.read_bytes()
        sha = hashlib.sha256(content).hexdigest()
        return PurgeFileMove(
            root=root_name,
            relative_path=rel,
            sha256=sha,
            size_bytes=len(content),
        )

    # ------------------------------------------------------------------
    # File quarantine
    # ------------------------------------------------------------------

    @staticmethod
    def _move_files_to_quarantine(
        manifest: CasePurgeManifest, quarantine_dir: Path,
    ) -> dict[str, Path]:
        """Atomically rename files to quarantine. Returns original->quarantine map."""

        settings_roots: dict[str, Path] = {}
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        moved: dict[str, Path] = {}
        for fm in manifest.files:
            root_key = fm.root
            if root_key not in settings_roots:
                continue
            original = settings_roots.get(root_key)
            if original is None:
                continue
            src = original / fm.relative_path
            if not src.exists():
                continue
            dst = quarantine_dir / fm.root / fm.relative_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dst)
            moved[str(src)] = dst
        return moved

    def _move_files_to_quarantine_v2(
        self, manifest: CasePurgeManifest, quarantine_dir: Path,
    ) -> dict[str, Path]:
        """Atomically rename files to quarantine using runtime settings."""

        settings = self._runtime.settings
        roots = {
            "uploads": settings.uploads_dir,
            "datasets": settings.datasets_dir,
            "experiments": settings.experiments_dir,
            "results": settings.results_dir,
            "exports": settings.exports_dir,
            "render_assets": settings.render_assets_dir,
            "comparisons": settings.comparisons_dir,
        }
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        moved: dict[str, Path] = {}
        for fm in manifest.files:
            root_dir = roots[fm.root]
            src = root_dir / fm.relative_path
            if not src.exists():
                continue
            dst = quarantine_dir / fm.root / fm.relative_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dst)
            moved[str(src)] = dst
        return moved

    @staticmethod
    def _restore_files_from_quarantine(
        manifest: CasePurgeManifest, quarantine_dir: Path,
    ) -> None:
        """Restore quarantined files to their original locations."""

        roots: dict[str, Path] = {}
        for fm in manifest.files:
            root_dir = roots.get(fm.root)
            if root_dir is None:
                continue
            src = quarantine_dir / fm.root / fm.relative_path
            if not src.exists():
                continue
            dst = root_dir / fm.relative_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(src, dst)
            except OSError:
                pass

    def _restore_files_from_quarantine_v2(
        self, manifest: CasePurgeManifest, quarantine_dir: Path,
    ) -> None:
        """Restore quarantined files to their original locations using runtime settings."""

        settings = self._runtime.settings
        roots = {
            "uploads": settings.uploads_dir,
            "datasets": settings.datasets_dir,
            "experiments": settings.experiments_dir,
            "results": settings.results_dir,
            "exports": settings.exports_dir,
            "render_assets": settings.render_assets_dir,
            "comparisons": settings.comparisons_dir,
        }
        for fm in manifest.files:
            root_dir = roots[fm.root]
            src = quarantine_dir / fm.root / fm.relative_path
            if not src.exists():
                continue
            dst = root_dir / fm.relative_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(src, dst)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Row deletion
    # ------------------------------------------------------------------

    @staticmethod
    def _delete_rows(session: Session, case_id: str, ownership: CaseOwnership) -> None:
        """Delete all owned rows in dependency order inside one transaction."""

        if ownership.run_ids:
            session.execute(
                Run.__table__.update()
                .where(Run.id.in_(ownership.run_ids), Run.retry_of_run_id.isnot(None))
                .values(retry_of_run_id=None)
            )
        if ownership.diagnosis_ids or ownership.extraction_ids:
            subject_ids = ownership.diagnosis_ids + ownership.extraction_ids
            session.execute(
                AnalysisJob.__table__.update()
                .where(
                    AnalysisJob.subject_id.in_(subject_ids),
                    AnalysisJob.retry_of_job_id.isnot(None),
                )
                .values(retry_of_job_id=None)
            )

        if ownership.diagnosis_ids or ownership.extraction_ids:
            subject_ids = ownership.diagnosis_ids + ownership.extraction_ids
            session.execute(
                AnalysisJob.__table__.delete()
                .where(AnalysisJob.subject_id.in_(subject_ids))
            )

        session.execute(
            Publication.__table__.delete()
            .where(Publication.export_id.in_(
                select(Export.id).where(Export.case_id == case_id)
            ))
        )

        session.execute(Export.__table__.delete().where(Export.case_id == case_id))

        if ownership.candidate_ids:
            session.execute(
                RenderAsset.__table__.delete()
                .where(RenderAsset.candidate_result_id.in_(ownership.candidate_ids))
            )
            session.execute(
                AnomalyExtraction.__table__.delete()
                .where(AnomalyExtraction.candidate_result_id.in_(ownership.candidate_ids))
            )
            session.execute(
                ProfessionalResultArtifacts.__table__.delete()
                .where(ProfessionalResultArtifacts.candidate_result_id.in_(ownership.candidate_ids))
            )

        session.execute(FormalSelection.__table__.delete().where(FormalSelection.case_id == case_id))

        if ownership.candidate_ids:
            session.execute(
                CandidateResult.__table__.delete()
                .where(CandidateResult.id.in_(ownership.candidate_ids))
            )

        if ownership.confirmation_ids:
            session.execute(
                ProfessionalConfirmation.__table__.delete()
                .where(ProfessionalConfirmation.id.in_(ownership.confirmation_ids))
            )
        if ownership.diagnosis_ids:
            session.execute(
                ProfessionalDiagnostic.__table__.delete()
                .where(ProfessionalDiagnostic.id.in_(ownership.diagnosis_ids))
            )

        if ownership.run_ids:
            session.execute(Run.__table__.delete().where(Run.id.in_(ownership.run_ids)))

        session.execute(Experiment.__table__.delete().where(Experiment.case_id == case_id))

        session.execute(
            QualityReport.__table__.delete()
            .where(QualityReport.dataset_version_id.in_(
                select(DatasetVersion.id).where(DatasetVersion.case_id == case_id)
            ))
        )

        session.execute(DatasetVersion.__table__.delete().where(DatasetVersion.case_id == case_id))

        session.execute(Case.__table__.delete().where(Case.id == case_id))

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
