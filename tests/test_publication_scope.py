"""Merge-blocker 5: exports belong to their result; publications never
reuse another result's package."""

from __future__ import annotations

import time

from geomodeling.platform import tables
from test_platform_results import make_client, prepare_completed_run


def _wait_run(client, run_id: str) -> str:
    deadline = time.time() + 30
    while time.time() < deadline:
        body = client.get(f"/api/runs/{run_id}").json()
        if body["status"] in ("succeeded", "failed"):
            return body["status"]
        time.sleep(0.1)
    raise AssertionError("run 未到达终态")


def test_export_persists_candidate_and_publication_scopes_by_result(tmp_path):
    client, runtime = make_client(tmp_path)
    case_id, dataset_id, _, candidate_a = prepare_completed_run(client)

    # 同案例第二个实验 → 另一个成果 B
    resp = client.post("/api/experiments", json={
        "case_id": case_id,
        "name": "第二实验",
        "algorithm": "idw",
        "dataset_version_id": dataset_id,
        "search_mode": "manual",
        "parameters": {"power": 3.0, "neighbor_count": 6},
        "validation": {"method": "spatial_kfold", "folds": 3, "seed": 2, "holdout_fraction": 0.2},
    })
    exp_b = resp.json()["id"]
    run_b = client.post(f"/api/experiments/{exp_b}/runs").json()["id"]
    assert _wait_run(client, run_b) == "succeeded"
    candidate_b = next(
        c["id"]
        for c in client.get(f"/api/experiments/{exp_b}/candidates").json()["candidates"]
        if c["status"] == "succeeded"
    )

    # 只导出 A；为 B 请求发布 → 必须构建 B 自己的导出，不能复用 A 的
    assert client.get(f"/api/results/{candidate_a}").status_code == 200
    assert client.get(f"/api/results/{candidate_b}").status_code == 200
    export_a = client.post(f"/api/results/{candidate_a}/exports").json()
    with runtime.session() as session:
        row_a = session.get(tables.Export, export_a["id"])
        assert row_a.candidate_result_id == candidate_a  # 持久化归属

    publication_b = client.post(f"/api/results/{candidate_b}/publications").json()
    assert publication_b["export_id"] != export_a["id"]
    with runtime.session() as session:
        row_b = session.get(tables.Export, publication_b["export_id"])
        assert row_b.candidate_result_id == candidate_b

    # 再次为 B 发布 → 复用 B 自己的导出（幂等），A 的不受影响
    again_b = client.post(f"/api/results/{candidate_b}/publications").json()
    assert again_b["export_id"] == publication_b["export_id"]
