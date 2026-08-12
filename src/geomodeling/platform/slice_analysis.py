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
from geomodeling.platform import tables
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
            [None if not np.isfinite(v) else float(v) for v in row] for row in masked
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
    if (
        not isinstance(index, (int, np.integer))
        or isinstance(index, bool)
        or index < 0
        or index >= axis_length
    ):
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
    *,
    dimension: str = "3d",
) -> SliceResult:
    """公共抽取：规则网格 → 一个真实坐标剖面（旧矩阵方向）。

    复用 ``modeling.slices.extract_slice`` 的轴向/越界/坐标合同；新剖面服务
    与旧结果切片 API 共用同一入口，避免两套抽取口径。旧调用方（结果切片
    API）保持既有 400 错误合同；新 RenderAsset 剖面服务在
    ``analyze_grid_slice`` 前置 422 校验（设计 §5.4）。
    """

    grid = GridResult(
        dimension=dimension,
        axes=tuple(np.asarray(a, dtype="float64") for a in axes),
        values=np.asarray(values, dtype="float64"),
        is_nodata=np.asarray(is_nodata, dtype=bool),
        metadata={},
    )
    return extract_slice(grid, axis, index)  # type: ignore[arg-type]


def _statistics(
    values: np.ndarray,
    mask: np.ndarray,
    *,
    full_grid_thresholds: tuple[float, float] | None = None,
) -> dict[str, Any]:
    valid = values[~mask]
    total = int(values.size)
    base: dict[str, Any] = {
        "total_count": total,
        "valid_count": int(valid.size),
        "nodata_count": int(total - valid.size),
    }
    if valid.size == 0:
        base.update(
            {
                "min": None,
                "max": None,
                "mean": None,
                "std_population": None,
                "p10": None,
                "p50": None,
                "p90": None,
                "low_count": 0,
                "normal_count": 0,
                "high_count": 0,
                "low_ratio": 0.0,
                "normal_ratio": 0.0,
                "high_ratio": 0.0,
                "thresholds": None,
            }
        )
        return base
    q = np.quantile(valid, [0.1, 0.5, 0.9], method="linear")
    base.update(
        {
            "min": float(valid.min()),
            "max": float(valid.max()),
            "mean": float(valid.mean()),
            "std_population": float(valid.std(ddof=0)),
            "p10": float(q[0]),
            "p50": float(q[1]),
            "p90": float(q[2]),
        }
    )
    if full_grid_thresholds is not None:
        low, high = full_grid_thresholds
        low_count = int((valid < low).sum())
        high_count = int((valid >= high).sum())
        normal_count = int(valid.size) - low_count - high_count
        base.update(
            {
                "low_count": low_count,
                "normal_count": normal_count,
                "high_count": high_count,
                "low_ratio": low_count / valid.size,
                "normal_ratio": normal_count / valid.size,
                "high_ratio": high_count / valid.size,
                "thresholds": {
                    "low": float(low),
                    "high": float(high),
                    "source": "full_grid_quartile",
                    "method": "numpy_linear_p25_p75",
                },
            }
        )
    else:
        base.update(
            {
                "low_count": None,
                "normal_count": None,
                "high_count": None,
                "low_ratio": None,
                "normal_ratio": None,
                "high_ratio": None,
                "thresholds": None,
            }
        )
    return base


def analyze_grid_slice(
    axes: tuple[np.ndarray, ...],
    values: np.ndarray,
    is_nodata: np.ndarray,
    axis: str,
    index: int,
    *,
    full_grid_thresholds: tuple[float, float] | None = None,
) -> GridSliceAnalysis:
    """图表方向剖面分析：转置到设计表格方向 + 有效掩膜 + 权威统计。

    固定轴/索引先经 422 合同校验（设计 §5.4），再复用公共抽取。
    """

    axis_length = (
        len(axes[{"x": 0, "y": 1, "z": 2}[axis]]) if axis in _PLANE_AXES else 0
    )
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
        row_coordinates=np.asarray(
            plane.axes[old_names.index(row_axis)], dtype="float64"
        ),
        column_coordinates=np.asarray(
            plane.axes[old_names.index(column_axis)], dtype="float64"
        ),
        values=matrix,
        nodata_mask=effective_mask,
        statistics=_statistics(
            matrix, effective_mask, full_grid_thresholds=full_grid_thresholds
        ),
    )


# ---------------------------------------------------------------------------
# Task 4：RenderAsset → 权威网格解析与公开剖面服务
#
# render_assets/legacy_render_sources/repositories 依赖 results.py，而
# results.py 复用本模块的公共抽取——相关导入必须保持在函数级，避免
# results → slice_analysis → render_assets → results 循环。
# ---------------------------------------------------------------------------

RENDER_ASSET_SOURCE_UNSUPPORTED = "RENDER_ASSET_SOURCE_UNSUPPORTED"
RENDER_GRID_IDENTITY_MISMATCH = "RENDER_GRID_IDENTITY_MISMATCH"


def load_ready_asset_grid(runtime, asset_id: str):
    """解析 ready RenderAsset 到其权威规则网格（纯查询，不建文件不改行）。

    顺序即防线：ready 门禁（404/409）→ 文件侧哈希复核（RENDER_ASSET_CORRUPT）
    → 按来源类型解析权威网格 → 资产/网格身份一致（RENDER_GRID_IDENTITY_MISMATCH）
    → 落盘网格完整校验。
    """

    from geomodeling.platform import render_assets as _render_assets
    from geomodeling.platform.legacy_render_sources import (
        resolve_legacy_render_source as _resolve_legacy_render_source,
    )
    from geomodeling.platform.repositories import (
        RenderAssetRepository as _RenderAssetRepository,
    )

    with runtime.session() as session:
        record = _RenderAssetRepository(session).get_ready(asset_id)
        row = session.get(tables.RenderAsset, asset_id)
    _render_assets.verify_ready_asset(runtime, record)
    if record.source_kind == "candidate_result":
        candidate_result_id = row.candidate_result_id if row is not None else None
        if candidate_result_id is None:
            raise PlatformError(
                RENDER_ASSET_SOURCE_UNSUPPORTED,
                "候选渲染资产缺少成果归属",
                {"asset_id": asset_id},
                http_status=409,
            )
        field = (
            record.source_id.removeprefix(f"{candidate_result_id}::")
            if record.source_id != candidate_result_id
            else "prediction"
        )
        source = _render_assets.resolve_candidate_render_source(
            runtime, candidate_result_id, field=field
        )
    elif record.source_kind == "builtin_legacy":
        source = _resolve_legacy_render_source(runtime, record.source_id)
    else:
        raise PlatformError(
            RENDER_ASSET_SOURCE_UNSUPPORTED,
            "不支持的渲染源类型",
            {"source_kind": record.source_kind},
            http_status=409,
        )
    if source.grid_sha256 != record.grid_sha256:
        raise PlatformError(
            RENDER_GRID_IDENTITY_MISMATCH,
            "渲染资产与权威网格身份不一致",
            {"asset_id": asset_id},
            http_status=409,
        )
    grid = source.validated_grid or _render_assets.validate_regular_grid(
        source.grid_path, source.grid_sha256
    )
    return record, source, grid


def _profile(
    source_kind: str, valid_min: float, valid_max: float, *, property_name: str, unit
):
    from geomodeling.platform.render_profiles import build_render_profile

    return build_render_profile(
        source_kind, valid_min, valid_max, property_name=property_name, unit=unit
    ).to_public()


def _field_profile(source, grid) -> dict[str, Any]:
    profile = _profile(
        source.source_kind,
        grid.valid_min,
        grid.valid_max,
        property_name=source.property_name,
        unit=source.units,
    )
    if source.palette_intent == "diverging_zero_centered":
        profile["default_palette"] = "coolwarm"
    elif source.palette_intent == "sequential_nonnegative":
        profile["default_palette"] = "viridis"
    profile["palette_intent"] = source.palette_intent
    return profile


def analyze_render_asset_slice(
    runtime, asset_id: str, axis: str, index: int
) -> dict[str, Any]:
    """公开剖面分析：资产身份 + 三轴坐标 + 图表方向剖面 + 权威统计 + render_profile。"""

    from geomodeling.platform.result_analysis import (
        finite_valid_values,
        result_thresholds,
    )

    record, source, grid = load_ready_asset_grid(runtime, asset_id)
    valid = finite_valid_values(grid.values, grid.is_nodata)
    thresholds = result_thresholds(valid) if valid.size > 0 else None
    analysis = analyze_grid_slice(
        grid.axes,
        grid.values,
        grid.is_nodata,
        axis,
        index,
        full_grid_thresholds=thresholds,
    )
    slice_payload = analysis.to_json_slice()
    return {
        "asset_identity": {
            "asset_id": record.id,
            "source_kind": record.source_kind,
            "source_id": record.source_id,
            "candidate_result_id": source.candidate_result_id,
            "field": source.field_name,
            "grid_sha256": record.grid_sha256,
            "netcdf_sha256": record.netcdf_sha256,
        },
        "property": {"name": source.property_name, "unit": source.units or "unknown"},
        "axes": {
            name: {
                "length": int(len(coords)),
                "coordinates": [float(v) for v in coords],
                "unit": "m",
            }
            for name, coords in zip(("x", "y", "z"), grid.axes, strict=True)
        },
        "slice": slice_payload,
        "statistics": analysis.statistics,
        "render_profile": _field_profile(source, grid),
    }
