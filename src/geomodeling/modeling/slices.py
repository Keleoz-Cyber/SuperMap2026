"""Real-coordinate slice extraction from persisted rule grids.

Horizontal slices fix Z (axes X/Y); vertical slices fix X (axes Y/Z) or Y
(axes X/Z). The slider index maps directly to the persisted axis array and
returns its real coordinate. 2D grids accept only ``z/index=0`` as the
full field. Arbitrary oblique planes are intentionally not offered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from geomodeling.platform.errors import PlatformError

SLICE_INDEX_OUT_OF_RANGE = "SLICE_INDEX_OUT_OF_RANGE"
SLICE_AXIS_UNSUPPORTED = "SLICE_AXIS_UNSUPPORTED"

Axis = Literal["x", "y", "z"]


@dataclass(frozen=True)
class GridResult:
    dimension: str
    axes: tuple[np.ndarray, ...]
    values: np.ndarray
    is_nodata: np.ndarray
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SliceResult:
    fixed_axis: str
    fixed_coordinate: float
    axes_names: tuple[str, ...]
    axes: tuple[np.ndarray, ...]
    matrix: np.ndarray
    nodata_mask: np.ndarray
    value_range: tuple[float, float]


def _axis_index(dimension: str, axis: str) -> int:
    names = ("x", "y", "z")
    if axis not in names:
        raise PlatformError(
            SLICE_AXIS_UNSUPPORTED,
            f"不支持的切片轴：{axis}（仅 x/y/z）",
            {"axis": axis},
        )
    return names.index(axis)


def _value_range(matrix: np.ndarray, mask: np.ndarray) -> tuple[float, float]:
    valid = matrix[~mask]
    valid = valid[np.isfinite(valid)]
    if not valid.size:
        return (float("nan"), float("nan"))
    return (float(valid.min()), float(valid.max()))


def extract_slice(grid: GridResult, axis: Axis, index: int) -> SliceResult:
    """Extract one real-coordinate slice from a persisted grid."""

    fixed = _axis_index(grid.dimension, axis)
    if grid.dimension == "2d":
        if axis != "z" or index != 0:
            raise PlatformError(
                SLICE_AXIS_UNSUPPORTED,
                "二维成果仅支持 axis=z&index=0 的完整场视图",
                {"axis": axis, "index": index, "dimension": grid.dimension},
            )
        return SliceResult(
            fixed_axis="z",
            fixed_coordinate=0.0,
            axes_names=("x", "y"),
            axes=(grid.axes[0], grid.axes[1]),
            matrix=grid.values,
            nodata_mask=grid.is_nodata,
            value_range=_value_range(grid.values, grid.is_nodata),
        )

    axis_len = len(grid.axes[fixed])
    if index < 0 or index >= axis_len:
        raise PlatformError(
            SLICE_INDEX_OUT_OF_RANGE,
            f"切片索引 {index} 超出轴 {axis} 的范围 [0, {axis_len})",
            {"axis": axis, "index": index, "axis_length": axis_len},
            http_status=400,
        )
    matrix = np.take(grid.values, index, axis=fixed)
    mask = np.take(grid.is_nodata, index, axis=fixed)
    remaining = tuple(i for i in range(3) if i != fixed)
    names = ("x", "y", "z")
    return SliceResult(
        fixed_axis=axis,
        fixed_coordinate=float(grid.axes[fixed][index]),
        axes_names=tuple(names[i] for i in remaining),
        axes=tuple(grid.axes[i] for i in remaining),
        matrix=matrix,
        nodata_mask=mask,
        value_range=_value_range(matrix, mask),
    )
