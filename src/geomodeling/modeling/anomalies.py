"""显式阈值异常连通区提取与网格支持度量（design §12）。

流水线（顺序固定）：

1. 规则网格合同：``axes`` 为 2 或 3 条一维轴，全部有限且严格递增
   （间距可非均匀，坐标本身必须单调）；非单调/重复/NaN 阻断为
   ``ANOMALY_GRID_IRREGULAR``，不对空间间隔不规则的网格使用该算法；
2. 掩膜：``direction=high`` 取 ``value >= threshold``，``low`` 取
   ``value <= threshold``（均含等号）；NoData 与非有限值节点不进入
   掩膜；
3. 不确定性门槛：``empirical_error_max`` / ``kriging_std_max`` 给出时
   必须传入对应层，缺失即 ``ANOMALY_UNCERTAINTY_UNAVAILABLE`` 结构化
   失败，不得静默忽略门槛；层内 NoData 或非有限的节点不进入掩膜；
4. 连通性：``scipy.ndimage.label`` + 显式十字形结构元（2D 四邻接、
   3D 六邻接，``connectivity_rule = face_2d4_3d6_v1``），对角接触不
   合并；逐连通区迭代处理，不使用递归；
5. 统计：``support_measure`` 为逐节点 Voronoi 支持度量之和——内部
   边界取相邻轴坐标中点、最外边界裁剪到网格 bounds，逐节点宽度乘积
   求和；几何中心按同一 Voronoi 权重加权。``min_support_nodes`` 过滤
   小规模连通区并计数入诊断。

命名纪律：``support_measure`` 仅称「网格支持面积/体积估计」
（``area_coordinate_unit2`` / ``volume_coordinate_unit3``），是阈值
掩膜下网格节点的 Voronoi 支持度量，不作任何资源量解释。取消语义与
``modeling.uncertainty`` 一致（``RUN_CANCELED`` / http 409，按连通
区批检查）。

设计依据：docs/superpowers/specs/2026-07-26-v0.6-professional-modeling-enhancements-design.md §12。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from scipy import ndimage

from geomodeling.modeling.base import CancelFn
from geomodeling.modeling.professional_contracts import AnomalyExtractionSpec
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import ContractModel

__all__ = [
    "ANOMALY_GRID_IRREGULAR",
    "ANOMALY_INPUT_INVALID",
    "ANOMALY_UNCERTAINTY_UNAVAILABLE",
    "COMPONENT_BATCH_SIZE",
    "RUN_CANCELED",
    "AnomalyComponent",
    "AnomalyExtractionResult",
    "UncertaintyLayer",
    "extract_anomalies",
]

RUN_CANCELED = "RUN_CANCELED"
ANOMALY_GRID_IRREGULAR = "ANOMALY_GRID_IRREGULAR"
ANOMALY_INPUT_INVALID = "ANOMALY_INPUT_INVALID"
ANOMALY_UNCERTAINTY_UNAVAILABLE = "ANOMALY_UNCERTAINTY_UNAVAILABLE"

# 取消检查粒度：每处理一批连通区检查一次 cancel。
COMPONENT_BATCH_SIZE = 256

_SUPPORT_UNIT_BY_DIM = {
    2: "area_coordinate_unit2",
    3: "volume_coordinate_unit3",
}


class AnomalyComponent(ContractModel):
    """单个连通区的统计记录（§12.3）。

    ``support_measure`` 为网格支持面积/体积估计（逐节点 Voronoi 宽度
    乘积之和）；``bounds`` 为逐轴节点坐标包围盒；``centroid`` 为按
    Voronoi 权重加权的几何中心。不确定性摘要仅在对应层提供时给出
    （层内 NoData/非有限节点不参与摘要）。
    """

    component_id: int
    support_node_count: int
    support_measure: float
    support_unit: Literal["area_coordinate_unit2", "volume_coordinate_unit3"]
    bounds: list[tuple[float, float]]
    centroid: list[float]
    value_min: float
    value_max: float
    value_mean: float
    touches_grid_boundary: bool
    empirical_error_scale_min: float | None = None
    empirical_error_scale_max: float | None = None
    empirical_error_scale_mean: float | None = None
    kriging_std_min: float | None = None
    kriging_std_max: float | None = None
    kriging_std_mean: float | None = None


@dataclass(frozen=True)
class UncertaintyLayer:
    """不确定性层：逐节点数值与 NoData 掩膜，与值场同形。

    ``values`` 为逐节点不确定性数值（经验误差尺度或 Kriging 原生标准
    差）；``is_nodata`` 为 True 的节点不进入掩膜、不参与摘要。
    """

    values: np.ndarray
    is_nodata: np.ndarray


@dataclass(frozen=True)
class _PreparedLayer:
    """通过形状校验的不确定性层及其可选门槛（内部类型）。"""

    values: np.ndarray
    nodata: np.ndarray
    gate: float | None


@dataclass(frozen=True)
class AnomalyExtractionResult:
    """一次异常提取的不可变结果。

    ``components`` 按连通区标记顺序排列，``component_id`` 从 1 连续编
    号；``diagnostics`` 只存有界聚合：掩膜计数、过滤计数与门槛状态。
    """

    components: tuple[AnomalyComponent, ...]
    diagnostics: dict[str, Any]


def _never_canceled() -> bool:
    return False


def _validate_axes(axes: tuple[np.ndarray, ...]) -> tuple[np.ndarray, ...]:
    """规则网格合同：2/3 条一维轴，全部有限且严格递增。"""

    try:
        items = tuple(np.asarray(axis, dtype=np.float64) for axis in axes)
    except (TypeError, ValueError) as exc:
        raise PlatformError(
            ANOMALY_GRID_IRREGULAR,
            "网格轴必须是数值一维数组",
            {"reason": str(exc)},
        ) from exc
    if len(items) not in (2, 3):
        raise PlatformError(
            ANOMALY_GRID_IRREGULAR,
            "网格轴数量必须为 2 或 3",
            {"axis_count": len(items)},
        )
    for index, axis in enumerate(items):
        if axis.ndim != 1 or axis.size < 2:
            raise PlatformError(
                ANOMALY_GRID_IRREGULAR,
                "每条网格轴必须是至少含 2 个节点的一维数组",
                {"axis_index": index, "size": int(axis.size)},
            )
        if not np.isfinite(axis).all():
            raise PlatformError(
                ANOMALY_GRID_IRREGULAR,
                "网格轴坐标必须全部为有限值",
                {"axis_index": index},
            )
        if not (np.diff(axis) > 0).all():
            raise PlatformError(
                ANOMALY_GRID_IRREGULAR,
                "网格轴坐标必须严格递增（间距可非均匀）",
                {"axis_index": index},
            )
    return items


def _validate_field(name: str, array: np.ndarray, shape: tuple[int, ...]) -> np.ndarray:
    field = np.asarray(array, dtype=np.float64)
    if field.shape != shape:
        raise PlatformError(
            ANOMALY_INPUT_INVALID,
            f"{name} 形状必须与网格轴节点数一致",
            {"field": name, "shape": list(field.shape), "expected": list(shape)},
        )
    return field


def _validate_mask(name: str, array: np.ndarray, shape: tuple[int, ...]) -> np.ndarray:
    mask = np.asarray(array, dtype=bool)
    if mask.shape != shape:
        raise PlatformError(
            ANOMALY_INPUT_INVALID,
            f"{name} 形状必须与网格轴节点数一致",
            {"field": name, "shape": list(mask.shape), "expected": list(shape)},
        )
    return mask


def _prepare_layer(
    name: str,
    layer: UncertaintyLayer | None,
    gate: float | None,
    shape: tuple[int, ...],
) -> _PreparedLayer | None:
    """校验不确定性层；门槛已请求而层缺失时结构化失败（不得忽略门槛）。"""

    if layer is None:
        if gate is not None:
            raise PlatformError(
                ANOMALY_UNCERTAINTY_UNAVAILABLE,
                f"已请求 {name} 不确定性上限，但未提供对应层；不得忽略该门槛",
                {"layer": name},
            )
        return None
    return _PreparedLayer(
        values=_validate_field(f"{name}.values", layer.values, shape),
        nodata=_validate_mask(f"{name}.is_nodata", layer.is_nodata, shape),
        gate=gate,
    )


def _voronoi_widths(axis: np.ndarray) -> np.ndarray:
    """逐节点 Voronoi 区间宽度：内部边界取相邻轴坐标中点，最外边界裁剪到轴端点。"""

    midpoints = (axis[:-1] + axis[1:]) / 2.0
    left = np.concatenate(([axis[0]], midpoints))
    right = np.concatenate((midpoints, [axis[-1]]))
    return right - left


def _layer_summary(
    prefix: str, layer: _PreparedLayer | None, local: np.ndarray, slice_: tuple[slice, ...]
) -> dict[str, float]:
    """连通区内不确定性层摘要（层内 NoData/非有限节点不参与）。"""

    if layer is None:
        return {}
    values = layer.values[slice_][local]
    valid = ~layer.nodata[slice_][local] & np.isfinite(values)
    gathered = values[valid]
    if gathered.size == 0:
        return {}
    return {
        f"{prefix}_min": float(gathered.min()),
        f"{prefix}_max": float(gathered.max()),
        f"{prefix}_mean": float(gathered.mean()),
    }


def extract_anomalies(
    *,
    axes: tuple[np.ndarray, ...],
    values: np.ndarray,
    is_nodata: np.ndarray,
    spec: AnomalyExtractionSpec,
    empirical_error_scale: UncertaintyLayer | None = None,
    kriging_std: UncertaintyLayer | None = None,
    cancel: CancelFn | None = None,
) -> AnomalyExtractionResult:
    """在规则网格上提取显式阈值异常连通区（语义见模块 docstring）。

    ``axes``/``values``/``is_nodata`` 只读；不确定性层与值场同形。返回
    连通区统计（含网格支持面积/体积估计）与有界聚合诊断。
    """

    cancel_fn = cancel if cancel is not None else _never_canceled
    axes64 = _validate_axes(axes)
    ndim = len(axes64)
    shape = tuple(int(axis.size) for axis in axes64)
    vals = _validate_field("values", values, shape)
    nodata = _validate_mask("is_nodata", is_nodata, shape)
    empirical = _prepare_layer(
        "empirical_error_scale", empirical_error_scale, spec.empirical_error_max, shape
    )
    kriging = _prepare_layer("kriging_std", kriging_std, spec.kriging_std_max, shape)

    # 掩膜：值阈值（含等号）；NoData 与非有限节点不进入
    finite = np.isfinite(vals)
    base = ~nodata & finite
    if spec.direction == "high":
        value_ok = vals >= spec.threshold
    else:
        value_ok = vals <= spec.threshold
    eligible = base & value_ok
    for layer in (empirical, kriging):
        if layer is None or layer.gate is None:
            continue
        layer_ok = ~layer.nodata & np.isfinite(layer.values) & (layer.values <= layer.gate)
        eligible &= layer_ok

    # 显式十字形结构元：2D 四邻接 / 3D 六邻接，不用对角接触合并
    structure = ndimage.generate_binary_structure(ndim, 1)
    labels, label_count = ndimage.label(eligible, structure=structure)
    sizes = np.bincount(labels.ravel(), minlength=label_count + 1)
    slices = ndimage.find_objects(labels)

    # 逐节点 Voronoi 支持度量网格：各轴宽度乘积
    measure_grid = np.ones(shape, dtype=np.float64)
    for dim, axis in enumerate(axes64):
        width_shape = [1] * ndim
        width_shape[dim] = shape[dim]
        measure_grid *= _voronoi_widths(axis).reshape(width_shape)

    components: list[AnomalyComponent] = []
    filtered = 0
    for offset, label_id in enumerate(range(1, label_count + 1)):
        if offset % COMPONENT_BATCH_SIZE == 0 and cancel_fn():
            raise PlatformError(
                RUN_CANCELED,
                "任务已被取消",
                {"processed_labels": offset},
                http_status=409,
            )
        size = int(sizes[label_id])
        if size < spec.min_support_nodes:
            filtered += 1
            continue
        slice_ = slices[label_id - 1]
        local = labels[slice_] == label_id
        indices = np.nonzero(local)
        global_indices = tuple(idx + sl.start for idx, sl in zip(indices, slice_))
        weights = measure_grid[slice_][local]
        total_weight = float(weights.sum())
        coords = [axes64[dim][global_indices[dim]] for dim in range(ndim)]
        centroid = [float((weights * coord).sum() / total_weight) for coord in coords]
        bounds = [(float(coord.min()), float(coord.max())) for coord in coords]
        component_values = vals[slice_][local]
        touches_boundary = any(
            bool((global_indices[dim] == 0).any())
            or bool((global_indices[dim] == shape[dim] - 1).any())
            for dim in range(ndim)
        )
        record: dict[str, Any] = {
            "component_id": len(components) + 1,
            "support_node_count": size,
            "support_measure": total_weight,
            "support_unit": _SUPPORT_UNIT_BY_DIM[ndim],
            "bounds": bounds,
            "centroid": centroid,
            "value_min": float(component_values.min()),
            "value_max": float(component_values.max()),
            "value_mean": float(component_values.mean()),
            "touches_grid_boundary": touches_boundary,
        }
        record.update(_layer_summary("empirical_error_scale", empirical, local, slice_))
        record.update(_layer_summary("kriging_std", kriging, local, slice_))
        components.append(AnomalyComponent(**record))

    diagnostics: dict[str, Any] = {
        "direction": spec.direction,
        "threshold": float(spec.threshold),
        "connectivity_rule": spec.connectivity_rule,
        "min_support_nodes": spec.min_support_nodes,
        "grid_shape": list(shape),
        "eligible_node_count": int(eligible.sum()),
        "excluded_nodata_count": int(nodata.sum()),
        "excluded_nonfinite_count": int((~nodata & ~finite).sum()),
        # 有限且非 NoData 但被值阈值或不确定性门槛排除的节点数
        "excluded_threshold_count": int((base & ~eligible).sum()),
        "labeled_component_count": int(label_count),
        "filtered_component_count": filtered,
        "component_count": len(components),
        "empirical_error_gated": spec.empirical_error_max is not None,
        "kriging_std_gated": spec.kriging_std_max is not None,
    }
    return AnomalyExtractionResult(components=tuple(components), diagnostics=diagnostics)
