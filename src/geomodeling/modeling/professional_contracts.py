"""v0.6 professional-analysis contracts and the algorithm capability matrix.

Strict Pydantic contracts shared by the professional modeling modules
(directional variograms, anisotropy transforms, search neighborhoods,
empirical error scale and anomaly extraction). Every model forbids unknown
keys and validates finiteness for each float field, so impossible parameter
combinations are rejected at the contract boundary instead of deep inside
numerical code. ``AlgorithmCapabilities`` records are immutable and express
"not applicable" as a typed capability state, never as an empty value.

设计依据：docs/superpowers/specs/2026-07-26-v0.6-professional-modeling-enhancements-design.md
§3.3 能力矩阵、§6.3 方向定义、§8.1 搜索邻域、§10.2 经验误差尺度、§12.1 异常配置。
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from geomodeling.modeling.distance import MAX_Z_SCALE
from geomodeling.platform.schemas import Algorithm, ContractModel, Dimension

__all__ = [
    "AlgorithmCapabilities",
    "AnomalyExtractionSpec",
    "CapabilityState",
    "DirectionSpec",
    "EmpiricalUncertaintySpec",
    "NeighborhoodSpec",
    "VariogramDiagnosticSpec",
    "ZScaleSpec",
    "capabilities_for",
]


class CapabilityState(str, Enum):
    """算法能力状态。

    「不适用」是类型化 capability 状态，不得以空数组、0 或失败状态表达。
    """

    SUPPORTED = "supported"
    NOT_APPLICABLE = "not_applicable"


def _require_finite(value: float | None, field_name: str) -> None:
    """每个浮点字段统一的 ``math.isfinite`` 校验（None 由字段可空性负责）。"""

    if value is not None and not math.isfinite(value):
        raise ValueError(f"{field_name} 必须为有限值，收到 {value!r}")


class DirectionSpec(ContractModel):
    """方向半变异函数的方向定义（§6.3）。

    方位角在 XY 平面内从 +X 朝 +Y 旋转，范围 ``[0°, 180°)``：方向无正反，
    向量 ``d`` 与 ``-d`` 属于同一方向，故 180°（≡ 0°）不被接受。倾角从
    水平面朝 +Z，范围 ``[-90°, 90°]``。2D 不接受倾角及其容差；3D 必须
    显式保存倾角与两个角度容差（有限且 > 0，上限 90°：无向方向的夹角
    不超出直角）。
    """

    dimension: Dimension
    azimuth_deg: float = Field(ge=0, lt=180)
    dip_deg: float | None = Field(default=None, ge=-90, le=90)
    azimuth_tolerance_deg: float = Field(default=15.0, gt=0, le=90)
    dip_tolerance_deg: float | None = Field(default=None, gt=0, le=90)

    @model_validator(mode="after")
    def _check_direction(self) -> "DirectionSpec":
        _require_finite(self.azimuth_deg, "azimuth_deg")
        _require_finite(self.dip_deg, "dip_deg")
        _require_finite(self.azimuth_tolerance_deg, "azimuth_tolerance_deg")
        _require_finite(self.dip_tolerance_deg, "dip_tolerance_deg")
        if self.dimension == Dimension.TWO_D:
            if self.dip_deg is not None:
                raise ValueError("2D 方向不接受倾角参数")
            if self.dip_tolerance_deg is not None:
                raise ValueError("2D 方向不接受倾角容差")
        else:
            if self.dip_deg is None:
                raise ValueError("3D 方向必须显式给出倾角（水平方向使用 0）")
            if self.dip_tolerance_deg is None:
                raise ValueError("3D 方向必须显式保存倾角容差")
        return self


class NeighborhoodSpec(ContractModel):
    """旋转椭圆（2D）/椭球（3D）搜索邻域（§8.1）。

    ``radii`` 二元组为 2D（主、次半径），三元组为 3D（增加垂向半径），
    全部半径有限且 > 0；2D 邻域（radii 长度为 2）不接受倾角/滚转角。
    约束 ``min_neighbors <= max_neighbors`` 且
    ``sector_count * max_per_sector >= min_neighbors``：扇区容量装不下
    最少邻点数时任何查询都不可能成功，契约层直接拒绝。
    """

    radii: tuple[float, float] | tuple[float, float, float]
    azimuth_deg: float = Field(default=0, ge=0, lt=180)
    dip_deg: float | None = Field(default=None, ge=-90, le=90)
    roll_deg: float | None = Field(default=None, ge=-180, le=180)
    min_neighbors: int = Field(default=3, ge=1, le=64)
    max_neighbors: int = Field(default=24, ge=1, le=128)
    sector_count: int = Field(default=4, ge=1, le=16)
    max_per_sector: int = Field(default=8, ge=1, le=128)

    @model_validator(mode="after")
    def _check_neighborhood(self) -> "NeighborhoodSpec":
        for index, radius in enumerate(self.radii):
            _require_finite(radius, f"radii[{index}]")
            if radius <= 0:
                raise ValueError(f"radii[{index}] 必须大于 0，收到 {radius!r}")
        _require_finite(self.azimuth_deg, "azimuth_deg")
        _require_finite(self.dip_deg, "dip_deg")
        _require_finite(self.roll_deg, "roll_deg")
        if len(self.radii) == 2 and (self.dip_deg is not None or self.roll_deg is not None):
            raise ValueError("2D 邻域（radii 长度为 2）不接受倾角/滚转角")
        if self.min_neighbors > self.max_neighbors:
            raise ValueError("min_neighbors 不得大于 max_neighbors")
        if self.sector_count * self.max_per_sector < self.min_neighbors:
            raise ValueError("sector_count × max_per_sector 必须不小于 min_neighbors")
        return self


class VariogramDiagnosticSpec(ContractModel):
    """全向/方向经验半变异函数诊断配置（§6）。

    ``directions`` 为空表示仅全向诊断；方向数量设硬上限（8）以防止
    无界参数组合。``max_pairs`` 默认维持 v0.5 的 50,000 点对上限；
    ``max_distance`` 为 None 时由数据范围推导。
    """

    lag_count: int = Field(default=12, ge=4, le=48)
    max_distance: float | None = Field(default=None, gt=0)
    min_pairs_per_bin: int = Field(default=30, ge=2, le=10_000)
    max_pairs: int = Field(default=50_000, ge=100, le=500_000)
    directions: tuple[DirectionSpec, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def _check_variogram(self) -> "VariogramDiagnosticSpec":
        _require_finite(self.max_distance, "max_distance")
        return self


class ZScaleSpec(ContractModel):
    """IDW 权重距离的 ``z_scale`` 契约（与 v0.5 语义一致）。

    有限且 ``0 < z_scale <= 20``，默认 1；距离在 ``(x, y, z × z_scale)``
    上计算，物理坐标永不改写（见 ``modeling.distance``）。
    """

    z_scale: float = Field(default=1.0, gt=0, le=MAX_Z_SCALE)

    @model_validator(mode="after")
    def _check_z_scale(self) -> "ZScaleSpec":
        _require_finite(self.z_scale, "z_scale")
        return self


class EmpiricalUncertaintySpec(ContractModel):
    """经验误差尺度参数（§10.2）：折外残差的距离加权局部 RMSE。

    权重为 ``1/d**power``。``neighborhood=None``（默认）表示复用候选
    搜索邻域的方向与半径，避免出现另一套未披露的空间假设；显式给出时
    作为独立的误差邻域记录。
    """

    min_neighbors: int = Field(default=3, ge=1, le=64)
    max_neighbors: int = Field(default=24, ge=1, le=128)
    power: float = Field(default=2.0, gt=0, le=8)
    neighborhood: NeighborhoodSpec | None = None

    @model_validator(mode="after")
    def _check_uncertainty(self) -> "EmpiricalUncertaintySpec":
        _require_finite(self.power, "power")
        if self.min_neighbors > self.max_neighbors:
            raise ValueError("min_neighbors 不得大于 max_neighbors")
        return self


class AnomalyExtractionSpec(ContractModel):
    """显式阈值异常连通区提取配置（§12.1）。

    高值使用 ``value >= threshold``，低值使用 ``value <= threshold``；
    ``threshold`` 为值阈值，任意有限符号均合法。两个不确定性上限是
    可选门槛，给出时必须有限且 > 0；NoData 与不满足门槛的节点不进入
    掩膜。``connectivity_rule`` 显式保存连通规则版本（2D 固定 4 邻接、
    3D 固定 6 邻接，不用对角接触合并）。
    """

    direction: Literal["high", "low"]
    threshold: float
    empirical_error_max: float | None = None
    kriging_std_max: float | None = None
    min_support_nodes: int = Field(default=1, ge=1)
    connectivity_rule: Literal["face_2d4_3d6_v1"] = "face_2d4_3d6_v1"

    @model_validator(mode="after")
    def _check_anomaly(self) -> "AnomalyExtractionSpec":
        _require_finite(self.threshold, "threshold")
        for name in ("empirical_error_max", "kriging_std_max"):
            value = getattr(self, name)
            _require_finite(value, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} 必须大于 0，收到 {value!r}")
        return self


class AlgorithmCapabilities(ContractModel):
    """单个算法的不可变能力记录（§3.3）。

    能力字段保留 :class:`CapabilityState` 枚举类型（不使用枚举值展开），
    「不适用」因此是类型化状态；``notes`` 保存「支持，人工确认」、
    「旧候选兼容」等矩阵限定语。
    """

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)

    algorithm: Algorithm
    empirical_variogram: CapabilityState
    model_anisotropy: CapabilityState
    z_scale_weight_distance: CapabilityState
    search_neighborhood: CapabilityState
    sector_neighbor_limits: CapabilityState
    spatial_fold_inspection: CapabilityState
    empirical_error_scale: CapabilityState
    native_kriging_std: CapabilityState
    anomaly_extraction: CapabilityState
    candidate_comparison: CapabilityState
    notes: dict[str, str] = Field(default_factory=dict)


_SUPPORTED = CapabilityState.SUPPORTED
_NA = CapabilityState.NOT_APPLICABLE

_ALGORITHM_CAPABILITIES: dict[Algorithm, AlgorithmCapabilities] = {
    Algorithm.IDW: AlgorithmCapabilities(
        algorithm=Algorithm.IDW,
        empirical_variogram=_NA,
        model_anisotropy=_NA,
        z_scale_weight_distance=_SUPPORTED,
        search_neighborhood=_SUPPORTED,
        sector_neighbor_limits=_SUPPORTED,
        spatial_fold_inspection=_SUPPORTED,
        empirical_error_scale=_SUPPORTED,
        native_kriging_std=_NA,
        anomaly_extraction=_SUPPORTED,
        candidate_comparison=_SUPPORTED,
        notes={
            "z_scale_weight_distance": "支持：(x, y, z × z_scale) 权重距离",
        },
    ),
    Algorithm.ORDINARY_KRIGING: AlgorithmCapabilities(
        algorithm=Algorithm.ORDINARY_KRIGING,
        empirical_variogram=_SUPPORTED,
        model_anisotropy=_SUPPORTED,
        z_scale_weight_distance=_SUPPORTED,
        search_neighborhood=_SUPPORTED,
        sector_neighbor_limits=_SUPPORTED,
        spatial_fold_inspection=_SUPPORTED,
        empirical_error_scale=_SUPPORTED,
        native_kriging_std=_SUPPORTED,
        anomaly_extraction=_SUPPORTED,
        candidate_comparison=_SUPPORTED,
        notes={
            "model_anisotropy": "支持，人工确认",
            "z_scale_weight_distance": "旧候选兼容；新候选归一化到空间变换",
        },
    ),
    # v0.8.0：DSI-like 无原生不确定性（与 IDW 同档：经验误差尺度可用、
    # 无 Kriging 原生方差）；规则网格邻接平滑，没有搜索邻域/z_scale/变异
    # 函数旋钮，诚实标记为类型化「不适用」。
    Algorithm.DSI_LIKE: AlgorithmCapabilities(
        algorithm=Algorithm.DSI_LIKE,
        empirical_variogram=_NA,
        model_anisotropy=_NA,
        z_scale_weight_distance=_NA,
        search_neighborhood=_NA,
        sector_neighbor_limits=_NA,
        spatial_fold_inspection=_SUPPORTED,
        empirical_error_scale=_SUPPORTED,
        native_kriging_std=_NA,
        anomaly_extraction=_SUPPORTED,
        candidate_comparison=_SUPPORTED,
        notes={
            "native_kriging_std": "不适用：无原生不确定性，经验误差尺度可用",
            "search_neighborhood": "不适用：规则网格 6/18/26 邻接平滑，无搜索邻域",
        },
    ),
}


def capabilities_for(algorithm: Algorithm | str) -> AlgorithmCapabilities:
    """返回算法的不可变能力记录；未知算法抛出 ``ValueError``。"""

    return _ALGORITHM_CAPABILITIES[Algorithm(algorithm)]
