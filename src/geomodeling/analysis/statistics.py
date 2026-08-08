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
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Union

import numpy as np
import pandas as pd

from geomodeling.analysis.schemas import (
    HistogramBin,
    NumericSummary,
    ProfileSliceBin,
    ProfileSliceSummary,
    QualitySummary,
    QuantileSummary,
    SpatialBin,
    SpatialSummary,
)
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import FieldMapping

__all__ = [
    "ANALYSIS_AXIS_INVALID",
    "ANALYSIS_EMPTY_COMMON_VALID",
    "aggregate_spatial",
    "histogram",
    "log10_positive",
    "profile_axis",
    "quantiles",
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
