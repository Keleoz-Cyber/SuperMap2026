"""Task 9 platform tests: result materialization, slices, formal selection, exports."""

from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.errors import platform_error_handler, PlatformError


def make_client(tmp_path: Path) -> tuple[TestClient, PlatformRuntime]:
    from geomodeling.api.routes import cases, datasets, experiments, results, runs
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
    app.include_router(results.router)
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


def prepare_completed_run(client: TestClient, algorithm: str = "idw") -> tuple[str, str, str, str]:
    resp = client.post("/api/cases", json={"name": "成果案例"})
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
        "name": "成果实验",
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
    return case_id, dataset_id, experiment_id, candidate_id


def test_materialize_result_writes_grid_and_metadata(tmp_path):
    client, runtime = make_client(tmp_path)
    case_id, dataset_id, experiment_id, candidate_id = prepare_completed_run(client)

    resp = client.post(f"/api/results/{candidate_id}/materialize")
    assert resp.status_code in (200, 201), resp.text
    result = resp.json()
    assert result["dimension"] == "3d"
    assert result["shape"] == [11, 11, 11]
    assert result["bounds"] == [[-150.0, -60.0], [260.0, 580.0], [-800.0, -200.0]]
    assert result["algorithm"] == "idw"
    assert result["parameters"]["power"] == 2.0
    assert result["dataset_version_id"] == dataset_id
    assert len(result["grid_sha256"]) == 64
    assert result["value_range"][0] < result["value_range"][1]

    grid_path = runtime.settings.result_grid(candidate_id)
    assert grid_path.exists()
    bundle = np.load(grid_path)
    assert bundle["values"].shape == (11, 11, 11)
    assert bundle["is_nodata"].shape == (11, 11, 11)
    metadata = json.loads((grid_path.parent / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["algorithm"] == "idw"
    assert metadata["dataset_version_id"] == dataset_id
    assert metadata["source_sha256"]

    # 幂等：重复 materialize 返回同一成果
    again = client.post(f"/api/results/{candidate_id}/materialize")
    assert again.status_code == 200
    assert again.json()["grid_sha256"] == result["grid_sha256"]


def test_result_metadata_and_preview(tmp_path):
    client, _ = make_client(tmp_path)
    _, dataset_id, _, candidate_id = prepare_completed_run(client)
    client.post(f"/api/results/{candidate_id}/materialize")

    resp = client.get(f"/api/results/{candidate_id}")
    assert resp.status_code == 200
    meta = resp.json()
    assert meta["dimension"] == "3d"
    assert meta["cell_count"] == 11 ** 3
    assert meta["dataset_version_id"] == dataset_id

    resp = client.get(f"/api/results/{candidate_id}/preview")
    assert resp.status_code == 200
    preview = resp.json()
    assert preview["original_cell_count"] == 11 ** 3
    assert preview["served_cell_count"] <= 50_000
    assert preview["served_cell_count"] == 11 ** 3
    assert len(preview["x"]) == preview["served_cell_count"]
    assert len(preview["values"]) == preview["served_cell_count"]


def test_result_slices_xyz_with_real_coordinates(tmp_path):
    client, _ = make_client(tmp_path)
    _, _, _, candidate_id = prepare_completed_run(client)
    client.post(f"/api/results/{candidate_id}/materialize")

    resp = client.get(f"/api/results/{candidate_id}/slices?axis=z&index=5")
    assert resp.status_code == 200, resp.text
    zslice = resp.json()
    assert zslice["fixed_axis"] == "z"
    assert zslice["fixed_coordinate"] == pytest.approx(-500.0)
    assert zslice["axes_names"] == ["x", "y"]
    assert len(zslice["matrix"]) == 11
    assert len(zslice["matrix"][0]) == 11
    assert zslice["value_range"][0] <= zslice["value_range"][1]

    resp = client.get(f"/api/results/{candidate_id}/slices?axis=x&index=2")
    assert resp.status_code == 200
    xslice = resp.json()
    assert xslice["fixed_axis"] == "x"
    assert xslice["fixed_coordinate"] == pytest.approx(-132.0)
    assert xslice["axes_names"] == ["y", "z"]

    resp = client.get(f"/api/results/{candidate_id}/slices?axis=y&index=3")
    assert resp.status_code == 200
    yslice = resp.json()
    assert yslice["fixed_axis"] == "y"
    assert yslice["axes_names"] == ["x", "z"]

    resp = client.get(f"/api/results/{candidate_id}/slices?axis=z&index=99")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "SLICE_INDEX_OUT_OF_RANGE"


def test_formal_selection_requires_reason_and_succeeded_run(tmp_path):
    client, _ = make_client(tmp_path)
    case_id, _, _, candidate_id = prepare_completed_run(client)
    client.post(f"/api/results/{candidate_id}/materialize")

    # 无理由 → 拒绝
    resp = client.post(
        f"/api/results/{candidate_id}/select-formal",
        json={"note": ""},
    )
    assert resp.status_code == 422

    resp = client.post(
        f"/api/results/{candidate_id}/select-formal",
        json={"note": "公共验证 RMSE 最低且覆盖率最高", "selected_by": "tester"},
    )
    assert resp.status_code in (200, 201), resp.text
    selection = resp.json()
    assert selection["candidate_result_id"] == candidate_id
    assert selection["note"].startswith("公共验证")

    # 再次选择产生新记录且不删除历史
    resp = client.post(
        f"/api/results/{candidate_id}/select-formal",
        json={"note": "复核后维持原选择", "selected_by": "tester"},
    )
    assert resp.status_code in (200, 201)
    resp = client.get(f"/api/cases/{case_id}/formal-selections")
    assert resp.status_code == 200
    assert len(resp.json()["selections"]) == 2


def test_select_formal_rejects_candidate_not_succeeded(tmp_path):
    """run succeeded 但候选非 succeeded → 409，且不写 FormalSelection。"""

    client, runtime = make_client(tmp_path)
    _, _, _, candidate_id = prepare_completed_run(client)

    for status in ("failed", "queued"):
        with runtime.session() as session:
            row = session.get(tables.CandidateResult, candidate_id)
            row.status = status
            session.commit()
        resp = client.post(
            f"/api/results/{candidate_id}/select-formal",
            json={"note": "尝试选为正式模型", "selected_by": "tester"},
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["error"]["code"] == "CANDIDATE_NOT_SUCCEEDED"
        assert resp.json()["error"]["details"]["candidate_status"] == status
    with runtime.session() as session:
        assert session.query(tables.FormalSelection).count() == 0


def test_select_formal_rejects_succeeded_candidate_of_failed_run(tmp_path):
    """手工构造：候选 succeeded 但 run failed → 409，且不写 FormalSelection。"""

    client, runtime = make_client(tmp_path)
    _, _, _, candidate_id = prepare_completed_run(client)

    with runtime.session() as session:
        candidate = session.get(tables.CandidateResult, candidate_id)
        run = session.get(tables.Run, candidate.run_id)
        run.status = "failed"
        session.commit()
    resp = client.post(
        f"/api/results/{candidate_id}/select-formal",
        json={"note": "尝试选为正式模型", "selected_by": "tester"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "CANDIDATE_NOT_SUCCEEDED"
    assert resp.json()["error"]["details"]["run_status"] == "failed"
    with runtime.session() as session:
        assert session.query(tables.FormalSelection).count() == 0


def test_publication_records_manual_required_without_iserver(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path)
    _, _, _, candidate_id = prepare_completed_run(client)
    client.post(f"/api/results/{candidate_id}/materialize")
    client.post(
        f"/api/results/{candidate_id}/exports",
    )

    # iServer 不在线（本测试不启动 8090）→ manual_required，绝不伪装已发布
    resp = client.post(f"/api/results/{candidate_id}/publications")
    assert resp.status_code in (200, 201), resp.text
    publication = resp.json()
    assert publication["status"] == "manual_required"
    assert publication["evidence"]["manual_instruction"]
    assert "published" not in publication["status"]


def test_export_zip_contains_full_lineage(tmp_path):
    client, _ = make_client(tmp_path)
    case_id, dataset_id, experiment_id, candidate_id = prepare_completed_run(client)
    client.post(f"/api/results/{candidate_id}/materialize")
    client.post(
        f"/api/results/{candidate_id}/select-formal",
        json={"note": "最优候选", "selected_by": "tester"},
    )

    resp = client.post(f"/api/results/{candidate_id}/exports")
    assert resp.status_code in (200, 201), resp.text
    export = resp.json()
    export_id = export["id"]
    assert export["package_sha256"]
    assert export["file_count"] == 7

    resp = client.get(f"/api/exports/{export_id}/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    bundle = zipfile.ZipFile(io.BytesIO(resp.content))
    # 通用数据集 ZIP 保持七文件不变（回归锁定），无领域证据
    names = set(bundle.namelist())
    assert names == {
        "manifest.json",
        "metadata.json",
        "metrics.json",
        "quality.json",
        "formal_selections.json",
        "failed_evidence.json",
        "grid.csv",
    }

    manifest = json.loads(bundle.read("manifest.json"))
    assert manifest["candidate_result_id"] == candidate_id
    assert manifest["source_sha256"]
    assert manifest["grid_sha256"]
    assert manifest["files"]
    assert "domain_evidence" not in manifest
    # legacy 候选（无专业工件行）：导出无 professional 节（逐位不变锁定）
    assert "professional" not in manifest

    metadata = json.loads(bundle.read("metadata.json"))
    assert metadata["algorithm"] == "idw"
    assert metadata["parameters"]["power"] == 2.0
    assert metadata["validation"]["folds"] == 3
    assert metadata["dataset_version_id"] == dataset_id

    metrics = json.loads(bundle.read("metrics.json"))
    assert metrics["public_metrics"]["common_valid_count"] > 0
    assert metrics["candidate"]["rmse"] is not None

    selections = json.loads(bundle.read("formal_selections.json"))
    assert selections[0]["note"] == "最优候选"


def test_legacy_materialize_has_no_professional_artifacts(tmp_path):
    """legacy 候选物化逐字节兼容：无 professional 文件、metadata 无 professional 键。"""

    client, runtime = make_client(tmp_path)
    _, _, _, candidate_id = prepare_completed_run(client)

    resp = client.post(f"/api/results/{candidate_id}/materialize")
    assert resp.status_code in (200, 201), resp.text
    metadata = resp.json()
    assert "professional" not in metadata
    assert set(metadata) == {
        "result_id", "run_id", "experiment_id", "dataset_version_id", "algorithm",
        "parameters", "dimension", "shape", "cell_count", "bounds", "resolution",
        "value_range", "nodata_count", "grid_sha256", "source_sha256",
        "standardized_sha256", "fingerprint", "validation", "created_at",
        # v0.6.1（Task 4）：新物化成果追加 property 语义三键（取自 profile.mapping）
        "property_name", "units", "coordinate_kind",
    }
    assert metadata["property_name"] == "属性"
    assert metadata["units"] == "unknown"
    assert metadata["coordinate_kind"] == "local_linear"

    professional_dir = runtime.settings.professional_result_dir(candidate_id)
    # Task 9 的 run 级折证据照常落盘，但绝不自动创建任何专业物化文件
    assert sorted(p.name for p in professional_dir.iterdir()) == [
        "fold_assignments.parquet",
        "out_of_fold_predictions.parquet",
    ]

    resp = client.get(f"/api/results/{candidate_id}/preview")
    assert resp.status_code == 200
    assert resp.json()["layer"] == "value"


def test_export_failure_cleans_staging_dir(tmp_path, monkeypatch):
    """任一导出阶段失败：原异常传播，且 export-* 暂存目录不得残留。"""

    client, runtime = make_client(tmp_path)
    _, _, _, candidate_id = prepare_completed_run(client)
    client.post(f"/api/results/{candidate_id}/materialize")

    from geomodeling.platform import exports as exports_module

    def boom(_path):
        raise RuntimeError("injected export failure")

    monkeypatch.setattr(exports_module, "_sha256", boom)
    with pytest.raises(RuntimeError, match="injected export failure"):
        exports_module.build_export(runtime, candidate_id)
    assert list(runtime.settings.exports_dir.rglob("export-*")) == []


def test_export_cleanup_failure_does_not_mask_original_error(tmp_path, monkeypatch, caplog):
    """清理本身失败（如权限拒绝）只能记日志，抛出的仍是原始业务异常。"""

    client, runtime = make_client(tmp_path)
    _, _, _, candidate_id = prepare_completed_run(client)
    client.post(f"/api/results/{candidate_id}/materialize")

    from geomodeling.platform import exports as exports_module

    def boom(_path):
        raise RuntimeError("injected export failure")

    def denied(*_args, **_kwargs):
        raise PermissionError("cleanup denied")

    monkeypatch.setattr(exports_module, "_sha256", boom)
    monkeypatch.setattr(exports_module.shutil, "rmtree", denied)
    with pytest.raises(RuntimeError, match="injected export failure"):
        exports_module.build_export(runtime, candidate_id)
    assert any(
        "export staging cleanup failed" in record.getMessage() and record.exc_info is not None
        for record in caplog.records
    )


def test_result_gets_are_pure_queries_until_materialized(tmp_path, monkeypatch):
    """v0.6.1（Task 7）：GET 结果/preview/slices 是纯查询，绝不隐式物化。

    未物化一律 404 ``RESULT_NOT_MATERIALIZED`` 且不落盘任何文件；显式
    POST /materialize（唯一创建操作）后 GET 只读既有工件，不重算、不改写。
    """

    client, runtime = make_client(tmp_path)
    _, _, _, candidate_id = prepare_completed_run(client)
    grid_path = runtime.settings.result_grid(candidate_id)

    # 未物化：GET 一律 404 RESULT_NOT_MATERIALIZED，且绝不创建工件
    for url in (
        f"/api/results/{candidate_id}",
        f"/api/results/{candidate_id}/preview",
        f"/api/results/{candidate_id}/slices?axis=z&index=0",
    ):
        resp = client.get(url)
        assert resp.status_code == 404, url
        assert resp.json()["error"]["code"] == "RESULT_NOT_MATERIALIZED"
        assert not grid_path.exists(), url

    # 显式物化后：GET 只读既有工件
    assert client.post(f"/api/results/{candidate_id}/materialize").status_code in (200, 201)
    mtime = grid_path.stat().st_mtime_ns

    # 证明 GET 路径不调用 materialize：炸掉路由层引用后 GET 仍正常
    import geomodeling.api.routes.results as results_routes

    def bomb(*_args, **_kwargs):
        raise AssertionError("GET 绝不调用 materialize")

    monkeypatch.setattr(results_routes, "materialize", bomb)
    resp = client.get(f"/api/results/{candidate_id}")
    assert resp.status_code == 200
    assert resp.json()["grid_sha256"]
    assert client.get(f"/api/results/{candidate_id}/preview").status_code == 200
    assert client.get(f"/api/results/{candidate_id}/slices?axis=z&index=0").status_code == 200
    assert grid_path.stat().st_mtime_ns == mtime  # 工件未被重写
