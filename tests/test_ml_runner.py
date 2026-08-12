from __future__ import annotations

import threading

import numpy as np
import pandas as pd

from geomodeling.modeling.runner import execute_run
from geomodeling.platform import PlatformRuntime, tables


def _prepare(runtime: PlatformRuntime, algorithm: str, parameters: dict) -> str:
    case_id = f"case-{algorithm}"
    dataset_id = f"dataset-{algorithm}"
    experiment_id = f"experiment-{algorithm}"
    run_id = f"run-{algorithm}"
    x, y = np.meshgrid(np.arange(16, dtype=float), np.arange(15, dtype=float), indexing="ij")
    x = x.ravel()
    y = y.ravel()
    z = ((x * 3 + y * 5) % 9).astype(float)
    value = 0.7 * x - 0.4 * y + np.sin(z) + 0.03 * x * y
    frame = pd.DataFrame(
        {
            "source_row": np.arange(len(x), dtype="int64"),
            "x": x,
            "y": y,
            "z": z,
            "value": value,
            "is_numeric_valid": True,
        }
    )
    target = runtime.settings.standardized_dataset(case_id, dataset_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(target, index=False)
    with runtime.session() as session:
        session.add(tables.Case(id=case_id, name="ML", case_type="generic", config_json="{}"))
        session.add(
            tables.DatasetVersion(
                id=dataset_id,
                case_id=case_id,
                version=1,
                status="validated",
                source_path="source.csv",
                standardized_path=str(target),
                profile_json=tables.dumps_canonical(
                    {
                        "mapping": {"dimension": "3d", "x": "x", "y": "y", "z": "z", "value": "value"},
                        "quality": {"status": "passed", "confirmed": True},
                        "standardized_sha256": "b" * 64,
                    }
                ),
            )
        )
        session.add(
            tables.Experiment(
                id=experiment_id,
                case_id=case_id,
                name="ML experiment",
                params_json=tables.dumps_canonical(
                    {
                        "algorithm": algorithm,
                        "dataset_version_id": dataset_id,
                        "search_mode": "manual",
                        "parameters": parameters,
                        "validation": {"method": "spatial_kfold", "folds": 3, "seed": 11, "holdout_fraction": 0.2},
                        "grid": None,
                    }
                ),
            )
        )
        session.add(tables.Run(id=run_id, experiment_id=experiment_id, status="queued"))
        session.commit()
    return run_id


def _candidate(runtime: PlatformRuntime, run_id: str):
    with runtime.session() as session:
        return session.query(tables.CandidateResult).filter_by(run_id=run_id).one()


def test_random_forest_runner_writes_common_metrics_and_oof_evidence(tmp_path):
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    run_id = _prepare(
        runtime,
        "random_forest_spatial",
        {"n_estimators": 40, "max_depth": 12, "random_state": 13},
    )

    outcome = execute_run(runtime, run_id, threading.Event())
    candidate = _candidate(runtime, run_id)
    metrics = tables.loads_canonical(candidate.metrics_json)

    assert outcome.status == "succeeded"
    assert candidate.status == "succeeded"
    assert metrics["common_valid_count"] == 240
    assert metrics["candidate_nodata_count"] == 0
    assert len(metrics["fold_assignments_sha256"]) == 64
    assert len(metrics["oof_predictions_sha256"]) == 64
    assert metrics["ml_diagnostics"]["feature_version"] == "spatial_features.v1"


def test_kriging_residual_runner_uses_composite_path_and_writes_diagnostics(tmp_path):
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    run_id = _prepare(
        runtime,
        "kriging_rf_residual",
        {
            "kriging": {"variogram_model": "spherical", "neighbor_count": 12},
            "random_forest": {"n_estimators": 40, "max_depth": 10, "random_state": 17},
        },
    )

    outcome = execute_run(runtime, run_id, threading.Event())
    candidate = _candidate(runtime, run_id)
    metrics = tables.loads_canonical(candidate.metrics_json)

    assert outcome.status == "succeeded"
    assert candidate.status == "succeeded"
    assert metrics["common_valid_count"] == 240
    assert metrics["ml_diagnostics"]["residual_target_semantics"] == "observed_minus_out_of_fold_kriging"
    assert metrics["ml_diagnostics"]["inner_fold_count"] == 3
    assert metrics["ml_diagnostics"]["oof_residual_count"] > 0

