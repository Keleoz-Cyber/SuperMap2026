"""v0.9.0 AI 辅助研判的严格合同 DTO。

``EvidencePacket`` 是发送给 AI 模型的有界、脱敏、可复算的证据摘要。
``AIReview`` 是 AI 返回的结构化多视角输出。两者都 ``extra="forbid"``，
未知字段拒绝；所有浮点字段必须有限。AI 引用只能指向当前
EvidencePacket 的合法证据 ID。

当前合同依据：docs/architecture.md。
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from geomodeling.platform.schemas import ContractModel

__all__ = [
    "PROMPT_VERSION",
    "AIAnalysisMode",
    "AIAnalysisStatus",
    "EvidenceIdentity",
    "EvidenceVariable",
    "EvidenceGridStatistics",
    "EvidenceThresholds",
    "EvidenceComposition",
    "EvidenceDepthProfile",
    "EvidenceComponentSummary",
    "EvidenceCurrentSlice",
    "EvidenceModelMetrics",
    "EvidenceUncertainty",
    "EvidenceInputQuality",
    "EvidenceConstraints",
    "EvidencePacket",
    "AIPerspective",
    "AIDecisionOption",
    "AIConsensus",
    "AIReview",
    "AIAnalysisRecord",
    "AIAnalysisRequest",
]

PROMPT_VERSION = "ai_review.v1"


class AIAnalysisMode(str, Enum):
    QUICK = "quick"
    REVIEW = "review"


class AIAnalysisStatus(str, Enum):
    SUCCEEDED = "succeeded"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class EvidenceIdentity(ContractModel):
    result_id: str
    grid_sha256: str
    calculation_version: str
    dimension: Literal["2d", "3d"]
    coordinate_type: str


class EvidenceVariable(ContractModel):
    name: str
    unit: str


class EvidenceGridStatistics(ContractModel):
    valid_count: int
    nodata_count: int
    min: float
    max: float
    mean: float
    p25: float
    p75: float

    @field_validator("min", "max", "mean", "p25", "p75")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("must be finite")
        return v


class EvidenceThresholds(ContractModel):
    low: float
    high: float
    method: str

    @field_validator("low", "high")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("must be finite")
        return v


class EvidenceCompositionBucket(ContractModel):
    category: Literal["low", "normal", "high"]
    count: int
    ratio: float

    @field_validator("ratio")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("must be finite")
        return v


class EvidenceComposition(ContractModel):
    buckets: list[EvidenceCompositionBucket]


class EvidenceDepthBin(ContractModel):
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
            raise ValueError("must be finite")
        return v


class EvidenceDepthProfile(ContractModel):
    status: Literal["applicable", "not_applicable"]
    bins: list[EvidenceDepthBin]


class EvidenceComponentSummary(ContractModel):
    label: str
    component_id: int
    support_node_count: int
    support_measure: float
    value_max: float
    value_mean: float
    touches_grid_boundary: bool

    @field_validator("support_measure", "value_max", "value_mean")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("must be finite")
        return v


class EvidenceCurrentSlice(ContractModel):
    axis: str
    coordinate: float
    valid_count: int
    mean: float
    high_count: int
    high_ratio: float

    @field_validator("coordinate", "mean", "high_ratio")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("must be finite")
        return v


class EvidenceModelMetrics(ContractModel):
    algorithm: str
    common_valid_count: int | None = None
    rmse: float | None = None
    mae: float | None = None
    r2: float | None = None
    coverage: float | None = None
    formal_selection_id: str | None = None

    @field_validator("rmse", "mae", "r2", "coverage")
    @classmethod
    def _finite_optional(cls, v: float | None) -> float | None:
        if v is not None and not math.isfinite(v):
            raise ValueError("must be finite or None")
        return v


class EvidenceUncertainty(ContractModel):
    availability: Literal["available", "missing", "not_applicable"]
    empirical_error_mean: float | None = None
    kriging_std_mean: float | None = None

    @field_validator("empirical_error_mean", "kriging_std_mean")
    @classmethod
    def _finite_optional(cls, v: float | None) -> float | None:
        if v is not None and not math.isfinite(v):
            raise ValueError("must be finite or None")
        return v


class EvidenceInputQuality(ContractModel):
    validated_count: int | None = None
    total_count: int | None = None
    coverage: float | None = None

    @field_validator("coverage")
    @classmethod
    def _finite_optional(cls, v: float | None) -> float | None:
        if v is not None and not math.isfinite(v):
            raise ValueError("must be finite or None")
        return v


class EvidenceConstraints(ContractModel):
    prohibited_claims: list[str]
    known_limitations: list[str]


class EvidenceResultGrid(ContractModel):
    statistics: EvidenceGridStatistics
    thresholds: EvidenceThresholds
    composition: EvidenceComposition
    depth_profile: EvidenceDepthProfile


class EvidencePacket(ContractModel):
    identity: EvidenceIdentity
    variable: EvidenceVariable
    result_grid: EvidenceResultGrid
    spatial_components: list[EvidenceComponentSummary] = Field(default_factory=list)
    current_slice: EvidenceCurrentSlice | None = None
    model_evidence: EvidenceModelMetrics
    uncertainty: EvidenceUncertainty
    input_quality: EvidenceInputQuality
    constraints: EvidenceConstraints

    @property
    def valid_evidence_ids(self) -> set[str]:
        """Return the set of valid evidence IDs for ref validation."""
        # Every top-level EvidencePacket node is a legitimate aggregate
        # citation; component/depth-bin IDs below provide finer granularity.
        ids: set[str] = {
            "identity",
            "variable",
            "result_grid",
            "spatial_components",
            "model_evidence",
            "uncertainty",
            "input_quality",
            "constraints",
        }
        for comp in self.spatial_components:
            ids.add(f"component-{comp.component_id}")
        ids.add("depth_profile")
        ids.add("composition")
        if self.current_slice is not None:
            ids.add("current_slice")
        for i in range(len(self.result_grid.depth_profile.bins)):
            ids.add(f"depth_bin-{i}")
        return ids


class AIPerspective(ContractModel):
    summary: str
    evidence_refs: list[str]


class AIDecisionOption(ContractModel):
    label: str
    trigger: str
    benefit: str
    cost: str
    evidence_refs: list[str] = Field(default_factory=list)


class AIConsensus(ContractModel):
    consensus: str
    disagreements: list[str] = Field(default_factory=list)
    recommended_checks: list[str] = Field(default_factory=list)
    decision_options: list[AIDecisionOption] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class AIReview(ContractModel):
    spatial_pattern: AIPerspective
    model_reliability: AIPerspective
    uncertainty_and_risk: AIPerspective
    review_and_next_checks: AIPerspective
    consensus: AIConsensus
    evidence_hash: str
    prompt_version: str
    provider: str
    model: str
    mode: AIAnalysisMode

    @model_validator(mode="after")
    def _check_evidence_refs(self) -> "AIReview":
        for perspective in (
            self.spatial_pattern,
            self.model_reliability,
            self.uncertainty_and_risk,
            self.review_and_next_checks,
        ):
            for ref in perspective.evidence_refs:
                if not ref:
                    raise ValueError("evidence_ref must not be empty")
        for opt in self.consensus.decision_options:
            for ref in opt.evidence_refs:
                if not ref:
                    raise ValueError("evidence_ref must not be empty")
        return self


class AIAnalysisRecord(ContractModel):
    id: str
    result_id: str
    grid_sha256: str
    evidence_hash: str
    prompt_version: str
    provider: str
    model: str
    mode: AIAnalysisMode
    status: AIAnalysisStatus
    review: AIReview | None = None
    error_code: str | None = None
    error_message: str | None = None
    usage_prompt_tokens: int | None = None
    usage_completion_tokens: int | None = None
    latency_ms: int | None = None
    created_at: str


class AIAnalysisRequest(ContractModel):
    mode: Literal["quick", "review"] = "quick"
    regenerate: bool = False
