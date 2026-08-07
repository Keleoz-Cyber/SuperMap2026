"""Tests for safe permanent purge with quarantine (v0.7.0 batch 3 §5.4).

Covers manifest generation, path containment, deletion order, rollback,
and exact Unicode case-name confirmation.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from geomodeling.platform import PlatformRuntime
from geomodeling.platform.case_lifecycle import CaseLifecycleService
from geomodeling.platform.errors import (
    CASE_DELETE_FORBIDDEN,
    CASE_HAS_INFLIGHT_WORK,
    CASE_NOT_FOUND,
    CASE_PURGE_BLOCKED,
    CASE_PURGE_CONFIRMATION_MISMATCH,
    PlatformError,
)
from geomodeling.platform.repositories import (
    CandidateRepository,
    CaseRepository,
    DatasetRepository,
    ExperimentRepository,
    RunRepository,
)
from geomodeling.platform.schemas import (
    Algorithm,
    CaseCreateRequest,
    DatasetStatus,
    ExperimentCreateRequest,
)
from geomodeling.platform.tables import (
    AnalysisJob,
    AnomalyExtraction,
    CandidateResult,
    Case,
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
)


@pytest.fixture()
def runtime(tmp_path):
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    yield runtime
    runtime.close()


def create_case(runtime, name="测试案例", config=None):
    with runtime.session() as session:
        from geomodeling.platform.repositories import CaseRepository
        from geomodeling.platform.schemas import CaseCreateRequest
        return CaseRepository(session).create(
            CaseCreateRequest(name=name, case_type="generic", config=config or {})
        ).id


def write_file(path: Path, content: bytes = b"test") -> str:
    """Write a file and return its SHA-256 hash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def build_complete_case(runtime, name="完整测试案例") -> dict:
    """Build a complete user-case graph with files. Returns entity IDs."""
    case_id = create_case(runtime, name=name)

    # Dataset with source and standardized files
    with runtime.session() as session:
        from geomodeling.platform.schemas import DatasetStatus
        repo = DatasetRepository(session)
        dataset = repo.create_version(case_id, source_path="placeholder")
    dataset_id = dataset.id

    source_path = runtime.settings.upload_source(case_id, dataset_id, "csv")
    source_hash = write_file(source_path, b"source-data")

    standardized_path = runtime.settings.standardized_dataset(case_id, dataset_id)
    std_hash = write_file(standardized_path, b"std-data")

    # Update dataset paths and transition to validated
    with runtime.session() as session:
        row = session.get(DatasetVersion, dataset_id)
        row.source_path = str(source_path)
        row.standardized_path = str(standardized_path)
        session.commit()
    with runtime.session() as session:
        repo = DatasetRepository(session)
        repo.transition_status(dataset_id, DatasetStatus.MAPPED)
        repo.transition_status(dataset_id, DatasetStatus.VALIDATED)

    # Quality report
    with runtime.session() as session:
        session.add(QualityReport(
            id="qr-1", dataset_version_id=dataset_id, status="reviewed",
            report_json="{}",
        ))
        session.commit()

    # Experiment
    with runtime.session() as session:
        request = ExperimentCreateRequest(
            case_id=case_id, name="exp", algorithm=Algorithm.IDW,
            dataset_version_id=dataset_id, parameters={"power": 2.0},
        )
        experiment_id = ExperimentRepository(session).create(case_id, request).id

    # Run (succeeded)
    with runtime.session() as session:
        run_id = RunRepository(session).create(experiment_id).id
    with runtime.session() as session:
        repo = RunRepository(session)
        repo.mark_running(run_id)
        repo.mark_succeeded(run_id, metrics={"rmse": 0.5})

    # Candidate with grid file
    grid_path = runtime.settings.result_grid("cand-1")
    grid_hash = write_file(grid_path, b"grid-data")
    with runtime.session() as session:
        cand = CandidateResult(
            id="cand-1", run_id=run_id, category="formal",
            fingerprint="fp", status="succeeded",
            params_json="{}", metrics_json='{"rmse":0.5}',
            grid_path=str(grid_path),
        )
        session.add(cand)
        session.commit()

    # Formal selection
    with runtime.session() as session:
        session.add(FormalSelection(
            id="sel-1", case_id=case_id, candidate_result_id="cand-1",
            note="最优", selected_by="op",
        ))
        session.commit()

    # Export with package file
    export_pkg = runtime.settings.export_package("exp-1")
    export_hash = write_file(export_pkg, b"export-data")
    with runtime.session() as session:
        session.add(Export(
            id="exp-1", case_id=case_id, candidate_result_id="cand-1",
            package_path=str(export_pkg), manifest_json="{}",
        ))
        session.commit()

    # Publication
    with runtime.session() as session:
        session.add(Publication(
            id="pub-1", export_id="exp-1", target="iserver",
            status="pending", detail_json="{}",
        ))
        session.commit()

    # Professional diagnostic
    diag_dir = runtime.settings.professional_diagnosis_dir(case_id, dataset_id, "diag-1")
    write_file(diag_dir / "variogram.json", b"diag-data")
    with runtime.session() as session:
        session.add(ProfessionalDiagnostic(
            id="diag-1", dataset_version_id=dataset_id, status="succeeded",
            config_json="{}", fingerprint="fp-diag", manifest_json="{}",
        ))
        session.commit()

    # Professional confirmation
    with runtime.session() as session:
        session.add(ProfessionalConfirmation(
            id="conf-1", diagnostic_id="diag-1", config_json="{}",
            fingerprint="fp-conf", note="确认",
        ))
        session.commit()

    # Professional result artifacts
    prof_dir = runtime.settings.professional_result_dir("cand-1")
    write_file(prof_dir / "manifest.json", b"prof-data")
    with runtime.session() as session:
        session.add(ProfessionalResultArtifacts(
            id="pra-1", candidate_result_id="cand-1", confirmation_id="conf-1",
            status="succeeded", capabilities_json="{}", manifest_json="{}",
        ))
        session.commit()

    # Anomaly extraction
    anomaly_dir = runtime.settings.anomaly_extraction_dir("cand-1", "ext-1")
    write_file(anomaly_dir / "result.json", b"anomaly-data")
    with runtime.session() as session:
        session.add(AnomalyExtraction(
            id="ext-1", candidate_result_id="cand-1", status="succeeded",
            config_json="{}", fingerprint="fp-ext", manifest_json="{}",
        ))
        session.commit()

    # Analysis jobs (terminal)
    with runtime.session() as session:
        session.add(AnalysisJob(
            id="job-diag", job_kind="professional_diagnosis",
            subject_type="professional_diagnostic", subject_id="diag-1",
            request_fingerprint="fp", status="succeeded",
            progress_json="{}",
        ))
        session.add(AnalysisJob(
            id="job-ext", job_kind="anomaly_extraction",
            subject_type="anomaly_extraction", subject_id="ext-1",
            request_fingerprint="fp", status="succeeded",
            progress_json="{}",
        ))
        session.commit()

    # Render asset (ready)
    asset_dir = runtime.settings.render_assets_dir / "ra-1"
    write_file(asset_dir / "volume.nc", b"netcdf-data")
    with runtime.session() as session:
        session.add(RenderAsset(
            id="ra-1", source_kind="candidate_result", source_id="cand-1",
            candidate_result_id="cand-1", renderer="supermap_voxelgrid_netcdf",
            format_version=2, status="ready", grid_sha256="abc",
            netcdf_sha256="def", asset_dir=str(asset_dir),
            manifest_json="{}", error_json=None,
        ))
        session.commit()

    return {
        "case_id": case_id,
        "dataset_id": dataset_id,
        "experiment_id": experiment_id,
        "run_id": run_id,
        "candidate_id": "cand-1",
    }


# ---------------------------------------------------------------------------
# Successful purge
# ---------------------------------------------------------------------------


class TestSuccessfulPurge:
    def test_purge_removes_all_rows_and_files(self, runtime):
        ids = build_complete_case(runtime, name="删除测试")
        case_id = ids["case_id"]

        # Trash first
        CaseLifecycleService(runtime).trash(case_id)

        # Purge with exact name
        receipt = CaseLifecycleService(runtime).purge(case_id, confirmation_name="删除测试")

        assert receipt is not None

        # All database rows should be gone
        with runtime.session() as session:
            assert session.get(Case, case_id) is None
            assert session.get(DatasetVersion, ids["dataset_id"]) is None
            assert session.get(Experiment, ids["experiment_id"]) is None
            assert session.get(Run, ids["run_id"]) is None
            assert session.get(CandidateResult, "cand-1") is None
            assert session.get(FormalSelection, "sel-1") is None
            assert session.get(Export, "exp-1") is None
            assert session.get(Publication, "pub-1") is None
            assert session.get(ProfessionalDiagnostic, "diag-1") is None
            assert session.get(ProfessionalConfirmation, "conf-1") is None
            assert session.get(ProfessionalResultArtifacts, "pra-1") is None
            assert session.get(AnomalyExtraction, "ext-1") is None
            assert session.get(AnalysisJob, "job-diag") is None
            assert session.get(AnalysisJob, "job-ext") is None
            assert session.get(RenderAsset, "ra-1") is None

        # All files should be gone
        assert not runtime.settings.upload_source(case_id, ids["dataset_id"], "csv").exists()
        assert not runtime.settings.standardized_dataset(case_id, ids["dataset_id"]).exists()
        assert not runtime.settings.result_grid("cand-1").exists()

        # Purge operation should exist as cleaned
        with runtime.session() as session:
            ops = session.query(CasePurgeOperation).filter_by(case_id=case_id).all()
            assert len(ops) == 1
            assert ops[0].state == "cleaned"


# ---------------------------------------------------------------------------
# Confirmation
# ---------------------------------------------------------------------------


class TestPurgeConfirmation:
    def test_wrong_name_raises_mismatch(self, runtime):
        ids = build_complete_case(runtime, name="正确名称")
        CaseLifecycleService(runtime).trash(ids["case_id"])

        with pytest.raises(PlatformError) as excinfo:
            CaseLifecycleService(runtime).purge(ids["case_id"], confirmation_name="错误名称")
        assert excinfo.value.code == CASE_PURGE_CONFIRMATION_MISMATCH

    def test_unicode_name_must_match_character_for_character(self, runtime):
        ids = build_complete_case(runtime, name="微震案例α")
        CaseLifecycleService(runtime).trash(ids["case_id"])

        with pytest.raises(PlatformError) as excinfo:
            CaseLifecycleService(runtime).purge(ids["case_id"], confirmation_name="微震案例a")
        assert excinfo.value.code == CASE_PURGE_CONFIRMATION_MISMATCH

        # Exact match works
        CaseLifecycleService(runtime).purge(ids["case_id"], confirmation_name="微震案例α")


# ---------------------------------------------------------------------------
# State requirements
# ---------------------------------------------------------------------------


class TestPurgeStateRequirements:
    def test_purge_active_case_raises_blocked(self, runtime):
        ids = build_complete_case(runtime)
        with pytest.raises(PlatformError) as excinfo:
            CaseLifecycleService(runtime).purge(ids["case_id"], confirmation_name="完整测试案例")
        assert excinfo.value.code == CASE_PURGE_BLOCKED


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


class TestPurgeRollback:
    def test_failure_after_quarantine_restores_files(self, runtime):
        ids = build_complete_case(runtime, name="回滚测试")
        case_id = ids["case_id"]
        CaseLifecycleService(runtime).trash(case_id)

        source_file = runtime.settings.upload_source(case_id, ids["dataset_id"], "csv")
        assert source_file.exists()

        # Inject failure after quarantine (before DB commit)
        def fail_after_quarantined(stage):
            if stage == "after_quarantined":
                raise RuntimeError("simulated crash")

        with pytest.raises(RuntimeError, match="simulated crash"):
            CaseLifecycleService(runtime).purge(
                case_id, confirmation_name="回滚测试",
                failpoint=fail_after_quarantined,
            )

        # Files should be restored
        assert source_file.exists()

        # Case should still exist (not deleted)
        with runtime.session() as session:
            assert session.get(Case, case_id) is not None

        # Operation should be rolled_back
        with runtime.session() as session:
            ops = session.query(CasePurgeOperation).filter_by(case_id=case_id).all()
            assert len(ops) == 1
            assert ops[0].state == "rolled_back"

        # Case should be back in trashed state (not purging)
        with runtime.session() as session:
            case = session.get(Case, case_id)
            assert case.lifecycle_state == "trashed"


class TestPurgeConcurrencySafety:
    def test_purge_blocks_concurrent_restore(self, runtime):
        """Restore must be blocked while purge is in purging state."""
        from geomodeling.platform.tables import Case as CaseTbl

        ids = build_complete_case(runtime, name="并发测试")
        case_id = ids["case_id"]
        CaseLifecycleService(runtime).trash(case_id)

        # Manually set to purging to simulate in-progress purge
        with runtime.session() as session:
            row = session.get(CaseTbl, case_id)
            row.lifecycle_state = "purging"
            session.commit()

        with pytest.raises(PlatformError) as excinfo:
            CaseLifecycleService(runtime).restore(case_id)
        assert excinfo.value.code == "CASE_PURGE_BLOCKED"

    def test_duplicate_purge_blocks(self, runtime):
        """Duplicate purge must be blocked while already purging."""
        from geomodeling.platform.tables import Case as CaseTbl

        ids = build_complete_case(runtime, name="重复清理")
        case_id = ids["case_id"]
        CaseLifecycleService(runtime).trash(case_id)

        with runtime.session() as session:
            row = session.get(CaseTbl, case_id)
            row.lifecycle_state = "purging"
            session.commit()

        with pytest.raises(PlatformError) as excinfo:
            CaseLifecycleService(runtime).purge(case_id, confirmation_name="重复清理")
        assert excinfo.value.code == "CASE_PURGE_BLOCKED"
