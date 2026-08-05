"""v0.6.1 体积基准种子脚本的数据质量回归测试。

基准网格保留角落 2×2×2 NoData（渲染口径），但 4×4×4 抽样子集不得把
未声明的 NaN 写进建模输入：抽样后排除非有限单元、``is_numeric_valid``
按真实有限性计算、profile 的有效/无效计数按帧真实统计。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from geomodeling.platform import PlatformRuntime, tables

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SEED_PATH = _REPO_ROOT / "web" / "e2e-live" / "fixtures" / "seed_volume_benchmarks.py"


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("seed_volume_benchmarks", _SEED_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def seed_module():
    return _load_seed_module()


def make_runtime(tmp_path: Path) -> PlatformRuntime:
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    return runtime


def test_benchmark_grid_keeps_nodata_corner(seed_module):
    """渲染网格口径不变：角落 2×2×2 为 NoData 且值置 NaN。"""

    _axes, values, is_nodata = seed_module._benchmark_grid(32)
    assert int(is_nodata.sum()) == 8
    assert np.isnan(values[is_nodata]).all()
    assert np.isfinite(values[~is_nodata]).all()


def test_sampled_subset_excludes_nodata_cells(seed_module, tmp_path):
    """抽样子集全部有限，is_numeric_valid 按真实有限性逐行计算。"""

    runtime = make_runtime(tmp_path)
    for n in seed_module.GRID_SIZES:
        axes, values, _is_nodata = seed_module._benchmark_grid(n)
        _src_sha, _std_sha, _src_path, standardized_path, _frame = (
            seed_module._write_source_and_standardized(runtime, f"case-{n}", f"ds-{n}", axes, values)
        )
        frame = pd.read_parquet(standardized_path)
        # 唯一命中 NoData 角落的抽样点 (0,0,0) 被排除：64 → 63
        assert len(frame) == 63
        assert np.isfinite(frame["value"].to_numpy(dtype="float64")).all()
        declared = frame["is_numeric_valid"].to_numpy(dtype=bool)
        finite = np.isfinite(frame["value"].to_numpy(dtype="float64"))
        assert (declared == finite).all()
        assert declared.all()


def test_seeded_profile_counts_reflect_frame(seed_module, tmp_path):
    """完整归属链落库后，profile 质量计数与标准化帧真实统计一致。"""

    runtime = make_runtime(tmp_path)
    info = seed_module._seed_size(runtime, 32)
    with runtime.session() as session:
        dataset = session.get(tables.DatasetVersion, info["dataset_version_id"])
        profile = tables.loads_canonical(dataset.profile_json)
    frame = pd.read_parquet(dataset.standardized_path)
    assert profile["row_count"] == len(frame) == 63
    assert profile["valid_row_count"] == int(frame["is_numeric_valid"].sum()) == 63
    assert profile["invalid_row_count"] == 0
    assert np.isfinite(frame["value"].to_numpy(dtype="float64")).all()
    # 网格工件仍保留 8 个 NoData 单元（渲染基准口径不受影响）
    assert info["nodata_count"] == 8
