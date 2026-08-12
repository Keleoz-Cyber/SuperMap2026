from __future__ import annotations

import threading
import uuid

from fastapi.testclient import TestClient

from geomodeling.modeling.runner import execute_run
from geomodeling.platform import tables
from geomodeling.platform.results import materialize
from test_ml_runner import _prepare
from test_public_dto import assert_no_path_leak
from test_rendering_api import make_app


def _run_ml(runtime, algorithm="random_forest_spatial") -> tuple[str, str, str]:
    parameters = (
        {"n_estimators": 40, "max_depth": 12, "random_state": 13}
        if algorithm == "random_forest_spatial"
        else {
            "kriging": {"variogram_model": "spherical", "neighbor_count": 12},
            "random_forest": {
                "n_estimators": 40,
                "max_depth": 10,
                "random_state": 17,
            },
        }
    )
    run_id = _prepare(runtime, algorithm, parameters)
    assert execute_run(runtime, run_id, threading.Event()).status == "succeeded"
    with runtime.session() as session:
        run = session.get(tables.Run, run_id)
        experiment = session.get(tables.Experiment, run.experiment_id)
        params = tables.loads_canonical(experiment.params_json)
        result_id = (
            session.query(tables.CandidateResult).filter_by(run_id=run_id).one().id
        )
    return params["dataset_version_id"], experiment.case_id, result_id


def _add_kriging_baseline(
    runtime, ml_result_id: str, *, compatible: bool = True
) -> str:
    with runtime.session() as session:
        ml = session.get(tables.CandidateResult, ml_result_id)
        ml_run = session.get(tables.Run, ml.run_id)
        ml_experiment = session.get(tables.Experiment, ml_run.experiment_id)
        ml_params = tables.loads_canonical(ml_experiment.params_json)
        ml_metrics = tables.loads_canonical(ml.metrics_json)
        validation = dict(ml_params["validation"])
        if not compatible:
            validation["seed"] = int(validation.get("seed", 0)) + 1

        suffix = uuid.uuid4().hex[:8]
        experiment_id = f"kriging-baseline-exp-{suffix}"
        run_id = f"kriging-baseline-run-{suffix}"
        result_id = f"kriging-baseline-result-{suffix}"
        session.add(
            tables.Experiment(
                id=experiment_id,
                case_id=ml_experiment.case_id,
                name="普通克里金可比基线",
                params_json=tables.dumps_canonical(
                    {
                        "algorithm": "ordinary_kriging",
                        "dataset_version_id": ml_params["dataset_version_id"],
                        "search_mode": "manual",
                        "parameters": {
                            "variogram_model": "spherical",
                            "neighbor_count": 12,
                        },
                        "validation": validation,
                        "grid": None,
                    }
                ),
            )
        )
        session.flush()
        session.add(
            tables.Run(id=run_id, experiment_id=experiment_id, status="succeeded")
        )
        session.flush()
        session.add(
            tables.CandidateResult(
                id=result_id,
                run_id=run_id,
                category="candidate",
                fingerprint="d" * 64,
                status="succeeded",
                params_json=tables.dumps_canonical(
                    {"variogram_model": "spherical", "neighbor_count": 12}
                ),
                metrics_json=tables.dumps_canonical(
                    {
                        "rmse": float(ml_metrics["rmse"]) * 1.1,
                        "mae": float(ml_metrics["mae"]) * 1.05,
                        "r2": ml_metrics.get("r2"),
                        "bias": ml_metrics.get("bias"),
                        "common_valid_count": ml_metrics["common_valid_count"],
                        "fold_assignments_sha256": ml_metrics[
                            "fold_assignments_sha256"
                        ],
                    }
                ),
            )
        )
        session.commit()
    return result_id


def test_dataset_ml_capability_is_readable_and_path_free(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        dataset_id, _, _ = _run_ml(runtime)

        response = client.get(f"/api/datasets/{dataset_id}/ml-capability")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["level"] == "supported"
        assert body["valid_sample_count"] == 240
        assert body["spatial_group_count"] >= 30
        assert body["validation_requirement"] == "spatial_cross_validation"
        assert body["available_algorithms"] == [
            "random_forest_spatial",
            "kriging_rf_residual",
        ]
        assert_no_path_leak(body, "$.ml_capability")


def test_dataset_ml_capability_respects_trashed_case_guard(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        dataset_id, case_id, _ = _run_ml(runtime)
        with runtime.session() as session:
            case = session.get(tables.Case, case_id)
            case.lifecycle_state = "trashed"
            case.trashed_at = tables.utc_now_iso()
            session.commit()

        response = client.get(f"/api/datasets/{dataset_id}/ml-capability")

        assert response.status_code == 410
        assert response.json()["error"]["code"] == "CASE_TRASHED"


def test_dataset_ml_capability_marks_58_point_dataset_not_recommended(
    tmp_path, monkeypatch
):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        dataset_id, _, _ = _run_ml(runtime)
        with runtime.session() as session:
            dataset = session.get(tables.DatasetVersion, dataset_id)
            standardized = dataset.standardized_path
        import pandas as pd

        frame = pd.read_parquet(standardized).iloc[:58].copy()
        frame.to_parquet(standardized, index=False)

        response = client.get(f"/api/datasets/{dataset_id}/ml-capability")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["level"] == "not_recommended"
        assert body["valid_sample_count"] == 58
        assert body["available_algorithms"] == []
        assert body["reason_code"] == "ML_DATASET_TOO_SMALL"
        assert "不建议" in body["message"]


def test_result_analysis_exposes_comparable_ml_evidence(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        _, _, result_id = _run_ml(runtime, "kriging_rf_residual")
        baseline_id = _add_kriging_baseline(runtime, result_id)
        materialize(runtime, result_id)

        response = client.get(f"/api/results/{result_id}/analysis-summary")

        assert response.status_code == 200, response.text
        evidence = response.json()["machine_learning"]
        assert evidence["algorithm"] == "kriging_rf_residual"
        assert evidence["comparison_status"] == "comparable"
        assert evidence["baseline"]["result_id"] == baseline_id
        assert evidence["baseline"]["algorithm"] == "ordinary_kriging"
        assert evidence["metric_change"]["rmse_percent"] < 0
        assert evidence["improved_over_kriging"] is True
        assert evidence["available_fields"] == [
            "prediction",
            "model_dispersion",
            "kriging_baseline",
            "residual_correction",
        ]
        assert evidence["dispersion_semantics"] == "model_dispersion_reference"
        assert any("不是严格" in item for item in evidence["limitations"])
        assert_no_path_leak(evidence, "$.machine_learning")


def test_result_analysis_does_not_compare_incompatible_kriging(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        _, _, result_id = _run_ml(runtime)
        _add_kriging_baseline(runtime, result_id, compatible=False)
        materialize(runtime, result_id)

        response = client.get(f"/api/results/{result_id}/analysis-summary")

        assert response.status_code == 200, response.text
        evidence = response.json()["machine_learning"]
        assert evidence["comparison_status"] == "unavailable"
        assert evidence["baseline"] is None
        assert evidence["metric_change"] is None
        assert evidence["improved_over_kriging"] is None
        assert (
            evidence["comparison_reason_code"] == "ML_KRIGING_BASELINE_NOT_COMPARABLE"
        )
