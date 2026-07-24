"""Task 8 API tests: experiment/run endpoints with quality gating and lifecycle."""

from __future__ import annotations

import io
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from geomodeling.platform import PlatformRuntime
from geomodeling.platform.errors import platform_error_handler, PlatformError

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def make_client(tmp_path: Path) -> tuple[TestClient, PlatformRuntime]:
    from geomodeling.api.routes import cases, datasets, experiments, runs
    from geomodeling.platform.worker import JobWorker

    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    worker = JobWorker(runtime)

    app = FastAPI()
    app.add_exception_handler(PlatformError, platform_error_handler)
    app.include_router(cases.router)
    app.include_router(datasets.router)
    app.include_router(experiments.router)
    app.include_router(runs.router)
    app.state.platform_runtime = runtime
    app.state.job_worker = worker
    client = TestClient(app)
    yield_client = client
    yield_client._worker = worker  # type: ignore[attr-defined]
    return yield_client, runtime


CSV_2D = "x,y,v\n" + "\n".join(
    f"{(i % 6) * 15},{(i // 6) * 20},{10 + (i % 7)}" for i in range(24)
) + "\n"

MAPPING_2D = {
    "dimension": "2d",
    "x": "x",
    "y": "y",
    "value": "v",
    "value_name": "属性",
    "coordinate_kind": "local_linear",
}


def prepare_dataset(client: TestClient, csv_text: str = CSV_2D, mapping: dict = MAPPING_2D) -> tuple[str, str]:
    resp = client.post("/api/cases", json={"name": "API 实验案例"})
    assert resp.status_code == 201
    case_id = resp.json()["id"]
    resp = client.post(
        f"/api/cases/{case_id}/datasets/uploads",
        files={"file": ("data.csv", io.BytesIO(csv_text.encode()), "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    dataset_id = resp.json()["id"]
    resp = client.post(f"/api/datasets/{dataset_id}/mapping", json=mapping)
    assert resp.status_code == 200, resp.text
    return case_id, dataset_id


def wait_run(client: TestClient, run_id: str, terminal: set[str], timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/runs/{run_id}")
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] in terminal:
            return body
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} 未到达终态 {terminal}")


def test_create_experiment_requires_quality_gate(tmp_path):
    client, _ = make_client(tmp_path)
    case_id, dataset_id = prepare_dataset(client)

    # 未 validate → 拒绝
    resp = client.post("/api/experiments", json={
        "case_id": case_id,
        "name": "手动 IDW",
        "algorithm": "idw",
        "dataset_version_id": dataset_id,
        "search_mode": "manual",
        "parameters": {"power": 2.0, "neighbor_count": 8},
        "validation": {"method": "spatial_kfold", "folds": 3, "seed": 1, "holdout_fraction": 0.2},
    })
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "QUALITY_GATE_FAILED"

    # validate 后 → 201
    assert client.post(f"/api/datasets/{dataset_id}/validate").status_code == 200
    resp = client.post("/api/experiments", json={
        "case_id": case_id,
        "name": "手动 IDW",
        "algorithm": "idw",
        "dataset_version_id": dataset_id,
        "search_mode": "manual",
        "parameters": {"power": 2.0, "neighbor_count": 8},
        "validation": {"method": "spatial_kfold", "folds": 3, "seed": 1, "holdout_fraction": 0.2},
    })
    assert resp.status_code == 201, resp.text
    experiment = resp.json()
    assert experiment["params"]["algorithm"] == "idw"


def test_create_experiment_requires_warning_confirmation(tmp_path):
    client, _ = make_client(tmp_path)
    # 含精确重复行 → DUPLICATE_ROWS 警告
    csv_text = CSV_2D + "0,0,10\n"
    case_id, dataset_id = prepare_dataset(client, csv_text=csv_text)
    assert client.post(f"/api/datasets/{dataset_id}/validate").status_code == 200

    resp = client.post("/api/experiments", json={
        "case_id": case_id,
        "name": "未确认警告",
        "algorithm": "idw",
        "dataset_version_id": dataset_id,
        "search_mode": "manual",
        "parameters": {"power": 2.0},
    })
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "QUALITY_GATE_FAILED"

    # 确认警告后 → 201
    quality = client.get(f"/api/datasets/{dataset_id}/quality").json()
    codes = sorted({i["code"] for i in quality["issues"] if i["kind"] == "warning"})
    resp = client.post(
        f"/api/datasets/{dataset_id}/quality/confirm-warnings",
        json={"issue_codes": codes},
    )
    assert resp.status_code == 200
    resp = client.post("/api/experiments", json={
        "case_id": case_id,
        "name": "已确认警告",
        "algorithm": "idw",
        "dataset_version_id": dataset_id,
        "search_mode": "manual",
        "parameters": {"power": 2.0},
    })
    assert resp.status_code == 201


def test_run_lifecycle_via_api(tmp_path):
    client, _ = make_client(tmp_path)
    case_id, dataset_id = prepare_dataset(client)
    assert client.post(f"/api/datasets/{dataset_id}/validate").status_code == 200

    resp = client.post("/api/experiments", json={
        "case_id": case_id,
        "name": "网格搜索",
        "algorithm": "idw",
        "dataset_version_id": dataset_id,
        "search_mode": "grid",
        "parameters": {"power": [1.0, 2.0], "neighbor_count": [6, 12]},
        "validation": {"method": "spatial_kfold", "folds": 3, "seed": 5, "holdout_fraction": 0.2},
    })
    assert resp.status_code == 201, resp.text
    experiment_id = resp.json()["id"]

    resp = client.post(f"/api/experiments/{experiment_id}/runs")
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]

    # 重复创建第二个活动 run → 409
    resp = client.post(f"/api/experiments/{experiment_id}/runs")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "RUN_ALREADY_ACTIVE"

    body = wait_run(client, run_id, {"succeeded", "failed"})
    assert body["status"] == "succeeded"
    assert body["metrics"]["total"] == 4
    assert body["metrics"]["completed"] == 4
    assert body["metrics"]["failed"] == 0

    resp = client.get(f"/api/experiments/{experiment_id}/candidates")
    assert resp.status_code == 200
    candidates = resp.json()["candidates"]
    assert len(candidates) == 4
    assert all(c["status"] == "succeeded" for c in candidates)
    assert all("rmse" in c["metrics"] and "coverage" in c["metrics"] for c in candidates)
    assert resp.json()["public_metrics"]["n_valid"] > 0


def test_cancel_and_retry_via_api(tmp_path):
    client, _ = make_client(tmp_path)
    case_id, dataset_id = prepare_dataset(client)
    assert client.post(f"/api/datasets/{dataset_id}/validate").status_code == 200

    resp = client.post("/api/experiments", json={
        "case_id": case_id,
        "name": "可取消实验",
        "algorithm": "idw",
        "dataset_version_id": dataset_id,
        "search_mode": "grid",
        "parameters": {"power": [1.0, 2.0, 3.0], "neighbor_count": [6, 12, 18]},
        "validation": {"method": "spatial_kfold", "folds": 3, "seed": 1, "holdout_fraction": 0.2},
    })
    experiment_id = resp.json()["id"]
    run_id = client.post(f"/api/experiments/{experiment_id}/runs").json()["id"]

    resp = client.post(f"/api/runs/{run_id}/cancel")
    assert resp.status_code == 200
    body = wait_run(client, run_id, {"canceled", "succeeded", "failed"})
    assert body["status"] == "canceled"

    # canceled 可以重试
    resp = client.post(f"/api/runs/{run_id}/retry")
    assert resp.status_code == 201, resp.text
    retry_id = resp.json()["id"]
    assert resp.json()["retry_of_run_id"] == run_id
    body = wait_run(client, retry_id, {"succeeded", "failed"})
    assert body["status"] == "succeeded"

    # 成功 run 不可重试
    resp = client.post(f"/api/runs/{retry_id}/retry")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "RUN_NOT_RETRYABLE"


def test_interrupted_run_visible_and_retryable(tmp_path):
    client, runtime = make_client(tmp_path)
    case_id, dataset_id = prepare_dataset(client)
    assert client.post(f"/api/datasets/{dataset_id}/validate").status_code == 200

    resp = client.post("/api/experiments", json={
        "case_id": case_id,
        "name": "恢复实验",
        "algorithm": "idw",
        "dataset_version_id": dataset_id,
        "search_mode": "manual",
        "parameters": {"power": 2.0},
    })
    experiment_id = resp.json()["id"]
    run_id = client.post(f"/api/experiments/{experiment_id}/runs").json()["id"]

    # 模拟进程重启：在途 run 标记为 interrupted
    runtime.recover_interrupted_runs()
    body = client.get(f"/api/runs/{run_id}").json()
    assert body["status"] == "interrupted"
    assert body["error_code"] == "PROCESS_RESTARTED"

    resp = client.post(f"/api/runs/{run_id}/retry")
    assert resp.status_code == 201
    retry_id = resp.json()["id"]
    body = wait_run(client, retry_id, {"succeeded", "failed"})
    assert body["status"] == "succeeded"
