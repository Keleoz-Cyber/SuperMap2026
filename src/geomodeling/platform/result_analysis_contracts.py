"""成果网格只读分析的严格公共合同。

这些 DTO 只描述已经物化的规则网格分析，不复用输入样本统计合同。所有
浮点值必须有限，未知字段一律拒绝，避免前端把残缺或旧版摘要当作真值。
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from geomodeling.platform.schemas import ContractModel

RESULT_ANALYSIS_VERSION = "result_analysis.v1"
THRESHOLD_METHOD = "numpy_linear_p25_p75"


class ResultAnalysisContract(ContractModel):
    """成果分析不可变基类。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        use_enum_values=True,
        allow_inf_nan=False,
    )


class ResultIdentity(ResultAnalysisContract):
    result_id: str = Field(min_length=1)
    grid_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_version: Literal["result_analysis.v1"] = RESULT_ANALYSIS_VERSION
    dimension: Literal["2d", "3d"]
    coordinate_type: str = Field(min_length=1)


class ResultVariable(ResultAnalysisContract):
    name: str = Field(min_length=1)
    unit: str = Field(min_length=1)


class ResultGridStatistics(ResultAnalysisContract):
    shape: list[int] = Field(min_length=2, max_length=3)
    total_count: int = Field(ge=0)
    valid_count: int = Field(ge=0)
    nodata_count: int = Field(ge=0)
    min: float
    max: float
    mean: float
    median: float
    p25: float
    p75: float

    @model_validator(mode="after")
    def _check_counts_and_order(self) -> "ResultGridStatistics":
        if any(size <= 0 for size in self.shape):
            raise ValueError("shape 各轴长度必须大于 0")
        if self.total_count != self.valid_count + self.nodata_count:
            raise ValueError("total_count 必须等于 valid_count + nodata_count")
        if self.total_count != math.prod(self.shape):
            raise ValueError("total_count 必须等于 shape 节点数乘积")
        if not self.min <= self.p25 <= self.median <= self.p75 <= self.max:
            raise ValueError("成果统计分位值顺序无效")
        return self


class ResultThresholds(ResultAnalysisContract):
    low: float
    high: float
    source: Literal["full_result_grid"] = "full_result_grid"
    method: Literal["numpy_linear_p25_p75"] = THRESHOLD_METHOD

    @model_validator(mode="after")
    def _check_order(self) -> "ResultThresholds":
        if self.low > self.high:
            raise ValueError("低阈值不得大于高阈值")
        return self


class ResultCompositionBucket(ResultAnalysisContract):
    kind: Literal["low", "normal", "high"]
    count: int = Field(ge=0)
    ratio: float = Field(ge=0.0, le=1.0)


class ResultComposition(ResultAnalysisContract):
    buckets: list[ResultCompositionBucket] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def _check_unique_kinds(self) -> "ResultComposition":
        if {item.kind for item in self.buckets} != {"low", "normal", "high"}:
            raise ValueError("composition 必须且只能包含 low/normal/high")
        if not math.isclose(sum(item.ratio for item in self.buckets), 1.0, abs_tol=1e-9):
            raise ValueError("composition ratio 之和必须为 1")
        return self


class ResultDepthBin(ResultAnalysisContract):
    index: int = Field(ge=0)
    z_lower: float
    z_upper: float
    valid_count: int = Field(ge=0)
    mean: float | None = None
    high_count: int = Field(ge=0)
    high_ratio: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_bin(self) -> "ResultDepthBin":
        if self.z_lower > self.z_upper:
            raise ValueError("z_lower 不得大于 z_upper")
        if self.high_count > self.valid_count:
            raise ValueError("high_count 不得大于 valid_count")
        if (self.valid_count == 0) != (self.mean is None):
            raise ValueError("空层 mean 必须为空，非空层 mean 必须存在")
        return self


class ResultDepthProfile(ResultAnalysisContract):
    status: Literal["available", "not_applicable"]
    bins: list[ResultDepthBin]

    @model_validator(mode="after")
    def _check_status(self) -> "ResultDepthProfile":
        if self.status == "not_applicable" and self.bins:
            raise ValueError("2D 不适用时不得返回深度分层")
        return self


class ResultAnomalyComponent(ResultAnalysisContract):
    rank: int = Field(ge=1)
    label: str = Field(pattern=r"^[A-Z]$")
    component_id: int = Field(ge=1)
    support_node_count: int = Field(ge=1)
    support_measure: float = Field(ge=0.0)
    support_unit: Literal["area_coordinate_unit2", "volume_coordinate_unit3"]
    bounds: list[tuple[float, float]] = Field(min_length=2, max_length=3)
    centroid: list[float] = Field(min_length=2, max_length=3)
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

    @model_validator(mode="after")
    def _check_component(self) -> "ResultAnomalyComponent":
        if len(self.bounds) != len(self.centroid):
            raise ValueError("bounds 与 centroid 维度必须一致")
        if any(lower > upper for lower, upper in self.bounds):
            raise ValueError("组件 bounds 顺序无效")
        if not self.value_min <= self.value_mean <= self.value_max:
            raise ValueError("组件值统计顺序无效")
        return self


class ResultComponentsPreview(ResultAnalysisContract):
    threshold: float
    connectivity_rule: Literal["face_2d4_3d6_v1"] = "face_2d4_3d6_v1"
    total: int = Field(ge=0)
    returned: int = Field(ge=0)
    rows: list[ResultAnomalyComponent]

    @model_validator(mode="after")
    def _check_counts(self) -> "ResultComponentsPreview":
        if self.returned != len(self.rows) or self.returned > self.total:
            raise ValueError("组件预览计数与 rows 不一致")
        return self


class ResultModelEvidence(ResultAnalysisContract):
    algorithm: str = Field(min_length=1)
    metrics: dict[str, float | int | None]
    common_valid_count: int | None = Field(default=None, ge=0)
    formal_selection: bool
    uncertainty_status: Literal["available", "unavailable", "not_applicable"]

    @field_validator("metrics")
    @classmethod
    def _finite_metrics(cls, metrics: dict[str, float | int | None]):
        for name, value in metrics.items():
            if not name or (value is not None and not math.isfinite(float(value))):
                raise ValueError("模型指标名称必须非空且数值必须有限")
        return metrics


class ResultEvidenceItem(ResultAnalysisContract):
    label: str = Field(min_length=1)
    value: float | int | str | bool
    unit: str | None = None

    @field_validator("value")
    @classmethod
    def _finite_value(cls, value: Any):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("发现证据数值必须有限")
        return value


class ResultSpatialTarget(ResultAnalysisContract):
    kind: Literal["none", "component", "depth_interval", "slice"]
    component_label: str | None = Field(default=None, pattern=r"^[A-Z]$")
    axis: Literal["x", "y", "z"] | None = None
    index: int | None = Field(default=None, ge=0)
    lower: float | None = None
    upper: float | None = None


class ResultFinding(ResultAnalysisContract):
    id: str = Field(min_length=1)
    kind: Literal[
        "dominant_depth_interval",
        "largest_high_component",
        "boundary_contact",
        "formal_model",
        "uncertainty_availability",
    ]
    title: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    evidence: list[ResultEvidenceItem]
    confidence: Literal["supported", "limited", "unavailable"]
    limitations: list[str]
    spatial_target: ResultSpatialTarget


class ResultAnalysisProvenance(ResultAnalysisContract):
    grid_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    calculation_version: Literal["result_analysis.v1"] = RESULT_ANALYSIS_VERSION
    threshold_method: Literal["numpy_linear_p25_p75"] = THRESHOLD_METHOD


class ResultAnalysisSummary(ResultAnalysisContract):
    identity: ResultIdentity
    variable: ResultVariable
    grid: ResultGridStatistics
    thresholds: ResultThresholds
    composition: ResultComposition
    depth_profile: ResultDepthProfile
    components_preview: ResultComponentsPreview
    model_evidence: ResultModelEvidence
    findings: list[ResultFinding]
    provenance: ResultAnalysisProvenance


__all__ = [
    "RESULT_ANALYSIS_VERSION",
    "THRESHOLD_METHOD",
    "ResultAnalysisProvenance",
    "ResultAnalysisSummary",
    "ResultAnomalyComponent",
    "ResultComponentsPreview",
    "ResultComposition",
    "ResultCompositionBucket",
    "ResultDepthBin",
    "ResultDepthProfile",
    "ResultEvidenceItem",
    "ResultFinding",
    "ResultGridStatistics",
    "ResultIdentity",
    "ResultModelEvidence",
    "ResultSpatialTarget",
    "ResultThresholds",
    "ResultVariable",
]
