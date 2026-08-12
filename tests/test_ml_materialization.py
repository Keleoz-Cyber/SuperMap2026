from __future__ import annotations

import threading

import numpy as np

from geomodeling.modeling.runner import execute_run
from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.ml_artifacts import load_ml_field, read_ml_fields_manifest
from geomodeling.platform.results import load_grid, materialize
from test_ml_runner import _prepare


def _run_candidate(runtime: PlatformRuntime, algorithm: str, parameters: dict) -> str:
    run_id = _prepare(runtime, algorithm, parameters)
    assert execute_run(runtime, run_id, threading.Event()).status == "succeeded"
    with runtime.session() as session:
        return session.query(tables.CandidateResult).filter_by(run_id=run_id).one().id


def test_random_forest_materialization_writes_bound_dispersion_field(tmp_path):
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    result_id = _run_candidate(
        runtime,
        "random_forest_spatial",
        {"n_estimators": 40, "max_depth": 12, "random_state": 13},
    )

    metadata = materialize(runtime, result_id)
    grid = load_grid(runtime, result_id)
    manifest = read_ml_fields_manifest(
        runtime.settings.result_grid(result_id).parent,
        expected_grid_sha256=metadata["grid_sha256"],
    )
    dispersion, nodata = load_ml_field(
        runtime.settings.result_grid(result_id).parent,
        "model_dispersion",
        expected_grid_sha256=metadata["grid_sha256"],
    )

    assert list(metadata["ml_fields"]) == ["model_dispersion"]
    assert manifest["algorithm"] == "random_forest_spatial"
    assert dispersion.shape == grid.values.shape
    assert np.array_equal(nodata, grid.is_nodata)
    assert np.nanmin(dispersion) >= 0
    assert materialize(runtime, result_id)["grid_sha256"] == metadata["grid_sha256"]


def test_residual_materialization_writes_baseline_correction_and_dispersion(tmp_path):
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    result_id = _run_candidate(
        runtime,
        "kriging_rf_residual",
        {
            "kriging": {"variogram_model": "spherical", "neighbor_count": 12},
            "random_forest": {"n_estimators": 40, "max_depth": 10, "random_state": 17},
        },
    )

    metadata = materialize(runtime, result_id)
    grid = load_grid(runtime, result_id)
    directory = runtime.settings.result_grid(result_id).parent
    baseline, baseline_nodata = load_ml_field(
        directory, "kriging_baseline", expected_grid_sha256=metadata["grid_sha256"]
    )
    correction, correction_nodata = load_ml_field(
        directory, "residual_correction", expected_grid_sha256=metadata["grid_sha256"]
    )
    dispersion, _ = load_ml_field(
        directory, "model_dispersion", expected_grid_sha256=metadata["grid_sha256"]
    )

    assert set(metadata["ml_fields"]) == {
        "model_dispersion",
        "kriging_baseline",
        "residual_correction",
    }
    usable = ~(grid.is_nodata | baseline_nodata | correction_nodata)
    assert np.allclose(grid.values[usable], baseline[usable] + correction[usable])
    assert dispersion.shape == grid.values.shape

