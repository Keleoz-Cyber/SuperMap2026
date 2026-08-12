from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from geomodeling.modeling.runner import execute_run
from geomodeling.platform import tables
from geomodeling.platform.render_assets import resolve_candidate_render_source
from test_ml_runner import _prepare
from test_rendering_api import assert_envelope, make_app
from test_slice_exports import _png


def _materialized_ml_candidate(runtime, algorithm: str, parameters: dict) -> str:
    run_id = _prepare(runtime, algorithm, parameters)
    assert execute_run(runtime, run_id, threading.Event()).status == "succeeded"
    with runtime.session() as session:
        result_id = (
            session.query(tables.CandidateResult).filter_by(run_id=run_id).one().id
        )
    return result_id


def test_ml_render_sources_have_field_specific_identity(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        result_id = _materialized_ml_candidate(
            runtime,
            "kriging_rf_residual",
            {
                "kriging": {"variogram_model": "spherical", "neighbor_count": 12},
                "random_forest": {
                    "n_estimators": 40,
                    "max_depth": 10,
                    "random_state": 17,
                },
            },
        )

        prediction = client.post(
            f"/api/results/{result_id}/render-assets/netcdf",
            params={"field": "prediction"},
        )
        dispersion = client.post(
            f"/api/results/{result_id}/render-assets/netcdf",
            params={"field": "model_dispersion"},
        )
        correction = client.post(
            f"/api/results/{result_id}/render-assets/netcdf",
            params={"field": "residual_correction"},
        )

        assert prediction.status_code == 201, prediction.text
        assert dispersion.status_code == 201, dispersion.text
        assert correction.status_code == 201, correction.text
        prediction_body = prediction.json()
        dispersion_body = dispersion.json()
        correction_body = correction.json()
        assert prediction_body["source_id"] == result_id
        assert dispersion_body["source_id"] == f"{result_id}::model_dispersion"
        assert correction_body["source_id"] == f"{result_id}::residual_correction"
        assert (
            len(
                {
                    prediction_body["id"],
                    dispersion_body["id"],
                    correction_body["id"],
                }
            )
            == 3
        )
        assert (
            len(
                {
                    prediction_body["grid_sha256"],
                    dispersion_body["grid_sha256"],
                    correction_body["grid_sha256"],
                }
            )
            == 3
        )

        manifest = client.get(dispersion_body["manifest_url"]).json()
        assert manifest["source_id"] == f"{result_id}::model_dispersion"
        assert manifest["field"] == "model_dispersion"
        assert manifest["property_name"].endswith("模型离散度")
        assert manifest["palette_intent"] == "sequential_nonnegative"

        source = resolve_candidate_render_source(
            runtime, result_id, field="model_dispersion"
        )
        assert source.candidate_result_id == result_id
        assert source.field_name == "model_dispersion"


def test_ml_render_field_status_slice_and_export_keep_candidate_provenance(
    tmp_path, monkeypatch
):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        result_id = _materialized_ml_candidate(
            runtime,
            "random_forest_spatial",
            {"n_estimators": 40, "max_depth": 12, "random_state": 13},
        )
        created = client.post(
            f"/api/results/{result_id}/render-assets/netcdf",
            params={"field": "model_dispersion"},
        )
        assert created.status_code == 201, created.text
        asset = created.json()

        status = client.get(
            f"/api/results/{result_id}/render-assets/netcdf",
            params={"field": "model_dispersion"},
        )
        assert status.status_code == 200, status.text
        assert status.json()["id"] == asset["id"]

        analysis = client.get(
            f"/api/render-assets/{asset['id']}/slice-analysis",
            params={"axis": "z", "index": 0},
        )
        assert analysis.status_code == 200, analysis.text
        body = analysis.json()
        assert body["asset_identity"]["source_id"] == (f"{result_id}::model_dispersion")
        assert body["asset_identity"]["candidate_result_id"] == result_id
        assert body["asset_identity"]["field"] == "model_dispersion"
        assert body["render_profile"]["default_palette"] != "diverging"

        exported = client.post(
            f"/api/render-assets/{asset['id']}/slice-exports",
            files={
                "axis": (None, "z"),
                "index": (None, "0"),
                "image": ("slice.png", _png(), "image/png"),
            },
        )
        assert exported.status_code == 201, exported.text
        assert exported.json()["candidate_result_id"] == result_id


def test_ml_render_field_rejects_unknown_and_unavailable_fields(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        result_id = _materialized_ml_candidate(
            runtime,
            "random_forest_spatial",
            {"n_estimators": 40, "max_depth": 12, "random_state": 13},
        )

        assert_envelope(
            client.post(
                f"/api/results/{result_id}/render-assets/netcdf",
                params={"field": "kriging_baseline"},
            ),
            409,
            "ML_FIELD_NOT_AVAILABLE",
        )
        assert_envelope(
            client.post(
                f"/api/results/{result_id}/render-assets/netcdf",
                params={"field": "made_up"},
            ),
            422,
            "ML_FIELD_NOT_AVAILABLE",
        )


def test_default_render_asset_remains_prediction_compatible(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        runtime = app.state.platform_runtime
        result_id = _materialized_ml_candidate(
            runtime,
            "random_forest_spatial",
            {"n_estimators": 40, "max_depth": 12, "random_state": 13},
        )

        default = client.post(f"/api/results/{result_id}/render-assets/netcdf")
        explicit = client.post(
            f"/api/results/{result_id}/render-assets/netcdf",
            params={"field": "prediction"},
        )
        assert default.status_code == 201, default.text
        assert explicit.status_code == 200, explicit.text
        assert default.json() == explicit.json()
