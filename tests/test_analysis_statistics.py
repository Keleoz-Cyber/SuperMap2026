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
    anomaly_thresholds,
    axis_trends,
    depth_slice_ratios,
    gradient_summary,
    histogram,
    log10_histogram,
    log10_positive,
    profile_axis,
    quantiles,
    spatial_anomaly_summary,
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
    "value_unit": "Ω·m",
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


# ---------------------------------------------------------------------------
# Task 6：微震 axis_trends（X/Y/Z 逐轴分箱均值/中位数趋势，profile_axis 口径）
# ---------------------------------------------------------------------------


def test_axis_trends_returns_per_axis_binned_trends_with_identity_and_counts():
    frame = _microseismic_frame()
    trends = axis_trends(frame, MICROSEISMIC_MAPPING, bins=8)
    assert [trend.axis for trend in trends] == ["x", "y", "z"]
    for trend in trends:
        assert trend.sample_count == 10  # 无效/非有限行守恒排除
        assert len(trend.bins) == 8
        assert sum(item.count for item in trend.bins) == trend.sample_count
    z_means = [item.mean for item in trends[2].bins if item.count]
    assert z_means == sorted(z_means)  # Vx 随深度单调增大的趋势被恢复


def test_axis_trends_is_bit_deterministic_and_serializes_finite():
    frame = _microseismic_frame()
    first = [trend.model_dump_json() for trend in axis_trends(frame, MICROSEISMIC_MAPPING)]
    second = [trend.model_dump_json() for trend in axis_trends(frame, MICROSEISMIC_MAPPING)]
    assert first == second
    for payload in first:
        _assert_json_finite(payload)


# ---------------------------------------------------------------------------
# Task 6：微震 gradient（相邻 XY 网格单元均值差分幅值的有限统计）
# ---------------------------------------------------------------------------


def test_gradient_summary_counts_finite_neighbor_diffs_and_preserves_excluded():
    frame = _standardized_frame(
        [
            (0.0, 0.0, 0.0, 1.0, True),
            (1.0, 0.0, 0.0, 3.0, True),
            (0.0, 1.0, 0.0, 5.0, True),
            (1.0, 1.0, 0.0, 9.0, True),
            (2.0, 2.0, 0.0, float("nan"), False),  # 无效行不进入任何格
        ]
    )
    summary = gradient_summary(frame, RESISTIVITY_MAPPING, grid_size=2)
    # 2×2 单元均值 1/3/5/9；相邻对：横向 |1-3|、|5-9|，纵向 |1-5|、|3-9|
    assert summary.pair_count == 4
    assert summary.excluded_pair_count == 0
    assert summary.count == 4
    assert summary.mean == pytest.approx(4.0)
    assert summary.max == pytest.approx(6.0)
    assert summary.p95 == pytest.approx(
        float(np.quantile([2.0, 4.0, 4.0, 6.0], 0.95, method="linear"))
    )


def test_gradient_summary_isolated_cells_keep_excluded_count_without_nan():
    frame = _standardized_frame([(0.0, 0.0, 0.0, 1.0, True)])
    summary = gradient_summary(frame, RESISTIVITY_MAPPING, grid_size=4)
    assert summary.count == 0
    assert summary.mean is None and summary.p95 is None and summary.max is None
    assert summary.excluded_pair_count == summary.pair_count > 0
    _assert_json_finite(summary.model_dump_json())


def test_gradient_summary_is_bit_deterministic():
    frame = _microseismic_frame()
    first = gradient_summary(frame, MICROSEISMIC_MAPPING).model_dump_json()
    second = gradient_summary(frame, MICROSEISMIC_MAPPING).model_dump_json()
    assert first == second
    _assert_json_finite(first)


# ---------------------------------------------------------------------------
# Task 6：分位阈值（depth_slices / spatial_anomaly 共用同一阈值机制）
# ---------------------------------------------------------------------------


def test_anomaly_thresholds_come_from_valid_quantiles_with_source():
    values = [float(v) for v in range(1, 101)]
    thresholds = anomaly_thresholds(values)
    assert thresholds.high == pytest.approx(
        float(np.quantile(values, 0.75, method="linear"))
    )
    assert thresholds.low == pytest.approx(
        float(np.quantile(values, 0.25, method="linear"))
    )
    assert thresholds.source  # 阈值来源字段必须存在
    assert "p75" in thresholds.method and "p25" in thresholds.method

    with pytest.raises(PlatformError) as excinfo:
        anomaly_thresholds([float("nan")])
    assert excinfo.value.code == ANALYSIS_EMPTY_COMMON_VALID


# ---------------------------------------------------------------------------
# Task 6：电阻率 log10 分箱（仅严格正值进 log10，排除计数保留）
# ---------------------------------------------------------------------------


def test_log10_histogram_bins_only_strictly_positive_and_preserves_excluded_count():
    bins, excluded = log10_histogram(
        [1.0, 10.0, 100.0, 0.0, -1.0, float("nan")], bins=4
    )
    assert excluded == 3  # 0.0、-1.0、NaN 全部排除且计数保留
    assert bins is not None
    assert len(bins) == 4
    assert sum(item.count for item in bins) == 3
    assert bins[0].lower == pytest.approx(0.0)  # log10(1)
    assert bins[-1].upper == pytest.approx(2.0)  # log10(100)


def test_log10_histogram_without_positive_values_returns_none_with_count():
    bins, excluded = log10_histogram([0.0, -2.0, float("nan")], bins=4)
    assert bins is None
    assert excluded == 3


# ---------------------------------------------------------------------------
# Task 6：电阻率 depth_slices（逐 Z 层超阈面积/体积占比，分位阈值来源明示）
# ---------------------------------------------------------------------------


def test_depth_slice_ratios_compute_per_layer_threshold_ratios():
    rows = [
        (0.0, 0.0, float(layer), float(layer * 4 + i + 1), True)
        for layer in range(4)
        for i in range(4)
    ]
    frame = _standardized_frame(rows)  # 4 个 Z 层，每层 4 个样本，值 1..16
    summary = depth_slice_ratios(frame, RESISTIVITY_MAPPING, bins=4)
    assert summary.slice_count == 4
    assert len(summary.slices) == 4

    values = [float(v) for v in range(1, 17)]
    thresholds = summary.thresholds
    assert thresholds.high == pytest.approx(
        float(np.quantile(values, 0.75, method="linear"))
    )
    assert thresholds.low == pytest.approx(
        float(np.quantile(values, 0.25, method="linear"))
    )
    assert thresholds.source  # 阈值来源字段必须存在
    assert sum(s.high_count for s in summary.slices) == sum(
        1 for v in values if v >= thresholds.high
    )
    assert sum(s.low_count for s in summary.slices) == sum(
        1 for v in values if v <= thresholds.low
    )
    # 顶层（值 13..16）全部超 p75=12.25，底层（值 1..4）全部低于 p25=4.75
    assert summary.slices[-1].count == 4
    assert summary.slices[-1].high_ratio == pytest.approx(1.0)
    assert summary.slices[-1].low_ratio == pytest.approx(0.0)
    assert summary.slices[0].low_ratio == pytest.approx(1.0)


def test_depth_slice_ratios_empty_layer_has_null_ratio_and_stays_finite():
    frame = _standardized_frame(
        [
            (0.0, 0.0, 0.0, 1.0, True),
            (0.0, 0.0, 0.0, 2.0, True),
            (0.0, 0.0, 10.0, 100.0, True),
        ]
    )
    summary = depth_slice_ratios(frame, RESISTIVITY_MAPPING, bins=4)
    empty = [s for s in summary.slices if s.count == 0]
    assert empty
    for slice_ in empty:
        assert slice_.high_ratio is None and slice_.low_ratio is None
    _assert_json_finite(summary.model_dump_json())


def test_depth_slice_ratios_is_bit_deterministic():
    frame = _microseismic_frame()
    first = depth_slice_ratios(frame, MICROSEISMIC_MAPPING).model_dump_json()
    second = depth_slice_ratios(frame, MICROSEISMIC_MAPPING).model_dump_json()
    assert first == second
    _assert_json_finite(first)


# ---------------------------------------------------------------------------
# Task 6：spatial_anomaly（XY 网格高/低值区域聚合，体积占比与阈值来源）
# ---------------------------------------------------------------------------


def test_spatial_anomaly_summary_classifies_regions_and_volume_ratios():
    frame = _standardized_frame(
        [
            (0.0, 0.0, 0.0, 1.0, True),
            (1.0, 0.0, 0.0, 2.0, True),
            (0.0, 1.0, 0.0, 3.0, True),
            (1.0, 1.0, 0.0, 4.0, True),
        ]
    )
    summary = spatial_anomaly_summary(frame, RESISTIVITY_MAPPING, grid_size=2)
    assert summary.grid_size == 2
    assert summary.cell_count == 4
    assert len(summary.bins) == 4
    # p75=3.25 / p25=1.75：均值 4 的单元为高值区域，均值 1 的单元为低值区域
    # （2×2 网格边界为 0.5，单元键为分箱下界）
    regions = {(item.x_lower, item.y_lower): item.region for item in summary.bins}
    assert regions[(0.0, 0.0)] == "low"
    assert regions[(0.5, 0.5)] == "high"
    assert regions[(0.5, 0.0)] == "normal"
    assert regions[(0.0, 0.5)] == "normal"
    assert summary.non_empty_cell_count == 4
    assert summary.high_cell_count == 1
    assert summary.low_cell_count == 1
    assert summary.high_point_count == 1
    assert summary.low_point_count == 1
    assert summary.high_volume_ratio == pytest.approx(0.25)
    assert summary.low_volume_ratio == pytest.approx(0.25)
    assert summary.thresholds.source  # 阈值来源字段必须存在
    assert "p75" in summary.thresholds.method


def test_spatial_anomaly_summary_is_bit_deterministic_and_finite():
    frame = _microseismic_frame()
    first = spatial_anomaly_summary(frame, MICROSEISMIC_MAPPING).model_dump_json()
    second = spatial_anomaly_summary(frame, MICROSEISMIC_MAPPING).model_dump_json()
    assert first == second
    _assert_json_finite(first)


def test_spatial_anomaly_thresholds_use_cell_mean_quantiles_not_sample_quantiles():
    """致密采样回归：样本值方差很大但单元均值平滑时，样本级阈值会把全部
    单元判为 normal（真实电阻率实测高/低占比恒 0%）；区域口径必须基于
    非空单元均值自身的 p75/p25，保证真实数据上区域可见且来源如实标注。
    """

    rows = []
    # 4 个 XY 柱；每柱内部样本值剧烈交替 ±10（样本方差大），但柱均值聚拢
    # 在 19–22：样本级 p75/p25（≈30.25/≈11.75）会把全部柱均值判为 normal，
    # 正是真实电阻率 17,549 行实测高/低占比恒 0% 的病理形态。
    for col, base in enumerate((19.0, 20.0, 21.0, 22.0)):
        for layer in range(20):
            rows.append((float(col), 0.0, float(layer), base + (10.0 if layer % 2 else -10.0), True))
    frame = _standardized_frame(rows)
    summary = spatial_anomaly_summary(frame, RESISTIVITY_MAPPING, grid_size=4)
    assert summary.thresholds.source == "cell_mean_quantiles_p25_p75"
    assert "单元均值" in summary.thresholds.method
    assert "p75" in summary.thresholds.method
    # 单元均值 19/20/21/22 → 最高柱为高值区域、最低柱为低值区域
    by_x = sorted((item.x_lower, item.region) for item in summary.bins if item.count > 0)
    assert len(by_x) == 4
    assert by_x[0][1] == "low"
    assert by_x[-1][1] == "high"
    assert summary.high_cell_count >= 1
    assert summary.low_cell_count >= 1
    assert summary.high_volume_ratio is not None and summary.high_volume_ratio > 0
    # 对照：样本级 p75/p25 会把这四个聚拢的柱均值全部判为 normal（旧行为）
    sample_values = frame["value"].to_numpy(dtype="float64")
    sample_q = anomaly_thresholds(sample_values[np.isfinite(sample_values)])
    assert all(sample_q.low < mean < sample_q.high for mean in (19.0, 20.0, 21.0, 22.0))


def test_spatial_anomaly_degenerate_cell_means_mark_all_normal():
    """单元均值无方差（p75==p25）时不伪造高/低区域：全部非空单元 normal。"""

    rows = [(float(i % 4), float(i // 4), 0.0, 7.0, True) for i in range(16)]
    frame = _standardized_frame(rows)
    summary = spatial_anomaly_summary(frame, RESISTIVITY_MAPPING, grid_size=4)
    assert summary.high_cell_count == 0
    assert summary.low_cell_count == 0
    assert summary.high_volume_ratio == 0.0
    assert summary.low_volume_ratio == 0.0
    regions = {item.region for item in summary.bins}
    assert regions == {"normal"}



# ---------------------------------------------------------------------------
# v0.8.0 第三批 Task 8：瓦斯形态帧（稀疏散点）阈值来源与空态合同
# ---------------------------------------------------------------------------

# 与 tests/test_analysis_profiles.py 一致的瓦斯真实 mapping 形态事实
GAS_MAPPING = {
    "dimension": "3d",
    "x": "X",
    "y": "Y",
    "z": "Z",
    "value": "CH4_content",
    "value_name": "CH4_content",
    "value_unit": "ml/g",
    "coordinate_kind": "local_linear",
}


def _gas_sparse_frame() -> pd.DataFrame:
    """瓦斯形态稀疏帧：4 个互不相邻的 XY 柱（网格化后无相邻非空单元对），
    Z 值只落在 3 个深度（16 层分箱必产生空层），CH4 含量逐点递增。"""

    return _standardized_frame(
        [
            (0.0, 0.0, 0.0, 1.0, True),
            (0.0, 0.0, 1.0, 2.0, True),
            (10.0, 0.0, 0.0, 3.0, True),
            (10.0, 0.0, 1.0, 4.0, True),
            (0.0, 10.0, 5.0, 5.0, True),
            (10.0, 10.0, 5.0, 6.0, True),
        ]
    )


def test_gas_depth_slices_sample_quantile_thresholds_and_empty_layers_null():
    """瓦斯 depth_slices：阈值为样本级（有效值）分位统计；空层占比 null 且
    序列化绝无 NaN/Infinity。"""

    summary = depth_slice_ratios(_gas_sparse_frame(), GAS_MAPPING, bins=16)
    assert summary.thresholds.source == "valid_value_quantiles_p25_p75"
    assert "有效值" in summary.thresholds.method
    empty = [slice_ for slice_ in summary.slices if slice_.count == 0]
    assert empty, "Z 只含 3 个深度，16 层分箱必须产生空层"
    for slice_ in empty:
        assert slice_.high_ratio is None and slice_.low_ratio is None
    _assert_json_finite(summary.model_dump_json())


def test_gas_spatial_anomaly_cell_mean_thresholds_without_normative_wording():
    """瓦斯 spatial_anomaly：阈值为非空单元均值 p25/p75 分位统计；来源与
    方法文案只含可计算表述，绝无「危险/安全/爆炸/突出」规范判断词。"""

    summary = spatial_anomaly_summary(_gas_sparse_frame(), GAS_MAPPING)
    assert summary.thresholds.source == "cell_mean_quantiles_p25_p75"
    assert "单元均值" in summary.thresholds.method
    for term in ("危险", "安全", "爆炸", "突出"):
        assert term not in summary.thresholds.source
        assert term not in summary.thresholds.method
    # 4 个非空单元均值 1.5/3.5/5/6：最高柱为高含量区域、最低柱为低含量区域
    non_empty = sorted(
        (cell.mean, cell.region) for cell in summary.bins if cell.count > 0
    )
    assert len(non_empty) == 4
    assert non_empty[0][1] == "low"
    assert non_empty[-1][1] == "high"
    assert summary.high_cell_count == 1
    assert summary.low_cell_count == 1
    _assert_json_finite(summary.model_dump_json())


def test_gas_sparse_frame_gradient_null_stats_and_finite_json():
    """瓦斯稀疏帧梯度：无相邻非空单元对 → count=0 且统计字段 null（解释性
    空态，绝不以 NaN 或 0 伪造），排除对计数保留且守恒。"""

    summary = gradient_summary(_gas_sparse_frame(), GAS_MAPPING)
    assert summary.count == 0
    assert summary.mean is None and summary.p95 is None and summary.max is None
    assert summary.excluded_pair_count == summary.pair_count > 0
    _assert_json_finite(summary.model_dump_json())
