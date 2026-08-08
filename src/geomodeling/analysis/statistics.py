"""v0.8.0 第二批 Task 2：有限统计与质量计算服务（设计 §5/§6）。

只读计算；输入为标准化 Parquet 帧（``source_row/x/y/z/value/is_numeric_valid``，
见 ``platform.ingest.STANDARDIZED_SCHEMA``）。有效行口径与
``modeling.runner._finite_valid_mask`` 完全一致：``is_numeric_valid`` 声明有效
且 ``value`` 有限——声明有效但值为 NaN/Inf 的行绝不进入统计，排除行计数保留
（``QualitySummary.invalid_count``；``summarize_numeric`` 的排除数 =
输入长度 − ``count``）。

空公共有效集 fail-closed：抛类型化 ``ANALYSIS_EMPTY_COMMON_VALID``（409），
绝不返回 ``null`` 堆叠的伪成功结果。分箱与网格定义确定性（数据范围 +
固定格数，恒定值范围对称扩展 ±0.5），同一输入两次调用逐位一致。输出全部
为 ``schemas.py`` 骨架模型：统计源头绝不产生 NaN/Inf（空分箱统计、
count=1 的样本标准差一律用 ``None`` 占位）。

Task 6 追加专属计算（同样遵守上述口径）：微震 ``axis_trends``（逐轴分箱
趋势，复用 ``profile_axis``）与 ``gradient_summary``（相邻 XY 网格单元均值
差分幅值有限统计）；电阻率/微震共用的分位阈值 ``anomaly_thresholds``
（有效值 p75/p25，阈值来源必须明示）、``depth_slice_ratios``（逐 Z 层超阈
占比）、``spatial_anomaly_summary``（XY 网格高/低值区域聚合）与
``log10_histogram``（仅严格正值进 log10，排除计数保留）。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Union

import numpy as np
import pandas as pd

from geomodeling.analysis.schemas import (
    AnomalyThresholds,
    AxisTrendSummary,
    DepthSliceBin,
    DepthSliceSummary,
    GradientSummary,
    HistogramBin,
    NumericSummary,
    ProfileSliceBin,
    ProfileSliceSummary,
    QualitySummary,
    QuantileSummary,
    SpatialAnomalyBin,
    SpatialAnomalySummary,
    SpatialBin,
    SpatialSummary,
)
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import FieldMapping

__all__ = [
    "ANALYSIS_AXIS_INVALID",
    "ANALYSIS_EMPTY_COMMON_VALID",
    "aggregate_spatial",
    "anomaly_thresholds",
    "axis_trends",
    "depth_slice_ratios",
    "gradient_summary",
    "histogram",
    "log10_histogram",
    "log10_positive",
    "profile_axis",
    "quantiles",
    "spatial_anomaly_summary",
    "summarize_numeric",
    "summarize_quality",
]

# 空公共有效集：类型化失败（409 Conflict，与平台 RUN_NOT_RETRYABLE 等 409 语义一致）
ANALYSIS_EMPTY_COMMON_VALID = "ANALYSIS_EMPTY_COMMON_VALID"
# 剖面轴非法或不在映射维度内（如 2D 数据请求 z 轴）
ANALYSIS_AXIS_INVALID = "ANALYSIS_AXIS_INVALID"

_QUANTILE_LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
_AXES = ("x", "y", "z")

Values = Union[Iterable[float], np.ndarray, pd.Series]
FrameMapping = Union[Mapping[str, Any], FieldMapping]


def _empty_common_valid(details: dict[str, Any] | None = None) -> PlatformError:
    return PlatformError(
        ANALYSIS_EMPTY_COMMON_VALID,
        "无有限公共有效样本，无法计算分析统计",
        details,
        http_status=409,
    )


def _coord_columns(mapping: FrameMapping) -> list[str]:
    """映射声明的坐标轴列：2D 为 x/y，3D 为 x/y/z。"""

    if isinstance(mapping, FieldMapping):
        has_z = mapping.z is not None
    elif isinstance(mapping, Mapping):
        has_z = bool(mapping.get("z"))
    else:
        has_z = False
    columns = ["x", "y"]
    if has_z:
        columns.append("z")
    return columns


def _finite_valid_mask(frame: pd.DataFrame) -> np.ndarray:
    """「声明有效且值有限」行掩膜（与 ``modeling.runner._finite_valid_mask`` 同口径）。"""

    declared = frame["is_numeric_valid"].to_numpy(dtype=bool)
    finite = np.isfinite(frame["value"].to_numpy(dtype="float64"))
    return declared & finite


def _finite_values(values: Values) -> np.ndarray:
    array = np.asarray(values, dtype="float64").ravel()
    return array[np.isfinite(array)]


def _bin_edges(low: float, high: float, bins: int) -> np.ndarray:
    """确定性格网边界：``linspace(数据范围, 固定格数)``。

    恒定值退化范围（low == high）确定性对称扩展 ±0.5，保证边界有限且
    lower < upper，绝不产生 NaN。
    """

    if low == high:
        low, high = low - 0.5, high + 0.5
    return np.linspace(low, high, bins + 1, dtype="float64")


def _bin_indices(edges: np.ndarray, coords: np.ndarray) -> np.ndarray:
    """确定性归属：右闭搜索，上边界点落入最后一格，结果裁剪到 [0, bins-1]。"""

    bins = edges.size - 1
    return np.clip(np.searchsorted(edges, coords, side="right") - 1, 0, bins - 1)


# ---------------------------------------------------------------------------
# 数据质量摘要
# ---------------------------------------------------------------------------


def summarize_quality(frame: pd.DataFrame, mapping: FrameMapping) -> QualitySummary:
    """行计数、有效/无效计数、重复坐标计数与坐标轴有限值 bounds。

    有效行口径同 runner（声明有效且值有限），排除行计数保留在
    ``invalid_count``；重复坐标按 pandas ``duplicated`` 语义（超出首次出现
    的行数，仅统计有效行，坐标列取映射维度）。全无效帧不抛错——质量摘要
    正是该状态的呈现载体，此时 ``bounds`` 为 None。
    """

    row_count = len(frame)
    valid = frame.loc[_finite_valid_mask(frame)]
    valid_count = len(valid)
    coord_cols = _coord_columns(mapping)
    duplicate_coordinate_count = (
        int(valid.duplicated(subset=coord_cols).sum()) if valid_count else 0
    )
    bounds: dict[str, tuple[float, float]] | None = None
    if valid_count:
        bounds = {
            col: (float(valid[col].min()), float(valid[col].max())) for col in coord_cols
        }
    return QualitySummary(
        row_count=row_count,
        valid_count=valid_count,
        invalid_count=row_count - valid_count,
        duplicate_coordinate_count=duplicate_coordinate_count,
        bounds=bounds,
    )


# ---------------------------------------------------------------------------
# 基础统计与分位数
# ---------------------------------------------------------------------------


def quantiles(values: Values) -> QuantileSummary:
    """p05/p25/p50/p75/p95（NumPy 线性插值，与 exports/slice_analysis 口径一致）。"""

    finite = _finite_values(values)
    if finite.size == 0:
        raise _empty_common_valid({"function": "quantiles"})
    result = np.quantile(finite, _QUANTILE_LEVELS, method="linear")
    return QuantileSummary(
        p05=float(result[0]),
        p25=float(result[1]),
        p50=float(result[2]),
        p75=float(result[3]),
        p95=float(result[4]),
    )


def summarize_numeric(values: Values) -> NumericSummary:
    """有限值基础统计：count/min/max/mean/median/std(ddof=1) + 分位数。

    只统计有限值；``count`` 即有限计数，排除计数 = 输入长度 − ``count``
    （帧级排除计数由 ``QualitySummary.invalid_count`` 保留）。样本标准差
    ddof=1 与 ``microseismic.aggregation``/``exports`` 既有口径一致；
    count=1 时 ddof=1 未定义，``std`` 为 None 而非 NaN。全无效输入抛
    ``ANALYSIS_EMPTY_COMMON_VALID``。
    """

    finite = _finite_values(values)
    count = int(finite.size)
    if count == 0:
        raise _empty_common_valid({"function": "summarize_numeric"})
    return NumericSummary(
        count=count,
        min=float(finite.min()),
        max=float(finite.max()),
        mean=float(finite.mean()),
        median=float(np.median(finite)),
        std=float(finite.std(ddof=1)) if count > 1 else None,
        quantiles=quantiles(finite),
    )


# ---------------------------------------------------------------------------
# 直方图
# ---------------------------------------------------------------------------


def histogram(values: Values, bins: int = 32) -> list[HistogramBin]:
    """确定性等宽分箱：数据范围 + 固定格数，计数总和守恒（= 有限值数）。

    恒定值范围对称扩展 ±0.5（见 ``_bin_edges``）；同一输入两次调用逐位
    一致；全无效输入抛 ``ANALYSIS_EMPTY_COMMON_VALID``。
    """

    if bins < 1:
        raise ValueError("bins 必须 >= 1")
    finite = _finite_values(values)
    if finite.size == 0:
        raise _empty_common_valid({"function": "histogram", "bins": bins})
    edges = _bin_edges(float(finite.min()), float(finite.max()), bins)
    counts = np.bincount(_bin_indices(edges, finite), minlength=bins)
    return [
        HistogramBin(lower=float(edges[i]), upper=float(edges[i + 1]), count=int(counts[i]))
        for i in range(bins)
    ]


# ---------------------------------------------------------------------------
# 空间聚合（XY 平面确定性格网）
# ---------------------------------------------------------------------------


def aggregate_spatial(
    frame: pd.DataFrame, mapping: FrameMapping, grid_size: int = 32
) -> SpatialSummary:
    """XY 平面确定性网格聚合：每格 count/mean（空格 mean 为 None）。

    网格定义 = 有效点数据范围 + 固定格数；``bounds`` 为真实数据范围（非
    扩展边界）。输出覆盖全部 ``grid_size²`` 格，行主序（x 最快）发射，
    供空间分布/异常区域模块消费。仅统计公共有效集内的点；空公共有效集
    抛 ``ANALYSIS_EMPTY_COMMON_VALID``。XY 平面聚合不读取 mapping 维度
    信息，签名与帧级服务（``summarize_quality``/``profile_axis``）对齐。
    """

    del mapping  # XY 平面网格与映射维度无关；签名保留与帧级服务对齐
    if grid_size < 1:
        raise ValueError("grid_size 必须 >= 1")
    valid = frame.loc[_finite_valid_mask(frame)]
    if len(valid) == 0:
        raise _empty_common_valid({"function": "aggregate_spatial", "grid_size": grid_size})
    xs = valid["x"].to_numpy(dtype="float64")
    ys = valid["y"].to_numpy(dtype="float64")
    values = valid["value"].to_numpy(dtype="float64")
    x_low, x_high = float(xs.min()), float(xs.max())
    y_low, y_high = float(ys.min()), float(ys.max())
    x_edges = _bin_edges(x_low, x_high, grid_size)
    y_edges = _bin_edges(y_low, y_high, grid_size)
    ix = _bin_indices(x_edges, xs)
    iy = _bin_indices(y_edges, ys)
    cell = iy * grid_size + ix
    counts = np.bincount(cell, minlength=grid_size * grid_size)
    sums = np.bincount(cell, weights=values, minlength=grid_size * grid_size)

    bins: list[SpatialBin] = []
    for row in range(grid_size):
        for col in range(grid_size):
            index = row * grid_size + col
            count = int(counts[index])
            bins.append(
                SpatialBin(
                    x_lower=float(x_edges[col]),
                    x_upper=float(x_edges[col + 1]),
                    y_lower=float(y_edges[row]),
                    y_upper=float(y_edges[row + 1]),
                    count=count,
                    mean=float(sums[index] / count) if count else None,
                )
            )
    return SpatialSummary(
        grid_size=grid_size,
        cell_count=grid_size * grid_size,
        bounds={"x": (x_low, x_high), "y": (y_low, y_high)},
        bins=bins,
    )


# ---------------------------------------------------------------------------
# 逐轴剖面（微震/电阻率 X/Y/Z 趋势基础函数）
# ---------------------------------------------------------------------------


def profile_axis(
    frame: pd.DataFrame, mapping: FrameMapping, axis: str, bins: int = 32
) -> ProfileSliceSummary:
    """沿单轴的等宽分箱统计：每格 count/mean/median（空格为 None）。

    轴必须在映射维度内（2D 数据请求 z 轴抛 ``ANALYSIS_AXIS_INVALID``）；
    公共有效集内该轴坐标非有限的行一并排除；空公共有效集抛
    ``ANALYSIS_EMPTY_COMMON_VALID``。分箱确定性（数据范围 + 固定格数）。
    """

    if axis not in _AXES:
        raise PlatformError(
            ANALYSIS_AXIS_INVALID,
            f"不支持的剖面轴：{axis!r}（仅支持 x/y/z）",
            {"axis": axis},
            http_status=400,
        )
    if axis not in _coord_columns(mapping):
        raise PlatformError(
            ANALYSIS_AXIS_INVALID,
            f"剖面轴 {axis!r} 不在映射维度内（2D 数据无 z 轴）",
            {"axis": axis},
            http_status=400,
        )
    if bins < 1:
        raise ValueError("bins 必须 >= 1")
    valid = frame.loc[_finite_valid_mask(frame)]
    coords = valid[axis].to_numpy(dtype="float64")
    finite_axis = np.isfinite(coords)
    coords = coords[finite_axis]
    values = valid["value"].to_numpy(dtype="float64")[finite_axis]
    if coords.size == 0:
        raise _empty_common_valid({"function": "profile_axis", "axis": axis, "bins": bins})

    edges = _bin_edges(float(coords.min()), float(coords.max()), bins)
    indices = _bin_indices(edges, coords)
    result: list[ProfileSliceBin] = []
    for i in range(bins):
        selected = indices == i
        count = int(selected.sum())
        result.append(
            ProfileSliceBin(
                lower=float(edges[i]),
                upper=float(edges[i + 1]),
                count=count,
                mean=float(values[selected].mean()) if count else None,
                median=float(np.median(values[selected])) if count else None,
            )
        )
    return ProfileSliceSummary(axis=axis, bins=result)


# ---------------------------------------------------------------------------
# 电阻率 log 分布前处理
# ---------------------------------------------------------------------------


def log10_positive(values: Values) -> tuple[np.ndarray, int]:
    """log10 变换前处理：仅严格正值有限值进入 log10，排除计数保留。

    返回 ``(log10 变换值, 排除计数)``；排除 = 非正值（含 0）+ 非有限值。
    供电阻率 profile 的对数分布模块（Task 6）消费。
    """

    array = np.asarray(values, dtype="float64").ravel()
    keep = np.isfinite(array) & (array > 0.0)
    excluded = int(array.size - keep.sum())
    return np.log10(array[keep]), excluded


# ---------------------------------------------------------------------------
# Task 6：电阻率 log10 分箱（与原始值分箱并存）
# ---------------------------------------------------------------------------


def log10_histogram(values: Values, bins: int = 32) -> tuple[list[HistogramBin] | None, int]:
    """log10 分箱：仅严格正值有限值进 log10，排除计数保留。

    返回 ``(分箱或 None, 排除计数)``；无严格正值有限值时分箱为 None
    （对数分布不可用是类型化空态，绝不伪造全零分箱），排除计数照常保留。
    分箱定义沿用 ``histogram`` 确定性口径（log10 值域 + 固定格数）。
    """

    transformed, excluded = log10_positive(values)
    if transformed.size == 0:
        return None, excluded
    return histogram(transformed, bins), excluded


# ---------------------------------------------------------------------------
# Task 6：微震 axis_trends（X/Y/Z 逐轴分箱趋势，复用 profile_axis 口径）
# ---------------------------------------------------------------------------


def axis_trends(
    frame: pd.DataFrame, mapping: FrameMapping, bins: int = 32
) -> list[AxisTrendSummary]:
    """映射维度内逐轴等宽分箱均值/中位数趋势，附轴身份与样本数。

    逐轴直接复用 ``profile_axis``（同一确定性分箱与排除口径）；样本数 =
    该轴全部分箱计数之和（守恒）。空公共有效集在 ``profile_axis`` 内
    fail-closed 抛 ``ANALYSIS_EMPTY_COMMON_VALID``。
    """

    trends: list[AxisTrendSummary] = []
    for axis in _coord_columns(mapping):
        summary = profile_axis(frame, mapping, axis, bins=bins)
        trends.append(
            AxisTrendSummary(
                axis=axis,  # type: ignore[arg-type]  # _coord_columns 只产出 x/y/z
                sample_count=sum(item.count for item in summary.bins),
                bins=summary.bins,
            )
        )
    return trends


# ---------------------------------------------------------------------------
# Task 6：微震 gradient（相邻 XY 网格单元均值差分幅值的有限统计）
# ---------------------------------------------------------------------------


def gradient_summary(
    frame: pd.DataFrame, mapping: FrameMapping, grid_size: int = 16
) -> GradientSummary:
    """局部变化强度：XY 网格相邻单元均值差分幅值 |Δmean| 的有限统计。

    网格定义与 ``aggregate_spatial`` 完全一致（数据范围 + 固定格数）。逐
    对相邻（X 向/Y 向）单元：两侧均值均非空（有限）才进入差分，任一侧为
    空格的对排除且计数保留（``excluded_pair_count``）。只用有限值；
    ``count=0`` 时统计字段为 None（绝不以 NaN 占位）。
    """

    spatial = aggregate_spatial(frame, mapping, grid_size)
    means = [item.mean for item in spatial.bins]  # 行主序（x 最快）
    diffs: list[float] = []
    pair_count = 0
    excluded = 0
    for row in range(grid_size):
        for col in range(grid_size):
            index = row * grid_size + col
            neighbors: list[int] = []
            if col + 1 < grid_size:
                neighbors.append(index + 1)
            if row + 1 < grid_size:
                neighbors.append(index + grid_size)
            for other in neighbors:
                pair_count += 1
                left, right = means[index], means[other]
                if left is None or right is None:
                    excluded += 1
                    continue
                diffs.append(abs(left - right))
    count = len(diffs)
    if count:
        array = np.asarray(diffs, dtype="float64")
        mean = float(array.mean())
        p95 = float(np.quantile(array, 0.95, method="linear"))
        peak = float(array.max())
    else:
        mean = p95 = peak = None
    return GradientSummary(
        grid_size=grid_size,
        pair_count=pair_count,
        excluded_pair_count=excluded,
        count=count,
        mean=mean,
        p95=p95,
        max=peak,
    )


# ---------------------------------------------------------------------------
# Task 6：分位阈值（depth_slices / spatial_anomaly 共用同一阈值机制）
# ---------------------------------------------------------------------------

#: 阈值来源标识：有效值 p75/p25 分位数（非人工输入）
_ANOMALY_THRESHOLD_SOURCE = "valid_value_quantiles_p25_p75"
_ANOMALY_THRESHOLD_METHOD = (
    "高值阈值=有效值 p75、低值阈值=有效值 p25（NumPy 线性插值分位数）；"
    "阈值由数据分位数产生，非人工输入"
)


def anomaly_thresholds(values: Values) -> AnomalyThresholds:
    """有效值 p75/p25 分位阈值（高/低值区域共用同一阈值机制）。

    阈值来源写进 ``source``/``method``；只统计有限值，空有效集抛
    ``ANALYSIS_EMPTY_COMMON_VALID``。
    """

    finite = _finite_values(values)
    if finite.size == 0:
        raise _empty_common_valid({"function": "anomaly_thresholds"})
    summary = quantiles(finite)
    assert summary.p75 is not None and summary.p25 is not None  # quantiles 恒产出
    return AnomalyThresholds(
        high=float(summary.p75),
        low=float(summary.p25),
        source=_ANOMALY_THRESHOLD_SOURCE,
        method=_ANOMALY_THRESHOLD_METHOD,
    )


# ---------------------------------------------------------------------------
# Task 6：电阻率 depth_slices（逐 Z 层超阈占比）
# ---------------------------------------------------------------------------


def depth_slice_ratios(
    frame: pd.DataFrame, mapping: FrameMapping, bins: int = 16
) -> DepthSliceSummary:
    """逐 Z 层异常占比：高值=样本值 ≥ p75，低值=样本值 ≤ p25（同一分位阈值）。

    Z 轴等宽分层（数据范围 + 固定层数，确定性同 ``profile_axis``）；层内
    高/低值占比 = 超阈样本数/层样本数（体积占比以样本计数为口径），空层
    占比为 None。阈值来源随 ``thresholds`` 出站。映射无 z 轴抛
    ``ANALYSIS_AXIS_INVALID``；空公共有效集抛 ``ANALYSIS_EMPTY_COMMON_VALID``。
    """

    if "z" not in _coord_columns(mapping):
        raise PlatformError(
            ANALYSIS_AXIS_INVALID,
            "深度切片要求映射含 z 轴",
            {"axis": "z"},
            http_status=400,
        )
    if bins < 1:
        raise ValueError("bins 必须 >= 1")
    valid = frame.loc[_finite_valid_mask(frame)]
    zs = valid["z"].to_numpy(dtype="float64")
    finite_z = np.isfinite(zs)
    zs = zs[finite_z]
    values = valid["value"].to_numpy(dtype="float64")[finite_z]
    if zs.size == 0:
        raise _empty_common_valid({"function": "depth_slice_ratios", "bins": bins})
    thresholds = anomaly_thresholds(values)
    edges = _bin_edges(float(zs.min()), float(zs.max()), bins)
    indices = _bin_indices(edges, zs)
    counts = np.bincount(indices, minlength=bins)
    high_counts = np.bincount(indices[values >= thresholds.high], minlength=bins)
    low_counts = np.bincount(indices[values <= thresholds.low], minlength=bins)
    slices: list[DepthSliceBin] = []
    for i in range(bins):
        count = int(counts[i])
        high = int(high_counts[i])
        low = int(low_counts[i])
        slices.append(
            DepthSliceBin(
                z_lower=float(edges[i]),
                z_upper=float(edges[i + 1]),
                count=count,
                high_count=high,
                low_count=low,
                high_ratio=high / count if count else None,
                low_ratio=low / count if count else None,
            )
        )
    return DepthSliceSummary(thresholds=thresholds, slice_count=bins, slices=slices)


# ---------------------------------------------------------------------------
# Task 6：spatial_anomaly（XY 网格高/低值区域聚合，微震/电阻率共用机制）
# ---------------------------------------------------------------------------


def spatial_anomaly_summary(
    frame: pd.DataFrame, mapping: FrameMapping, grid_size: int = 32
) -> SpatialAnomalySummary:
    """XY 网格高/低值区域聚合：单元均值与有效值 p75/p25 阈值比较分类。

    区域口径：单元均值 ≥ 高值阈值 → ``high``，≤ 低值阈值 → ``low``，其余
    非空单元 → ``normal``，空格 → ``empty``。体积占比 = 区域内样本计数 /
    有效样本总数（样本计数口径）。网格与 ``aggregate_spatial`` 同一确定
    性定义；阈值来源随 ``thresholds`` 出站。
    """

    spatial = aggregate_spatial(frame, mapping, grid_size)
    valid_values = frame["value"].to_numpy(dtype="float64")[_finite_valid_mask(frame)]
    thresholds = anomaly_thresholds(valid_values)
    total_points = int(valid_values.size)

    bins: list[SpatialAnomalyBin] = []
    non_empty = high_cells = low_cells = high_points = low_points = 0
    for cell in spatial.bins:
        if cell.count == 0 or cell.mean is None:
            region = "empty"
        elif cell.mean >= thresholds.high:
            region = "high"
        elif cell.mean <= thresholds.low:
            region = "low"
        else:
            region = "normal"
        if region == "high":
            high_cells += 1
            high_points += cell.count
            non_empty += 1
        elif region == "low":
            low_cells += 1
            low_points += cell.count
            non_empty += 1
        elif region == "normal":
            non_empty += 1
        bins.append(SpatialAnomalyBin(**cell.model_dump(), region=region))
    return SpatialAnomalySummary(
        grid_size=grid_size,
        cell_count=grid_size * grid_size,
        bounds=spatial.bounds,
        thresholds=thresholds,
        non_empty_cell_count=non_empty,
        high_cell_count=high_cells,
        low_cell_count=low_cells,
        high_point_count=high_points,
        low_point_count=low_points,
        high_volume_ratio=high_points / total_points if total_points else None,
        low_volume_ratio=low_points / total_points if total_points else None,
        bins=bins,
    )
