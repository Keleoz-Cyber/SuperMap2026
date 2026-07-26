from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field


class MicroseismicSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKER = "blocker"


class MicroseismicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class SourceFileManifestEntry(MicroseismicModel):
    source_file_id: str
    relative_path: str
    file_name: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mtime: datetime
    encoding: str
    header_text: str | None
    nul_terminator: bool
    nul_pseudo_line_count: int = Field(ge=0)
    point_id: str
    line_id: str
    source_record_count: int = Field(ge=0)
    valid_numeric_count: int = Field(ge=0)
    invalid_numeric_count: int = Field(ge=0)
    parse_status: str
    quality_issues: list[str] = Field(default_factory=list)


class VelocitySample(MicroseismicModel):
    sample_id: str
    point_id: str
    line_id: str
    source_file_id: str
    source_file_name: str
    source_line_number: int = Field(ge=1)
    wl_half_km_raw_token: str | None
    vx_raw_token: str | None
    wl_half_km_value: float | None
    vx_value: float | None
    source_unit: str
    is_numeric_valid: bool
    invalid_reason: str | None = None
    quality_flags: list[str] = Field(default_factory=list)
    included_in_raw: bool = True
    included_in_valid_numeric: bool = False
    included_in_clean_candidate: bool = False
    outlier_reason: str | None = None
    imputed: bool = False
    imputation_method: str | None = None
    cleaning_version: str = "none_v0.2a"
    derived_depth_m: float | None = None
    derived_z_m: float | None = None
    depth_derivation_status: str = "unconfirmed"
    notes: str | None = None


class DerivationContractError(ValueError):
    """A supposedly finite source sample is missing values required for derivation."""


class AggregationContractError(ValueError):
    """Exactly collocated rows disagree on point or line identity."""


# Golden-compatible rule strings, kept byte-identical to the confirmed golden
# derived table (microseismic_local_3d_v0.2b_confirmed_2026-07-20).
DEPTH_RULE = "DEPTH_M=WL_HALF_KM*1000;down_positive"
Z_RULE = "Z_LOCAL_M=-DEPTH_M;up_positive"
COORD_TYPE_LOCAL = "local_engineering_m"


class DerivedVelocitySample(MicroseismicModel):
    """v0.5 local-XYZ row derived from one finite v0.2a VelocitySample.

    Field set mirrors the golden derived table columns in snake case. The Vx
    unit is a fixed contract constant (the golden table has no unit column),
    so vx_unit is exposed as a class attribute, not a serialized field.
    """

    vx_unit: ClassVar[str] = "km/s"

    sample_id: str
    point_id: str
    line_id: str
    x_local_m: float
    y_local_m: float
    depth_m: float
    z_local_m: float
    vx_km_s: float
    wl_half_km: float
    source_file: str
    source_line: int
    vx_raw_token: str
    is_valid: bool = True
    coord_type: str = COORD_TYPE_LOCAL
    depth_rule: str
    z_rule: str
    rule_version: str

    @classmethod
    def from_source(
        cls,
        sample: VelocitySample,
        *,
        x: float,
        y: float,
        depth: float,
        z: float,
        rule_version: str,
    ) -> "DerivedVelocitySample":
        missing = [
            name
            for name, value in (
                ("wl_half_km_value", sample.wl_half_km_value),
                ("vx_value", sample.vx_value),
                ("vx_raw_token", sample.vx_raw_token),
            )
            if value is None
        ]
        if missing:
            raise DerivationContractError(
                f"sample {sample.sample_id} is numeric-valid but missing {', '.join(missing)}"
            )
        return cls(
            sample_id=sample.sample_id,
            point_id=sample.point_id,
            line_id=sample.line_id,
            x_local_m=x,
            y_local_m=y,
            depth_m=depth,
            z_local_m=z,
            vx_km_s=sample.vx_value,
            wl_half_km=sample.wl_half_km_value,
            source_file=sample.source_file_name,
            source_line=sample.source_line_number,
            vx_raw_token=sample.vx_raw_token,
            depth_rule=DEPTH_RULE,
            z_rule=Z_RULE,
            rule_version=rule_version,
        )


class RejectedFilteredSample(DerivedVelocitySample):
    """Derived row rejected by the one-pass global 3σ filter.

    Keeps every derived source field and adds both z-scores plus the filter
    outcome. The four outcome fields serialize to the uppercase golden
    columns; the source record is never deleted, interpolated, or backfilled.
    """

    depth_zscore: float = Field(serialization_alias="DEPTH_ZSCORE")
    vx_zscore: float = Field(serialization_alias="VX_ZSCORE")
    filter_status: str = Field(serialization_alias="FILTER_STATUS")
    filter_reason: str = Field(serialization_alias="FILTER_REASON")

    @classmethod
    def from_derived(
        cls,
        row: DerivedVelocitySample,
        *,
        depth_zscore: float,
        vx_zscore: float,
        filter_reason: str,
        filter_status: str = "剔除",
    ) -> "RejectedFilteredSample":
        return cls(
            **row.model_dump(),
            depth_zscore=depth_zscore,
            vx_zscore=vx_zscore,
            filter_status=filter_status,
            filter_reason=filter_reason,
        )


class ThreeSigmaResult(MicroseismicModel):
    """Immutable outcome of one global 3σ pass over all finite derived rows.

    Statistics are computed exactly once from the full input (sample standard
    deviation, ddof=1); accepted and rejected each preserve source order.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True, frozen=True)

    threshold: float
    ddof: int
    depth_mean: float
    depth_std: float
    vx_mean: float
    vx_std: float
    accepted: list[DerivedVelocitySample]
    rejected: list[RejectedFilteredSample]


class AggregatedModelingNode(MicroseismicModel):
    """One unique modeling node produced by exact-XYZ aggregation.

    vx_km_s is the arithmetic mean of the group's candidate Vx values; a
    single-record group keeps its source value exactly. Provenance fields keep
    every source sample id in source order, and vx_sample_std_km_s is null for
    single-record groups and uses ddof=1 otherwise.
    """

    x_local_m: float
    y_local_m: float
    z_local_m: float
    vx_km_s: float
    point_id: str
    line_id: str
    source_sample_ids: list[str]
    sample_count: int = Field(ge=1)
    vx_min_km_s: float
    vx_max_km_s: float
    vx_sample_std_km_s: float | None


class AggregationResult(MicroseismicModel):
    """Immutable outcome of exact-XYZ aggregation over the accepted rows.

    The accepted golden candidate set is never modified; aggregation only
    produces this modeling-node collection. Conflict statistics describe the
    groups whose sample_count is greater than one.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True, frozen=True)

    nodes: list[AggregatedModelingNode]
    conflict_group_count: int = Field(ge=0)
    conflict_row_count: int = Field(ge=0)
    collapsed_row_count: int = Field(ge=0)
    max_value_range: float = Field(ge=0)


class InvalidDerivedSample(MicroseismicModel):
    """Non-finite source record routed out of derivation with its raw trace."""

    sample_id: str
    point_id: str
    line_id: str
    source_file: str
    source_line: int
    wl_half_km_raw_token: str | None
    vx_raw_token: str | None
    invalid_reason: str | None
    is_valid: bool = False
    rule_version: str = ""

    @classmethod
    def from_source(cls, sample: VelocitySample, *, rule_version: str = "") -> "InvalidDerivedSample":
        return cls(
            sample_id=sample.sample_id,
            point_id=sample.point_id,
            line_id=sample.line_id,
            source_file=sample.source_file_name,
            source_line=sample.source_line_number,
            wl_half_km_raw_token=sample.wl_half_km_raw_token,
            vx_raw_token=sample.vx_raw_token,
            invalid_reason=sample.invalid_reason,
            rule_version=rule_version,
        )


class SurveyPoint(MicroseismicModel):
    point_id: str
    original_point_label: str
    source_file_id: str
    line_id: str
    sequence_on_line: int | None = Field(default=None, ge=1)
    previous_point_id: str | None = None
    interval_from_previous_m: float | None = None
    cumulative_s_m: float | None = Field(default=None, ge=0)
    interval_source: str | None = None
    order_source: str
    included_in_formal_set: bool = True
    exclusion_reason: str | None = None
    source_record_count: int = Field(ge=0)
    valid_numeric_count: int = Field(ge=0)
    coordinate_status: str = "unconfirmed"
    x_local_m: float | None = None
    y_local_m: float | None = None
    z_reference_status: str = "unconfirmed"
    source_confidence: str
    notes: str | None = None


class SurveyLine(MicroseismicModel):
    line_id: str
    point_start: str
    point_end: str
    formal_point_count: int = Field(ge=0)
    source_record_count: int = Field(ge=0)
    valid_numeric_count: int = Field(ge=0)
    geometry_status: str = "cumulative_1d_only"
    crs_type: str = "none"
    origin_status: str = "unconfirmed"
    direction_status: str = "unconfirmed"
    geometry_source: str
    source_confidence: str
    notes: str | None = None


class MicroseismicIssue(MicroseismicModel):
    severity: MicroseismicSeverity
    code: str
    message: str
    affected_scope: str
    evidence: str | None = None
    source_a: str | None = None
    source_b: str | None = None
    current_handling: str
    blocks_geometry: bool = False
    blocks_cleaning: bool = False
    blocks_interpolation: bool = False


class MicroseismicCheck(MicroseismicModel):
    name: str
    passed: bool
    severity: MicroseismicSeverity = MicroseismicSeverity.BLOCKER
    evidence: str | None = None


class MicroseismicValidationReport(MicroseismicModel):
    passed: bool
    checks: list[MicroseismicCheck]
    counts: dict[str, Any] = Field(default_factory=dict)
    sha256_protection: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MicroseismicAuditResult(MicroseismicModel):
    output_dir: str
    manifest: list[SourceFileManifestEntry]
    lines: list[SurveyLine]
    points: list[SurveyPoint]
    samples: list[VelocitySample]
    issues: list[MicroseismicIssue]
    validation: MicroseismicValidationReport
    counts: dict[str, Any] = Field(default_factory=dict)
