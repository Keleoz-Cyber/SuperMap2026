#!/usr/bin/env python
"""v0.6.1 Task 14：32³/64³ 确定性体渲染基准网格种子（仅写隔离运行时）。

按计划公式生成 32³ 与 64³ 规则网格（float64）：

    value = sin(x*3) + cos(y*4) + 0.5*sin(z*5) + 0.25*x*y

公式在归一化坐标 u/v/w ∈ [0,1] 上求值（计划公式中的 x/y/z 即该归一化
坐标）；轴本身取米制 x/y ∈ [0,500]、z ∈ [-500,0]——显示锚点经/纬以
NetCDF Float32 存储，[0,1] 米级跨度在 120°E 会坍缩（Float32 步长
≈7.6e-6°），回读严格递增校验 fail-closed，米制百米跨度是真实管线的
最小诚实尺度。角落 2×2×2 共 8 个单元为确定性 NoData
（is_nodata=True 且值置 NaN）；4×4×4 建模样本子集排除命中 NoData 的
抽样点（样本数由 64 如实缩减），标准化帧 ``is_numeric_valid`` 按值的
真实有限性逐行计算，profile 有效/无效计数按帧统计——未声明的 NaN
绝不进入建模输入。每个尺寸在平台仓储中建立完整归属链：
case → dataset version（含真实标准化 parquet profile）→ experiment →
succeeded run → succeeded candidate，并手工落盘 ``grid.npz`` +
``metadata.json``、更新 ``candidate_results.grid_path``（与
``results.materialize`` 落盘路径同构），使候选 POST 渲染资产走真实链路
而**绝不重跑插值模型**。

两个 candidate ID 与网格身份写入
``<GEOMODELING_DATA_DIR>/live-fixtures/volume-benchmarks.json``，供
``web/e2e-live/supermap-native-volume-live.spec.ts`` 消费。

安全约束：
- 必须在调用环境提供唯一的 ``GEOMODELING_DATA_DIR``；默认/演示数据目录
  （``var/geomodeling``、``var/demo_v041``）一律拒绝，**绝不写用户正常运行时**；
- 确定性 UUID5 主键：同一隔离目录重复执行幂等（行已存在则复用并刷新工件）。

用法::

    GEOMODELING_DATA_DIR=<隔离目录> python web/e2e-live/fixtures/seed_volume_benchmarks.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

# worktree 自带源码优先：editable 安装可能指向主目录，绝不允许种子落到错误代码上
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from geomodeling.platform import PlatformRuntime, tables  # noqa: E402

GRID_SIZES = (32, 64)
PROPERTY_NAME = "BENCH"
UNITS = "arb.unit"
ALGORITHM = "idw"
CANDIDATE_PARAMS = {"power": 2.0, "neighbor_count": 8}
VALIDATION = {
    "method": "spatial_kfold",
    "folds": 3,
    "seed": 11,
    "holdout_fraction": 0.2,
}

# 固定 UUID5 命名空间：同一隔离目录内重复执行得到同一组主键（幂等）
_NAMESPACE = uuid.UUID("8b3a4c2e-6f1d-4e5a-9c7b-2d8e0f1a3b4c")


def _isolated_data_dir() -> Path:
    raw = os.environ.get("GEOMODELING_DATA_DIR")
    if not raw:
        raise SystemExit("基准种子要求调用环境提供唯一的 GEOMODELING_DATA_DIR")
    normalized = raw.replace("\\", "/").rstrip("/")
    if normalized.endswith("var/geomodeling") or normalized.endswith("var/demo_v041"):
        raise SystemExit(f"基准种子不得使用默认/演示数据目录：{raw}")
    return Path(raw)


def _benchmark_grid(n: int) -> tuple[tuple[np.ndarray, ...], np.ndarray, np.ndarray]:
    """计划公式场（归一化坐标求值，米制轴）+ 角落 2×2×2 确定性 NoData。"""

    axes = (
        np.linspace(0.0, 500.0, n),
        np.linspace(0.0, 500.0, n),
        np.linspace(-500.0, 0.0, n),
    )
    xx, yy, zz = np.meshgrid(*axes, indexing="ij")
    # 计划公式的 x/y/z 即归一化坐标 u/v/w ∈ [0,1]（米制轴仅承载显示尺度）
    uu, vv, ww = xx / 500.0, yy / 500.0, (zz + 500.0) / 500.0
    values = (
        np.sin(uu * 3.0) + np.cos(vv * 4.0) + 0.5 * np.sin(ww * 5.0) + 0.25 * uu * vv
    ).astype(np.float64)
    is_nodata = np.zeros(values.shape, dtype=bool)
    is_nodata[:2, :2, :2] = True
    values[is_nodata] = np.nan
    return axes, values, is_nodata


def _write_source_and_standardized(
    runtime: PlatformRuntime,
    case_id: str,
    dataset_id: str,
    axes: tuple[np.ndarray, ...],
    values: np.ndarray,
) -> tuple[str, str, str, Path, pd.DataFrame]:
    """确定性 4×4×4 抽样子集：source.csv + 标准化 parquet，返回三哈希、路径与帧。

    抽样子集排除 NoData 单元（命中角落的抽样点在写出前丢弃，样本数由
    64 如实缩减），``is_numeric_valid`` 按帧内值的真实有限性逐行计算——
    未声明的 NaN 绝不进入建模输入。
    """

    n = values.shape[0]
    picks = np.linspace(0, n - 1, 4).round().astype(int)
    rows = []
    for i in picks:
        for j in picks:
            for k in picks:
                rows.append(
                    (
                        float(axes[0][i]),
                        float(axes[1][j]),
                        float(axes[2][k]),
                        float(values[i, j, k]),
                    )
                )
    # 排除 NoData 单元：抽样命中角落 2×2×2 的行不进入 source/标准化帧
    rows = [row for row in rows if np.isfinite(row[3])]
    sampled_values = np.array([r[3] for r in rows], dtype="float64")
    frame = pd.DataFrame(
        {
            "source_row": np.arange(1, len(rows) + 1),
            "x": [r[0] for r in rows],
            "y": [r[1] for r in rows],
            "z": [r[2] for r in rows],
            "value": [r[3] for r in rows],
            # 防御性：按真实有限性计算，绝不硬编码 True 配 NaN
            "is_numeric_valid": np.isfinite(sampled_values),
        }
    )
    source_path = runtime.settings.upload_source(case_id, dataset_id, "csv")
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        "x,y,z,value\n" + "".join(f"{r[0]},{r[1]},{r[2]},{r[3]}\n" for r in rows),
        encoding="utf-8",
    )
    standardized_path = runtime.settings.standardized_dataset(case_id, dataset_id)
    standardized_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(standardized_path, index=False)
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    standardized_sha = hashlib.sha256(standardized_path.read_bytes()).hexdigest()
    return source_sha, standardized_sha, str(source_path), standardized_path, frame


def _seed_size(runtime: PlatformRuntime, n: int) -> dict:
    """建完整归属链 + 网格工件（幂等：行已存在则复用并刷新工件）。"""

    case_id = str(uuid.uuid5(_NAMESPACE, f"v0.6.1-volume-benchmark-{n}-case"))
    dataset_id = str(uuid.uuid5(_NAMESPACE, f"v0.6.1-volume-benchmark-{n}-dataset"))
    experiment_id = str(
        uuid.uuid5(_NAMESPACE, f"v0.6.1-volume-benchmark-{n}-experiment")
    )
    run_id = str(uuid.uuid5(_NAMESPACE, f"v0.6.1-volume-benchmark-{n}-run"))
    candidate_id = str(uuid.uuid5(_NAMESPACE, f"v0.6.1-volume-benchmark-{n}-candidate"))
    fingerprint = hashlib.sha256(f"v0.6.1-volume-benchmark-{n}".encode()).hexdigest()

    axes, values, is_nodata = _benchmark_grid(n)
    source_sha, standardized_sha, source_path, standardized_path, frame = (
        _write_source_and_standardized(runtime, case_id, dataset_id, axes, values)
    )
    # 质量计数按标准化帧真实统计写入 profile，门禁不得谎报
    valid_row_count = int(frame["is_numeric_valid"].to_numpy(dtype=bool).sum())

    profile = {
        "source_kind": "csv_upload",
        "dimension": "3d",
        "mapping": {
            "dimension": "3d",
            "x": "x",
            "y": "y",
            "z": "z",
            "value": "value",
            "value_name": PROPERTY_NAME,
            "value_unit": UNITS,
            "coordinate_kind": "local_linear",
        },
        "row_count": int(len(frame)),
        "valid_row_count": valid_row_count,
        "invalid_row_count": int(len(frame)) - valid_row_count,
        "source_sha256": source_sha,
        "standardized_sha256": standardized_sha,
        "standardized_path": str(standardized_path),
        "quality": {"status": "passed", "confirmed": True},
    }
    experiment_params = {
        "algorithm": ALGORITHM,
        "dataset_version_id": dataset_id,
        "search_mode": "manual",
        "parameters": CANDIDATE_PARAMS,
        "validation": VALIDATION,
        "grid": None,
    }

    with runtime.session() as session:
        if session.get(tables.Case, case_id) is None:
            session.add(
                tables.Case(
                    id=case_id,
                    name=f"体积基准 {n}³",
                    case_type="generic",
                    config_json="{}",
                )
            )
        if session.get(tables.DatasetVersion, dataset_id) is None:
            session.add(
                tables.DatasetVersion(
                    id=dataset_id,
                    case_id=case_id,
                    version=1,
                    status="validated",
                    source_path=source_path,
                    standardized_path=str(standardized_path),
                    profile_json=tables.dumps_canonical(profile),
                )
            )
        if session.get(tables.Experiment, experiment_id) is None:
            session.add(
                tables.Experiment(
                    id=experiment_id,
                    case_id=case_id,
                    name=f"体积基准实验 {n}³",
                    params_json=tables.dumps_canonical(experiment_params),
                )
            )
        if session.get(tables.Run, run_id) is None:
            session.add(
                tables.Run(id=run_id, experiment_id=experiment_id, status="succeeded")
            )
        session.commit()
    # 候选行单独提交：与 run 同事务时 UOW 不保插入序，FK 约束可能失败
    with runtime.session() as session:
        if session.get(tables.CandidateResult, candidate_id) is None:
            session.add(
                tables.CandidateResult(
                    id=candidate_id,
                    run_id=run_id,
                    category="final",
                    fingerprint=fingerprint,
                    status="succeeded",
                    params_json=tables.dumps_canonical(CANDIDATE_PARAMS),
                )
            )
        session.commit()

    # 网格工件：与 results.materialize 同路径同格式（npz + metadata + 哈希登记）
    grid_path = runtime.settings.result_grid(candidate_id)
    grid_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        grid_path,
        axes=np.array(axes, dtype=object),
        values=values,
        is_nodata=is_nodata,
    )
    grid_sha = hashlib.sha256(grid_path.read_bytes()).hexdigest()
    finite = values[np.isfinite(values)]
    metadata = {
        "result_id": candidate_id,
        "run_id": run_id,
        "experiment_id": experiment_id,
        "dataset_version_id": dataset_id,
        "algorithm": ALGORITHM,
        "parameters": CANDIDATE_PARAMS,
        "dimension": "3d",
        "shape": [n, n, n],
        "cell_count": int(n**3),
        "bounds": [[float(a[0]), float(a[-1])] for a in axes],
        "resolution": [float(a[1] - a[0]) for a in axes],
        "value_range": [float(finite.min()), float(finite.max())],
        "nodata_count": int(is_nodata.sum()),
        "grid_sha256": grid_sha,
        "source_sha256": source_sha,
        "standardized_sha256": standardized_sha,
        "fingerprint": fingerprint,
        "validation": VALIDATION,
        "created_at": tables.utc_now_iso(),
        "property_name": PROPERTY_NAME,
        "units": UNITS,
        "coordinate_kind": "local_linear",
    }
    (grid_path.parent / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # 与 materialize 落盘路径一致：工件暴露后更新 candidate_results.grid_path
    with runtime.session() as session:
        row = session.get(tables.CandidateResult, candidate_id)
        row.grid_path = str(grid_path)
        session.commit()

    return {
        "candidate_id": candidate_id,
        "case_id": case_id,
        "dataset_version_id": dataset_id,
        "experiment_id": experiment_id,
        "run_id": run_id,
        "grid_sha256": grid_sha,
        "shape": [n, n, n],
        "value_range": metadata["value_range"],
        "nodata_count": metadata["nodata_count"],
        "property_name": PROPERTY_NAME,
        "units": UNITS,
        "variable_name": PROPERTY_NAME,
    }


def main() -> None:
    data_dir = _isolated_data_dir()
    runtime = PlatformRuntime(data_dir)
    runtime.initialize()
    try:
        sizes = {str(n): _seed_size(runtime, n) for n in GRID_SIZES}
    finally:
        runtime.close()
    doc = {
        "schema": "v0.6.1-volume-benchmarks/v1",
        "seeded_at": tables.utc_now_iso(),
        "sizes": sizes,
    }
    out = data_dir / "live-fixtures" / "volume-benchmarks.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # stdout 同文输出，便于调用方直接消费
    print(json.dumps(doc, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
