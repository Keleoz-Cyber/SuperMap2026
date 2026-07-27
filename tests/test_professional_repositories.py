"""State tests for the v0.6 professional repositories (SQLite v5).

Covers the five typed repositories over the new tables: diagnostics,
immutable confirmations, per-candidate professional artifacts, idempotent
anomaly extractions and persistent analysis jobs — plus the deterministic
artifact paths and the typed record contracts.
"""

from __future__ import annotations

import json
import re
import sqlite3

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError

from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.errors import (
    ANALYSIS_JOB_ALREADY_ACTIVE,
    ANALYSIS_JOB_NOT_FOUND,
    ANALYSIS_JOB_NOT_RETRYABLE,
    ANOMALY_EXTRACTION_NOT_FOUND,
    CANDIDATE_NOT_FOUND,
    DATASET_NOT_FOUND,
    INVALID_STATUS_TRANSITION,
    PROFESSIONAL_ARTIFACTS_CONFLICT,
    PROFESSIONAL_ARTIFACTS_NOT_FOUND,
    PROFESSIONAL_CONFIRMATION_CONFLICT,
    PROFESSIONAL_CONFIRMATION_NOT_FOUND,
    PROFESSIONAL_DIAGNOSIS_NOT_FOUND,
    PROFESSIONAL_DIAGNOSIS_NOT_SUCCEEDED,
    PlatformError,
)
from geomodeling.platform.repositories import (
    AnalysisJobRepository,
    AnomalyExtractionRepository,
    ProfessionalConfirmationRepository,
    ProfessionalDiagnosticRepository,
    ProfessionalResultArtifactsRepository,
)
from geomodeling.platform.schemas import (
    AnalysisJobRecord,
    AnomalyExtractionRecord,
    ProfessionalConfirmationRecord,
    ProfessionalDiagnosticRecord,
    ProfessionalResultArtifactsRecord,
)
from geomodeling.platform.tables import ERROR_PROCESS_RESTARTED, RunStatus
from test_platform_repositories import (
    create_case,
    create_dataset,
    create_succeeded_candidate,
)

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@pytest.fixture()
def runtime(tmp_path):
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    yield runtime
    runtime.close()


def create_diagnostic(
    runtime: PlatformRuntime,
    status: str = "queued",
    *,
    fingerprint: str = "fp-diag",
    config: dict | None = None,
) -> str:
    dataset_id = create_dataset(runtime, create_case(runtime))
    with runtime.session() as session:
        repo = ProfessionalDiagnosticRepository(session)
        diagnosis_id = repo.create(
            dataset_id, config=config or {"lag": 1.0, "directions": ["omni"]}, fingerprint=fingerprint
        ).id
        if status == "queued":
            return diagnosis_id
        repo.mark_running(diagnosis_id)
        if status == "running":
            return diagnosis_id
        if status == "succeeded":
            repo.mark_succeeded(diagnosis_id, manifest={"artifacts": {"omni": {"sha256": "aa"}}})
            return diagnosis_id
        if status == "failed":
            repo.mark_failed(diagnosis_id, error={"code": "BOOM", "message": "失败"})
            return diagnosis_id
    raise AssertionError(f"unknown target status {status}")


def create_analysis_job(
    runtime: PlatformRuntime,
    *,
    job_kind: str = "professional_diagnosis",
    subject_type: str = "professional_diagnostic",
    subject_id: str = "diag-1",
    request_fingerprint: str = "fp-request",
) -> str:
    with runtime.session() as session:
        return (
            AnalysisJobRepository(session)
            .create(
                job_kind=job_kind,
                subject_type=subject_type,
                subject_id=subject_id,
                request_fingerprint=request_fingerprint,
            )
            .id
        )


# ---------------------------------------------------------------------------
# Professional diagnostics
# ---------------------------------------------------------------------------


class TestProfessionalDiagnostics:
    def test_create_returns_typed_record_with_server_uuid(self, runtime):
        with runtime.session() as session:
            dataset_id = create_dataset(runtime, create_case(runtime))
            record = ProfessionalDiagnosticRepository(session).create(
                dataset_id,
                config={"lag": 0.5, "方向": "全向"},
                fingerprint="fp-1",
            )
        assert isinstance(record, BaseModel)
        assert isinstance(record, ProfessionalDiagnosticRecord)
        assert not hasattr(record, "_sa_instance_state")
        assert UUID_RE.match(record.id)
        assert record.dataset_version_id == dataset_id
        assert record.status == RunStatus.QUEUED
        assert record.config == {"lag": 0.5, "方向": "全向"}
        assert record.fingerprint == "fp-1"
        assert record.manifest == {}
        assert record.error is None
        assert record.created_at and record.updated_at
        assert record.finished_at is None

    def test_create_requires_existing_dataset(self, runtime):
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                ProfessionalDiagnosticRepository(session).create(
                    "ghost", config={}, fingerprint="fp"
                )
        assert excinfo.value.code == DATASET_NOT_FOUND
        assert excinfo.value.http_status == 404

    def test_get_missing_diagnosis_is_404(self, runtime):
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                ProfessionalDiagnosticRepository(session).get("ghost")
        assert excinfo.value.code == PROFESSIONAL_DIAGNOSIS_NOT_FOUND
        assert excinfo.value.http_status == 404

    def test_queued_running_succeeded_happy_path(self, runtime):
        diagnosis_id = create_diagnostic(runtime)
        with runtime.session() as session:
            repo = ProfessionalDiagnosticRepository(session)
            running = repo.mark_running(diagnosis_id)
            assert running.status == RunStatus.RUNNING
            succeeded = repo.mark_succeeded(
                diagnosis_id, manifest={"artifacts": {"omni": {"sha256": "bb", "大小": 3}}}
            )
        assert succeeded.status == RunStatus.SUCCEEDED
        assert succeeded.manifest == {"artifacts": {"omni": {"sha256": "bb", "大小": 3}}}
        assert succeeded.finished_at is not None
        raw = sqlite3.connect(runtime.db_path)
        try:
            manifest_json = raw.execute(
                "SELECT manifest_json FROM professional_diagnostics WHERE id = ?",
                (diagnosis_id,),
            ).fetchone()[0]
        finally:
            raw.close()
        assert manifest_json == json.dumps(
            {"artifacts": {"omni": {"sha256": "bb", "大小": 3}}},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def test_mark_failed_persists_structured_error(self, runtime):
        diagnosis_id = create_diagnostic(runtime, status="running")
        with runtime.session() as session:
            record = ProfessionalDiagnosticRepository(session).mark_failed(
                diagnosis_id, error={"code": "GRID_TOO_SMALL", "message": "有效 bin 不足"}
            )
        assert record.status == RunStatus.FAILED
        assert record.error == {"code": "GRID_TOO_SMALL", "message": "有效 bin 不足"}
        assert record.finished_at is not None

    @pytest.mark.parametrize(
        "transition",
        ["mark_running", "mark_succeeded", "mark_failed"],
    )
    def test_terminal_diagnosis_rejects_further_transitions(self, runtime, transition):
        diagnosis_id = create_diagnostic(runtime, status="succeeded")
        with runtime.session() as session:
            repo = ProfessionalDiagnosticRepository(session)
            with pytest.raises(PlatformError) as excinfo:
                if transition == "mark_running":
                    repo.mark_running(diagnosis_id)
                elif transition == "mark_succeeded":
                    repo.mark_succeeded(diagnosis_id, manifest={})
                else:
                    repo.mark_failed(diagnosis_id, error={"code": "X", "message": "y"})
        assert excinfo.value.code == INVALID_STATUS_TRANSITION
        assert excinfo.value.http_status == 409

    def test_queued_diagnosis_cannot_complete_directly(self, runtime):
        diagnosis_id = create_diagnostic(runtime)
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                ProfessionalDiagnosticRepository(session).mark_succeeded(
                    diagnosis_id, manifest={}
                )
        assert excinfo.value.code == INVALID_STATUS_TRANSITION


# ---------------------------------------------------------------------------
# Immutable professional confirmations
# ---------------------------------------------------------------------------


class TestProfessionalConfirmations:
    def test_create_on_succeeded_diagnosis(self, runtime):
        diagnosis_id = create_diagnostic(runtime, status="succeeded")
        with runtime.session() as session:
            record = ProfessionalConfirmationRepository(session).create(
                diagnosis_id,
                config={"model": "spherical", "策略": "人工"},
                fingerprint="fp-conf-1",
                note="采纳候选主轴方向",
            )
        assert isinstance(record, ProfessionalConfirmationRecord)
        assert UUID_RE.match(record.id)
        assert record.diagnostic_id == diagnosis_id
        assert record.config == {"model": "spherical", "策略": "人工"}
        assert record.fingerprint == "fp-conf-1"
        assert record.note == "采纳候选主轴方向"

    def test_create_requires_succeeded_diagnosis(self, runtime):
        diagnosis_id = create_diagnostic(runtime, status="running")
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                ProfessionalConfirmationRepository(session).create(
                    diagnosis_id, config={}, fingerprint="fp", note="抢跑"
                )
        assert excinfo.value.code == PROFESSIONAL_DIAGNOSIS_NOT_SUCCEEDED
        assert excinfo.value.http_status == 409

    def test_create_requires_existing_diagnosis(self, runtime):
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                ProfessionalConfirmationRepository(session).create(
                    "ghost", config={}, fingerprint="fp", note="无诊断"
                )
        assert excinfo.value.code == PROFESSIONAL_DIAGNOSIS_NOT_FOUND

    def test_duplicate_fingerprint_snapshot_is_rejected(self, runtime):
        """同一诊断下同一配置指纹的确认是纯粹重复：拒绝，而不是静默覆盖。"""

        diagnosis_id = create_diagnostic(runtime, status="succeeded")
        with runtime.session() as session:
            repo = ProfessionalConfirmationRepository(session)
            repo.create(diagnosis_id, config={"model": "spherical"}, fingerprint="fp-x", note="一")
            with pytest.raises(PlatformError) as excinfo:
                repo.create(diagnosis_id, config={"model": "spherical"}, fingerprint="fp-x", note="二")
        assert excinfo.value.code == PROFESSIONAL_CONFIRMATION_CONFLICT
        assert excinfo.value.http_status == 409
        # 原始快照保持原样（含备注），未被第二次创建覆盖
        with runtime.session() as session:
            snapshots = ProfessionalConfirmationRepository(session).list_for_diagnostic(diagnosis_id)
        assert len(snapshots) == 1
        assert snapshots[0].note == "一"

    def test_distinct_fingerprints_create_separate_snapshots(self, runtime):
        """一个诊断可产生多个确认快照用于比较不同人工判断；修改参数必须新快照。"""

        diagnosis_id = create_diagnostic(runtime, status="succeeded")
        with runtime.session() as session:
            repo = ProfessionalConfirmationRepository(session)
            first = repo.create(diagnosis_id, config={"model": "spherical"}, fingerprint="fp-a", note="甲")
            second = repo.create(diagnosis_id, config={"model": "exponential"}, fingerprint="fp-b", note="乙")
            snapshots = repo.list_for_diagnostic(diagnosis_id)
        assert first.id != second.id
        assert [s.id for s in snapshots] == [first.id, second.id]

    def test_confirmation_is_immutable_and_has_no_update_path(self, runtime):
        """一次性不可变确认：仓储不提供任何更新入口。"""

        assert not hasattr(ProfessionalConfirmationRepository, "update")
        assert not hasattr(ProfessionalConfirmationRepository, "mark_succeeded")
        diagnosis_id = create_diagnostic(runtime, status="succeeded")
        with runtime.session() as session:
            repo = ProfessionalConfirmationRepository(session)
            created = repo.create(diagnosis_id, config={"model": "spherical"}, fingerprint="fp", note="原始")
            loaded = repo.get(created.id)
        assert loaded.model_dump() == created.model_dump()

    def test_get_missing_confirmation_is_404(self, runtime):
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                ProfessionalConfirmationRepository(session).get("ghost")
        assert excinfo.value.code == PROFESSIONAL_CONFIRMATION_NOT_FOUND


# ---------------------------------------------------------------------------
# Per-candidate professional result artifacts
# ---------------------------------------------------------------------------


class TestProfessionalResultArtifacts:
    def test_create_pending_and_complete(self, runtime):
        candidate_id = create_succeeded_candidate(runtime, create_case(runtime))
        with runtime.session() as session:
            repo = ProfessionalResultArtifactsRepository(session)
            record = repo.create(
                candidate_id,
                confirmation_id=None,
                capabilities={"fold_evidence": "available"},
            )
            assert isinstance(record, ProfessionalResultArtifactsRecord)
            assert UUID_RE.match(record.id)
            assert record.candidate_result_id == candidate_id
            assert record.confirmation_id is None
            assert record.status == "pending"
            assert record.capabilities == {"fold_evidence": "available"}
            assert record.manifest == {}
            succeeded = repo.mark_succeeded(record.id, manifest={"files": {"fold": {"sha256": "cc"}}})
        assert succeeded.status == "succeeded"
        assert succeeded.manifest == {"files": {"fold": {"sha256": "cc"}}}

    def test_one_artifact_set_per_candidate(self, runtime):
        """candidate_result_id 唯一：一个候选只有一套专业真相。"""

        candidate_id = create_succeeded_candidate(runtime, create_case(runtime))
        with runtime.session() as session:
            repo = ProfessionalResultArtifactsRepository(session)
            repo.create(candidate_id, confirmation_id=None, capabilities={})
            with pytest.raises(PlatformError) as excinfo:
                repo.create(candidate_id, confirmation_id=None, capabilities={})
        assert excinfo.value.code == PROFESSIONAL_ARTIFACTS_CONFLICT
        assert excinfo.value.http_status == 409
        # DB 层唯一约束兜底：绕过仓储裸插同样被拒绝
        with runtime.session() as session:
            with pytest.raises(IntegrityError):
                session.execute(
                    tables.ProfessionalResultArtifacts.__table__.insert().values(
                        id="raw-dup",
                        candidate_result_id=candidate_id,
                        confirmation_id=None,
                        status="pending",
                        capabilities_json="{}",
                        manifest_json="{}",
                        created_at="t",
                    )
                )
            session.rollback()

    def test_create_requires_existing_candidate(self, runtime):
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                ProfessionalResultArtifactsRepository(session).create(
                    "ghost", confirmation_id=None, capabilities={}
                )
        assert excinfo.value.code == CANDIDATE_NOT_FOUND

    def test_create_requires_existing_confirmation_when_given(self, runtime):
        candidate_id = create_succeeded_candidate(runtime, create_case(runtime))
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                ProfessionalResultArtifactsRepository(session).create(
                    candidate_id, confirmation_id="ghost", capabilities={}
                )
        assert excinfo.value.code == PROFESSIONAL_CONFIRMATION_NOT_FOUND

    def test_get_for_candidate(self, runtime):
        candidate_id = create_succeeded_candidate(runtime, create_case(runtime))
        with runtime.session() as session:
            repo = ProfessionalResultArtifactsRepository(session)
            created = repo.create(candidate_id, confirmation_id=None, capabilities={})
            loaded = repo.get_for_candidate(candidate_id)
        assert loaded.id == created.id
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                ProfessionalResultArtifactsRepository(session).get_for_candidate("ghost")
        assert excinfo.value.code == PROFESSIONAL_ARTIFACTS_NOT_FOUND
        assert excinfo.value.http_status == 404

    def test_terminal_artifacts_reject_further_transitions(self, runtime):
        candidate_id = create_succeeded_candidate(runtime, create_case(runtime))
        with runtime.session() as session:
            repo = ProfessionalResultArtifactsRepository(session)
            record = repo.create(candidate_id, confirmation_id=None, capabilities={})
            repo.mark_failed(record.id)
            with pytest.raises(PlatformError) as excinfo:
                repo.mark_succeeded(record.id, manifest={})
        assert excinfo.value.code == INVALID_STATUS_TRANSITION


# ---------------------------------------------------------------------------
# Idempotent anomaly extractions
# ---------------------------------------------------------------------------


class TestAnomalyExtractions:
    def test_create_returns_typed_pending_record(self, runtime):
        candidate_id = create_succeeded_candidate(runtime, create_case(runtime))
        with runtime.session() as session:
            record = AnomalyExtractionRepository(session).create(
                candidate_id,
                config={"threshold": 2.0, "最小规模": 4},
                fingerprint="fp-anom",
            )
        assert isinstance(record, AnomalyExtractionRecord)
        assert UUID_RE.match(record.id)
        assert record.candidate_result_id == candidate_id
        assert record.status == "pending"
        assert record.config == {"threshold": 2.0, "最小规模": 4}
        assert record.fingerprint == "fp-anom"
        assert record.error is None

    def test_create_requires_existing_candidate(self, runtime):
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                AnomalyExtractionRepository(session).create("ghost", config={}, fingerprint="fp")
        assert excinfo.value.code == CANDIDATE_NOT_FOUND

    def test_same_fingerprint_returns_existing_succeeded_extraction(self, runtime):
        """同成果 + 同配置指纹幂等返回同一成功提取，不产生新行。"""

        candidate_id = create_succeeded_candidate(runtime, create_case(runtime))
        with runtime.session() as session:
            repo = AnomalyExtractionRepository(session)
            first = repo.create(candidate_id, config={"threshold": 2.0}, fingerprint="fp-a")
            repo.mark_succeeded(first.id, manifest={"components": 3})
            second = repo.create(candidate_id, config={"threshold": 2.0}, fingerprint="fp-a")
        assert second.id == first.id
        assert second.status == "succeeded"
        assert second.manifest == {"components": 3}
        raw = sqlite3.connect(runtime.db_path)
        try:
            count = raw.execute(
                "SELECT COUNT(*) FROM anomaly_extractions WHERE candidate_result_id = ?",
                (candidate_id,),
            ).fetchone()[0]
        finally:
            raw.close()
        assert count == 1

    def test_pending_extraction_does_not_short_circuit_idempotency(self, runtime):
        """幂等只认成功提取：既有 pending 行不影响新提取的创建。"""

        candidate_id = create_succeeded_candidate(runtime, create_case(runtime))
        with runtime.session() as session:
            repo = AnomalyExtractionRepository(session)
            pending = repo.create(candidate_id, config={}, fingerprint="fp-p")
            another = repo.create(candidate_id, config={}, fingerprint="fp-p")
        assert another.id != pending.id

    def test_failed_extraction_allows_rerun_with_same_fingerprint(self, runtime):
        candidate_id = create_succeeded_candidate(runtime, create_case(runtime))
        with runtime.session() as session:
            repo = AnomalyExtractionRepository(session)
            failed = repo.create(candidate_id, config={}, fingerprint="fp-f")
            repo.mark_failed(failed.id, error={"code": "EMPTY_MASK", "message": "无异常区域"})
            rerun = repo.create(candidate_id, config={}, fingerprint="fp-f")
            succeeded = repo.mark_succeeded(rerun.id, manifest={"components": 1})
        assert rerun.id != failed.id
        assert succeeded.status == "succeeded"

    def test_distinct_fingerprints_create_distinct_extractions(self, runtime):
        candidate_id = create_succeeded_candidate(runtime, create_case(runtime))
        with runtime.session() as session:
            repo = AnomalyExtractionRepository(session)
            first = repo.create(candidate_id, config={"threshold": 2.0}, fingerprint="fp-1")
            repo.mark_succeeded(first.id, manifest={})
            second = repo.create(candidate_id, config={"threshold": 3.0}, fingerprint="fp-2")
        assert second.id != first.id

    def test_succeeded_fingerprint_partial_unique_index_is_db_enforced(self, runtime):
        """同一成果同一指纹最多一条成功提取（结构兜底）。"""

        candidate_id = create_succeeded_candidate(runtime, create_case(runtime))
        with runtime.session() as session:
            repo = AnomalyExtractionRepository(session)
            first = repo.create(candidate_id, config={}, fingerprint="fp-dup")
            second = repo.create(candidate_id, config={}, fingerprint="fp-dup")
            repo.mark_succeeded(first.id, manifest={})
            with pytest.raises(IntegrityError):
                repo.mark_succeeded(second.id, manifest={})

    def test_get_missing_extraction_is_404(self, runtime):
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                AnomalyExtractionRepository(session).get("ghost")
        assert excinfo.value.code == ANOMALY_EXTRACTION_NOT_FOUND


# ---------------------------------------------------------------------------
# Persistent analysis jobs
# ---------------------------------------------------------------------------


class TestAnalysisJobs:
    def test_create_returns_typed_queued_record(self, runtime):
        with runtime.session() as session:
            record = AnalysisJobRepository(session).create(
                job_kind="professional_diagnosis",
                subject_type="professional_diagnostic",
                subject_id="diag-1",
                request_fingerprint="fp-req",
            )
        assert isinstance(record, AnalysisJobRecord)
        assert UUID_RE.match(record.id)
        assert record.job_kind == "professional_diagnosis"
        assert record.subject_type == "professional_diagnostic"
        assert record.subject_id == "diag-1"
        assert record.request_fingerprint == "fp-req"
        assert record.status == RunStatus.QUEUED
        assert record.retry_of_job_id is None
        assert record.progress == {}
        assert record.error is None
        assert record.started_at is None and record.finished_at is None

    def test_get_missing_job_is_404(self, runtime):
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                AnalysisJobRepository(session).get("ghost")
        assert excinfo.value.code == ANALYSIS_JOB_NOT_FOUND

    def test_duplicate_inflight_job_is_409(self, runtime):
        create_analysis_job(runtime, subject_id="diag-1")
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                AnalysisJobRepository(session).create(
                    job_kind="professional_diagnosis",
                    subject_type="professional_diagnostic",
                    subject_id="diag-1",
                    request_fingerprint="fp-req",
                )
        assert excinfo.value.code == ANALYSIS_JOB_ALREADY_ACTIVE
        assert excinfo.value.http_status == 409

    def test_distinct_kind_or_subject_each_have_their_own_slot(self, runtime):
        create_analysis_job(runtime, job_kind="professional_diagnosis", subject_id="s-1")
        create_analysis_job(runtime, job_kind="anomaly_extraction", subject_id="s-1")
        create_analysis_job(runtime, job_kind="professional_diagnosis", subject_id="s-2")

    def test_terminal_job_frees_the_inflight_slot(self, runtime):
        job_id = create_analysis_job(runtime, subject_id="diag-1")
        with runtime.session() as session:
            repo = AnalysisJobRepository(session)
            repo.cancel(job_id)
            replacement = repo.create(
                job_kind="professional_diagnosis",
                subject_type="professional_diagnostic",
                subject_id="diag-1",
                request_fingerprint="fp-req",
            )
        assert replacement.id != job_id

    def test_find_active(self, runtime):
        job_id = create_analysis_job(runtime, subject_id="diag-9")
        with runtime.session() as session:
            repo = AnalysisJobRepository(session)
            active = repo.find_active(
                job_kind="professional_diagnosis", subject_id="diag-9"
            )
            assert active is not None and active.id == job_id
            repo.cancel(job_id)
            assert (
                repo.find_active(job_kind="professional_diagnosis", subject_id="diag-9") is None
            )

    def test_queued_running_succeeded_with_progress(self, runtime):
        job_id = create_analysis_job(runtime)
        with runtime.session() as session:
            repo = AnalysisJobRepository(session)
            running = repo.mark_running(job_id)
            assert running.status == RunStatus.RUNNING
            assert running.started_at is not None
            succeeded = repo.mark_succeeded(job_id, progress={"percent": 100, "阶段": "完成"})
        assert succeeded.status == RunStatus.SUCCEEDED
        assert succeeded.progress == {"percent": 100, "阶段": "完成"}
        assert succeeded.finished_at is not None
        raw = sqlite3.connect(runtime.db_path)
        try:
            progress_json = raw.execute(
                "SELECT progress_json FROM analysis_jobs WHERE id = ?", (job_id,)
            ).fetchone()[0]
        finally:
            raw.close()
        assert progress_json == json.dumps(
            {"percent": 100, "阶段": "完成"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def test_mark_failed_persists_structured_error(self, runtime):
        job_id = create_analysis_job(runtime)
        with runtime.session() as session:
            repo = AnalysisJobRepository(session)
            repo.mark_running(job_id)
            failed = repo.mark_failed(job_id, error={"code": "BOOM", "message": "炸"})
        assert failed.status == RunStatus.FAILED
        assert failed.error == {"code": "BOOM", "message": "炸"}

    def test_cancel_queued_and_running_jobs(self, runtime):
        queued_id = create_analysis_job(runtime, subject_id="d-q")
        running_id = create_analysis_job(runtime, subject_id="d-r")
        with runtime.session() as session:
            repo = AnalysisJobRepository(session)
            assert repo.cancel(queued_id).status == RunStatus.CANCELED
            repo.mark_running(running_id)
            canceled = repo.cancel(running_id)
        assert canceled.status == RunStatus.CANCELED
        assert canceled.finished_at is not None

    def test_cancel_terminal_job_is_rejected(self, runtime):
        job_id = create_analysis_job(runtime)
        with runtime.session() as session:
            repo = AnalysisJobRepository(session)
            repo.mark_running(job_id)
            repo.mark_succeeded(job_id)
            with pytest.raises(PlatformError) as excinfo:
                repo.cancel(job_id)
        assert excinfo.value.code == INVALID_STATUS_TRANSITION

    def test_worker_completion_cannot_overwrite_a_cancel(self, runtime):
        job_id = create_analysis_job(runtime)
        with runtime.session() as session:
            repo = AnalysisJobRepository(session)
            repo.mark_running(job_id)
            repo.cancel(job_id)
            with pytest.raises(PlatformError) as excinfo:
                repo.mark_succeeded(job_id)
        assert excinfo.value.code == INVALID_STATUS_TRANSITION
        with runtime.session() as session:
            assert AnalysisJobRepository(session).get(job_id).status == RunStatus.CANCELED

    @pytest.mark.parametrize("status", ["queued", "running"])
    def test_inflight_jobs_cannot_retry(self, runtime, status):
        job_id = create_analysis_job(runtime)
        if status == "running":
            with runtime.session() as session:
                AnalysisJobRepository(session).mark_running(job_id)
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                AnalysisJobRepository(session).retry(job_id)
        assert excinfo.value.code == ANALYSIS_JOB_NOT_RETRYABLE
        assert excinfo.value.http_status == 409

    @pytest.mark.parametrize("status", ["failed", "canceled"])
    def test_retry_creates_new_identity_and_preserves_original(self, runtime, status):
        job_id = create_analysis_job(runtime)
        with runtime.session() as session:
            repo = AnalysisJobRepository(session)
            repo.mark_running(job_id)
            if status == "failed":
                repo.mark_failed(job_id, error={"code": "X", "message": "y"})
            else:
                repo.cancel(job_id)
            retried = repo.retry(job_id)
        assert retried.id != job_id
        assert retried.status == RunStatus.QUEUED
        assert retried.retry_of_job_id == job_id
        assert retried.job_kind == "professional_diagnosis"
        assert retried.subject_id == "diag-1"
        assert retried.request_fingerprint == "fp-request"
        with runtime.session() as session:
            original = AnalysisJobRepository(session).get(job_id)
        assert original.status == status  # 原记录保持不动

    def test_retry_is_rejected_while_another_job_is_active(self, runtime):
        job_id = create_analysis_job(runtime)
        with runtime.session() as session:
            repo = AnalysisJobRepository(session)
            repo.mark_running(job_id)
            repo.mark_failed(job_id, error={"code": "X", "message": "y"})
            repo.create(
                job_kind="professional_diagnosis",
                subject_type="professional_diagnostic",
                subject_id="diag-1",
                request_fingerprint="fp-request",
            )
            with pytest.raises(PlatformError) as excinfo:
                repo.retry(job_id)
        assert excinfo.value.code == ANALYSIS_JOB_ALREADY_ACTIVE

    def test_retry_of_missing_job_is_404(self, runtime):
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                AnalysisJobRepository(session).retry("ghost")
        assert excinfo.value.code == ANALYSIS_JOB_NOT_FOUND

    def test_restart_recovery_marks_inflight_jobs_interrupted(self, runtime):
        queued_id = create_analysis_job(runtime, subject_id="d-q")
        running_id = create_analysis_job(runtime, subject_id="d-r")
        succeeded_id = create_analysis_job(runtime, subject_id="d-s")
        with runtime.session() as session:
            repo = AnalysisJobRepository(session)
            repo.mark_running(running_id)
            repo.mark_running(succeeded_id)
            repo.mark_succeeded(succeeded_id)

        assert runtime.recover_interrupted_runs() == 2

        with runtime.session() as session:
            repo = AnalysisJobRepository(session)
            for job_id in (queued_id, running_id):
                recovered = repo.get(job_id)
                assert recovered.status == RunStatus.INTERRUPTED
                assert recovered.error is not None
                assert recovered.error["code"] == ERROR_PROCESS_RESTARTED
            untouched = repo.get(succeeded_id)
            assert untouched.status == RunStatus.SUCCEEDED
            assert untouched.error is None
        # 幂等：再次恢复不再翻转任何行
        assert runtime.recover_interrupted_runs() == 0

    def test_interrupted_job_can_retry(self, runtime):
        job_id = create_analysis_job(runtime)
        with runtime.session() as session:
            AnalysisJobRepository(session).mark_running(job_id)
        assert runtime.recover_interrupted_runs() == 1
        with runtime.session() as session:
            retried = AnalysisJobRepository(session).retry(job_id)
        assert retried.retry_of_job_id == job_id
        assert retried.status == RunStatus.QUEUED


# ---------------------------------------------------------------------------
# Record contracts
# ---------------------------------------------------------------------------


class TestRecordContracts:
    def test_analysis_job_kind_vocabulary(self):
        for kind in ("professional_diagnosis", "anomaly_extraction"):
            record = AnalysisJobRecord(
                id="j",
                job_kind=kind,
                subject_type="professional_diagnostic",
                subject_id="s",
                request_fingerprint="fp",
                status="queued",
                retry_of_job_id=None,
                progress={},
                error=None,
                created_at="t",
                updated_at="t",
            )
            assert record.job_kind == kind
        with pytest.raises(ValidationError):
            AnalysisJobRecord(
                id="j",
                job_kind="grid_interpolation",
                subject_type="x",
                subject_id="s",
                request_fingerprint="fp",
                status="queued",
                retry_of_job_id=None,
                progress={},
                error=None,
                created_at="t",
                updated_at="t",
            )

    def test_records_forbid_unknown_keys(self):
        with pytest.raises(ValidationError):
            ProfessionalDiagnosticRecord(
                id="d",
                dataset_version_id="ds",
                status="queued",
                config={},
                fingerprint="fp",
                manifest={},
                error=None,
                created_at="t",
                updated_at="t",
                finished_at=None,
                rogue="field",
            )


# ---------------------------------------------------------------------------
# Deterministic artifact paths
# ---------------------------------------------------------------------------


class TestDeterministicPaths:
    def test_professional_paths_are_server_generated_id_segments(self, tmp_path):
        settings = PlatformRuntime(tmp_path / "runtime").settings
        assert (
            settings.professional_diagnosis_dir("caseA", "ds1", "diag9")
            == tmp_path
            / "runtime"
            / "datasets"
            / "caseA"
            / "ds1"
            / "professional"
            / "diagnostics"
            / "diag9"
        )
        assert (
            settings.professional_result_dir("cand7")
            == tmp_path / "runtime" / "results" / "cand7" / "professional"
        )
        assert (
            settings.anomaly_extraction_dir("cand7", "ax3")
            == tmp_path / "runtime" / "results" / "cand7" / "anomalies" / "ax3"
        )
