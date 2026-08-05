"""v0.7.0 Batch 2 Task 3：权威正交剖面分析核心。

统一入口：

- ``extract_grid_plane``：公共抽取（复用既有 ``extract_slice`` 的轴向校验、
  真实坐标与掩膜；旧 ``/api/results/{id}/slices`` 经它保持字节兼容）。
- ``analyze_grid_slice``：面向图表的明确方向（设计 §5.2 表格），合并显式
  NoData 与 NaN/Inf 为有效 NoData 掩膜，统计只用有效原始值（总体标准差
  ddof=0、NumPy 线性插值分位数），并给出后端计算的 SDK 相对位置。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from geomodeling.modeling.slices import GridResult, SliceResult, extract_slice
from geomodeling.platform.errors import PlatformError

SLICE_AXIS_INVALID = "SLICE_AXIS_INVALID"
SLICE_INDEX_OUT_OF_RANGE = "SLICE_INDEX_OUT_OF_RANGE"

#: 图表方向：固定轴 → (纵轴 row, 横轴 column)
_PLANE_AXES: dict[str, tuple[str, str]] = {
    "x": ("z", "y"),
    "y": ("z", "x"),
    "z": ("y", "x"),
}


@dataclass(frozen=True)
class GridSliceAnalysis:
    """一个正交剖面的权威内容（NumPy 内部形态）。"""

    fixed_axis: str
    index: int
    coordinate: float
    sdk_relative_position: float
    row_axis: str
    column_axis: str
    row_coordinates: np.ndarray
    column_coordinates: np.ndarray
    values: np.ndarray
    nodata_mask: np.ndarray
    statistics: dict[str, Any]

    def to_json_slice(self) -> dict[str, Any]:
        """JSON 序列化：掩膜单元为 None，绝不输出 NaN/Infinity 字面量。"""

        masked = np.where(self.nodata_mask, np.nan, self.values)
        values_json = [
            [None if not np.isfinite(v) else float(v) for v in row]
            for row in masked
        ]
        return {
            "fixed_axis": self.fixed_axis,
            "index": self.index,
            "coordinate": self.coordinate,
            "sdk_relative_position": self.sdk_relative_position,
            "row_axis": self.row_axis,
            "column_axis": self.column_axis,
            "row_coordinates": [float(v) for v in self.row_coordinates],
            "column_coordinates": [float(v) for v in self.column_coordinates],
            "values": values_json,
            "nodata_mask": self.nodata_mask.tolist(),
        }


def _validate_axis_index(axis: str, index: int, axis_length: int) -> None:
    if axis not in _PLANE_AXES:
        raise PlatformError(
            SLICE_AXIS_INVALID,
            "剖面固定轴必须是 x/y/z",
            {"axis": axis},
            http_status=422,
        )
    if not isinstance(index, (int, np.integer)) or isinstance(index, bool) or index < 0 or index >= axis_length:
        raise PlatformError(
            SLICE_INDEX_OUT_OF_RANGE,
            f"剖面索引 {index} 超出轴 {axis} 的范围 [0, {axis_length})",
            {"axis": axis, "index": index, "axis_length": axis_length},
            http_status=422,
        )


def extract_grid_plane(
    axes: tuple[np.ndarray, ...],
    values: np.ndarray,
    is_nodata: np.ndarray,
    axis: str,
    index: int,
) -> SliceResult:
    """公共抽取：三维网格 → 一个真实坐标剖面（旧矩阵方向）。

    复用 ``modeling.slices.extract_slice`` 的轴向/越界/坐标合同；新剖面服务
    与旧结果切片 API 共用同一入口，避免两套抽取口径。旧调用方（结果切片
    API）保持既有 400 错误合同；新 RenderAsset 剖面服务在
    ``analyze_grid_slice`` 前置 422 校验（设计 §5.4）。
    """

    grid = GridResult(
        dimension="3d",
        axes=tuple(np.asarray(a, dtype="float64") for a in axes),
        values=np.asarray(values, dtype="float64"),
        is_nodata=np.asarray(is_nodata, dtype=bool),
        metadata={},
    )
    return extract_slice(grid, axis, index)  # type: ignore[arg-type]


def _statistics(values: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
    valid = values[~mask]
    total = int(values.size)
    if valid.size == 0:
        return {
            "total_count": total,
            "valid_count": 0,
            "nodata_count": total,
            "min": None,
            "max": None,
            "mean": None,
            "std_population": None,
            "p10": None,
            "p50": None,
            "p90": None,
        }
    q = np.quantile(valid, [0.1, 0.5, 0.9], method="linear")
    return {
        "total_count": total,
        "valid_count": int(valid.size),
        "nodata_count": int(total - valid.size),
        "min": float(valid.min()),
        "max": float(valid.max()),
        "mean": float(valid.mean()),
        "std_population": float(valid.std(ddof=0)),
        "p10": float(q[0]),
        "p50": float(q[1]),
        "p90": float(q[2]),
    }


def analyze_grid_slice(
    axes: tuple[np.ndarray, ...],
    values: np.ndarray,
    is_nodata: np.ndarray,
    axis: str,
    index: int,
) -> GridSliceAnalysis:
    """图表方向剖面分析：转置到设计表格方向 + 有效掩膜 + 权威统计。

    固定轴/索引先经 422 合同校验（设计 §5.4），再复用公共抽取。
    """

    axis_length = len(axes[{"x": 0, "y": 1, "z": 2}[axis]]) if axis in _PLANE_AXES else 0
    _validate_axis_index(axis, index, axis_length)
    plane = extract_grid_plane(axes, values, is_nodata, axis, index)
    row_axis, column_axis = _PLANE_AXES[plane.fixed_axis]
    old_names = list(plane.axes_names)
    order = [old_names.index(row_axis), old_names.index(column_axis)]
    matrix = np.transpose(plane.matrix, axes=order)
    mask = np.transpose(plane.nodata_mask, axes=order)
    effective_mask = mask | ~np.isfinite(matrix)
    axis_length = len(axes[{"x": 0, "y": 1, "z": 2}[plane.fixed_axis]])
    return GridSliceAnalysis(
        fixed_axis=plane.fixed_axis,
        index=index,
        coordinate=plane.fixed_coordinate,
        sdk_relative_position=index / (axis_length - 1),
        row_axis=row_axis,
        column_axis=column_axis,
        row_coordinates=np.asarray(plane.axes[old_names.index(row_axis)], dtype="float64"),
        column_coordinates=np.asarray(plane.axes[old_names.index(column_axis)], dtype="float64"),
        values=matrix,
        nodata_mask=effective_mask,
        statistics=_statistics(matrix, effective_mask),
    )
