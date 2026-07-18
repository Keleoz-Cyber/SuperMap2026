from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

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


class SurveyPoint(MicroseismicModel):
    point_id: str
    original_point_label: str
    source_file_id: str
    line_id: str
    sequence_on_line: int = Field(ge=0)
    previous_point_id: str | None = None
    interval_from_previous_m: float | None = None
    cumulative_s_m: float = Field(ge=0)
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
