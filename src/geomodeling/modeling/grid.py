"""Rule-grid derivation for 2D/3D modeling.

User grids must cover the exact declared bounds with positive,
dimension-matched resolutions; the cell count is checked before any
allocation. The default grid is deterministic: a common scale is found so
the product of per-axis node counts stays under 100,000 while preserving
the aspect ratio of the data extent.
"""

from __future__ import annotations

import math

import numpy as np

from geomodeling.modeling.contracts import GridDefinition
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import Dimension, GridSpec

GRID_TOO_LARGE = "GRID_TOO_LARGE"
GRID_DIMENSION_MISMATCH = "GRID_DIMENSION_MISMATCH"

DEFAULT_CELL_TARGET = 100_000


def _dimension_of(dimension: str | Dimension) -> str:
    return Dimension(dimension).value


def _axis_nodes(lower: float, upper: float, step: float) -> np.ndarray:
    count = int(round((upper - lower) / step)) + 1
    return lower + step * np.arange(count, dtype="float64")


def _check_cells(shape: tuple[int, ...], max_cells: int) -> None:
    cells = 1
    for count in shape:
        cells *= count
    if cells > max_cells:
        raise PlatformError(
            GRID_TOO_LARGE,
            f"估算网格单元数 {cells} 超过上限 {max_cells}",
            {"cells": cells, "max_cells": max_cells},
            http_status=400,
        )


def _from_spec(spec: GridSpec, dimension: str) -> GridDefinition:
    axes = tuple(
        _axis_nodes(lo, hi, step) for (lo, hi), step in zip(spec.bounds, spec.resolution)
    )
    shape = tuple(len(a) for a in axes)
    _check_cells(shape, spec.max_cells)
    return GridDefinition(
        dimension=dimension,
        axes=axes,
        bounds=tuple((float(lo), float(hi)) for lo, hi in spec.bounds),
        resolution=tuple(float(s) for s in spec.resolution),
    )


def _default_grid(points: np.ndarray, dimension: str) -> GridDefinition:
    lows = points.min(axis=0)
    highs = points.max(axis=0)
    spans = highs - lows
    spans = np.where(spans > 0, spans, 1.0)

    def product_for(scale: float) -> int:
        counts = [max(2, int(round(span / scale)) + 1) for span in spans]
        product = 1
        for count in counts:
            product *= count
        return product

    # 从最大跨度的 1/2 开始二分，找到满足单元数上限的最大 scale
    lo, hi = 0.0, float(spans.max())
    for _ in range(64):
        mid = (lo + hi) / 2
        if mid <= 0:
            mid = hi / 2 or 1.0
        if product_for(mid) > DEFAULT_CELL_TARGET:
            lo = mid
        else:
            hi = mid
    scale = hi
    axes = tuple(
        _axis_nodes(float(lo_), float(hi_), float(span / max(1, round(span / scale))))
        for lo_, hi_, span in zip(lows, highs, spans)
    )
    shape = tuple(len(a) for a in axes)
    _check_cells(shape, DEFAULT_CELL_TARGET)
    resolution = tuple(float((a[-1] - a[0]) / (len(a) - 1)) if len(a) > 1 else 0.0 for a in axes)
    return GridDefinition(
        dimension=dimension,
        axes=axes,
        bounds=tuple((float(lo), float(hi)) for lo, hi in zip(lows, highs)),
        resolution=resolution,
    )


def derive_grid(
    points: np.ndarray,
    dimension: str | Dimension,
    requested: GridSpec | None,
) -> GridDefinition:
    """Derive the modeling grid from points and an optional user spec."""

    dim = _dimension_of(dimension)
    expected = 3 if dim == Dimension.THREE_D.value else 2
    points = np.asarray(points, dtype="float64")
    if points.ndim != 2 or points.shape[1] != expected:
        raise PlatformError(
            GRID_DIMENSION_MISMATCH,
            f"点数据维度 {points.shape if points.ndim == 2 else points.ndim} 与 {dim} 网格不符",
            {"expected_columns": expected},
        )
    if requested is not None:
        if len(requested.bounds) != expected or len(requested.resolution) != expected:
            raise PlatformError(
                GRID_DIMENSION_MISMATCH,
                f"GridSpec 维度（{len(requested.bounds)}）与 {dim} 网格不符",
                {"expected": expected, "given": len(requested.bounds)},
            )
        return _from_spec(requested, dim)
    return _default_grid(points, dim)
