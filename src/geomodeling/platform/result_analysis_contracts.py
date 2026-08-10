"""v0.9.0 成果级分析的严格合同 DTO 与计算版本。

所有模型 ``extra="forbid"``，未知字段在合同边界拒绝；所有浮点字段
必须有限（``math.isfinite``），NaN/Inf fail-closed。「不适用」用类型化
状态表达，绝不以空数组或 0 值代替。

设计依据：docs/superpowers/specs/2026-08-10-v0.9.0-result-analysis-integration-design.md §5。
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Literal

from pydantic import Field, field_validator

from geomodeling.platform.schemas import ContractModel

__all__ = [
    "RESULT_ANALYSIS_VERSION",
    "RESULT_ANALYSIS_NO_VALID_CELLS",
    "RESULT_ANALYSIS_GRID_CORRUPT",
    "RESULT_ANALYSIS_NOT_APPLICABLE",
    "DepthProfileStatus",
    "ThresholdSource",
    "FindingKind",
    "FindingConfidence",
    "ResultIdentity",
    "VariableInfo",
    "GridStatistics",
    "Thresholds",
    "CompositionBucket",
    "Composition",
    "DepthBin",
    "DepthProfile",
    "ComponentPreview",
    "ComponentsPreview",
    "ModelEvidence",
    "SpatialTarget",
    "FindingEvidence",
    "Finding",
    "Provenance",
    "ResultAnalysisSummary",
]

RESULT_ANALYSIS_VERSION = "result_analysis.v1"

RESULT_ANALYSIS_NO_VALID_CELLS = "RESULT_ANALYSIS_NO_VALID_CELLS"
RESULT_ANALYSIS_GRID_CORRUPT = "RESULT_ANALYSIS_GRID_CORRUPT"
RESULT_ANALYSIS_NOT_APPLICABLE = "RESULT_ANALYSIS_NOT_APPLICABLE"


class DepthProfileStatus(str, Enum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"


class ThresholdSource(str, Enum):
    FULL_GRID_QUARTILE = "full_grid_quartile"


class FindingKind(str, Enum):
    DOMINANT_DEPTH_INTERVAL = "dominant_depth_interval"
    LARGEST_HIGH_COMPONENT = "largest_high_component"
    BOUNDARY_CONTACT = "boundary_contact"
    FORMAL_MODEL = "formal_model"
    UNCERTAINTY_AVAILABILITY = "uncertainty_availability"


class FindingConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CoordinateType(str, Enum):
    LOCAL_LINEAR = "local_linear"
    WGS84 = "wgs84"


class ResultIdentity(ContractModel):
    result_id: str
    grid_sha256: str
    analysis_version: str
    dimension: Literal["2d", "3d"]
    coordinate_type: str


class VariableInfo(ContractModel):
    name: str
    unit: str


class GridStatistics(ContractModel):
    shape: list[int]
    valid_count: int
    nodata_count: int
    min: float
    max: float
    mean: float
    median: float
    p25: float
    p75: float

    @field_validator("min", "max", "mean", "median", "p25", "p75")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("grid statistics must be finite")
        return v


class Thresholds(ContractModel):
    low: float
    high: float
    source: str
    method: str

    @field_validator("low", "high")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("thresholds must be finite")
        return v


class CompositionBucket(ContractModel):
    category: Literal["low", "normal", "high"]
    count: int
    ratio: float

    @field_validator("ratio")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("ratio must be finite")
        return v


class Composition(ContractModel):
    buckets: list[CompositionBucket]


class DepthBin(ContractModel):
    z_lower: float
    z_upper: float
    valid_count: int
    mean: float
    high_count: int
    high_ratio: float

    @field_validator("z_lower", "z_upper", "mean", "high_ratio")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("depth bin values must be finite")
        return v


class DepthProfile(ContractModel):
    status: str
    bins: list[DepthBin]


class ComponentPreview(ContractModel):
    rank: int
    label: str
    component_id: int
    support_node_count: int
    support_measure: float
    support_unit: Literal["area_coordinate_unit2", "volume_coordinate_unit3"]
    bounds: list[list[float]]
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

    @field_validator(
        "support_measure", "value_min", "value_max", "value_mean",
        "empirical_error_scale_min", "empirical_error_scale_max",
        "empirical_error_scale_mean", "kriging_std_min",
        "kriging_std_max", "kriging_std_mean",
    )
    @classmethod
    def _finite_optional(cls, v: float | None) -> float | None:
        if v is not None and not math.isfinite(v):
            raise ValueError("component values must be finite or None")
        return v

    @field_validator("bounds")
    @classmethod
    def _bounds_finite(cls, v: list[list[float]]) -> list[list[float]]:
        for pair in v:
            for x in pair:
                if not math.isfinite(x):
                    raise ValueError("bounds must be finite")
        return v

    @field_validator("centroid")
    @classmethod
    def _centroid_finite(cls, v: list[float]) -> list[float]:
        for x in v:
            if not math.isfinite(x):
                raise ValueError("centroid must be finite")
        return v


class ComponentsPreview(ContractModel):
    threshold: float
    connectivity_rule: str
    total: int
    returned: int
    rows: list[ComponentPreview]

    @field_validator("threshold")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("threshold must be finite")
        return v


class ModelEvidence(ContractModel):
    algorithm: str
    metrics: dict[str, float | int | None] = Field(default_factory=dict)
    common_valid_count: int | None = None
    formal_selection_id: str | None = None
    formal_selection_note: str | None = None


class SpatialTarget(ContractModel):
    kind: Literal["component", "depth_bin", "grid"]
    component_id: int | None = None
    depth_bin_index: int | None = None


class FindingEvidence(ContractModel):
    name: str
    value: float | int | str | None = None

    @field_validator("value")
    @classmethod
    def _finite_optional(cls, v: float | int | str | None) -> float | int | str | None:
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError("evidence value must be finite")
        return v


class Finding(ContractModel):
    id: str
    kind: str
    title: str
    statement: str
    evidence: list[FindingEvidence]
    confidence: str
    limitations: list[str]
    spatial_target: SpatialTarget | None = None


class Provenance(ContractModel):
    grid_sha256: str
    calculation_version: str
    threshold_method: str


class ResultAnalysisSummary(ContractModel):
    identity: ResultIdentity
    variable: VariableInfo
    grid: GridStatistics
    thresholds: Thresholds
    composition: Composition
    depth_profile: DepthProfile
    components_preview: ComponentsPreview
    model_evidence: ModelEvidence
    findings: list[Finding]
    provenance: Provenance
