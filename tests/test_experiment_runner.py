"""Task 8 runner tests: search expansion, candidate evaluation, common metrics."""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from geomodeling.platform import PlatformRuntime, tables


def make_runtime(tmp_path: Path) -> PlatformRuntime:
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    return runtime


def make_standardized(runtime: PlatformRuntime, case_id: str, dataset_id: str, dimension: str = "2d"):
    """直接构造小样本标准化 parquet（平滑场，便于插值验证）。"""
    rng = np.random.default_rng(20260723)
    n = 36
    x = rng.uniform(-160.0, -40.0, n)
    y = rng.uniform(220.0, 660.0, n)
    if dimension == "3d":
        z = rng.uniform(-840.0, 0.0, n)
        value = np.sin(x / 40) + np.cos(y / 90) + 0.001 * z + 10.0
    else:
        z = np.full(n, np.nan)
        value = np.sin(x / 40) + np.cos(y / 90) + 10.0
    frame = pd.DataFrame(
        {
            "source_row": np.arange(1, n + 1),
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
    return target, frame


def insert_experiment(runtime: PlatformRuntime, case_id: str, dataset_id: str, search: dict) -> str:
    import uuid

    experiment_id = str(uuid.uuid4())
    with runtime.session() as session:
        session.add(tables.Case(id=case_id, name="案例", case_type="generic", config_json="{}"))
        session.add(
            tables.DatasetVersion(
                id=dataset_id, case_id=case_id, version=1, status="validated",
                source_path="x.csv", profile_json=tables.dumps_canonical(
                    {"mapping": {"dimension": search.pop("dimension"), "x": "x", "y": "y",
                                 "z": search.pop("z_field", None), "value": "value",
                                 "value_name": "属性", "coordinate_kind": "local_linear"},
                     "source_sha256": "a" * 64, "standardized_sha256": "b" * 64,
                     "quality": {"status": "passed", "confirmed": True}}
                ),
            )
        )
        session.add(
            tables.Experiment(
                id=experiment_id, case_id=case_id, name="实验",
                params_json=tables.dumps_canonical(search),
            )
        )
        session.commit()
    return experiment_id


def insert_run(runtime: PlatformRuntime, experiment_id: str) -> str:
    import uuid

    run_id = str(uuid.uuid4())
    with runtime.session() as session:
        session.add(tables.Run(id=run_id, experiment_id=experiment_id, status="queued"))
        session.commit()
    return run_id


def load_candidates(runtime: PlatformRuntime, run_id: str) -> list[dict]:
    with runtime.session() as session:
        rows = (
            session.query(tables.CandidateResult)
            .filter(tables.CandidateResult.run_id == run_id)
            .all()
        )
        return [
            {
                "id": row.id,
                "fingerprint": row.fingerprint,
                "status": row.status,
                "params": tables.loads_canonical(row.params_json),
                "metrics": tables.loads_canonical(row.metrics_json),
                "error": tables.loads_canonical(row.error_json) if row.error_json else None,
                "predictions_path": row.predictions_path,
            }
            for row in rows
        ]


SEARCH_IDW_MANUAL = {
    "dimension": "2d",
    "algorithm": "idw",
    "dataset_version_id": "ds1",
    "search_mode": "manual",
    "parameters": {"power": 2.0, "neighbor_count": 8},
    "validation": {"method": "spatial_kfold", "folds": 3, "seed": 11, "holdout_fraction": 0.2},
    "grid": None,
}


def test_manual_search_expands_to_exactly_one_candidate():
    from geomodeling.platform.experiments import expand_candidates

    candidates = expand_candidates(SEARCH_IDW_MANUAL)
    assert len(candidates) == 1
    assert candidates[0].parameters["power"] == 2.0
    assert len(candidates[0].fingerprint) == 64


def test_grid_search_expands_cartesian_and_caps():
    from geomodeling.platform.experiments import expand_candidates
    from geomodeling.platform.errors import PlatformError

    search = dict(SEARCH_IDW_MANUAL)
    search["search_mode"] = "grid"
    search["parameters"] = {"power": [1.0, 2.0], "neighbor_count": [4, 8, 16]}
    candidates = expand_candidates(search)
    assert len(candidates) == 6
    fingerprints = {c.fingerprint for c in candidates}
    assert len(fingerprints) == 6

    search["parameters"] = {"power": list(range(60))}
    with pytest.raises(PlatformError) as exc:
        expand_candidates(search)
    assert exc.value.code == "SEARCH_TOO_LARGE"

    search["parameters"] = {"power": []}
    with pytest.raises(PlatformError) as exc:
        expand_candidates(search)
    assert exc.value.code == "SEARCH_TOO_LARGE"


def test_manual_idw_run_succeeds_with_predictions_and_metrics(tmp_path):
    from geomodeling.modeling.runner import execute_run

    runtime = make_runtime(tmp_path)
    target, frame = make_standardized(runtime, "c1", "ds1")
    experiment_id = insert_experiment(runtime, "c1", "ds1", dict(SEARCH_IDW_MANUAL))
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"

    candidates = load_candidates(runtime, run_id)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["status"] == "succeeded"
    metrics = candidate["metrics"]
    assert metrics["rmse"] >= 0
    assert metrics["mae"] >= 0
    assert metrics["coverage"] > 0.9
    assert metrics["n_valid"] > 0
    assert metrics["runtime_seconds"] >= 0
    assert Path(candidate["predictions_path"]).exists()
    predictions = pd.read_parquet(candidate["predictions_path"])
    assert set(predictions.columns) >= {"source_row", "truth", "prediction", "is_nodata", "fold"}
    assert predictions["is_nodata"].sum() == 0


def test_partial_candidate_failure_keeps_others(tmp_path):
    from geomodeling.modeling.runner import execute_run

    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")
    search = dict(SEARCH_IDW_MANUAL)
    search["search_mode"] = "grid"
    search["parameters"] = [
        {"power": 2.0, "neighbor_count": 8},
        {"power": -1.0, "neighbor_count": 8},  # 非法参数 → 该候选失败
    ]
    experiment_id = insert_experiment(runtime, "c1", "ds1", search)
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"  # 单候选失败不拖垮整个 run
    candidates = load_candidates(runtime, run_id)
    statuses = {c["params"]["power"]: c["status"] for c in candidates}
    assert statuses[2.0] == "succeeded"
    assert statuses[-1.0] == "failed"
    failed = next(c for c in candidates if c["status"] == "failed")
    assert failed["error"] is not None
    assert failed["error"]["code"]


def test_all_candidates_failed_marks_run_failed(tmp_path):
    from geomodeling.modeling.runner import execute_run

    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")
    search = dict(SEARCH_IDW_MANUAL)
    search["search_mode"] = "grid"
    search["parameters"] = [{"power": -1.0}, {"power": -2.0}]
    experiment_id = insert_experiment(runtime, "c1", "ds1", search)
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "failed"


def test_cancellation_before_first_candidate(tmp_path):
    from geomodeling.modeling.runner import execute_run

    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")
    experiment_id = insert_experiment(runtime, "c1", "ds1", dict(SEARCH_IDW_MANUAL))
    run_id = insert_run(runtime, experiment_id)

    event = threading.Event()
    event.set()
    outcome = execute_run(runtime, run_id, event)
    assert outcome.status == "canceled"
    assert load_candidates(runtime, run_id) == []


def test_common_valid_mask_and_coverage_honesty(tmp_path):
    from geomodeling.modeling.runner import execute_run

    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")
    search = dict(SEARCH_IDW_MANUAL)
    search["search_mode"] = "grid"
    search["parameters"] = [
        {"power": 2.0, "neighbor_count": 8, "search_radius": None},
        {"power": 2.0, "neighbor_count": 8, "search_radius": 40.0},  # 中等半径 → 部分 NoData
    ]
    experiment_id = insert_experiment(runtime, "c1", "ds1", search)
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    with runtime.session() as session:
        run = session.get(tables.Run, run_id)
        metrics = tables.loads_canonical(run.metrics_json)
    public = metrics["public_metrics"]
    candidates = load_candidates(runtime, run_id)
    by_radius = {c["params"]["search_radius"]: c for c in candidates}
    unlimited = by_radius[None]["metrics"]
    limited = by_radius[40.0]["metrics"]
    assert by_radius[None]["status"] == "succeeded"
    assert by_radius[40.0]["status"] == "succeeded"
    # 公共掩膜上两者使用同一 n_valid；覆盖率独立呈现，小半径候选覆盖率更低
    assert unlimited["n_valid"] == limited["n_valid"] == public["n_valid"]
    assert 0 < limited["n_valid"] < 36
    assert limited["coverage"] < 1.0
    assert unlimited["coverage"] == 1.0
    # 公共指标挂在 run 上，字段齐全
    for key in ("rmse", "mae", "r2", "bias", "n_valid", "coverage"):
        assert key in public


def test_zero_common_valid_candidate_cannot_rank(tmp_path):
    from geomodeling.modeling.runner import execute_run

    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")
    search = dict(SEARCH_IDW_MANUAL)
    search["search_mode"] = "grid"
    search["parameters"] = [
        {"power": 2.0, "neighbor_count": 8, "search_radius": None},
        {"power": 2.0, "neighbor_count": 8, "search_radius": 0.001},  # 几乎全覆盖 NoData
    ]
    experiment_id = insert_experiment(runtime, "c1", "ds1", search)
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    candidates = load_candidates(runtime, run_id)
    tiny = next(c for c in candidates if c["params"]["search_radius"] == 0.001)
    assert tiny["status"] == "failed"
    assert tiny["error"]["code"] == "METRICS_EMPTY_COMMON_VALID"


def test_kriging_manual_and_auto_both_run(tmp_path):
    from geomodeling.modeling.runner import execute_run

    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")
    search = dict(SEARCH_IDW_MANUAL)
    search["algorithm"] = "ordinary_kriging"
    search["search_mode"] = "grid"
    search["parameters"] = [
        {"variogram_model": "spherical", "variogram_mode": "auto", "neighbor_count": 8},
        {"variogram_model": "spherical", "variogram_mode": "manual",
         "nugget": 0.0, "sill": 1.0, "range": 100.0, "neighbor_count": 8},
    ]
    experiment_id = insert_experiment(runtime, "c1", "ds1", search)
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    candidates = load_candidates(runtime, run_id)
    assert all(c["status"] == "succeeded" for c in candidates)
    assert any(c["metrics"]["rmse"] >= 0 for c in candidates)
