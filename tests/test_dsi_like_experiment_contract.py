"""v0.8.0 Task 4 tests: dsi_like 实验合同注册。

覆盖：API 创建合同（3D 201 / 2D 422 类型化拒绝）、manual/grid 候选展开与
组合上限、候选指纹对全部 DSI 参数的规范化覆盖、能力矩阵诚实项、runner 级
折分/OOF 工件与 IDW 同语义、公共有效掩膜指标复算、泄漏安全（验证点绝不
进入硬约束集合）、物化（有限网格 + 观测包围盒外 NoData）与单候选失败不
拖垮 run 的失败语义。
"""

from __future__ import annotations

import io
import threading
import time
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from geomodeling.modeling.runner import execute_run
from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.errors import PlatformError, platform_error_handler
from geomodeling.platform.experiments import expand_candidates
from geomodeling.platform.results import materialize

# ---------------------------------------------------------------------------
# 共享构造：API 客户端与 3D/2D 数据集
# ---------------------------------------------------------------------------

CSV_3D = "x,y,z,v\n" + "\n".join(
    f"{(i % 4) * 30 - 150},{(j % 5) * 80 + 260},{(k % 4) * 200 - 800},{10 + i + j + k}"
    for i in range(4) for j in range(5) for k in range(4)
) + "\n"

CSV_2D = "x,y,v\n" + "\n".join(
    f"{(i % 4) * 30 - 150},{(j % 5) * 80 + 260},{10 + i + j}"
    for i in range(4) for j in range(5)
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

MAPPING_2D = {
    "dimension": "2d",
    "x": "x",
    "y": "y",
    "value": "v",
    "value_name": "属性",
    "coordinate_kind": "local_linear",
}


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


def prepare_validated_dataset(
    client: TestClient, csv_text: str, mapping: dict
) -> tuple[str, str]:
    resp = client.post("/api/cases", json={"name": "DSI 合同案例"})
    assert resp.status_code == 201
    case_id = resp.json()["id"]
    resp = client.post(
        f"/api/cases/{case_id}/datasets/uploads",
        files={"file": ("data.csv", io.BytesIO(csv_text.encode()), "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    dataset_id = resp.json()["id"]
    assert client.post(f"/api/datasets/{dataset_id}/mapping", json=mapping).status_code == 200
    assert client.post(f"/api/datasets/{dataset_id}/validate").status_code == 200
    return case_id, dataset_id


def create_experiment(
    client: TestClient, case_id: str, dataset_id: str, algorithm: str, parameters: dict
):
    return client.post(
        "/api/experiments",
        json={
            "case_id": case_id,
            "name": "DSI 实验",
            "algorithm": algorithm,
            "dataset_version_id": dataset_id,
            "search_mode": "manual",
            "parameters": parameters,
            "validation": {"method": "spatial_kfold", "folds": 3, "seed": 1, "holdout_fraction": 0.2},
        },
    )


def wait_run(client: TestClient, run_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/runs/{run_id}").json()
        if body["status"] in ("succeeded", "failed", "canceled"):
            return body
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} 未到达终态")


# ---------------------------------------------------------------------------
# runner 级构造：直接落库的标准化 3D 数据集（确定性、无重复坐标）
# ---------------------------------------------------------------------------


def make_runtime(tmp_path: Path) -> PlatformRuntime:
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    return runtime


def make_standardized_3d(runtime: PlatformRuntime, case_id: str, dataset_id: str, n: int = 48):
    rng = np.random.default_rng(20260808)
    x = rng.uniform(-160.0, -40.0, n)
    y = rng.uniform(220.0, 660.0, n)
    z = rng.uniform(-840.0, 0.0, n)
    value = (
        np.sin(x / 25.0)
        + np.cos(y / 60.0)
        + 0.002 * z
        + 0.35 * np.sin(x / 6.0 + y / 11.0)
        + 8.0
    )
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


def dsi_search(**overrides):
    search = {
        "dimension": "3d",
        "algorithm": "dsi_like",
        "dataset_version_id": "ds1",
        "search_mode": "manual",
        "parameters": {},
        "validation": {"method": "spatial_kfold", "folds": 3, "seed": 11, "holdout_fraction": 0.2},
        "grid": None,
    }
    search.update(overrides)
    return search


def insert_case_dataset(
    runtime: PlatformRuntime, case_id: str, dataset_id: str, dimension: str = "3d"
) -> None:
    """落库案例 + 已验证数据版本（含 standardized_path，供物化读取）。"""

    with runtime.session() as session:
        session.add(tables.Case(id=case_id, name="案例", case_type="generic", config_json="{}"))
        session.add(
            tables.DatasetVersion(
                id=dataset_id,
                case_id=case_id,
                version=1,
                status="validated",
                source_path="x.csv",
                profile_json=tables.dumps_canonical(
                    {
                        "mapping": {
                            "dimension": dimension,
                            "x": "x",
                            "y": "y",
                            "z": "z" if dimension == "3d" else None,
                            "value": "value",
                            "value_name": "属性",
                            "coordinate_kind": "local_linear",
                        },
                        "source_sha256": "a" * 64,
                        "standardized_sha256": "b" * 64,
                        "standardized_path": str(
                            runtime.settings.standardized_dataset(case_id, dataset_id)
                        ),
                        "quality": {"status": "passed", "confirmed": True},
                    }
                ),
            )
        )
        session.commit()


def insert_experiment(runtime: PlatformRuntime, case_id: str, dataset_id: str, search: dict) -> str:
    """按生产 params_json 形状直接落库实验行（dimension 只进数据集 profile）。"""

    search = dict(search)
    dimension = search.pop("dimension")
    with runtime.session() as session:
        dataset_exists = session.get(tables.DatasetVersion, dataset_id) is not None
    if not dataset_exists:
        insert_case_dataset(runtime, case_id, dataset_id, dimension)
    experiment_id = str(uuid.uuid4())
    with runtime.session() as session:
        session.add(
            tables.Experiment(
                id=experiment_id,
                case_id=case_id,
                name="实验",
                params_json=tables.dumps_canonical(search),
            )
        )
        session.commit()
    return experiment_id


def insert_run(runtime: PlatformRuntime, experiment_id: str) -> str:
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


def run_dsi_experiment(tmp_path: Path, search: dict) -> tuple[PlatformRuntime, str, list[dict], pd.DataFrame]:
    """建数据集 → 落库实验 → 执行 run，返回 (runtime, run_id, candidates, frame)。"""

    runtime = make_runtime(tmp_path)
    _target, frame = make_standardized_3d(runtime, "c1", "ds1")
    experiment_id = insert_experiment(runtime, "c1", "ds1", search)
    run_id = insert_run(runtime, experiment_id)
    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    return runtime, run_id, load_candidates(runtime, run_id), frame


# ---------------------------------------------------------------------------
# 计划 Step 1：API 创建合同——3D 合法、2D 类型化拒绝
# ---------------------------------------------------------------------------


def test_dsi_like_is_a_valid_3d_algorithm_and_invalid_in_2d(tmp_path):
    client, _runtime = make_client(tmp_path)
    case3, dataset3 = prepare_validated_dataset(client, CSV_3D, MAPPING_3D)
    created = create_experiment(client, case3, dataset3, "dsi_like", {"init_power": 2.0})
    assert created.status_code == 201, created.text
    assert created.json()["params"]["algorithm"] == "dsi_like"

    case2, dataset2 = prepare_validated_dataset(client, CSV_2D, MAPPING_2D)
    rejected = create_experiment(client, case2, dataset2, "dsi_like", {})
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "ALGORITHM_DIMENSION_MISMATCH"

    # 既有算法在 2D 数据集上的行为逐位不变（只拦截 dsi_like）
    legacy = create_experiment(client, case2, dataset2, "idw", {"power": 2.0})
    assert legacy.status_code == 201, legacy.text


# ---------------------------------------------------------------------------
# 候选展开：manual/grid、组合上限、指纹规范化
# ---------------------------------------------------------------------------


def test_dsi_like_manual_and_grid_expansion():
    manual = expand_candidates(dsi_search())
    assert len(manual) == 1
    assert manual[0].algorithm == "dsi_like"
    assert manual[0].parameters == {}
    # 相同输入相同指纹
    assert expand_candidates(dsi_search())[0].fingerprint == manual[0].fingerprint

    grid = dsi_search(
        search_mode="grid",
        parameters={
            "init_power": [1.5, 2.0],
            "neighbor_connectivity": [6, 18],
            "smoothing_strength": [0.5],
            "max_iterations": [25, 50],
        },
    )
    candidates = expand_candidates(grid)
    assert len(candidates) == 8
    assert len({c.fingerprint for c in candidates}) == 8
    for candidate in candidates:
        assert set(candidate.parameters) == {
            "init_power",
            "neighbor_connectivity",
            "smoothing_strength",
            "max_iterations",
        }


def test_dsi_like_grid_combination_cap_applies():
    search = dsi_search(
        search_mode="grid", parameters={"init_power": [0.5 + 0.1 * i for i in range(51)]}
    )
    with pytest.raises(PlatformError) as exc:
        expand_candidates(search)
    assert exc.value.code == "SEARCH_TOO_LARGE"


def test_dsi_like_fingerprint_covers_all_parameters():
    base = {
        "init_power": 2.0,
        "neighbor_connectivity": 6,
        "smoothing_strength": 0.5,
        "max_iterations": 25,
        "convergence_tolerance": 1e-4,
        "hard_constraints": True,
    }
    reference = expand_candidates(dsi_search(parameters=dict(base)))[0].fingerprint
    assert expand_candidates(dsi_search(parameters=dict(base)))[0].fingerprint == reference
    variants = [
        {"init_power": 3.0},
        {"neighbor_connectivity": 18},
        {"smoothing_strength": 0.75},
        {"max_iterations": 50},
        {"convergence_tolerance": 1e-5},
    ]
    for delta in variants:
        fingerprint = expand_candidates(dsi_search(parameters={**base, **delta}))[0].fingerprint
        assert fingerprint != reference, delta
    # hard_constraints 只能取 True（Literal[True]）：省略该键必须改变指纹，
    # 证明固定字段同样参与规范化哈希
    omitted = {key: value for key, value in base.items() if key != "hard_constraints"}
    assert expand_candidates(dsi_search(parameters=omitted))[0].fingerprint != reference


def test_dsi_like_capability_matrix_is_honest():
    from geomodeling.modeling.professional_contracts import CapabilityState, capabilities_for

    caps = capabilities_for("dsi_like")
    # 无原生不确定性：与 IDW 同档（经验误差尺度可用、无 Kriging 原生方差）
    assert caps.native_kriging_std is CapabilityState.NOT_APPLICABLE
    assert caps.empirical_error_scale is CapabilityState.SUPPORTED
    # 通用平台能力：折分证据、异常提取、候选比较
    assert caps.spatial_fold_inspection is CapabilityState.SUPPORTED
    assert caps.anomaly_extraction is CapabilityState.SUPPORTED
    assert caps.candidate_comparison is CapabilityState.SUPPORTED
    # DSI-like 没有的建模旋钮诚实标记为不适用
    assert caps.empirical_variogram is CapabilityState.NOT_APPLICABLE
    assert caps.model_anisotropy is CapabilityState.NOT_APPLICABLE
    assert caps.z_scale_weight_distance is CapabilityState.NOT_APPLICABLE
    assert caps.search_neighborhood is CapabilityState.NOT_APPLICABLE
    assert caps.sector_neighbor_limits is CapabilityState.NOT_APPLICABLE


# ---------------------------------------------------------------------------
# runner 级：成功候选、折分/OOF 工件与 IDW 同语义
# ---------------------------------------------------------------------------


def test_dsi_like_run_succeeds_with_metrics_and_fold_artifacts(tmp_path):
    runtime, _run_id, candidates, frame = run_dsi_experiment(tmp_path, dsi_search())
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["status"] == "succeeded"

    metrics = candidate["metrics"]
    # 与 IDW 候选完全相同的指标键集合（含两个工件 SHA 引用）
    assert set(metrics) == {
        "rmse", "mae", "r2", "bias", "coverage",
        "common_valid_count", "candidate_valid_count", "candidate_nodata_count",
        "total_count", "runtime_seconds", "fold_metrics",
        "fold_assignments_sha256", "oof_predictions_sha256",
    }
    assert metrics["common_valid_count"] > 0
    # 折训练包围盒边缘的验证点恒为 NoData（不外推），覆盖率诚实小于 1
    assert metrics["coverage"] > 0.5
    assert np.isfinite(metrics["rmse"]) and metrics["rmse"] >= 0
    assert metrics["candidate_valid_count"] + metrics["candidate_nodata_count"] == metrics["total_count"]

    professional_dir = runtime.settings.professional_result_dir(candidate["id"])
    assignments_path = professional_dir / "fold_assignments.parquet"
    oof_path = professional_dir / "out_of_fold_predictions.parquet"
    assert assignments_path.exists()
    assert oof_path.exists()

    oof = pd.read_parquet(oof_path)
    assert list(oof.columns) == [
        "source_row", "fold_index", "x", "y", "z", "observed",
        "predicted", "residual", "absolute_error", "squared_error", "is_nodata",
    ]
    assert oof["source_row"].is_unique
    assert set(oof["source_row"]) == set(frame["source_row"])
    valid_oof = oof.loc[~oof["is_nodata"]]
    assert np.isfinite(valid_oof["predicted"]).all()
    assert np.isfinite(valid_oof["residual"]).all()

    assignments = pd.read_parquet(assignments_path)
    assert {"fold_index", "source_row", "group_key", "role", "leakage_detected"} <= set(
        assignments.columns
    )
    assert set(assignments["role"]) == {"training", "validation"}
    assert not assignments["leakage_detected"].any()
    validation = assignments[assignments["role"] == "validation"]
    assert validation.groupby("source_row").size().eq(1).all()


def test_dsi_like_uses_same_fold_assignments_as_idw(tmp_path):
    runtime = make_runtime(tmp_path)
    _target, frame = make_standardized_3d(runtime, "c1", "ds1")

    dsi_experiment = insert_experiment(runtime, "c1", "ds1", dsi_search())
    dsi_run = insert_run(runtime, dsi_experiment)
    assert execute_run(runtime, dsi_run, threading.Event()).status == "succeeded"

    idw_search = dsi_search(algorithm="idw", parameters={"power": 2.0, "neighbor_count": 8})
    idw_experiment = insert_experiment(runtime, "c1", "ds1", idw_search)
    idw_run = insert_run(runtime, idw_experiment)
    assert execute_run(runtime, idw_run, threading.Event()).status == "succeeded"

    dsi_candidate = load_candidates(runtime, dsi_run)[0]
    idw_candidate = load_candidates(runtime, idw_run)[0]
    assert dsi_candidate["status"] == "succeeded"
    assert idw_candidate["status"] == "succeeded"

    dsi_assignments = pd.read_parquet(
        runtime.settings.professional_result_dir(dsi_candidate["id"]) / "fold_assignments.parquet"
    )
    idw_assignments = pd.read_parquet(
        runtime.settings.professional_result_dir(idw_candidate["id"]) / "fold_assignments.parquet"
    )
    # 同一数据版本 + 同一验证规格 → 折分证据逐位一致
    pd.testing.assert_frame_equal(dsi_assignments, idw_assignments)
    assert (
        dsi_candidate["metrics"]["fold_assignments_sha256"]
        == idw_candidate["metrics"]["fold_assignments_sha256"]
    )

    dsi_oof = pd.read_parquet(
        runtime.settings.professional_result_dir(dsi_candidate["id"])
        / "out_of_fold_predictions.parquet"
    )
    assert set(dsi_oof["source_row"]) == set(frame["source_row"])


def test_validation_rows_never_enter_hard_constraints(tmp_path):
    """泄漏安全：验证点绝不进入该折的硬约束集合。

    插值器级已证明：恰在观测节点上的查询逐位复现观测原值（硬约束恒开）。
    若验证点泄漏进 fit，其 OOF 预测将精确等于真值、整体残差≈0；实际
    OOF 残差显著非零，证明每折只用训练点重建初始场与平滑场。
    """

    runtime, _run_id, candidates, _frame = run_dsi_experiment(tmp_path, dsi_search())
    candidate = candidates[0]
    assert candidate["status"] == "succeeded"
    assert candidate["metrics"]["rmse"] > 1e-3

    oof = pd.read_parquet(
        runtime.settings.professional_result_dir(candidate["id"])
        / "out_of_fold_predictions.parquet"
    )
    residuals = oof.loc[~oof["is_nodata"], "residual"].to_numpy(dtype="float64")
    assert (np.abs(residuals) > 1e-6).any()

    # 折分配表：同一折内每行只有一个角色（训练/验证不相交）
    assignments = pd.read_parquet(
        runtime.settings.professional_result_dir(candidate["id"]) / "fold_assignments.parquet"
    )
    assert not assignments.duplicated(["fold_index", "source_row"]).any()


def test_common_valid_mask_and_metric_recompute_match_idw_semantics(tmp_path):
    search = dsi_search(
        search_mode="grid",
        parameters=[{}, {"init_power": 3.0, "neighbor_connectivity": 26}],
    )
    runtime, run_id, candidates, _frame = run_dsi_experiment(tmp_path, search)
    assert len(candidates) == 2
    by_params = {tuple(sorted(c["params"].items())): c for c in candidates}
    first = by_params[()]
    second = by_params[(("init_power", 3.0), ("neighbor_connectivity", 26))]
    assert first["status"] == "succeeded"
    assert second["status"] == "succeeded"

    with runtime.session() as session:
        run_metrics = tables.loads_canonical(session.get(tables.Run, run_id).metrics_json)
    public = run_metrics["public_metrics"]
    assert (
        first["metrics"]["common_valid_count"]
        == second["metrics"]["common_valid_count"]
        == public["common_valid_count"]
    )

    # 公共有效掩膜上手工复算 RMSE/MAE，与落库公共指标一致
    pa = pd.read_parquet(first["predictions_path"]).sort_values("source_row").reset_index(drop=True)
    pb = pd.read_parquet(second["predictions_path"]).sort_values("source_row").reset_index(drop=True)
    assert pa["source_row"].equals(pb["source_row"])
    np.testing.assert_array_equal(pa["truth"].to_numpy(), pb["truth"].to_numpy())
    common = (~pa["is_nodata"].to_numpy()) & (~pb["is_nodata"].to_numpy())
    assert int(common.sum()) == first["metrics"]["common_valid_count"]
    truth = pa["truth"].to_numpy()
    for candidate, predictions in ((first, pa), (second, pb)):
        errors = predictions["prediction"].to_numpy()[common] - truth[common]
        expected_rmse = float(np.sqrt((errors**2).mean()))
        expected_mae = float(np.abs(errors).mean())
        assert candidate["metrics"]["rmse"] == pytest.approx(expected_rmse, rel=1e-12)
        assert candidate["metrics"]["mae"] == pytest.approx(expected_mae, rel=1e-12)
        assert (
            candidate["metrics"]["candidate_valid_count"]
            + candidate["metrics"]["candidate_nodata_count"]
            == candidate["metrics"]["total_count"]
        )


def test_invalid_dsi_candidate_fails_without_sinking_run(tmp_path):
    """失败语义：非法参数值/非法参数键的候选结构化失败，不拖垮整个 run。"""

    search = dsi_search(
        search_mode="grid",
        parameters=[
            {},
            {"hard_constraints": False},  # 固定字段不允许关闭 → 契约验证失败
            {"unknown_key": 1},  # 未知参数键 → extra="forbid" 验证失败
        ],
    )
    runtime, _run_id, candidates, _frame = run_dsi_experiment(tmp_path, search)
    assert len(candidates) == 3
    good = next(c for c in candidates if c["params"] == {})
    assert good["status"] == "succeeded"
    bad = [c for c in candidates if c["params"] != {}]
    assert len(bad) == 2
    for candidate in bad:
        assert candidate["status"] == "failed"
        assert candidate["error"]["code"] == "CANDIDATE_EVALUATION_FAILED"


# ---------------------------------------------------------------------------
# 物化：有限网格 + 观测包围盒外 NoData（永不外推填值）
# ---------------------------------------------------------------------------


def test_materialize_produces_finite_grid_and_nodata_outside_bounds(tmp_path):
    # 观测包围盒真子集的网格：x/y/z 每轴各外扩 10%
    grid = {
        "bounds": [[-172.0, -28.0], [176.0, 704.0], [-924.0, 84.0]],
        "resolution": [14.4, 52.8, 100.8],
        "max_cells": 100_000,
    }
    _runtime, _run_id, candidates, frame = run_dsi_experiment(
        tmp_path, dsi_search(grid=grid)
    )
    candidate = candidates[0]
    assert candidate["status"] == "succeeded"

    metadata = materialize(_runtime, candidate["id"])
    assert metadata["algorithm"] == "dsi_like"
    assert metadata["dimension"] == "3d"
    assert metadata["shape"] == [11, 11, 11]
    assert metadata["nodata_count"] > 0

    grid_path = _runtime.settings.result_grid(candidate["id"])
    with np.load(grid_path, allow_pickle=True) as bundle:
        values = bundle["values"]
        is_nodata = bundle["is_nodata"]
    assert values.shape == (11, 11, 11)
    # x 轴两端切片整体在观测包围盒外 → 整层 NoData，绝不外推填值
    assert is_nodata[0, :, :].all()
    assert is_nodata[-1, :, :].all()
    assert int(is_nodata.sum()) == metadata["nodata_count"]
    # 界内节点有限且有界（平滑场不超出训练值域）
    finite = values[~is_nodata]
    assert finite.size > 0
    assert np.isfinite(finite).all()
    assert finite.min() >= frame["value"].min() - 1e-9
    assert finite.max() <= frame["value"].max() + 1e-9

    # 幂等：重复物化返回同一网格身份
    again = materialize(_runtime, candidate["id"])
    assert again["grid_sha256"] == metadata["grid_sha256"]


# ---------------------------------------------------------------------------
# API 端到端：创建 → 运行 → 候选 → 物化
# ---------------------------------------------------------------------------


def test_dsi_like_api_end_to_end_run_and_materialize(tmp_path):
    client, _runtime = make_client(tmp_path)
    case_id, dataset_id = prepare_validated_dataset(client, CSV_3D, MAPPING_3D)
    created = create_experiment(client, case_id, dataset_id, "dsi_like", {})
    assert created.status_code == 201, created.text
    experiment_id = created.json()["id"]

    run_id = client.post(f"/api/experiments/{experiment_id}/runs").json()["id"]
    body = wait_run(client, run_id)
    assert body["status"] == "succeeded", body

    board = client.get(f"/api/experiments/{experiment_id}/candidates").json()
    assert len(board["candidates"]) == 1
    candidate = board["candidates"][0]
    assert candidate["status"] == "succeeded"
    assert candidate["metrics"]["common_valid_count"] > 0
    assert board["public_metrics"]["common_valid_count"] > 0

    resp = client.post(f"/api/results/{candidate['id']}/materialize")
    assert resp.status_code in (200, 201), resp.text
    result = resp.json()
    assert result["algorithm"] == "dsi_like"
    assert result["dimension"] == "3d"
    assert result["shape"] == [11, 11, 11]
    # 默认物化网格恰为观测包围盒：全部节点界内，无 NoData
    assert result["nodata_count"] == 0
    assert result["value_range"][0] < result["value_range"][1]
