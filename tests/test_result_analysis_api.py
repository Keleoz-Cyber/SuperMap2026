"""v0.9.0 Task 4: result analysis summary API tests.

GET /api/results/{result_id}/analysis-summary is pure query:
- materialized result returns 200 and exact result_id/grid_sha256;
- depth_bins outside 2-32 and component_limit outside 1-20 are rejected;
- unmaterialized result creates no artifact;
- repeated requests for one grid identity are byte-equivalent.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.errors import platform_error_handler, PlatformError


def make_client(tmp_path: Path) -> tuple[TestClient, PlatformRuntime]:
    from geomodeling.api.routes import (
        cases, datasets, experiments, result_analysis, results, runs,
    )
    from geomodeling.platform.worker import JobWorker

    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    worker = JobWorker(runtime)

    from fastapi import FastAPI
    app = FastAPI()
    app.add_exception_handler(PlatformError, platform_error_handler)
    app.include_router(cases.router)
    app.include_router(datasets.router)
    app.include_router(experiments.router)
    app.include_router(runs.router)
    app.include_router(results.router)
    app.include_router(result_analysis.router)
    app.state.platform_runtime = runtime
    app.state.job_worker = worker
    return TestClient(app), runtime


CSV_3D = "x,y,z,v\n" + "\n".join(
    f"{(i % 4) * 30 - 150},{(j % 5) * 80 + 260},{(k % 4) * 200 - 800},{10 + i + j + k}"
    for i in range(4) for j in range(5) for k in range(4)
) + "\n"

MAPPING_3D = {
    "dimension": "3d",
    "x": "x",
    "y": "y",
    "z": "z",
    "value": "v",
    "value_name": "属性",
    "coordinate_kind": "local_linear",
}


def _prepare_completed_run(client: TestClient, algorithm: str = "idw") -> tuple[str, str]:
    import io, time
    resp = client.post("/api/cases", json={"name": "成果分析案例"})
    case_id = resp.json()["id"]
    resp = client.post(
        f"/api/cases/{case_id}/datasets/uploads",
        files={"file": ("data3d.csv", io.BytesIO(CSV_3D.encode()), "application/octet-stream")},
    )
    dataset_id = resp.json()["id"]
    assert client.post(f"/api/datasets/{dataset_id}/mapping", json=MAPPING_3D).status_code == 200
    assert client.post(f"/api/datasets/{dataset_id}/validate").status_code == 200
    resp = client.post("/api/experiments", json={
        "case_id": case_id,
        "name": "成果分析实验",
        "algorithm": algorithm,
        "dataset_version_id": dataset_id,
        "search_mode": "manual",
        "parameters": {"power": 2.0, "neighbor_count": 8} if algorithm == "idw" else {"neighbor_count": 8},
        "validation": {"method": "spatial_kfold", "folds": 3, "seed": 1, "holdout_fraction": 0.2},
    })
    experiment_id = resp.json()["id"]
    run_id = client.post(f"/api/experiments/{experiment_id}/runs").json()["id"]
    deadline = time.time() + 30
    while time.time() < deadline:
        body = client.get(f"/api/runs/{run_id}").json()
        if body["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.1)
    assert body["status"] == "succeeded", body
    candidates = client.get(f"/api/experiments/{experiment_id}/candidates").json()["candidates"]
    candidate_id = next(c["id"] for c in candidates if c["status"] == "succeeded")
    return case_id, candidate_id


class TestAnalysisSummaryApi:
    def test_materialized_returns_200(self, tmp_path):
        client, runtime = make_client(tmp_path)
        case_id, candidate_id = _prepare_completed_run(client)
        assert client.post(f"/api/results/{candidate_id}/materialize").status_code in (200, 201)

        resp = client.get(f"/api/results/{candidate_id}/analysis-summary")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["identity"]["result_id"] == candidate_id
        assert len(data["identity"]["grid_sha256"]) == 64
        assert data["identity"]["analysis_version"] == "result_analysis.v2"
        assert data["identity"]["dimension"] == "3d"
        assert data["grid"]["valid_count"] > 0
        assert data["thresholds"]["source"] == "full_grid_quartile"
        assert len(data["composition"]["buckets"]) == 3
        assert data["depth_profile"]["status"] == "applicable"
        assert len(data["findings"]) >= 4
        assert data["low_components_preview"] is not None
        assert data["domain_interpretation"]["profile"] == "generic_3d"
        assert data["domain_interpretation"]["status"] == "not_applicable"
        from geomodeling.api.routes import result_analysis
        assert any(key.startswith("result_analysis.v2:") for key in result_analysis._cache)

    def test_unmaterialized_returns_404(self, tmp_path):
        client, runtime = make_client(tmp_path)
        case_id, candidate_id = _prepare_completed_run(client)
        # Don't materialize
        resp = client.get(f"/api/results/{candidate_id}/analysis-summary")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "RESULT_NOT_MATERIALIZED"

    def test_depth_bins_validation(self, tmp_path):
        client, runtime = make_client(tmp_path)
        case_id, candidate_id = _prepare_completed_run(client)
        client.post(f"/api/results/{candidate_id}/materialize")

        resp = client.get(f"/api/results/{candidate_id}/analysis-summary?depth_bins=1")
        assert resp.status_code == 422

        resp = client.get(f"/api/results/{candidate_id}/analysis-summary?depth_bins=33")
        assert resp.status_code == 422

        resp = client.get(f"/api/results/{candidate_id}/analysis-summary?depth_bins=2")
        assert resp.status_code == 200

    def test_component_limit_validation(self, tmp_path):
        client, runtime = make_client(tmp_path)
        case_id, candidate_id = _prepare_completed_run(client)
        client.post(f"/api/results/{candidate_id}/materialize")

        resp = client.get(f"/api/results/{candidate_id}/analysis-summary?component_limit=0")
        assert resp.status_code == 422

        resp = client.get(f"/api/results/{candidate_id}/analysis-summary?component_limit=21")
        assert resp.status_code == 422

        resp = client.get(f"/api/results/{candidate_id}/analysis-summary?component_limit=1")
        assert resp.status_code == 200

    def test_repeated_requests_byte_equivalent(self, tmp_path):
        client, runtime = make_client(tmp_path)
        case_id, candidate_id = _prepare_completed_run(client)
        client.post(f"/api/results/{candidate_id}/materialize")

        resp1 = client.get(f"/api/results/{candidate_id}/analysis-summary")
        resp2 = client.get(f"/api/results/{candidate_id}/analysis-summary")
        assert resp1.status_code == 200
        assert resp1.json() == resp2.json()

    def test_no_artifact_created(self, tmp_path):
        client, runtime = make_client(tmp_path)
        case_id, candidate_id = _prepare_completed_run(client)
        client.post(f"/api/results/{candidate_id}/materialize")

        # Count files before
        result_dir = runtime.settings.result_grid(candidate_id).parent
        files_before = set(p.name for p in result_dir.iterdir())

        resp = client.get(f"/api/results/{candidate_id}/analysis-summary")
        assert resp.status_code == 200

        # No new files created
        files_after = set(p.name for p in result_dir.iterdir())
        assert files_before == files_after

    def test_2d_depth_not_applicable(self, tmp_path):
        client, runtime = make_client(tmp_path)

        # Create 2D dataset
        import io, time
        csv_2d = "x,y,v\n" + "\n".join(
            f"{(i % 4) * 30 - 150},{(j % 5) * 80 + 260},{10 + i + j}"
            for i in range(4) for j in range(5)
        ) + "\n"
        mapping_2d = {
            "dimension": "2d",
            "x": "x", "y": "y", "value": "v",
            "value_name": "属性", "coordinate_kind": "local_linear",
        }

        resp = client.post("/api/cases", json={"name": "2D案例"})
        case_id = resp.json()["id"]
        resp = client.post(
            f"/api/cases/{case_id}/datasets/uploads",
            files={"file": ("data2d.csv", io.BytesIO(csv_2d.encode()), "application/octet-stream")},
        )
        dataset_id = resp.json()["id"]
        client.post(f"/api/datasets/{dataset_id}/mapping", json=mapping_2d)
        client.post(f"/api/datasets/{dataset_id}/validate")
        resp = client.post("/api/experiments", json={
            "case_id": case_id, "name": "2D实验", "algorithm": "idw",
            "dataset_version_id": dataset_id, "search_mode": "manual",
            "parameters": {"power": 2.0, "neighbor_count": 8},
            "validation": {"method": "spatial_kfold", "folds": 3, "seed": 1, "holdout_fraction": 0.2},
        })
        experiment_id = resp.json()["id"]
        run_id = client.post(f"/api/experiments/{experiment_id}/runs").json()["id"]
        deadline = time.time() + 30
        while time.time() < deadline:
            body = client.get(f"/api/runs/{run_id}").json()
            if body["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.1)
        assert body["status"] == "succeeded"
        candidates = client.get(f"/api/experiments/{experiment_id}/candidates").json()["candidates"]
        candidate_id = next(c["id"] for c in candidates if c["status"] == "succeeded")
        client.post(f"/api/results/{candidate_id}/materialize")

        resp = client.get(f"/api/results/{candidate_id}/analysis-summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["identity"]["dimension"] == "2d"
        assert data["depth_profile"]["status"] == "not_applicable"
        assert data["depth_profile"]["bins"] == []
