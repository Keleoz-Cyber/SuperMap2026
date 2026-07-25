"""Task 9: optional provenance sidecar and per-line/point group diagnostics.

A dataset profile that declares ``modeling_provenance`` makes the runner join
candidate predictions to the sidecar by stable ``source_row`` and report
RMSE/MAE/R²/Bias/count per survey line and survey point on the public
common-valid mask. Group diagnostics never feed ``best`` selection, coverage,
or the public ranking; datasets without the declaration run byte-identically
to before (no ``group_diagnostics`` key). A declared but missing, corrupt,
schema-incomplete, non-unique or non-covering sidecar fails closed: the run
reaches a structured ``failed`` state and can never succeed.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from geomodeling.modeling.provenance import (
    PROVENANCE_ARTIFACT_MISSING,
    PROVENANCE_DUPLICATE_SOURCE_ROW,
    PROVENANCE_SCHEMA_MISMATCH,
    PROVENANCE_SOURCE_ROW_UNMATCHED,
    load_optional_provenance,
)
from geomodeling.modeling.runner import execute_run
from geomodeling.platform import PlatformRuntime, tables
from test_experiment_runner import insert_run, load_candidates, make_runtime

PROVENANCE_RELATIVE = "derived/modeling_provenance.parquet"

# 24 个建模节点：2 条测线 × 2 个测点 × 6 个节点，source_row 与标准化表一致。
GROUPS: dict[int, tuple[str, str]] = {
    **{row: ("L1", "W1") for row in range(1, 7)},
    **{row: ("L1", "W2") for row in range(7, 13)},
    **{row: ("L2", "W3") for row in range(13, 19)},
    **{row: ("L2", "W4") for row in range(19, 25)},
}

GENERIC_METRIC_KEYS = {
    "rmse",
    "mae",
    "r2",
    "bias",
    "coverage",
    "common_valid_count",
    "candidate_valid_count",
    "candidate_nodata_count",
    "total_count",
    "runtime_seconds",
    "fold_metrics",
}


def make_standardized(runtime: PlatformRuntime, case_id: str, dataset_id: str) -> pd.DataFrame:
    """24 节点平滑三维场（确定性种子，跨 run 指标可逐位比较）。"""

    rng = np.random.default_rng(20260725)
    n = 24
    x = rng.uniform(-160.0, -40.0, n)
    y = rng.uniform(220.0, 660.0, n)
    z = rng.uniform(-840.0, 0.0, n)
    value = np.sin(x / 40) + np.cos(y / 90) + 0.001 * z + 10.0
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
    return frame


def make_provenance_frame(
    frame: pd.DataFrame,
    groups: dict[int, tuple[str, str]] | None = None,
) -> pd.DataFrame:
    """与 Task 5 实际产物相同的 12 列 provenance sidecar。"""

    groups = GROUPS if groups is None else groups
    rows = []
    for row in frame.itertuples():
        line_id, point_id = groups[int(row.source_row)]
        rows.append(
            {
                "source_row": int(row.source_row),
                "point_id": point_id,
                "line_id": line_id,
                "x_local_m": row.x,
                "y_local_m": row.y,
                "z_local_m": row.z,
                "vx_km_s": row.value,
                "source_sample_ids": f"S{int(row.source_row)}",
                "sample_count": 1,
                "vx_min_km_s": row.value,
                "vx_max_km_s": row.value,
                "vx_sample_std_km_s": 0.0,
            }
        )
    return pd.DataFrame(rows)


def write_provenance(runtime: PlatformRuntime, case_id: str, dataset_id: str, provenance: pd.DataFrame) -> Path:
    path = runtime.settings.modeling_provenance(case_id, dataset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    provenance.to_parquet(path, index=False)
    return path


def insert_experiment(
    runtime: PlatformRuntime,
    case_id: str,
    dataset_id: str,
    search: dict,
    *,
    declare_provenance: bool,
) -> str:
    profile = {
        "source_kind": "microseismic_dat_bundle",
        "mapping": {
            "dimension": search.pop("dimension"),
            "x": "x",
            "y": "y",
            "z": "z",
            "value": "value",
            "value_name": "Vx",
            "value_unit": "km/s",
            "coordinate_kind": "local_linear",
        },
        "source_sha256": "a" * 64,
        "standardized_sha256": "b" * 64,
        "quality": {"status": "passed", "confirmed": True},
    }
    if declare_provenance:
        profile["modeling_provenance"] = PROVENANCE_RELATIVE
    experiment_id = str(uuid.uuid4())
    with runtime.session() as session:
        session.add(tables.Case(id=case_id, name="微震速度建模", case_type="microseismic", config_json="{}"))
        session.add(
            tables.DatasetVersion(
                id=dataset_id,
                case_id=case_id,
                version=1,
                status="validated",
                source_path="source/source_manifest.json",
                profile_json=tables.dumps_canonical(profile),
            )
        )
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


def search_payload(dataset_id: str, parameters) -> dict:
    return {
        "dimension": "3d",
        "algorithm": "idw",
        "dataset_version_id": dataset_id,
        "search_mode": "manual" if isinstance(parameters, dict) else "grid",
        "parameters": parameters,
        "validation": {"method": "spatial_kfold", "folds": 3, "seed": 11, "holdout_fraction": 0.2},
        "grid": None,
    }


def run_experiment(runtime: PlatformRuntime, case_id: str, dataset_id: str, search: dict, *, declare: bool):
    experiment_id = insert_experiment(runtime, case_id, dataset_id, search, declare_provenance=declare)
    run_id = insert_run(runtime, experiment_id)
    outcome = execute_run(runtime, run_id, threading.Event())
    return outcome, load_candidates(runtime, run_id), run_id


def run_error_code(runtime: PlatformRuntime, run_id: str) -> str | None:
    with runtime.session() as session:
        return session.get(tables.Run, run_id).error_code


def run_public_metrics(runtime: PlatformRuntime, run_id: str) -> dict:
    with runtime.session() as session:
        return tables.loads_canonical(session.get(tables.Run, run_id).metrics_json)["public_metrics"]


def median_neighbor_radius(frame: pd.DataFrame, k: int = 8) -> float:
    """各点到第 k 近邻距离的中位数：配合 ``min_neighbors=k`` 制造部分 NoData。"""

    coords = frame[["x", "y", "z"]].to_numpy(dtype="float64")
    diff = coords[:, None, :] - coords[None, :, :]
    distances = np.sqrt((diff**2).sum(axis=-1))
    kth = np.sort(distances, axis=1)[:, k]
    return float(np.median(kth))


def test_group_diagnostics_do_not_change_public_ranking(tmp_path):
    runtime = make_runtime(tmp_path)
    frame = make_standardized(runtime, "c1", "ds1")
    write_provenance(runtime, "c1", "ds1", make_provenance_frame(frame))
    # 对照组：同一份标准化数据、同一验证种子，但 profile 不声明 provenance
    make_standardized(runtime, "c2", "ds2")

    outcome, candidates, run_id = run_experiment(
        runtime, "c1", "ds1", search_payload("ds1", {"power": 2.0, "neighbor_count": 8}), declare=True
    )
    assert outcome.status == "succeeded"
    metrics = candidates[0]["metrics"]

    diagnostics = metrics["group_diagnostics"]
    assert set(diagnostics) == {"line", "point"}
    assert set(diagnostics["line"]) == {"L1", "L2"}
    assert set(diagnostics["point"]) == {"W1", "W2", "W3", "W4"}
    assert diagnostics["line"]["L1"]["count"] == 12
    assert diagnostics["point"]["W1"]["count"] == 6
    for groups in diagnostics.values():
        assert sum(group["count"] for group in groups.values()) == metrics["common_valid_count"]
        for group in groups.values():
            assert set(group) == {"rmse", "mae", "r2", "bias", "count"}
            assert group["rmse"] >= 0
            assert group["mae"] >= 0

    # 分组指标确实在同一个公共掩膜上复算：分组 MSE/Bias 加权还原总体指标
    for groups in diagnostics.values():
        total = sum(group["count"] for group in groups.values())
        mse = sum(group["count"] * group["rmse"] ** 2 for group in groups.values()) / total
        bias = sum(group["count"] * group["bias"] for group in groups.values()) / total
        assert mse == pytest.approx(metrics["rmse"] ** 2, rel=1e-9)
        assert bias == pytest.approx(metrics["bias"], abs=1e-12)

    # 对照 run：公开指标与 best 选择逐位一致，且没有 group_diagnostics 键
    control_outcome, control_candidates, control_run_id = run_experiment(
        runtime, "c2", "ds2", search_payload("ds2", {"power": 2.0, "neighbor_count": 8}), declare=False
    )
    assert control_outcome.status == "succeeded"
    control_metrics = control_candidates[0]["metrics"]
    assert set(control_metrics) == GENERIC_METRIC_KEYS
    assert set(metrics) == GENERIC_METRIC_KEYS | {"group_diagnostics"}
    for key in GENERIC_METRIC_KEYS - {"runtime_seconds"}:
        assert metrics[key] == control_metrics[key], key

    public = run_public_metrics(runtime, run_id)
    control_public = run_public_metrics(runtime, control_run_id)
    assert public == control_public
    assert public["rmse"] == metrics["rmse"]


def test_group_diagnostics_use_common_mask_not_own_mask(tmp_path):
    runtime = make_runtime(tmp_path)
    frame = make_standardized(runtime, "c1", "ds1")
    write_provenance(runtime, "c1", "ds1", make_provenance_frame(frame))
    radius = median_neighbor_radius(frame)
    search = search_payload(
        "ds1",
        [
            {"power": 2.0, "neighbor_count": 8, "search_radius": None},
            {"power": 2.0, "neighbor_count": 8, "search_radius": radius, "min_neighbors": 8},
        ],
    )
    outcome, candidates, _run_id = run_experiment(runtime, "c1", "ds1", search, declare=True)
    assert outcome.status == "succeeded"

    by_radius = {c["params"].get("search_radius"): c for c in candidates}
    unlimited = by_radius[None]["metrics"]
    limited = by_radius[radius]["metrics"]
    assert by_radius[None]["status"] == "succeeded"
    assert by_radius[radius]["status"] == "succeeded"
    # 掩膜非平凡：小半径候选确实产生了 NoData
    assert limited["candidate_nodata_count"] > 0
    assert limited["coverage"] < 1.0
    assert unlimited["common_valid_count"] == limited["common_valid_count"]

    # 两个候选的分组计数都按公共掩膜给出，逐组相等；总和等于公共有效数
    for kind in ("line", "point"):
        unlimited_groups = unlimited["group_diagnostics"][kind]
        limited_groups = limited["group_diagnostics"][kind]
        assert set(unlimited_groups) == set(limited_groups)
        for key in unlimited_groups:
            assert unlimited_groups[key]["count"] == limited_groups[key]["count"]
        assert (
            sum(group["count"] for group in unlimited_groups.values())
            == unlimited["common_valid_count"]
        )


def test_missing_provenance_declaration_leaves_generic_runs_unchanged(tmp_path):
    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")

    outcome, candidates, _run_id = run_experiment(
        runtime, "c1", "ds1", search_payload("ds1", {"power": 2.0, "neighbor_count": 8}), declare=False
    )
    assert outcome.status == "succeeded"
    metrics = candidates[0]["metrics"]
    # 逐位不变：通用数据集的指标键集合与 Task 9 之前完全一致
    assert set(metrics) == GENERIC_METRIC_KEYS
    assert "group_diagnostics" not in metrics


def test_load_optional_provenance_returns_none_without_declaration(tmp_path):
    runtime = make_runtime(tmp_path)
    frame = make_standardized(runtime, "c1", "ds1")
    # 即使磁盘上存在 sidecar，未声明的 profile 也一律返回 None
    write_provenance(runtime, "c1", "ds1", make_provenance_frame(frame))

    assert load_optional_provenance(runtime.settings, "c1", "ds1", {}) is None
    assert load_optional_provenance(runtime.settings, "c1", "ds1", {"mapping": {}}) is None

    loaded = load_optional_provenance(
        runtime.settings, "c1", "ds1", {"modeling_provenance": PROVENANCE_RELATIVE}
    )
    assert loaded is not None
    assert len(loaded) == len(frame)


def test_declared_but_missing_file_fails_closed(tmp_path):
    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")

    experiment_id = insert_experiment(
        runtime, "c1", "ds1", search_payload("ds1", {"power": 2.0, "neighbor_count": 8}),
        declare_provenance=True,
    )
    run_id = insert_run(runtime, experiment_id)
    outcome = execute_run(runtime, run_id, threading.Event())

    assert outcome.status == "failed"
    assert run_error_code(runtime, run_id) == PROVENANCE_ARTIFACT_MISSING
    assert load_candidates(runtime, run_id) == []  # 快速失败：不产生任何候选


def test_declared_but_incomplete_columns_fails_closed(tmp_path):
    runtime = make_runtime(tmp_path)
    frame = make_standardized(runtime, "c1", "ds1")
    provenance = make_provenance_frame(frame).drop(columns=["line_id", "point_id"])
    write_provenance(runtime, "c1", "ds1", provenance)

    experiment_id = insert_experiment(
        runtime, "c1", "ds1", search_payload("ds1", {"power": 2.0, "neighbor_count": 8}),
        declare_provenance=True,
    )
    run_id = insert_run(runtime, experiment_id)
    outcome = execute_run(runtime, run_id, threading.Event())

    assert outcome.status == "failed"
    assert run_error_code(runtime, run_id) == PROVENANCE_SCHEMA_MISMATCH
    assert load_candidates(runtime, run_id) == []


def test_declared_but_duplicate_source_row_fails_closed(tmp_path):
    runtime = make_runtime(tmp_path)
    frame = make_standardized(runtime, "c1", "ds1")
    provenance = pd.concat(
        [make_provenance_frame(frame), make_provenance_frame(frame).iloc[[0]]],
        ignore_index=True,
    )
    write_provenance(runtime, "c1", "ds1", provenance)

    experiment_id = insert_experiment(
        runtime, "c1", "ds1", search_payload("ds1", {"power": 2.0, "neighbor_count": 8}),
        declare_provenance=True,
    )
    run_id = insert_run(runtime, experiment_id)
    outcome = execute_run(runtime, run_id, threading.Event())

    assert outcome.status == "failed"
    assert run_error_code(runtime, run_id) == PROVENANCE_DUPLICATE_SOURCE_ROW
    assert load_candidates(runtime, run_id) == []


def test_declared_but_unmatched_source_row_fails_closed(tmp_path):
    runtime = make_runtime(tmp_path)
    frame = make_standardized(runtime, "c1", "ds1")
    provenance = make_provenance_frame(frame).iloc[:-1]  # 缺少最后一个 source_row
    write_provenance(runtime, "c1", "ds1", provenance)

    experiment_id = insert_experiment(
        runtime, "c1", "ds1", search_payload("ds1", {"power": 2.0, "neighbor_count": 8}),
        declare_provenance=True,
    )
    run_id = insert_run(runtime, experiment_id)
    outcome = execute_run(runtime, run_id, threading.Event())

    assert outcome.status == "failed"
    assert run_error_code(runtime, run_id) == PROVENANCE_SOURCE_ROW_UNMATCHED
    assert load_candidates(runtime, run_id) == []
