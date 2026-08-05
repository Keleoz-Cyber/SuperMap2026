"""Task 14: portable end-to-end vertical flow with restart recovery.

Covers: case → upload fixture → mapping → quality gate (confirm warnings if
any) → IDW + Kriging finite searches → public common metrics → formal
selection → Z/X/Y slices → ZIP export → runtime reopen with all resources
still resolvable. Everything stays inside pytest's tmp_path.
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from geomodeling.platform import PlatformRuntime
from test_platform_results import make_client

FIXTURE = Path("demo/platform_demo_3d.csv")

MAPPING_3D = {
    "dimension": "3d",
    "x": "x",
    "y": "y",
    "z": "z",
    "value": "rho",
    "value_name": "电阻率",
    "value_unit": "Ω·m",
    "coordinate_kind": "local_linear",
}

VALIDATION = {"method": "spatial_kfold", "folds": 3, "seed": 7, "holdout_fraction": 0.2}


def wait_run(client: TestClient, run_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/runs/{run_id}").json()
        if body["status"] in ("succeeded", "failed", "canceled"):
            return body
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} 未在 {timeout}s 内到达终态")


def start_experiment(client: TestClient, case_id: str, dataset_id: str, name: str, algorithm: str, parameters: dict) -> str:
    resp = client.post("/api/experiments", json={
        "case_id": case_id,
        "name": name,
        "algorithm": algorithm,
        "dataset_version_id": dataset_id,
        "search_mode": "grid",
        "parameters": parameters,
        "validation": VALIDATION,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_portable_vertical_flow_and_restart_recovery(tmp_path):
    client, runtime = make_client(tmp_path)
    assert FIXTURE.exists()

    # ------------------------------------------------------ case + upload
    case_id = client.post("/api/cases", json={"name": "端到端演示案例"}).json()["id"]
    upload = client.post(
        f"/api/cases/{case_id}/datasets/uploads",
        files={"file": ("platform_demo_3d.csv", FIXTURE.read_bytes(), "application/octet-stream")},
    )
    assert upload.status_code == 201, upload.text
    dataset_id = upload.json()["id"]

    # ------------------------------------------------------ mapping + quality
    assert client.post(f"/api/datasets/{dataset_id}/mapping", json=MAPPING_3D).status_code == 200
    report = client.post(f"/api/datasets/{dataset_id}/validate").json()
    assert report["status"] in ("passed", "warnings"), report
    if report["status"] == "warnings":
        codes = sorted(i["code"] for i in report["issues"] if i["kind"] == "warning")
        confirmed = client.post(
            f"/api/datasets/{dataset_id}/quality/confirm-warnings", json={"issue_codes": codes}
        )
        assert confirmed.status_code == 200, confirmed.text

    # ------------------------------------------------------ IDW + Kriging 有限搜索
    idw_exp = start_experiment(client, case_id, dataset_id, "IDW 网格", "idw", {"power": [1.5, 2.0], "neighbor_count": [8]})
    krg_exp = start_experiment(client, case_id, dataset_id, "Kriging 网格", "ordinary_kriging", {"variogram_model": ["spherical"], "neighbor_count": [8, 16]})

    idw_run = client.post(f"/api/experiments/{idw_exp}/runs").json()["id"]
    krg_run = client.post(f"/api/experiments/{krg_exp}/runs").json()["id"]
    assert wait_run(client, idw_run)["status"] == "succeeded"
    assert wait_run(client, krg_run)["status"] == "succeeded"

    # ------------------------------------------------------ 公共有效指标
    idw_board = client.get(f"/api/experiments/{idw_exp}/candidates").json()
    krg_board = client.get(f"/api/experiments/{krg_exp}/candidates").json()
    assert idw_board["public_metrics"]["common_valid_count"] > 0
    assert krg_board["public_metrics"]["common_valid_count"] > 0
    idw_ok = [c for c in idw_board["candidates"] if c["status"] == "succeeded"]
    krg_ok = [c for c in krg_board["candidates"] if c["status"] == "succeeded"]
    assert len(idw_ok) == 2 and len(krg_ok) == 2
    assert all(c["metrics"]["rmse"] is not None for c in idw_ok + krg_ok)

    # ------------------------------------------------------ 正式选择（最优 IDW 候选）
    best = min(idw_ok, key=lambda c: c["metrics"]["rmse"])
    selection = client.post(
        f"/api/results/{best['id']}/select-formal",
        json={"note": "端到端：公共验证 RMSE 最低", "selected_by": "e2e"},
    )
    assert selection.status_code == 201, selection.text

    # ------------------------------------------------------ 成果与 Z/X/Y 切片
    # v0.6.1（Task 7）：GET 不再隐式物化，先显式 POST materialize
    materialized = client.post(f"/api/results/{best['id']}/materialize")
    assert materialized.status_code in (200, 201), materialized.text
    metadata = client.get(f"/api/results/{best['id']}").json()
    assert metadata["dimension"] == "3d"
    assert len(metadata["shape"]) == 3
    for axis in ("z", "x", "y"):
        slice_body = client.get(f"/api/results/{best['id']}/slices?axis={axis}&index=0")
        assert slice_body.status_code == 200, slice_body.text
        payload = slice_body.json()
        assert payload["fixed_axis"] == axis
        assert isinstance(payload["fixed_coordinate"], (int, float))
        assert payload["matrix"] and payload["matrix"][0]

    # ------------------------------------------------------ 证据导出
    export = client.post(f"/api/results/{best['id']}/exports")
    assert export.status_code == 201, export.text
    export_id = export.json()["id"]
    assert "manifest.json" in export.json()["files"]
    assert "grid.csv" in export.json()["files"]
    download = client.get(f"/api/exports/{export_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"

    # ------------------------------------------------------ 重启恢复
    runtime.close()
    reopened = PlatformRuntime(tmp_path / "runtime")
    reopened.initialize()
    assert reopened.recover_interrupted_runs() == 0  # 全部终态，无误标
    client.app.state.platform_runtime = reopened  # type: ignore[union-attr]

    assert client.get(f"/api/cases/{case_id}").status_code == 200
    datasets = client.get(f"/api/cases/{case_id}/datasets").json()["datasets"]
    assert [d["id"] for d in datasets] == [dataset_id]
    assert client.get(f"/api/experiments/{idw_exp}").status_code == 200
    assert client.get(f"/api/runs/{idw_run}").json()["status"] == "succeeded"
    board_after = client.get(f"/api/experiments/{idw_exp}/candidates").json()
    assert len(board_after["candidates"]) == 2
    metadata_after = client.get(f"/api/results/{best['id']}").json()
    assert metadata_after["grid_sha256"] == metadata["grid_sha256"]
    selections = client.get(f"/api/cases/{case_id}/formal-selections").json()["selections"]
    assert len(selections) == 1
    assert client.get(f"/api/exports/{export_id}/download").status_code == 200

    # 所有工件都在受控运行时目录内
    assert (tmp_path / "runtime").exists()
    reopened.close()
