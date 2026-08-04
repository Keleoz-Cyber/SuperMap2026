"""Candidate render-source resolution and regular-grid validation (v0.6.1 Task 4).

解析候选成果的渲染源：沿归属链 ``candidate -> run -> experiment ->
dataset_version.profile_json`` 取 ``mapping.value_name`` / ``mapping.value_unit``
/ ``mapping.coordinate_kind``——**不固定 rho 语义**；单位缺失才回退字面
``"unknown"``。老 metadata 缺 property 字段仍可解析（语义来自数据集 profile，
绝不改写既有工件）。

所有函数都是纯查询：绝不物化成果、绝不创建文件、绝不改写数据库行。规则网格校验
fail-closed，错误码稳定（非 3D / 轴非法 / 轴不规则 / 形状不符 / 全 NoData /
登记哈希与实际文件哈希不符）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from geomodeling.platform import tables
from geomodeling.platform.errors import (
    CANDIDATE_NOT_FOUND,
    DATASET_NOT_FOUND,
    PlatformError,
)
from geomodeling.platform.render_contracts import (
    DisplayAnchor,
    RenderGridSource,
    ValidatedGrid,
)
from geomodeling.platform.render_coordinates import (
    display_transform_for_bounds,
    sha256_file,
)

# 同包私有复用（与 professional 复用 results 原子写助手同款约定）
from geomodeling.platform.results import (
    CANDIDATE_NOT_SUCCEEDED,
    RESULT_ARTIFACT_INVALID,
    RESULT_NOT_MATERIALIZED,
    _load_candidate,
    _mapping_property_semantics,
)

RENDER_REQUIRES_3D = "RENDER_REQUIRES_3D"
RENDER_AXIS_INVALID = "RENDER_AXIS_INVALID"
RENDER_GRID_IRREGULAR = "RENDER_GRID_IRREGULAR"
RENDER_GRID_SHAPE_MISMATCH = "RENDER_GRID_SHAPE_MISMATCH"
RENDER_NO_VALID_VALUES = "RENDER_NO_VALID_VALUES"
RENDER_GRID_IDENTITY_MISMATCH = "RENDER_GRID_IDENTITY_MISMATCH"

# 近似规则网格判定（与 modeling/grid.py 的 derive_grid 落盘轴一致：节点即
# linspace，允许浮点回算误差）：每轴与首尾等距参考轴比较，容差随轴跨度缩放。
_REGULAR_RTOL = 1e-6
_REGULAR_ATOL_SCALE = 1e-9


@dataclass(frozen=True)
class RenderCapability:
    """候选渲染能力（设计 §2.3 响应的内部形态；路由层再序列化为公共 DTO）。"""

    source_kind: str
    source_id: str
    supported: bool
    reason_code: str | None
    reason: str | None
    dimension: str | None
    grid_kind: str | None
    property_name: str | None
    units: str | None
    geolocation_status: str
    display_transform: dict[str, Any] | None


def _validate_axis(axis: np.ndarray, name: str) -> np.ndarray:
    """单轴校验：≥2 节点、有限、严格递增（RENDER_AXIS_INVALID）、近似等距
    （RENDER_GRID_IRREGULAR）。"""

    array = np.asarray(axis, dtype="float64")
    if (
        array.ndim != 1
        or array.size < 2
        or not np.all(np.isfinite(array))
        or not np.all(np.diff(array) > 0)
    ):
        raise PlatformError(
            RENDER_AXIS_INVALID,
            f"渲染网格 {name} 轴必须是不少于 2 个节点、有限且严格递增的一维坐标",
            {"axis": name},
            http_status=409,
        )
    span = float(array[-1] - array[0])
    reference = np.linspace(array[0], array[-1], array.size)
    tolerance = (_REGULAR_RTOL + _REGULAR_ATOL_SCALE) * max(1.0, span)
    if not np.all(np.abs(array - reference) <= tolerance):
        raise PlatformError(
            RENDER_GRID_IRREGULAR,
            f"渲染网格 {name} 轴不是近似等距的规则轴",
            {"axis": name},
            http_status=409,
        )
    return array


def validate_regular_grid(grid_path: Path, expected_sha256: str) -> ValidatedGrid:
    """校验落盘 grid.npz 并返回有效值统计。

    顺序即防线：登记哈希 == 实际文件哈希（RENDER_GRID_IDENTITY_MISMATCH）→
    三轴各自合法且近似规则 → values/is_nodata 形状与轴长度一致
    （RENDER_GRID_SHAPE_MISMATCH）→ 至少一个有限有效值（RENDER_NO_VALID_VALUES）。
    """

    actual_sha256 = sha256_file(grid_path)
    if actual_sha256 != expected_sha256:
        raise PlatformError(
            RENDER_GRID_IDENTITY_MISMATCH,
            "渲染网格实际文件哈希与登记哈希不符",
            {"expected_sha256": expected_sha256, "actual_sha256": actual_sha256},
            http_status=409,
        )
    with np.load(grid_path, allow_pickle=True) as bundle:
        axes = tuple(np.asarray(a, dtype="float64") for a in bundle["axes"])
        values = np.asarray(bundle["values"], dtype="float64")
        is_nodata = np.asarray(bundle["is_nodata"], dtype=bool)
    if len(axes) != 3:
        raise PlatformError(
            RENDER_REQUIRES_3D,
            "原生体渲染要求三维成果网格",
            {"axis_count": len(axes)},
            http_status=409,
        )
    checked_axes = tuple(
        _validate_axis(axis, name)
        for axis, name in zip(axes, ("x", "y", "z"), strict=True)
    )
    expected_shape = tuple(axis.size for axis in checked_axes)
    if values.shape != expected_shape or is_nodata.shape != expected_shape:
        raise PlatformError(
            RENDER_GRID_SHAPE_MISMATCH,
            "渲染网格 values/is_nodata 形状与轴长度不一致",
            {
                "expected_shape": list(expected_shape),
                "values_shape": list(values.shape),
                "is_nodata_shape": list(is_nodata.shape),
            },
            http_status=409,
        )
    valid = values[~is_nodata]
    finite = valid[np.isfinite(valid)]
    if finite.size == 0:
        raise PlatformError(
            RENDER_NO_VALID_VALUES,
            "渲染网格没有任何有限有效值（全 NoData）",
            http_status=409,
        )
    return ValidatedGrid(
        axes=checked_axes,
        values=values,
        is_nodata=is_nodata,
        valid_min=float(finite.min()),
        valid_max=float(finite.max()),
    )


def _trace_candidate(runtime, result_id: str):
    """candidate -> run -> experiment -> dataset_version.profile_json 归属链核验。"""

    candidate, _, experiment = _load_candidate(runtime, result_id)
    params = tables.loads_canonical(experiment.params_json)
    dataset_version_id = params["dataset_version_id"]
    with runtime.session() as session:
        dataset = session.get(tables.DatasetVersion, dataset_version_id)
    if dataset is None:
        raise PlatformError(
            DATASET_NOT_FOUND,
            "成果所属数据版本缺失，归属链不完整",
            {"result_id": result_id, "dataset_version_id": dataset_version_id},
            http_status=409,
        )
    return candidate, experiment, tables.loads_canonical(dataset.profile_json)


def _resolve_candidate_grid(
    runtime, result_id: str
) -> tuple[RenderGridSource, ValidatedGrid]:
    candidate, _, profile = _trace_candidate(runtime, result_id)
    if candidate.status != "succeeded":
        raise PlatformError(
            CANDIDATE_NOT_SUCCEEDED,
            "只有成功候选可以作为渲染源",
            {"result_id": result_id, "status": candidate.status},
            http_status=409,
        )
    semantics = _mapping_property_semantics(profile)
    grid_path = runtime.settings.result_grid(result_id)
    metadata_path = grid_path.parent / "metadata.json"
    if not grid_path.is_file() or not metadata_path.is_file():
        raise PlatformError(
            RESULT_NOT_MATERIALIZED,
            "成果尚未生成，请先调用 materialize",
            {"result_id": result_id},
            http_status=404,
        )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("dimension") != "3d":
        raise PlatformError(
            RENDER_REQUIRES_3D,
            "原生体渲染要求三维成果网格",
            {"result_id": result_id, "dimension": metadata.get("dimension")},
            http_status=409,
        )
    grid_sha256 = metadata.get("grid_sha256")
    if not grid_sha256:
        raise PlatformError(
            RESULT_ARTIFACT_INVALID,
            "成果 metadata 缺少 grid_sha256，网格身份无法核验",
            {"result_id": result_id},
            http_status=409,
        )
    grid = validate_regular_grid(grid_path, grid_sha256)
    source = RenderGridSource(
        source_kind="candidate_result",
        source_id=result_id,
        grid_path=grid_path,
        grid_sha256=grid_sha256,
        property_name=semantics["property_name"],
        units=semantics["units"],
        coordinate_kind=semantics["coordinate_kind"],
        dimension="3d",
    )
    return source, grid


def resolve_candidate_render_source(runtime, result_id: str) -> RenderGridSource:
    """解析候选成果的渲染源（纯查询：绝不物化、绝不创建文件、绝不改行）。"""

    source, _ = _resolve_candidate_grid(runtime, result_id)
    return source


def _best_effort_semantics(runtime, result_id: str):
    """能力报告的尽力语义回填：归属链可解析则取 profile 维度/属性，否则 None。"""

    try:
        _, _, profile = _trace_candidate(runtime, result_id)
    except PlatformError:
        return None, None, None
    mapping = profile.get("mapping", {}) if isinstance(profile, dict) else {}
    semantics = _mapping_property_semantics(profile)
    return mapping.get("dimension"), semantics["property_name"], semantics["units"]


def candidate_render_capability(runtime, result_id: str) -> RenderCapability:
    """候选渲染能力（纯查询：不物化、不创建文件、不改行）。

    解析失败报告 ``supported=False`` + 稳定 ``reason_code``（2D、未物化、网格
    非法等）；候选不存在仍按 ``CANDIDATE_NOT_FOUND``（404）抛出。
    """

    anchor = DisplayAnchor()
    try:
        source, grid = _resolve_candidate_grid(runtime, result_id)
    except PlatformError as exc:
        if exc.code == CANDIDATE_NOT_FOUND:
            raise
        dimension, property_name, units = _best_effort_semantics(runtime, result_id)
        return RenderCapability(
            source_kind="candidate_result",
            source_id=result_id,
            supported=False,
            reason_code=exc.code,
            reason=exc.message,
            dimension=dimension,
            grid_kind=None,
            property_name=property_name,
            units=units,
            geolocation_status=anchor.geolocation_status,
            display_transform=None,
        )
    x_axis, y_axis = grid.axes[0], grid.axes[1]
    transform = display_transform_for_bounds(
        (float(x_axis[0]), float(x_axis[-1])),
        (float(y_axis[0]), float(y_axis[-1])),
        anchor,
    )
    return RenderCapability(
        source_kind="candidate_result",
        source_id=result_id,
        supported=True,
        reason_code=None,
        reason=None,
        dimension=source.dimension,
        grid_kind="regular",
        property_name=source.property_name,
        units=source.units,
        geolocation_status=anchor.geolocation_status,
        display_transform=transform,
    )
