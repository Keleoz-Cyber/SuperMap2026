"""v0.8.0 第二批 Task 2：有限统计与质量计算合同测试。

断言（计划 Task 2 与设计 §5/§6）：统计只覆盖「声明有效且值有限」的公共
有效集（与 ``modeling.runner._finite_valid_mask`` 同口径），排除行计数保留；
空公共有效集 fail-closed 抛类型化 ``ANALYSIS_EMPTY_COMMON_VALID``（409）；
分箱与网格定义确定性（数据范围 + 固定格数），两次调用逐位一致；输出全部
走 Task 1 schemas 骨架，序列化绝不含 NaN/Infinity（空分箱统计用 None）。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from geomodeling.analysis.statistics import (
    ANALYSIS_AXIS_INVALID,
    ANALYSIS_EMPTY_COMMON_VALID,
    aggregate_spatial,
    histogram,
    log10_positive,
    profile_axis,
    quantiles,
    summarize_numeric,
    summarize_quality,
)
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import FieldMapping

# 与 tests/test_analysis_profiles.py 一致的真实 mapping 形态事实
RESISTIVITY_MAPPING = {
    "dimension": "3d",
    "x": "X",
    "y": "Y",
    "z": "Z",
    "value": "RHO",
    "value_name": "RHO",
    "value_unit": "RHO 单位待来源确认",
    "coordinate_kind": "local_linear",
}

MICROSEISMIC_MAPPING = {
    "dimension": "3d",
    "x": "X_LOCAL_M",
    "y": "Y_LOCAL_M",
    "z": "Z_LOCAL_M",
    "value": "VX_KM_S",
    "value_name": "Vx",
    "value_unit": "km/s",
    "coordinate_kind": "local_linear",
}

TWO_D_MAPPING = {
    "dimension": "2d",
    "x": "X",
    "y": "Y",
    "z": None,
    "value": "VALUE",
    "value_name": "VALUE",
    "value_unit": None,
    "coordinate_kind": "local_linear",
}


def _standardized_frame(rows: list[tuple[float, float, float, float, bool]]) -> pd.DataFrame:
    """构造标准化 Parquet 同形态帧（source_row/x/y/z/value/is_numeric_valid）。"""

    return pd.DataFrame(
        {
            "source_row": pd.Series(range(1, len(rows) + 1), dtype="int64"),
            "x": pd.Series([row[0] for row in rows], dtype="float64"),
            "y": pd.Series([row[1] for row in rows], dtype="float64"),
            "z": pd.Series([row[2] for row in rows], dtype="float64"),
            "value": pd.Series([row[3] for row in rows], dtype="float64"),
            "is_numeric_valid": pd.Series([row[4] for row in rows], dtype=bool),
        }
    )


def _microseismic_frame() -> pd.DataFrame:
    """确定性微震形态帧：Vx 随 z 单调增大，含一行声明无效与一行非有限值。"""

    rows = [
        (float(i % 4), float(i % 3), float(i), 3.0 + 0.1 * i, True) for i in range(10)
    ]
    rows.append((1.0, 1.0, 5.0, float("nan"), True))  # 声明有效但值非有限
    rows.append((2.0, 2.0, 6.0, 4.0, False))  # 声明无效
    return _standardized_frame(rows)


def _assert_json_finite(payload: str) -> None:
    assert "NaN" not in payload
    assert "Infinity" not in payload


# ---------------------------------------------------------------------------
# 基础统计（计划 Step 1）
# ---------------------------------------------------------------------------


def test_numeric_summary_excludes_non_finite_values_from_truth_and_prediction():
    result = summarize_numeric([1.0, float("nan"), 3.0, float("inf")])
    assert result.count == 2
    assert result.min == 1.0
    assert result.max == 3.0


def test_histogram_has_deterministic_32_bins_and_total_count():
    result = histogram([0.0, 1.0, 2.0, 3.0], bins=32)
    assert len(result) == 32
    assert sum(item.count for item in result) == 4


def test_numeric_summary_statistics_and_quantiles_match_platform_convention():
    values = [float(v) for v in range(1, 101)]
    result = summarize_numeric(values)
    assert result.count == 100
    assert result.min == 1.0
    assert result.max == 100.0
    assert result.mean == pytest.approx(50.5)
    assert result.median == pytest.approx(50.5)
    # 样本标准差 ddof=1（与 microseismic/aggregation、exports 既有口径一致）
    assert result.std == pytest.approx(float(np.std(values, ddof=1)))
    summary = result.quantiles
    assert summary is not None
    for field, level in (("p05", 0.05), ("p25", 0.25), ("p50", 0.5), ("p75", 0.75), ("p95", 0.95)):
        assert getattr(summary, field) == pytest.approx(
            float(np.quantile(values, level, method="linear"))
        )
    assert summary.p50 == result.median


def test_numeric_summary_accepts_series_and_ndarray_identically():
    base = summarize_numeric([1.0, 2.0, 3.0])
    assert summarize_numeric(pd.Series([1.0, 2.0, 3.0])).model_dump() == base.model_dump()
    assert summarize_numeric(np.array([1.0, 2.0, 3.0])).model_dump() == base.model_dump()


def test_numeric_summary_single_finite_value_has_no_sample_std():
    result = summarize_numeric([7.5])
    assert result.count == 1
    assert result.std is None  # ddof=1 在 count=1 时未定义，绝不以 NaN 占位
    assert result.min == result.max == result.mean == result.median == 7.5
    assert result.quantiles is not None
    assert result.quantiles.p50 == 7.5


def test_quantiles_helper_returns_p05_to_p95_and_rejects_empty():
    values = [0.0, 10.0, 20.0, 30.0, 40.0]
    summary = quantiles(values)
    assert summary.p05 == pytest.approx(float(np.quantile(values, 0.05, method="linear")))
    assert summary.p50 == pytest.approx(20.0)
    assert summary.p95 == pytest.approx(float(np.quantile(values, 0.95, method="linear")))
    with pytest.raises(PlatformError) as excinfo:
        quantiles([float("nan")])
    assert excinfo.value.code == ANALYSIS_EMPTY_COMMON_VALID


# ---------------------------------------------------------------------------
# 全无效输入：类型化 fail-closed
# ---------------------------------------------------------------------------


def test_numeric_summary_all_invalid_raises_typed_empty_common_valid():
    with pytest.raises(PlatformError) as excinfo:
        summarize_numeric([float("nan"), float("inf"), float("-inf")])
    assert excinfo.value.code == ANALYSIS_EMPTY_COMMON_VALID
    assert excinfo.value.http_status == 409

    with pytest.raises(PlatformError) as excinfo_empty:
        summarize_numeric([])
    assert excinfo_empty.value.code == ANALYSIS_EMPTY_COMMON_VALID
    assert excinfo_empty.value.http_status == 409


def test_histogram_and_spatial_and_profile_reject_empty_common_valid_set():
    frame = _standardized_frame(
        [
            (0.0, 0.0, 0.0, float("nan"), True),
            (1.0, 1.0, 1.0, 2.0, False),
        ]
    )
    for invoke in (
        lambda: histogram([float("nan")]),
        lambda: aggregate_spatial(frame, RESISTIVITY_MAPPING),
        lambda: profile_axis(frame, RESISTIVITY_MAPPING, "x"),
    ):
        with pytest.raises(PlatformError) as excinfo:
            invoke()
        assert excinfo.value.code == ANALYSIS_EMPTY_COMMON_VALID
        assert excinfo.value.http_status == 409


# ---------------------------------------------------------------------------
# 直方图分箱
# ---------------------------------------------------------------------------


def test_histogram_constant_values_use_deterministic_expanded_range():
    result = histogram([4.2, 4.2, 4.2])
    assert len(result) == 32
    assert sum(item.count for item in result) == 3
    for item in result:
        assert math.isfinite(item.lower) and math.isfinite(item.upper)
        assert item.lower < item.upper  # 恒定值边界确定扩展，绝不退化为 NaN


def test_histogram_is_bit_deterministic_across_calls():
    values = np.linspace(0.0, 10.0, 57).tolist() + [float("nan"), float("inf")]
    first = histogram(values)
    second = histogram(values)
    assert [item.model_dump() for item in first] == [item.model_dump() for item in second]
    # 上边界点落入最后一格（计数守恒）
    assert sum(item.count for item in first) == 57


# ---------------------------------------------------------------------------
# 数据质量摘要
# ---------------------------------------------------------------------------


def test_quality_summary_uses_declared_and_finite_valid_semantics():
    frame = _standardized_frame(
        [
            (0.0, 0.0, 0.0, 1.0, True),
            (1.0, 0.0, 0.0, float("nan"), True),  # 声明有效但值非有限 → 排除且计数保留
            (2.0, 0.0, 0.0, 3.0, False),  # 声明无效
            (120.0, 440.0, 813.4, 4.0, True),
        ]
    )
    summary = summarize_quality(frame, RESISTIVITY_MAPPING)
    assert summary.row_count == 4
    assert summary.valid_count == 2
    assert summary.invalid_count == 2
    assert summary.bounds == {
        "x": (0.0, 120.0),
        "y": (0.0, 440.0),
        "z": (0.0, 813.4),
    }


def test_quality_summary_counts_duplicate_coordinates():
    frame = _standardized_frame(
        [
            (0.0, 0.0, 0.0, 1.0, True),
            (0.0, 0.0, 0.0, 2.0, True),  # 坐标重复（值不同，仍计重复坐标）
            (1.0, 1.0, 1.0, 3.0, True),
            (2.0, 2.0, 2.0, float("nan"), False),  # 无效行不参与重复判定
        ]
    )
    summary = summarize_quality(frame, RESISTIVITY_MAPPING)
    assert summary.duplicate_coordinate_count == 1


def test_quality_summary_all_invalid_preserves_counts_without_bounds():
    frame = _standardized_frame(
        [
            (0.0, 0.0, 0.0, float("nan"), True),
            (1.0, 1.0, 1.0, 2.0, False),
        ]
    )
    summary = summarize_quality(frame, RESISTIVITY_MAPPING)
    assert summary.row_count == 2
    assert summary.valid_count == 0
    assert summary.invalid_count == 2
    assert summary.duplicate_coordinate_count == 0
    assert summary.bounds is None


def test_quality_summary_2d_mapping_omits_z_bounds():
    frame = _standardized_frame(
        [
            (0.0, 10.0, float("nan"), 1.0, True),
            (5.0, 20.0, float("nan"), 2.0, True),
        ]
    )
    summary = summarize_quality(frame, TWO_D_MAPPING)
    assert summary.bounds == {"x": (0.0, 5.0), "y": (10.0, 20.0)}


def test_quality_summary_accepts_field_mapping_instance():
    frame = _standardized_frame([(0.0, 0.0, 0.0, 1.0, True)])
    mapping = FieldMapping.model_validate(RESISTIVITY_MAPPING)
    summary = summarize_quality(frame, mapping)
    assert summary.valid_count == 1
    assert summary.bounds == {"x": (0.0, 0.0), "y": (0.0, 0.0), "z": (0.0, 0.0)}


# ---------------------------------------------------------------------------
# 电阻率 log 分布前处理（strictly positive 才进 log10，排除计数保留）
# ---------------------------------------------------------------------------


def test_log10_positive_keeps_strictly_positive_finite_values_and_counts_excluded():
    transformed, excluded = log10_positive(
        [1.0, 10.0, 100.0, 0.0, -5.0, float("nan"), float("inf")]
    )
    assert list(transformed) == pytest.approx([0.0, 1.0, 2.0])
    assert excluded == 4  # 0.0、-5.0、NaN、Inf 全部排除且计数保留


def test_log10_positive_real_resistivity_range_roundtrips():
    values = np.geomspace(1.4, 133.1, 25)
    transformed, excluded = log10_positive(values)
    assert excluded == 0
    assert len(transformed) == 25
    assert list(transformed) == pytest.approx(list(np.log10(values)))


# ---------------------------------------------------------------------------
# 空间聚合（XY 平面确定性格网）
# ---------------------------------------------------------------------------


def test_aggregate_spatial_places_points_in_deterministic_bins_and_conserves_counts():
    frame = _standardized_frame(
        [
            (0.5, 0.5, 0.0, 1.0, True),
            (1.5, 0.5, 0.0, 3.0, True),
            (0.5, 1.5, 0.0, 5.0, True),
            (3.5, 3.5, 0.0, 7.0, True),
            (2.0, 2.0, 0.0, float("nan"), False),  # 无效行不进入任何格
        ]
    )
    summary = aggregate_spatial(frame, RESISTIVITY_MAPPING, grid_size=4)
    assert summary.grid_size == 4
    assert summary.cell_count == 16
    assert len(summary.bins) == 16
    assert sum(item.count for item in summary.bins) == 4
    # 格网定义 = 数据范围 + 固定格数；bounds 为真实数据范围（非扩展边界）
    assert summary.bounds == {"x": (0.5, 3.5), "y": (0.5, 3.5)}
    first = summary.bins[0]
    assert (first.x_lower, first.y_lower) == (0.5, 0.5)

    target = next(
        item
        for item in summary.bins
        if item.x_lower <= 0.5 < item.x_upper and item.y_lower <= 0.5 < item.y_upper
    )
    assert target.count == 1
    assert target.mean == pytest.approx(1.0)

    empty = [item for item in summary.bins if item.count == 0]
    assert empty
    assert all(item.mean is None for item in empty)  # 空格均值 None，绝不 NaN


def test_aggregate_spatial_upper_edge_points_land_in_last_cell():
    frame = _standardized_frame(
        [
            (0.0, 0.0, 0.0, 1.0, True),
            (4.0, 4.0, 0.0, 2.0, True),
        ]
    )
    summary = aggregate_spatial(frame, RESISTIVITY_MAPPING, grid_size=4)
    last = next(item for item in summary.bins if item.x_upper == 4.0 and item.y_upper == 4.0)
    assert last.count == 1
    assert last.mean == pytest.approx(2.0)
    first = summary.bins[0]
    assert first.count == 1
    assert first.mean == pytest.approx(1.0)


def test_aggregate_spatial_is_bit_deterministic_across_calls():
    frame = _microseismic_frame()
    first = aggregate_spatial(frame, MICROSEISMIC_MAPPING).model_dump_json()
    second = aggregate_spatial(frame, MICROSEISMIC_MAPPING).model_dump_json()
    assert first == second


# ---------------------------------------------------------------------------
# 逐轴剖面（微震 X/Y/Z 趋势基础函数）
# ---------------------------------------------------------------------------


def test_profile_axis_recovers_microseismic_depth_trend():
    frame = _microseismic_frame()
    summary = profile_axis(frame, MICROSEISMIC_MAPPING, "z", bins=5)
    assert summary.axis == "z"
    assert len(summary.bins) == 5
    assert sum(item.count for item in summary.bins) == 10  # 无效/非有限行守恒排除
    means = [item.mean for item in summary.bins]
    assert all(value is not None for value in means)
    assert means == sorted(means)  # Vx 随深度单调增大的趋势被恢复
    medians = [item.median for item in summary.bins]
    assert all(value is not None for value in medians)


def test_profile_axis_supports_each_microseismic_axis():
    frame = _microseismic_frame()
    for axis in ("x", "y", "z"):
        summary = profile_axis(frame, MICROSEISMIC_MAPPING, axis, bins=8)
        assert summary.axis == axis
        assert len(summary.bins) == 8
        assert sum(item.count for item in summary.bins) == 10


def test_profile_axis_is_bit_deterministic_across_calls():
    frame = _microseismic_frame()
    first = profile_axis(frame, MICROSEISMIC_MAPPING, "x").model_dump_json()
    second = profile_axis(frame, MICROSEISMIC_MAPPING, "x").model_dump_json()
    assert first == second


def test_profile_axis_rejects_unknown_axis_and_z_on_2d_mapping():
    frame = _microseismic_frame()
    with pytest.raises(PlatformError) as excinfo:
        profile_axis(frame, MICROSEISMIC_MAPPING, "w")
    assert excinfo.value.code == ANALYSIS_AXIS_INVALID
    assert excinfo.value.http_status == 400

    with pytest.raises(PlatformError) as excinfo_2d:
        profile_axis(frame, TWO_D_MAPPING, "z")
    assert excinfo_2d.value.code == ANALYSIS_AXIS_INVALID


# ---------------------------------------------------------------------------
# 序列化绝不含 NaN/Infinity（模型层兜底之外的源头断言）
# ---------------------------------------------------------------------------


def test_all_outputs_serialize_without_nan_or_infinity():
    frame = _microseismic_frame()
    quality = summarize_quality(frame, MICROSEISMIC_MAPPING)
    numeric = summarize_numeric(frame["value"])
    spatial = aggregate_spatial(frame, MICROSEISMIC_MAPPING, grid_size=8)  # 含空格
    profile = profile_axis(frame, MICROSEISMIC_MAPPING, "y", bins=8)
    constant_hist = histogram([2.5, 2.5])  # 恒定值扩展路径

    payloads = [quality.model_dump_json(), numeric.model_dump_json()]
    payloads.extend(item.model_dump_json() for item in histogram(frame["value"]))
    payloads.extend(item.model_dump_json() for item in constant_hist)
    payloads.append(spatial.model_dump_json())
    payloads.append(profile.model_dump_json())
    for payload in payloads:
        _assert_json_finite(payload)
