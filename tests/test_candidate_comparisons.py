"""Tests for candidate catalog and multi-candidate comparison (v0.7.0 batch 3 §8)."""

from __future__ import annotations

import pytest

from geomodeling.platform import PlatformRuntime
from geomodeling.platform.candidate_comparisons import (
    candidate_catalog,
    compare_candidates_multi,
)
from geomodeling.platform.errors import (
    COMPARISON_DATASET_MISMATCH,
    COMPARISON_SELECTION_INVALID,
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
from geomodeling.platform.tables import CandidateResult, Experiment, Run, RunStatus


@pytest.fixture()
def runtime(tmp_path):
    rt = PlatformRuntime(tmp_path / "runtime")
    rt.initialize()
    yield rt
    rt.close()


def create_case(runtime, name="test"):
    with runtime.session() as session:
        return CaseRepository(session).create(
            CaseCreateRequest(name=name, case_type="generic")
        ).id


def create_dataset(runtime, case_id):
    with runtime.session() as session:
        return DatasetRepository(session).create_version(
            case_id, source_path="uploads/x/source.csv"
        ).id


def create_experiment(runtime, case_id, dataset_id, name="exp", algorithm=Algorithm.IDW):
    with runtime.session() as session:
        request = ExperimentCreateRequest(
            case_id=case_id, name=name, algorithm=algorithm,
            dataset_version_id=dataset_id, parameters={"power": 2.0},
        )
        return ExperimentRepository(session).create(case_id, request).id


def create_run(runtime, experiment_id):
    with runtime.session() as session:
        return RunRepository(session).create(experiment_id).id


def drive_run_succeeded(runtime, run_id):
    with runtime.session() as session:
        repo = RunRepository(session)
        repo.mark_running(run_id)
        repo.mark_succeeded(run_id, metrics={"rmse": 1.0})


def create_succeeded_candidate(runtime, run_id, metrics=None):
    with runtime.session() as session:
        cand_id = CandidateRepository(session).create(
            run_id, metrics=metrics or {"rmse": 0.5}
        ).id
    with runtime.session() as session:
        row = session.get(CandidateResult, cand_id)
        row.status = "succeeded"
        session.commit()
    return cand_id


class TestCandidateCatalog:
    def test_catalog_groups_by_experiment(self, runtime):
        case_id = create_case(runtime)
        dataset_id = create_dataset(runtime, case_id)
        exp1 = create_experiment(runtime, case_id, dataset_id, name="exp1")
        run1 = create_run(runtime, exp1)
        drive_run_succeeded(runtime, run1)
        cand1 = create_succeeded_candidate(runtime, run1, {"rmse": 0.5})

        exp2 = create_experiment(runtime, case_id, dataset_id, name="exp2")
        run2 = create_run(runtime, exp2)
        drive_run_succeeded(runtime, run2)
        cand2 = create_succeeded_candidate(runtime, run2, {"rmse": 0.3})

        catalog = candidate_catalog(runtime, dataset_id)
        assert catalog["dataset_id"] == dataset_id
        assert len(catalog["groups"]) == 2

    def test_catalog_includes_configuration_fingerprint(self, runtime):
        """Catalog candidates include configuration_fingerprint."""
        case_id = create_case(runtime)
        dataset_id = create_dataset(runtime, case_id)
        exp1 = create_experiment(runtime, case_id, dataset_id, name="exp1")
        run1 = create_run(runtime, exp1)
        drive_run_succeeded(runtime, run1)
        create_succeeded_candidate(runtime, run1, {"rmse": 0.5})

        catalog = candidate_catalog(runtime, dataset_id)
        assert len(catalog["groups"]) == 1
        c = catalog["groups"][0]["candidates"][0]
        assert "configuration_fingerprint" in c
        assert len(c["configuration_fingerprint"]) == 64  # SHA-256 hex

    def test_same_config_same_fingerprint_different_experiments(self, runtime):
        """Same dataset/algorithm/parameters/validation -> same fingerprint."""
        case_id = create_case(runtime)
        dataset_id = create_dataset(runtime, case_id)
        exp1 = create_experiment(runtime, case_id, dataset_id, name="exp1")
        run1 = create_run(runtime, exp1)
        drive_run_succeeded(runtime, run1)
        create_succeeded_candidate(runtime, run1, {"rmse": 0.5})

        exp2 = create_experiment(runtime, case_id, dataset_id, name="exp2")
        run2 = create_run(runtime, exp2)
        drive_run_succeeded(runtime, run2)
        create_succeeded_candidate(runtime, run2, {"rmse": 0.3})

        catalog = candidate_catalog(runtime, dataset_id)
        fp1 = catalog["groups"][0]["candidates"][0]["configuration_fingerprint"]
        fp2 = catalog["groups"][1]["candidates"][0]["configuration_fingerprint"]
        # Same algorithm (IDW) and parameters -> same fingerprint
        assert fp1 == fp2

    def test_different_parameters_different_fingerprint(self, runtime):
        """Different parameters -> different fingerprint."""
        case_id = create_case(runtime)
        dataset_id = create_dataset(runtime, case_id)
        exp1 = create_experiment(runtime, case_id, dataset_id, name="exp1")
        run1 = create_run(runtime, exp1)
        drive_run_succeeded(runtime, run1)
        create_succeeded_candidate(runtime, run1, {"rmse": 0.5})

        # Create experiment with different parameters
        with runtime.session() as session:
            from geomodeling.platform.schemas import ExperimentCreateRequest
            request = ExperimentCreateRequest(
                case_id=case_id, name="exp2", algorithm=Algorithm.IDW,
                dataset_version_id=dataset_id, parameters={"power": 3.0},
            )
            exp2_id = ExperimentRepository(session).create(case_id, request).id
        run2 = create_run(runtime, exp2_id)
        drive_run_succeeded(runtime, run2)
        create_succeeded_candidate(runtime, run2, {"rmse": 0.3})

        catalog = candidate_catalog(runtime, dataset_id)
        fp1 = catalog["groups"][1]["candidates"][0]["configuration_fingerprint"]
        fp2 = catalog["groups"][0]["candidates"][0]["configuration_fingerprint"]
        assert fp1 != fp2  # power=2 vs power=3
        # Newest experiment first
        assert catalog["groups"][0]["experiment_id"] == exp2_id

    def test_failed_candidate_not_selectable(self, runtime):
        case_id = create_case(runtime)
        dataset_id = create_dataset(runtime, case_id)
        exp_id = create_experiment(runtime, case_id, dataset_id)
        run_id = create_run(runtime, exp_id)
        drive_run_succeeded(runtime, run_id)
        with runtime.session() as session:
            cand_id = CandidateRepository(session).create(run_id, metrics={}).id
        # Candidate stays queued (not succeeded)
        catalog = candidate_catalog(runtime, dataset_id)
        assert len(catalog["groups"]) == 1
        assert catalog["groups"][0]["candidates"][0]["selectable"] is False

    def test_future_algorithm_renders_generically(self, runtime):
        case_id = create_case(runtime)
        dataset_id = create_dataset(runtime, case_id)
        # Create experiment with raw algorithm string
        with runtime.session() as session:
            row = Experiment(
                id="exp-dsi", case_id=case_id, name="dsi-exp",
                params_json='{"algorithm": "dsi_like", "dataset_version_id": "'
                            + dataset_id + '", "parameters": {}}',
            )
            session.add(row)
            session.flush()
            run = Run(id="run-dsi", experiment_id="exp-dsi", status="succeeded")
            session.add(run)
            session.flush()
            cand = CandidateResult(
                id="cand-dsi", run_id="run-dsi", category="preview",
                fingerprint="fp", status="succeeded",
                params_json="{}", metrics_json='{"rmse": 0.1}',
            )
            session.add(cand)
            session.commit()

        catalog = candidate_catalog(runtime, dataset_id)
        assert len(catalog["groups"]) == 1
        c = catalog["groups"][0]["candidates"][0]
        assert c["algorithm"] == "dsi_like"
        assert c["selectable"] is True


class TestMultiCandidateComparison:
    def test_comparable_candidates_ranked(self, runtime):
        case_id = create_case(runtime)
        dataset_id = create_dataset(runtime, case_id)
        exp1 = create_experiment(runtime, case_id, dataset_id, name="exp1")
        run1 = create_run(runtime, exp1)
        drive_run_succeeded(runtime, run1)
        cand1 = create_succeeded_candidate(runtime, run1, {"rmse": 0.5, "mae": 0.3, "r2": 0.8, "bias": 0.01})

        exp2 = create_experiment(runtime, case_id, dataset_id, name="exp2")
        run2 = create_run(runtime, exp2)
        drive_run_succeeded(runtime, run2)
        cand2 = create_succeeded_candidate(runtime, run2, {"rmse": 0.3, "mae": 0.2, "r2": 0.9, "bias": 0.02})

        result = compare_candidates_multi(runtime, [cand1, cand2])
        assert result.comparable is True
        assert result.ranking == [cand2, cand1]  # lower RMSE first
        assert result.comparison_fingerprint

    def test_duplicate_ids_rejected(self, runtime):
        case_id = create_case(runtime)
        dataset_id = create_dataset(runtime, case_id)
        exp_id = create_experiment(runtime, case_id, dataset_id)
        run_id = create_run(runtime, exp_id)
        drive_run_succeeded(runtime, run_id)
        cand_id = create_succeeded_candidate(runtime, run_id)

        with pytest.raises(PlatformError) as excinfo:
            compare_candidates_multi(runtime, [cand_id, cand_id])
        assert excinfo.value.code == COMPARISON_SELECTION_INVALID

    def test_single_id_rejected(self, runtime):
        with pytest.raises(PlatformError) as excinfo:
            compare_candidates_multi(runtime, ["c1"])
        assert excinfo.value.code == COMPARISON_SELECTION_INVALID

    def test_five_ids_rejected(self, runtime):
        with pytest.raises(PlatformError) as excinfo:
            compare_candidates_multi(runtime, ["c1", "c2", "c3", "c4", "c5"])
        assert excinfo.value.code == COMPARISON_SELECTION_INVALID

    def test_different_dataset_raises_mismatch(self, runtime):
        case_id = create_case(runtime)
        ds1 = create_dataset(runtime, case_id)
        ds2 = create_dataset(runtime, case_id)
        exp1 = create_experiment(runtime, case_id, ds1, name="e1")
        run1 = create_run(runtime, exp1)
        drive_run_succeeded(runtime, run1)
        cand1 = create_succeeded_candidate(runtime, run1)

        exp2 = create_experiment(runtime, case_id, ds2, name="e2")
        run2 = create_run(runtime, exp2)
        drive_run_succeeded(runtime, run2)
        cand2 = create_succeeded_candidate(runtime, run2)

        with pytest.raises(PlatformError) as excinfo:
            compare_candidates_multi(runtime, [cand1, cand2])
        assert excinfo.value.code == COMPARISON_DATASET_MISMATCH

    def test_input_permutation_same_ranking(self, runtime):
        case_id = create_case(runtime)
        dataset_id = create_dataset(runtime, case_id)
        exp1 = create_experiment(runtime, case_id, dataset_id, name="e1")
        run1 = create_run(runtime, exp1)
        drive_run_succeeded(runtime, run1)
        cand1 = create_succeeded_candidate(runtime, run1, {"rmse": 0.5})

        exp2 = create_experiment(runtime, case_id, dataset_id, name="e2")
        run2 = create_run(runtime, exp2)
        drive_run_succeeded(runtime, run2)
        cand2 = create_succeeded_candidate(runtime, run2, {"rmse": 0.3})

        r1 = compare_candidates_multi(runtime, [cand1, cand2])
        r2 = compare_candidates_multi(runtime, [cand2, cand1])
        assert r1.ranking == r2.ranking
        assert r1.comparison_fingerprint == r2.comparison_fingerprint
