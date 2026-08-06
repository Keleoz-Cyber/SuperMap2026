"""Tests for case lifecycle: trash, restore, inflight detection, eligibility.

Everything runs against tmp_path PlatformRuntime; no real data directories,
UDBX, S3M caches, or iServer endpoints are touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from geomodeling.platform import PlatformRuntime
from geomodeling.platform.case_lifecycle import (
    CaseLifecycleService,
    CaseOwnership,
)
from geomodeling.platform.errors import (
    CASE_DELETE_FORBIDDEN,
    CASE_HAS_INFLIGHT_WORK,
    CASE_NOT_FOUND,
    CASE_TRASHED,
    PlatformError,
)
from geomodeling.platform.repositories import (
    CandidateRepository,
    CaseRepository,
    DatasetRepository,
    ExperimentRepository,
    FormalSelectionRepository,
    RunRepository,
)
from geomodeling.platform.schemas import (
    Algorithm,
    CaseCreateRequest,
    DatasetStatus,
    ExperimentCreateRequest,
    FormalSelectionRequest,
)
from geomodeling.platform.tables import (
    AnalysisJob,
    AnomalyExtraction,
    Case,
    CaseLifecycleState,
    DatasetVersion,
    Experiment,
    ProfessionalDiagnostic,
    QualityReport,
    RenderAsset,
    Run,
    RunStatus,
)
from geomodeling.platform import tables as tbl

# Adapter-only builtin IDs (no persisted Case row).
ADAPTER_BUILTIN_IDS = ("resistivity", "gas", "microseismic")


@pytest.fixture()
def runtime(tmp_path):
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    yield runtime
    runtime.close()


def create_case(
    runtime: PlatformRuntime,
    name: str = "upload-case",
    case_type: str = "generic",
    config: dict | None = None,
) -> str:
    with runtime.session() as session:
        return CaseRepository(session).create(
            CaseCreateRequest(name=name, case_type=case_type, config=config or {})
        ).id


def create_preset_case(runtime: PlatformRuntime) -> str:
    """A persisted builtin_preset case with read_only=True."""
    return create_case(
        runtime,
        name="微震速度",
        config={"workspace_kind": "builtin_preset", "read_only": True},
    )


def create_dataset(runtime: PlatformRuntime, case_id: str) -> str:
    with runtime.session() as session:
        return DatasetRepository(session).create_version(
            case_id, source_path="uploads/x/source.csv"
        ).id


def create_validated_dataset(runtime: PlatformRuntime, case_id: str) -> str:
    dataset_id = create_dataset(runtime, case_id)
    with runtime.session() as session:
        repo = DatasetRepository(session)
        repo.transition_status(dataset_id, DatasetStatus.MAPPED)
        repo.transition_status(dataset_id, DatasetStatus.VALIDATED)
    return dataset_id


def create_experiment(runtime: PlatformRuntime, case_id: str, dataset_id: str | None = None) -> str:
    dataset_id = dataset_id or create_dataset(runtime, case_id)
    with runtime.session() as session:
        request = ExperimentCreateRequest(
            case_id=case_id,
            name="exp",
            algorithm=Algorithm.IDW,
            dataset_version_id=dataset_id,
            parameters={"power": 2.0},
        )
        return ExperimentRepository(session).create(case_id, request).id


def create_run(runtime: PlatformRuntime, experiment_id: str) -> str:
    with runtime.session() as session:
        return RunRepository(session).create(experiment_id).id


def drive_run_to(runtime: PlatformRuntime, run_id: str, status: str) -> None:
    with runtime.session() as session:
        repo = RunRepository(session)
        if status == "queued":
            return
        repo.mark_running(run_id)
        if status == "running":
            return
        if status == "succeeded":
            repo.mark_succeeded(run_id, metrics={"rmse": 1.0})
        elif status == "failed":
            repo.mark_failed(run_id, error_code="BOOM")
        elif status == "canceled":
            repo.cancel(run_id)


def create_succeeded_candidate(runtime: PlatformRuntime, case_id: str) -> str:
    experiment_id = create_experiment(runtime, case_id)
    run_id = create_run(runtime, experiment_id)
    drive_run_to(runtime, run_id, "succeeded")
    with runtime.session() as session:
        candidate_id = CandidateRepository(session).create(run_id, metrics={"rmse": 0.5}).id
    with runtime.session() as session:
        row = session.get(tbl.CandidateResult, candidate_id)
        row.status = "succeeded"
        session.commit()
    return candidate_id


def set_run_status(runtime: PlatformRuntime, run_id: str, status: str) -> None:
    with runtime.session() as session:
        row = session.get(Run, run_id)
        row.status = status
        session.commit()


def set_candidate_status(runtime: PlatformRuntime, candidate_id: str, status: str) -> None:
    with runtime.session() as session:
        row = session.get(tbl.CandidateResult, candidate_id)
        row.status = status
        session.commit()


# ---------------------------------------------------------------------------
# Ownership resolution
# ---------------------------------------------------------------------------


class TestOwnership:
    def test_ownership_resolves_complete_graph(self, runtime):
        case_id = create_case(runtime)
        dataset_id = create_dataset(runtime, case_id)
        experiment_id = create_experiment(runtime, case_id, dataset_id)
        run_id = create_run(runtime, experiment_id)
        with runtime.session() as session:
            candidate_id = CandidateRepository(session).create(run_id, metrics={}).id

        ownership = CaseLifecycleService(runtime).ownership(case_id)

        assert isinstance(ownership, CaseOwnership)
        assert ownership.case_id == case_id
        assert dataset_id in ownership.dataset_ids
        assert experiment_id in ownership.experiment_ids
        assert run_id in ownership.run_ids
        assert candidate_id in ownership.candidate_ids

    def test_ownership_includes_professional_entities(self, runtime):
        case_id = create_case(runtime)
        dataset_id = create_validated_dataset(runtime, case_id)
        experiment_id = create_experiment(runtime, case_id, dataset_id)
        run_id = create_run(runtime, experiment_id)
        drive_run_to(runtime, run_id, "succeeded")
        with runtime.session() as session:
            candidate_id = CandidateRepository(session).create(run_id, metrics={}).id
            set_candidate_status(runtime, candidate_id, "succeeded")

        # Create a professional diagnostic on the dataset
        with runtime.session() as session:
            diag = ProfessionalDiagnostic(
                id="diag-1",
                dataset_version_id=dataset_id,
                status="succeeded",
                config_json="{}",
                fingerprint="fp-1",
                manifest_json="{}",
            )
            session.add(diag)
            session.commit()

        ownership = CaseLifecycleService(runtime).ownership(case_id)
        assert "diag-1" in ownership.diagnosis_ids

    def test_ownership_unknown_case_raises_not_found(self, runtime):
        with pytest.raises(PlatformError) as excinfo:
            CaseLifecycleService(runtime).ownership("no-such-case")
        assert excinfo.value.code == CASE_NOT_FOUND


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


class TestEligibility:
    @pytest.mark.parametrize("builtin_id", ADAPTER_BUILTIN_IDS)
    def test_adapter_builtin_ids_are_forbidden_before_lookup(self, runtime, builtin_id):
        with pytest.raises(PlatformError) as excinfo:
            CaseLifecycleService(runtime).trash(builtin_id)
        assert excinfo.value.code == CASE_DELETE_FORBIDDEN
        assert excinfo.value.http_status == 409

    @pytest.mark.parametrize("builtin_id", ADAPTER_BUILTIN_IDS)
    def test_adapter_builtin_restore_is_forbidden(self, runtime, builtin_id):
        with pytest.raises(PlatformError) as excinfo:
            CaseLifecycleService(runtime).restore(builtin_id)
        assert excinfo.value.code == CASE_DELETE_FORBIDDEN

    def test_preset_case_is_forbidden(self, runtime):
        case_id = create_preset_case(runtime)
        with pytest.raises(PlatformError) as excinfo:
            CaseLifecycleService(runtime).trash(case_id)
        assert excinfo.value.code == CASE_DELETE_FORBIDDEN

    def test_preset_restore_is_forbidden(self, runtime):
        case_id = create_preset_case(runtime)
        with pytest.raises(PlatformError) as excinfo:
            CaseLifecycleService(runtime).restore(case_id)
        assert excinfo.value.code == CASE_DELETE_FORBIDDEN


# ---------------------------------------------------------------------------
# Inflight detection
# ---------------------------------------------------------------------------


class TestInflightDetection:
    @pytest.mark.parametrize("status", ["queued", "running"])
    def test_inflight_run_blocks_trash(self, runtime, status):
        case_id = create_case(runtime)
        experiment_id = create_experiment(runtime, case_id)
        run_id = create_run(runtime, experiment_id)
        drive_run_to(runtime, run_id, status)

        with pytest.raises(PlatformError) as excinfo:
            CaseLifecycleService(runtime).trash(case_id)
        assert excinfo.value.code == CASE_HAS_INFLIGHT_WORK

        # Case lifecycle state must not have changed
        with runtime.session() as session:
            row = session.get(Case, case_id)
            assert row.lifecycle_state == "active"

    def test_inflight_diagnosis_job_blocks_trash(self, runtime):
        case_id = create_case(runtime)
        dataset_id = create_dataset(runtime, case_id)

        with runtime.session() as session:
            diag = ProfessionalDiagnostic(
                id="diag-inflight",
                dataset_version_id=dataset_id,
                status="queued",
                config_json="{}",
                fingerprint="fp",
                manifest_json="{}",
            )
            session.add(diag)
            session.add(AnalysisJob(
                id="job-diag",
                job_kind="professional_diagnosis",
                subject_type="professional_diagnostic",
                subject_id="diag-inflight",
                request_fingerprint="fp",
                status="queued",
            ))
            session.commit()

        with pytest.raises(PlatformError) as excinfo:
            CaseLifecycleService(runtime).trash(case_id)
        assert excinfo.value.code == CASE_HAS_INFLIGHT_WORK

    def test_inflight_extraction_job_blocks_trash(self, runtime):
        case_id = create_case(runtime)
        candidate_id = create_succeeded_candidate(runtime, case_id)

        with runtime.session() as session:
            extraction = AnomalyExtraction(
                id="ext-inflight",
                candidate_result_id=candidate_id,
                status="pending",
                config_json="{}",
                fingerprint="fp",
                manifest_json="{}",
            )
            session.add(extraction)
            session.add(AnalysisJob(
                id="job-ext",
                job_kind="anomaly_extraction",
                subject_type="anomaly_extraction",
                subject_id="ext-inflight",
                request_fingerprint="fp",
                status="queued",
            ))
            session.commit()

        with pytest.raises(PlatformError) as excinfo:
            CaseLifecycleService(runtime).trash(case_id)
        assert excinfo.value.code == CASE_HAS_INFLIGHT_WORK

    def test_creating_render_asset_blocks_trash(self, runtime):
        case_id = create_case(runtime)
        candidate_id = create_succeeded_candidate(runtime, case_id)

        with runtime.session() as session:
            session.add(RenderAsset(
                id="ra-creating",
                source_kind="candidate_result",
                source_id=candidate_id,
                candidate_result_id=candidate_id,
                renderer="supermap_voxelgrid_netcdf",
                format_version=2,
                status="creating",
                grid_sha256="abc123",
            ))
            session.commit()

        with pytest.raises(PlatformError) as excinfo:
            CaseLifecycleService(runtime).trash(case_id)
        assert excinfo.value.code == CASE_HAS_INFLIGHT_WORK

    def test_terminal_run_does_not_block_trash(self, runtime):
        case_id = create_case(runtime)
        experiment_id = create_experiment(runtime, case_id)
        run_id = create_run(runtime, experiment_id)
        drive_run_to(runtime, run_id, "succeeded")

        record = CaseLifecycleService(runtime).trash(case_id)
        assert record.lifecycle_state == "trashed"


# ---------------------------------------------------------------------------
# Trash and restore
# ---------------------------------------------------------------------------


class TestTrashAndRestore:
    def test_trash_active_case_sets_trashed_state(self, runtime):
        case_id = create_case(runtime)
        record = CaseLifecycleService(runtime).trash(case_id)
        assert record.lifecycle_state == "trashed"
        assert record.trashed_at is not None

    def test_trash_preserves_first_trashed_at(self, runtime):
        case_id = create_case(runtime)
        first = CaseLifecycleService(runtime).trash(case_id)
        first_trashed_at = first.trashed_at

        second = CaseLifecycleService(runtime).trash(case_id)
        assert second.trashed_at == first_trashed_at

    def test_restore_trashed_case_sets_active(self, runtime):
        case_id = create_case(runtime)
        CaseLifecycleService(runtime).trash(case_id)
        record = CaseLifecycleService(runtime).restore(case_id)
        assert record.lifecycle_state == "active"
        assert record.trashed_at is None

    def test_restore_active_is_idempotent(self, runtime):
        case_id = create_case(runtime)
        record = CaseLifecycleService(runtime).restore(case_id)
        assert record.lifecycle_state == "active"
        assert record.trashed_at is None

    def test_trash_preserves_all_entity_ids(self, runtime):
        case_id = create_case(runtime)
        dataset_id = create_dataset(runtime, case_id)
        experiment_id = create_experiment(runtime, case_id, dataset_id)
        run_id = create_run(runtime, experiment_id)
        drive_run_to(runtime, run_id, "succeeded")

        CaseLifecycleService(runtime).trash(case_id)

        ownership = CaseLifecycleService(runtime).ownership(case_id)
        assert dataset_id in ownership.dataset_ids
        assert experiment_id in ownership.experiment_ids
        assert run_id in ownership.run_ids

    def test_restore_reactivates_all_entity_ids(self, runtime):
        case_id = create_case(runtime)
        dataset_id = create_dataset(runtime, case_id)
        experiment_id = create_experiment(runtime, case_id, dataset_id)
        run_id = create_run(runtime, experiment_id)
        drive_run_to(runtime, run_id, "succeeded")

        CaseLifecycleService(runtime).trash(case_id)
        CaseLifecycleService(runtime).restore(case_id)

        ownership = CaseLifecycleService(runtime).ownership(case_id)
        assert dataset_id in ownership.dataset_ids
        assert experiment_id in ownership.experiment_ids
        assert run_id in ownership.run_ids

    def test_trash_unknown_case_raises_not_found(self, runtime):
        with pytest.raises(PlatformError) as excinfo:
            CaseLifecycleService(runtime).trash("no-such-case")
        assert excinfo.value.code == CASE_NOT_FOUND

    def test_restore_unknown_case_raises_not_found(self, runtime):
        with pytest.raises(PlatformError) as excinfo:
            CaseLifecycleService(runtime).restore("no-such-case")
        assert excinfo.value.code == CASE_NOT_FOUND
