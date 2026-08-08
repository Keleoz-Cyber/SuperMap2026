"""Contract and transition tests for the v0.4 platform repositories.

Everything runs against a tmp_path PlatformRuntime; no real data
directories, UDBX, S3M caches, or iServer endpoints are touched.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError

from geomodeling.platform import PlatformRuntime
from geomodeling.platform.errors import (
    CANDIDATE_NOT_IN_CASE,
    CANDIDATE_NOT_SUCCEEDED,
    CASE_NOT_FOUND,
    DATASET_NOT_FOUND,
    DATASET_NOT_IN_CASE,
    DATASET_VERSION_CONFLICT,
    EXPERIMENT_NOT_IN_CASE,
    INVALID_STATUS_TRANSITION,
    RUN_ALREADY_ACTIVE,
    RUN_NOT_FOUND,
    RUN_NOT_RETRYABLE,
    PlatformError,
    platform_error_handler,
    sanitize_public_details,
)
from geomodeling.platform.repositories import (
    ALLOWED_DATASET_TRANSITIONS,
    DATASET_STATUS_TRANSITIONS,
    RUN_RETRYABLE_STATUSES,
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
    CasePurgeOperationRecord,
    DatasetStatus,
    Dimension,
    ExperimentCreateRequest,
    FieldMapping,
    FormalSelectionRequest,
    GridSpec,
    SpatialValidationSpec,
)
from geomodeling.platform.tables import (
    CandidateResult,
    DatasetVersion,
    FormalSelection,
    RunStatus,
)

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

MAPPING_2D = {
    "dimension": "2d",
    "x": "Easting",
    "y": "Northing",
    "value": "rho",
    "value_name": "电阻率",
    "value_unit": "Ω·m",
    "coordinate_kind": "local_linear",
}

MAPPING_3D = {
    **MAPPING_2D,
    "dimension": "3d",
    "z": "Depth",
    "coordinate_kind": "projected",
    "crs_text": "EPSG:4547",
}


@pytest.fixture()
def runtime(tmp_path):
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    yield runtime
    runtime.close()


def create_case(runtime: PlatformRuntime, name: str = "demo", case_type: str = "generic") -> str:
    with runtime.session() as session:
        return CaseRepository(session).create(
            CaseCreateRequest(name=name, case_type=case_type)
        ).id


def create_dataset(runtime: PlatformRuntime, case_id: str) -> str:
    with runtime.session() as session:
        return DatasetRepository(session).create_version(
            case_id, source_path="uploads/x/source.csv"
        ).id


def create_experiment(
    runtime: PlatformRuntime,
    case_id: str,
    dataset_id: str | None = None,
    name: str = "exp",
) -> str:
    dataset_id = dataset_id or create_dataset(runtime, case_id)
    with runtime.session() as session:
        request = ExperimentCreateRequest(
            case_id=case_id,
            name=name,
            algorithm=Algorithm.IDW,
            dataset_version_id=dataset_id,
            parameters={"power": 2.0},
        )
        return ExperimentRepository(session).create(case_id, request).id


def create_run(runtime: PlatformRuntime, experiment_id: str) -> str:
    with runtime.session() as session:
        return RunRepository(session).create(experiment_id).id


def drive_run_to(runtime: PlatformRuntime, run_id: str, status: str) -> None:
    """Drive a run through the legal path to a terminal status."""

    with runtime.session() as session:
        repo = RunRepository(session)
        if status == RunStatus.QUEUED.value:
            return
        repo.mark_running(run_id)
        if status == RunStatus.RUNNING.value:
            return
        if status == RunStatus.SUCCEEDED.value:
            repo.mark_succeeded(run_id, metrics={"rmse": 1.0})
        elif status == RunStatus.FAILED.value:
            repo.mark_failed(run_id, error_code="BOOM")
        elif status == RunStatus.CANCELED.value:
            repo.cancel(run_id)
        elif status == RunStatus.INTERRUPTED.value:
            # interrupted is only produced by startup recovery
            pass
        else:  # pragma: no cover - fixture misuse
            raise AssertionError(f"unknown target status {status}")


def create_succeeded_candidate(runtime: PlatformRuntime, case_id: str) -> str:
    experiment_id = create_experiment(runtime, case_id)
    run_id = create_run(runtime, experiment_id)
    drive_run_to(runtime, run_id, RunStatus.SUCCEEDED.value)
    with runtime.session() as session:
        candidate_id = CandidateRepository(session).create(run_id, metrics={"rmse": 0.5}).id
    # 成功 run 产出的候选携带 succeeded 状态（与 runner 落库行为一致）：
    # CandidateRepository.create 只登记列默认 queued，这里补齐终态。
    set_candidate_status(runtime, candidate_id, RunStatus.SUCCEEDED.value)
    return candidate_id


def set_candidate_status(runtime: PlatformRuntime, candidate_id: str, status: str) -> None:
    """直写候选状态（手工构造场景；生产路径只有 runner 会迁移候选状态）。"""

    with runtime.session() as session:
        row = session.get(CandidateResult, candidate_id)
        row.status = status
        session.commit()


def formal_selection_count(runtime: PlatformRuntime, candidate_id: str) -> int:
    with runtime.session() as session:
        return (
            session.query(FormalSelection)
            .filter(FormalSelection.candidate_result_id == candidate_id)
            .count()
        )


# ---------------------------------------------------------------------------
# FieldMapping / SpatialValidationSpec / GridSpec contracts
# ---------------------------------------------------------------------------


class TestFieldMappingContract:
    def test_2d_mapping_requires_x_y_value_and_accepts_missing_z(self):
        mapping = FieldMapping(**MAPPING_2D)
        assert mapping.dimension == Dimension.TWO_D
        assert mapping.z is None
        assert mapping.value_name == "电阻率"

    def test_2d_mapping_rejects_a_selected_z_field(self):
        with pytest.raises(ValidationError, match="2D"):
            FieldMapping(**{**MAPPING_2D, "z": "Depth"})

    def test_3d_mapping_requires_z(self):
        payload = {k: v for k, v in MAPPING_3D.items() if k != "z"}
        with pytest.raises(ValidationError, match="3D"):
            FieldMapping(**payload)

    def test_3d_mapping_accepts_x_y_z_value(self):
        mapping = FieldMapping(**MAPPING_3D)
        assert mapping.dimension == Dimension.THREE_D
        assert mapping.z == "Depth"
        assert mapping.coordinate_kind == "projected"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"y": "Easting"},  # x == y
            {"value": "Easting"},  # x == value
            {"z": "Easting", "dimension": "3d"},  # x == z
            {"z": "rho", "dimension": "3d"},  # z == value
        ],
    )
    def test_duplicate_field_selection_is_rejected(self, overrides):
        with pytest.raises(ValidationError, match="重复"):
            FieldMapping(**{**MAPPING_2D, **overrides})

    def test_unknown_keys_are_forbidden(self):
        with pytest.raises(ValidationError):
            FieldMapping(**{**MAPPING_2D, "sheet": "Sheet1"})

    def test_blank_value_name_and_oversized_crs_are_rejected(self):
        with pytest.raises(ValidationError):
            FieldMapping(**{**MAPPING_2D, "value_name": ""})
        with pytest.raises(ValidationError):
            FieldMapping(**{**MAPPING_3D, "crs_text": "x" * 513})

    @pytest.mark.parametrize("kind", ["local_linear", "projected", "geographic"])
    def test_coordinate_kind_vocabulary(self, kind):
        assert FieldMapping(**{**MAPPING_2D, "coordinate_kind": kind}).coordinate_kind == kind

    def test_coordinate_kind_rejects_unknown_values(self):
        with pytest.raises(ValidationError):
            FieldMapping(**{**MAPPING_2D, "coordinate_kind": "wgs84_magic"})


class TestSpatialValidationSpec:
    def test_defaults_match_the_plan(self):
        spec = SpatialValidationSpec()
        assert spec.method == "spatial_kfold"
        assert spec.folds == 5
        assert spec.seed == 20260723
        assert spec.holdout_fraction == pytest.approx(0.2)

    @pytest.mark.parametrize("folds", [2, 11])
    def test_folds_bounds(self, folds):
        with pytest.raises(ValidationError):
            SpatialValidationSpec(folds=folds)

    @pytest.mark.parametrize("fraction", [0.05, 0.5])
    def test_holdout_fraction_bounds(self, fraction):
        with pytest.raises(ValidationError):
            SpatialValidationSpec(method="spatial_holdout", holdout_fraction=fraction)

    def test_method_vocabulary_and_extra_forbid(self):
        with pytest.raises(ValidationError):
            SpatialValidationSpec(method="random_shuffle")
        with pytest.raises(ValidationError):
            SpatialValidationSpec(group_column="block")


class TestGridSpec:
    def test_valid_2d_grid(self):
        spec = GridSpec(bounds=[(0.0, 10.0), (0.0, 10.0)], resolution=[1.0, 1.0])
        assert spec.max_cells == 1_000_000

    def test_valid_3d_grid(self):
        GridSpec(bounds=[(0.0, 9.0), (0.0, 9.0), (0.0, 9.0)], resolution=[1.0, 1.0, 1.0])

    def test_bounds_and_resolution_lengths_must_match(self):
        with pytest.raises(ValidationError):
            GridSpec(bounds=[(0.0, 1.0), (0.0, 1.0)], resolution=[1.0])

    def test_degenerate_bounds_are_rejected(self):
        with pytest.raises(ValidationError):
            GridSpec(bounds=[(0.0, 0.0), (0.0, 1.0)], resolution=[1.0, 1.0])
        with pytest.raises(ValidationError):
            GridSpec(bounds=[(2.0, 1.0), (0.0, 1.0)], resolution=[1.0, 1.0])

    def test_non_positive_resolution_is_rejected(self):
        with pytest.raises(ValidationError):
            GridSpec(bounds=[(0.0, 1.0), (0.0, 1.0)], resolution=[1.0, 0.0])

    def test_estimated_cells_must_stay_under_max_cells(self):
        with pytest.raises(ValidationError, match="单元"):
            GridSpec(bounds=[(0.0, 100.0), (0.0, 100.0)], resolution=[1.0, 1.0], max_cells=100)

    def test_max_cells_hard_cap(self):
        with pytest.raises(ValidationError):
            GridSpec(
                bounds=[(0.0, 1.0), (0.0, 1.0)],
                resolution=[1.0, 1.0],
                max_cells=1_000_001,
            )


# ---------------------------------------------------------------------------
# Cases, datasets, ownership
# ---------------------------------------------------------------------------


class TestCasesAndOwnership:
    def test_create_case_returns_pydantic_record_with_server_uuid(self, runtime):
        with runtime.session() as session:
            record = CaseRepository(session).create(
                CaseCreateRequest(name="边坡案例", case_type="generic", config={"k": 1})
            )
        assert isinstance(record, BaseModel)
        assert not hasattr(record, "_sa_instance_state")
        assert UUID_RE.match(record.id)
        assert record.name == "边坡案例"
        assert record.config == {"k": 1}
        assert record.created_at and record.updated_at

    def test_new_case_record_has_active_lifecycle_and_null_trashed_at(self, runtime):
        case_id = create_case(runtime)
        with runtime.session() as session:
            record = CaseRepository(session).get(case_id)
        assert record.lifecycle_state == "active"
        assert record.trashed_at is None

    def test_case_name_is_display_metadata_not_a_path(self, runtime):
        evil = create_case(runtime, name="../../etc/passwd")
        with runtime.session() as session:
            assert CaseRepository(session).get(evil).name == "../../etc/passwd"
        # nothing was written outside tmp_path's runtime tree
        assert not (runtime.settings.data_dir / ".." / "etc").exists()

    def test_get_missing_case_raises_stable_404(self, runtime):
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                CaseRepository(session).get("no-such-case")
        assert excinfo.value.code == CASE_NOT_FOUND
        assert excinfo.value.http_status == 404

    def test_dataset_versions_increment_per_case(self, runtime):
        case_id = create_case(runtime)
        first = create_dataset(runtime, case_id)
        second = create_dataset(runtime, case_id)
        with runtime.session() as session:
            repo = DatasetRepository(session)
            assert repo.get(first).version == 1
            assert repo.get(second).version == 2
            assert repo.get(first).status == DatasetStatus.UPLOADED

    def test_dataset_creation_requires_existing_case(self, runtime):
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                DatasetRepository(session).create_version("ghost", source_path="u/x.csv")
        assert excinfo.value.code == CASE_NOT_FOUND

    def test_dataset_ownership_is_enforced(self, runtime):
        owner = create_case(runtime, name="owner")
        other = create_case(runtime, name="other")
        dataset_id = create_dataset(runtime, owner)
        with runtime.session() as session:
            repo = DatasetRepository(session)
            assert repo.get_for_case(owner, dataset_id).id == dataset_id
            with pytest.raises(PlatformError) as excinfo:
                repo.get_for_case(other, dataset_id)
        assert excinfo.value.code == DATASET_NOT_IN_CASE
        assert excinfo.value.http_status == 404

    def test_get_missing_dataset_raises_stable_404(self, runtime):
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                DatasetRepository(session).get("ghost")
        assert excinfo.value.code == DATASET_NOT_FOUND

    def test_experiment_rejects_dataset_from_another_case(self, runtime):
        owner = create_case(runtime, name="owner")
        other = create_case(runtime, name="other")
        foreign_dataset = create_dataset(runtime, other)
        with runtime.session() as session:
            request = ExperimentCreateRequest(
                case_id=owner,
                name="exp",
                algorithm=Algorithm.ORDINARY_KRIGING,
                dataset_version_id=foreign_dataset,
            )
            with pytest.raises(PlatformError) as excinfo:
                ExperimentRepository(session).create(owner, request)
        assert excinfo.value.code == DATASET_NOT_IN_CASE

    def test_experiment_ownership_is_enforced(self, runtime):
        owner = create_case(runtime, name="owner")
        other = create_case(runtime, name="other")
        experiment_id = create_experiment(runtime, owner)
        with runtime.session() as session:
            repo = ExperimentRepository(session)
            assert repo.get_for_case(owner, experiment_id).id == experiment_id
            with pytest.raises(PlatformError) as excinfo:
                repo.get_for_case(other, experiment_id)
        assert excinfo.value.code == EXPERIMENT_NOT_IN_CASE

    def test_experiment_params_roundtrip_as_canonical_json(self, runtime):
        case_id = create_case(runtime)
        experiment_id = create_experiment(runtime, case_id)
        raw = sqlite3.connect(runtime.db_path)
        try:
            params_json = raw.execute(
                "SELECT params_json FROM experiments WHERE id = ?", (experiment_id,)
            ).fetchone()[0]
        finally:
            raw.close()
        payload = json.loads(params_json)
        assert payload["algorithm"] == "idw"
        assert payload["parameters"] == {"power": 2.0}
        assert payload["validation"]["method"] == "spatial_kfold"
        assert params_json == json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )


# ---------------------------------------------------------------------------
# Dataset version allocation
# ---------------------------------------------------------------------------


class TestVersionAllocation:
    def test_case_version_pair_has_unique_constraint(self, runtime):
        case_id = create_case(runtime)
        create_dataset(runtime, case_id)  # v1
        with runtime.session() as session:
            session.add(
                DatasetVersion(
                    id="00000000-0000-0000-0000-0000000000dd",
                    case_id=case_id,
                    version=1,
                    source_path="u/x.csv",
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()

    def test_duplicate_allocation_gets_409_not_500(self, runtime, monkeypatch):
        """并发抢号：唯一约束兜底，后提交写者得到可重试的 409。"""

        case_id = create_case(runtime)
        create_dataset(runtime, case_id)  # v1
        with runtime.session() as session:
            repo = DatasetRepository(session)
            # 模拟并发写者拿着过期快照分配到同一版本号（仅作用于本实例）
            monkeypatch.setattr(repo, "_allocate_version", lambda cid: 1)
            with pytest.raises(PlatformError) as excinfo:
                repo.create_version(case_id, source_path="u/dup.csv")
        assert excinfo.value.code == DATASET_VERSION_CONFLICT
        assert excinfo.value.http_status == 409
        assert excinfo.value.details == {"case_id": case_id, "version": 1}
        # 冲突已回滚，会话与库均可继续正常分配
        with runtime.session() as session:
            record = DatasetRepository(session).create_version(
                case_id, source_path="u/ok.csv"
            )
        assert record.version == 2


# ---------------------------------------------------------------------------
# Dataset status transitions
# ---------------------------------------------------------------------------


class TestDatasetStatusTransitions:
    def test_transition_table_is_explicit_and_has_no_uploaded_skip(self):
        assert ALLOWED_DATASET_TRANSITIONS[DatasetStatus.UPLOADED.value] == frozenset(
            {DatasetStatus.MAPPED.value, DatasetStatus.BLOCKED.value, DatasetStatus.ABANDONED.value}
        )
        assert DatasetStatus.VALIDATED.value not in ALLOWED_DATASET_TRANSITIONS[
            DatasetStatus.UPLOADED.value
        ]
        assert ALLOWED_DATASET_TRANSITIONS[DatasetStatus.BLOCKED.value] == frozenset(
            {DatasetStatus.MAPPED.value, DatasetStatus.ABANDONED.value}
        )

    def test_abandoned_is_terminal(self):
        assert ALLOWED_DATASET_TRANSITIONS[DatasetStatus.ABANDONED.value] == frozenset()

    def test_validated_is_terminal(self):
        assert ALLOWED_DATASET_TRANSITIONS[DatasetStatus.VALIDATED.value] == frozenset()

    def test_mapped_allows_validated_blocked_and_abandoned(self):
        assert ALLOWED_DATASET_TRANSITIONS[DatasetStatus.MAPPED.value] >= {
            "validated", "blocked", "abandoned"
        }

    def test_legacy_alias_matches_new_name(self):
        assert DATASET_STATUS_TRANSITIONS is ALLOWED_DATASET_TRANSITIONS

    def test_dataset_cannot_skip_uploaded_to_validated(self, runtime):
        dataset_id = create_dataset(runtime, create_case(runtime))
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                DatasetRepository(session).transition_status(dataset_id, DatasetStatus.VALIDATED)
        assert excinfo.value.code == INVALID_STATUS_TRANSITION
        assert excinfo.value.http_status == 409
        assert excinfo.value.details["current"] == DatasetStatus.UPLOADED.value
        assert excinfo.value.details["target"] == DatasetStatus.VALIDATED.value

    def test_happy_path_uploaded_mapped_validated(self, runtime):
        dataset_id = create_dataset(runtime, create_case(runtime))
        with runtime.session() as session:
            repo = DatasetRepository(session)
            assert repo.transition_status(dataset_id, DatasetStatus.MAPPED).status == "mapped"
            assert repo.transition_status(dataset_id, DatasetStatus.VALIDATED).status == "validated"

    def test_detour_uploaded_blocked_mapped_validated(self, runtime):
        dataset_id = create_dataset(runtime, create_case(runtime))
        with runtime.session() as session:
            repo = DatasetRepository(session)
            assert repo.transition_status(dataset_id, DatasetStatus.BLOCKED).status == "blocked"
            assert repo.transition_status(dataset_id, DatasetStatus.MAPPED).status == "mapped"
            assert repo.transition_status(dataset_id, DatasetStatus.VALIDATED).status == "validated"

    def test_blocked_cannot_jump_to_validated(self, runtime):
        dataset_id = create_dataset(runtime, create_case(runtime))
        with runtime.session() as session:
            repo = DatasetRepository(session)
            repo.transition_status(dataset_id, DatasetStatus.BLOCKED)
            with pytest.raises(PlatformError) as excinfo:
                repo.transition_status(dataset_id, DatasetStatus.VALIDATED)
        assert excinfo.value.code == INVALID_STATUS_TRANSITION

    def test_validated_is_terminal(self, runtime):
        dataset_id = create_dataset(runtime, create_case(runtime))
        with runtime.session() as session:
            repo = DatasetRepository(session)
            repo.transition_status(dataset_id, DatasetStatus.MAPPED)
            repo.transition_status(dataset_id, DatasetStatus.VALIDATED)
            with pytest.raises(PlatformError):
                repo.transition_status(dataset_id, DatasetStatus.MAPPED)

    def test_transition_on_missing_dataset_is_404(self, runtime):
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                DatasetRepository(session).transition_status("ghost", DatasetStatus.MAPPED)
        assert excinfo.value.code == DATASET_NOT_FOUND


# ---------------------------------------------------------------------------
# Run lifecycle, retry, compare-and-update
# ---------------------------------------------------------------------------


class TestRunLifecycleAndRetry:
    def test_retryable_status_set_is_explicit(self):
        assert RUN_RETRYABLE_STATUSES == frozenset({"failed", "canceled", "interrupted"})

    def test_new_run_is_queued_with_server_uuid(self, runtime):
        case_id = create_case(runtime)
        run_id = create_run(runtime, create_experiment(runtime, case_id))
        with runtime.session() as session:
            record = RunRepository(session).get(run_id)
        assert isinstance(record, BaseModel)
        assert UUID_RE.match(record.id)
        assert record.status == RunStatus.QUEUED
        assert record.retry_of_run_id is None

    def test_get_missing_run_is_404(self, runtime):
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                RunRepository(session).get("ghost")
        assert excinfo.value.code == RUN_NOT_FOUND

    @pytest.mark.parametrize("status", ["queued", "running"])
    def test_queued_and_running_runs_cannot_retry(self, runtime, status):
        case_id = create_case(runtime)
        run_id = create_run(runtime, create_experiment(runtime, case_id))
        drive_run_to(runtime, run_id, status)
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                RunRepository(session).retry(run_id)
        assert excinfo.value.code == RUN_NOT_RETRYABLE
        assert excinfo.value.http_status == 409
        assert excinfo.value.details["status"] == status

    @pytest.mark.parametrize("status", ["failed", "canceled"])
    def test_terminal_failed_and_canceled_runs_can_retry(self, runtime, status):
        case_id = create_case(runtime)
        run_id = create_run(runtime, create_experiment(runtime, case_id))
        drive_run_to(runtime, run_id, status)
        with runtime.session() as session:
            retried = RunRepository(session).retry(run_id)
        assert retried.id != run_id
        assert retried.status == RunStatus.QUEUED
        assert retried.retry_of_run_id == run_id
        # original record is preserved untouched
        with runtime.session() as session:
            original = RunRepository(session).get(run_id)
        assert original.status == status
        assert retried.experiment_id == original.experiment_id

    def test_interrupted_run_can_retry(self, runtime):
        case_id = create_case(runtime)
        run_id = create_run(runtime, create_experiment(runtime, case_id))
        drive_run_to(runtime, run_id, "running")
        assert runtime.recover_interrupted_runs() == 1
        with runtime.session() as session:
            retried = RunRepository(session).retry(run_id)
        assert retried.retry_of_run_id == run_id
        assert retried.status == RunStatus.QUEUED

    def test_retry_of_missing_run_is_404(self, runtime):
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                RunRepository(session).retry("ghost")
        assert excinfo.value.code == RUN_NOT_FOUND

    def test_retry_is_rejected_while_another_run_is_active(self, runtime):
        case_id = create_case(runtime)
        experiment_id = create_experiment(runtime, case_id)
        failed = create_run(runtime, experiment_id)
        drive_run_to(runtime, failed, "failed")
        create_run(runtime, experiment_id)  # a queued sibling exists
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                RunRepository(session).retry(failed)
        assert excinfo.value.code == RUN_ALREADY_ACTIVE

    def test_cancel_queued_run(self, runtime):
        case_id = create_case(runtime)
        run_id = create_run(runtime, create_experiment(runtime, case_id))
        with runtime.session() as session:
            assert RunRepository(session).cancel(run_id).status == RunStatus.CANCELED

    def test_cancel_terminal_run_is_rejected(self, runtime):
        case_id = create_case(runtime)
        run_id = create_run(runtime, create_experiment(runtime, case_id))
        drive_run_to(runtime, run_id, "succeeded")
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                RunRepository(session).cancel(run_id)
        assert excinfo.value.code == INVALID_STATUS_TRANSITION

    def test_worker_completion_cannot_overwrite_a_cancel(self, runtime):
        """Compare-and-update: cancel wins the race against worker completion."""

        case_id = create_case(runtime)
        run_id = create_run(runtime, create_experiment(runtime, case_id))
        drive_run_to(runtime, run_id, "running")
        with runtime.session() as session:
            repo = RunRepository(session)
            repo.cancel(run_id)
            with pytest.raises(PlatformError) as excinfo:
                repo.mark_succeeded(run_id, metrics={"rmse": 0.1})
        assert excinfo.value.code == INVALID_STATUS_TRANSITION
        with runtime.session() as session:
            assert RunRepository(session).get(run_id).status == RunStatus.CANCELED

    def test_mark_succeeded_persists_metrics_as_canonical_json(self, runtime):
        case_id = create_case(runtime)
        run_id = create_run(runtime, create_experiment(runtime, case_id))
        drive_run_to(runtime, run_id, "running")
        with runtime.session() as session:
            record = RunRepository(session).mark_succeeded(
                run_id, metrics={"rmse": 0.42, "label": "中文"}
            )
        assert record.status == RunStatus.SUCCEEDED
        assert record.metrics == {"rmse": 0.42, "label": "中文"}
        assert record.finished_at is not None
        raw = sqlite3.connect(runtime.db_path)
        try:
            metrics_json = raw.execute(
                "SELECT metrics_json FROM runs WHERE id = ?", (run_id,)
            ).fetchone()[0]
        finally:
            raw.close()
        assert metrics_json == json.dumps(
            {"rmse": 0.42, "label": "中文"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


# ---------------------------------------------------------------------------
# Formal selection
# ---------------------------------------------------------------------------


class TestFormalSelection:
    def test_succeeded_candidate_can_become_formal(self, runtime):
        case_id = create_case(runtime)
        candidate_id = create_succeeded_candidate(runtime, case_id)
        with runtime.session() as session:
            record = FormalSelectionRepository(session).select(
                case_id,
                FormalSelectionRequest(
                    candidate_result_id=candidate_id, note="公共有效集 RMSE 最低", selected_by="op"
                ),
            )
        assert isinstance(record, BaseModel)
        assert record.case_id == case_id
        assert record.candidate_result_id == candidate_id
        assert record.note == "公共有效集 RMSE 最低"
        assert UUID_RE.match(record.id)

    def test_candidate_of_a_failed_run_cannot_become_formal(self, runtime):
        case_id = create_case(runtime)
        experiment_id = create_experiment(runtime, case_id)
        run_id = create_run(runtime, experiment_id)
        drive_run_to(runtime, run_id, "failed")
        with runtime.session() as session:
            candidate_id = CandidateRepository(session).create(run_id, metrics={}).id
            with pytest.raises(PlatformError) as excinfo:
                FormalSelectionRepository(session).select(
                    case_id,
                    FormalSelectionRequest(candidate_result_id=candidate_id, note="尝试"),
                )
        assert excinfo.value.code == CANDIDATE_NOT_SUCCEEDED
        assert excinfo.value.http_status == 409
        assert excinfo.value.details["run_status"] == "failed"

    def test_candidate_of_a_canceled_run_cannot_become_formal(self, runtime):
        case_id = create_case(runtime)
        run_id = create_run(runtime, create_experiment(runtime, case_id))
        drive_run_to(runtime, run_id, "canceled")
        with runtime.session() as session:
            candidate_id = CandidateRepository(session).create(run_id, metrics={}).id
            with pytest.raises(PlatformError) as excinfo:
                FormalSelectionRepository(session).select(
                    case_id, FormalSelectionRequest(candidate_result_id=candidate_id, note="x")
                )
        assert excinfo.value.code == CANDIDATE_NOT_SUCCEEDED

    def test_failed_candidate_of_succeeded_run_cannot_become_formal(self, runtime):
        """run succeeded 但候选 failed → 409，且不写 FormalSelection。"""

        case_id = create_case(runtime)
        candidate_id = create_succeeded_candidate(runtime, case_id)
        set_candidate_status(runtime, candidate_id, "failed")
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                FormalSelectionRepository(session).select(
                    case_id,
                    FormalSelectionRequest(candidate_result_id=candidate_id, note="尝试"),
                )
        assert excinfo.value.code == CANDIDATE_NOT_SUCCEEDED
        assert excinfo.value.http_status == 409
        assert excinfo.value.details["candidate_status"] == "failed"
        assert formal_selection_count(runtime, candidate_id) == 0

    @pytest.mark.parametrize("status", ["queued", "pending", "running"])
    def test_unfinished_candidate_of_succeeded_run_cannot_become_formal(self, runtime, status):
        """run succeeded 但候选未到 succeeded（queued/pending/running）→ 409 不写。"""

        case_id = create_case(runtime)
        candidate_id = create_succeeded_candidate(runtime, case_id)
        set_candidate_status(runtime, candidate_id, status)
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                FormalSelectionRepository(session).select(
                    case_id,
                    FormalSelectionRequest(candidate_result_id=candidate_id, note="尝试"),
                )
        assert excinfo.value.code == CANDIDATE_NOT_SUCCEEDED
        assert excinfo.value.http_status == 409
        assert excinfo.value.details["candidate_status"] == status
        assert formal_selection_count(runtime, candidate_id) == 0

    def test_succeeded_candidate_of_failed_run_cannot_become_formal(self, runtime):
        """手工构造：候选 succeeded 但 run failed → 409（run 状态兜底），不写。"""

        case_id = create_case(runtime)
        experiment_id = create_experiment(runtime, case_id)
        run_id = create_run(runtime, experiment_id)
        drive_run_to(runtime, run_id, "failed")
        with runtime.session() as session:
            candidate_id = CandidateRepository(session).create(run_id, metrics={}).id
        set_candidate_status(runtime, candidate_id, "succeeded")
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                FormalSelectionRepository(session).select(
                    case_id,
                    FormalSelectionRequest(candidate_result_id=candidate_id, note="尝试"),
                )
        assert excinfo.value.code == CANDIDATE_NOT_SUCCEEDED
        assert excinfo.value.http_status == 409
        assert excinfo.value.details["run_status"] == "failed"
        assert formal_selection_count(runtime, candidate_id) == 0

    def test_formal_selection_enforces_case_ownership(self, runtime):
        owner = create_case(runtime, name="owner")
        other = create_case(runtime, name="other")
        candidate_id = create_succeeded_candidate(runtime, owner)
        with runtime.session() as session:
            with pytest.raises(PlatformError) as excinfo:
                FormalSelectionRepository(session).select(
                    other, FormalSelectionRequest(candidate_result_id=candidate_id, note="抢注")
                )
        assert excinfo.value.code == CANDIDATE_NOT_IN_CASE

    def test_ownership_is_checked_before_run_status(self, runtime):
        """跨案例探测失败任务的候选：一律 404，不泄露候选存在性与 run 状态。"""

        owner = create_case(runtime, name="owner")
        other = create_case(runtime, name="other")
        experiment_id = create_experiment(runtime, owner)
        run_id = create_run(runtime, experiment_id)
        drive_run_to(runtime, run_id, "failed")
        with runtime.session() as session:
            candidate_id = CandidateRepository(session).create(run_id, metrics={}).id
            with pytest.raises(PlatformError) as excinfo:
                FormalSelectionRepository(session).select(
                    other, FormalSelectionRequest(candidate_result_id=candidate_id, note="探测")
                )
        assert excinfo.value.code == CANDIDATE_NOT_IN_CASE
        assert excinfo.value.http_status == 404

    def test_formal_selection_requires_a_reason(self, runtime):
        with pytest.raises(ValidationError):
            FormalSelectionRequest(candidate_result_id="cand", note="")

    def test_candidate_repository_returns_pydantic_records(self, runtime):
        case_id = create_case(runtime)
        candidate_id = create_succeeded_candidate(runtime, case_id)
        with runtime.session() as session:
            record = CandidateRepository(session).get(candidate_id)
        assert isinstance(record, BaseModel)
        assert not hasattr(record, "_sa_instance_state")
        assert record.metrics == {"rmse": 0.5}
        assert record.category == "preview"


# ---------------------------------------------------------------------------
# Safe platform errors
# ---------------------------------------------------------------------------


class TestSafePlatformErrors:
    def test_public_payload_shape(self):
        err = PlatformError("X_CODE", "出错了", details={"k": "v"}, http_status=418)
        assert err.public_payload() == {
            "error": {"code": "X_CODE", "message": "出错了", "details": {"k": "v"}}
        }

    def test_details_default_and_http_status_default(self):
        err = PlatformError("X", "m")
        assert err.details == {}
        assert err.http_status == 400

    def test_sanitize_removes_path_objects_and_absolute_paths(self):
        details = {
            "path": Path("/var/geomodeling/uploads/secret.csv"),
            "windows": "C:\\Users\\keleoz\\secret.csv",
            "posix": "/home/user/secret.csv",
            "unc": "\\\\server\\share\\secret.csv",
            "relative": "uploads/case/source.csv",
            "nested": [{"inner": Path("D:/study/secret.parquet")}],
            "count": 3,
            "flag": None,
        }
        clean = sanitize_public_details(details)
        assert clean["path"] == "<redacted-path>"
        assert clean["windows"] == "<redacted-path>"
        assert clean["posix"] == "<redacted-path>"
        assert clean["unc"] == "<redacted-path>"
        assert clean["relative"] == "uploads/case/source.csv"
        assert clean["nested"] == [{"inner": "<redacted-path>"}]
        assert clean["count"] == 3
        assert clean["flag"] is None

    def test_sanitize_covers_root_relative_and_drive_relative_forms(self):
        details = {
            "root_relative": "\\Windows\\System32\\x.dll",
            "drive_relative": "C:secret.txt",
            "safe_filename": "data.csv",
            "safe_crs": "EPSG:4547",
        }
        clean = sanitize_public_details(details)
        assert clean["root_relative"] == "<redacted-path>"
        assert clean["drive_relative"] == "<redacted-path>"
        assert clean["safe_filename"] == "data.csv"
        assert clean["safe_crs"] == "EPSG:4547"

    def test_sanitize_pure_path_fallback_stays_json_serializable(self):
        details = {
            "pure_posix": PurePosixPath("/etc/secret.conf"),
            "pure_windows": PureWindowsPath("D:/data/secret.parquet"),
        }
        clean = sanitize_public_details(details)
        assert clean == {"pure_posix": "<redacted-path>", "pure_windows": "<redacted-path>"}
        # 脱敏结果必须可直接 JSON 序列化，不会在响应层 500
        json.dumps(clean)

    def test_handler_returns_sanitized_payload_and_logs_full_details(self, caplog):
        fastapi = pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        app = fastapi.FastAPI()
        app.add_exception_handler(PlatformError, platform_error_handler)

        @app.get("/boom")
        def boom():
            raise PlatformError(
                "UPLOAD_TOO_LARGE",
                "文件超过上限",
                details={"stored_at": Path("/var/geomodeling/uploads/a.part")},
                http_status=413,
            )

        client = TestClient(app, raise_server_exceptions=False)
        with caplog.at_level(logging.ERROR, logger="geomodeling.platform"):
            resp = client.get("/boom")
        assert resp.status_code == 413
        assert resp.json() == {
            "error": {
                "code": "UPLOAD_TOO_LARGE",
                "message": "文件超过上限",
                "details": {"stored_at": "<redacted-path>"},
            }
        }
        # 服务端日志保留完整诊断（含原始路径）
        assert "/var/geomodeling/uploads/a.part" in caplog.text


# ---------------------------------------------------------------------------
# Persistence boundary
# ---------------------------------------------------------------------------


def test_records_survive_runtime_reopen(tmp_path):
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    case_id = create_case(runtime, name="reopen")
    dataset_id = create_dataset(runtime, case_id)
    runtime.close()

    reopened = PlatformRuntime(tmp_path / "runtime")
    reopened.initialize()
    with reopened.session() as session:
        dataset = DatasetRepository(session).get_for_case(case_id, dataset_id)
        assert dataset.status == DatasetStatus.UPLOADED
        assert dataset.case_id == case_id
    reopened.close()


# ---------------------------------------------------------------------------
# v7: case lifecycle records
# ---------------------------------------------------------------------------


def test_case_purge_operation_record_roundtrip(tmp_path):
    from geomodeling.platform.tables import CasePurgeOperation

    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    with runtime.session() as session:
        row = CasePurgeOperation(
            id="purge-op-1",
            case_id="case-1",
            state="prepared",
            manifest_json='{"version": 1}',
            receipt_json='{"deleted": 0}',
        )
        session.add(row)
        session.commit()

        record = CasePurgeOperationRecord(
            id=row.id,
            case_id=row.case_id,
            state=row.state,
            manifest={"version": 1},
            receipt={"deleted": 0},
            error=None,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        assert record.id == "purge-op-1"
        assert record.case_id == "case-1"
        assert record.state == "prepared"
        assert record.manifest == {"version": 1}
        assert record.receipt == {"deleted": 0}
        assert record.error is None
    runtime.close()
