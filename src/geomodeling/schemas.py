from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DatasetType(str, Enum):
    RAW_OBSERVATION = "raw_observation"
    STANDARDIZED_OBSERVATION = "standardized_observation"
    TRAIN_VALIDATION_SPLIT = "train_validation_split"
    MODEL_RESULT = "model_result"
    VISUAL_DERIVATIVE = "visual_derivative"


class QualityStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


class IssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKER = "blocker"


class ModelMethod(str, Enum):
    IDW = "IDW"
    KRIGING_ORDINARY = "KRIGING_ORDINARY"


class ModelStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INVALIDATED = "invalidated"


class ResultCategory(str, Enum):
    FORMAL = "formal"
    VALIDATION = "validation"
    PREVIEW = "preview"
    FAILED_EMPTY = "failed_empty"


class EvidenceLevel(str, Enum):
    DECLARED = "declared"
    FILE_VERIFIED = "file_verified"
    DATASET_VERIFIED = "dataset_verified"
    MANUAL_EVIDENCE = "manual_evidence"


MODEL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class DatasetRegistration(ContractModel):
    dataset_id: str
    dataset_type: DatasetType
    version: str
    source_path: str
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    row_count: int | None = Field(default=None, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str
    source_reference: str
    quality_status: QualityStatus = QualityStatus.UNREVIEWED
    notes: str | None = None
    statistics: dict[str, Any] = Field(default_factory=dict)


class ValidationIssue(ContractModel):
    severity: IssueSeverity
    code: str
    message: str
    scope: str | None = None
    evidence: str | None = None
    blocking: bool = True
    current_handling: str | None = None


class ValidationReport(ContractModel):
    dataset_id: str
    source_path: str
    dataset_type: DatasetType
    row_count: int = Field(ge=0)
    expected_row_count: int | None = Field(default=None, ge=0)
    quality_status: QualityStatus
    checks: dict[str, Any] = Field(default_factory=dict)
    statistics: dict[str, Any] = Field(default_factory=dict)
    issues: list[ValidationIssue] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ModelMetadata(ContractModel):
    model_id: str = Field(pattern=MODEL_ID_PATTERN)
    property: str = "RHO"
    property_unit: str | None = None
    method: ModelMethod
    input_dataset_id: str
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    crs: dict[str, Any]
    axis: dict[str, Any]
    grid: dict[str, Any]
    parameters: dict[str, Any] = Field(default_factory=dict)
    supermap: dict[str, Any] = Field(default_factory=dict)
    status: ModelStatus = ModelStatus.CREATED
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ModelTask(ContractModel):
    model_id: str = Field(pattern=MODEL_ID_PATTERN)
    display_name: str
    method: ModelMethod
    input_dataset_id: str
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parameters: dict[str, Any] = Field(default_factory=dict)
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    status: ModelStatus = ModelStatus.CREATED
    role: str = "candidate"
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ModelSelection(ContractModel):
    default_model_id: str = Field(pattern=MODEL_ID_PATTERN)
    comparison_model_id: str = Field(pattern=MODEL_ID_PATTERN)
    rationale: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MetricSummary(ContractModel):
    model: str
    n_total: int = Field(ge=0)
    n_valid: int = Field(ge=0)
    n_nodata: int = Field(ge=0)
    coverage_rate: float
    mae: float
    rmse: float
    r2: float
    median_abs_error: float
    mean_abs_relative_error: float
    median_abs_relative_error: float
    log10_rmse: float
    bias: float
    p90_abs_error: float


class SuperMapResultRegistration(ContractModel):
    dataset: str
    model_id: str
    dataset_type: str
    method: ModelMethod
    datasource_alias: str
    udbx_path: str | None = None
    status: ModelStatus
    result_category: ResultCategory
    rows: int | None = Field(default=None, ge=0)
    columns: int | None = Field(default=None, ge=0)
    bands: int | None = Field(default=None, ge=0)
    cell_count: int | None = Field(default=None, ge=0)
    object_count: int | None = Field(default=None, ge=0)
    value_min: float | None = None
    value_max: float | None = None
    openable: bool = False
    parameters: dict[str, Any] = Field(default_factory=dict)
    error_evidence: str | None = None
    evidence_level: EvidenceLevel = EvidenceLevel.DECLARED
    file_verified: bool = False
    dataset_verified: bool = False
    file_size_bytes: int | None = Field(default=None, ge=0)
    file_mtime: datetime | None = None
    file_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    dataset_verification_note: str | None = None
    manual_evidence: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def prevent_false_success(self):
        if self.status == ModelStatus.SUCCEEDED:
            if self.object_count == 0 or not self.openable or self.error_evidence:
                raise ValueError("successful SuperMap result must be openable, non-empty, and free of error evidence")
        if self.result_category == ResultCategory.FAILED_EMPTY and self.status != ModelStatus.FAILED:
            raise ValueError("failed_empty results must use failed status")
        if self.evidence_level == EvidenceLevel.FILE_VERIFIED and not self.file_verified:
            raise ValueError("file_verified evidence requires file_verified=true")
        if self.evidence_level == EvidenceLevel.DATASET_VERIFIED and not self.dataset_verified:
            raise ValueError("dataset_verified evidence requires dataset_verified=true")
        if self.dataset_verified and not self.file_verified:
            raise ValueError("dataset_verified evidence requires file_verified=true")
        if self.file_verified and (not self.udbx_path or self.file_size_bytes is None or self.file_mtime is None):
            raise ValueError("file_verified evidence requires udbx_path, file size, and file mtime")
        return self


class SuperMapVerificationReport(ContractModel):
    udbx_path: str | None
    file_exists: bool
    file_verified: bool
    dataset_api: str
    dataset_verified: bool
    records: list[SuperMapResultRegistration]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SliceConfiguration(ContractModel):
    name: str
    mode: str
    normalized_min: float | None = None
    normalized_max: float | None = None
    actual_min_z_m: float | None = None
    actual_max_z_m: float | None = None
    thickness_m: float | None = None
    verified: bool = False
    evidence: str | None = None

    @field_validator("mode")
    @classmethod
    def check_mode(cls, value: str) -> str:
        if value not in {"normalized_z", "actual_z"}:
            raise ValueError("slice mode must be normalized_z or actual_z")
        return value


class ThresholdConfiguration(ContractModel):
    label: str
    min_rho: float
    max_rho: float | None = None
    demonstration_only: bool = True
    note: str

    @model_validator(mode="after")
    def check_demo_threshold(self):
        if not self.demonstration_only:
            raise ValueError("MVP thresholds must remain demonstration_only unless a validated geological basis is added")
        if "geological hazard" in self.note.lower() and "not" not in self.note.lower():
            raise ValueError("threshold note must not claim an unvalidated geological hazard threshold")
        return self


class ViewConfiguration(ContractModel):
    name: str
    model_id: str
    dataset: str
    evidence_level: EvidenceLevel = EvidenceLevel.DECLARED
    extent: dict[str, Any] = Field(default_factory=dict)
    rows: int | None = Field(default=None, ge=0)
    columns: int | None = Field(default=None, ge=0)
    bands: int | None = Field(default=None, ge=0)
    value_min: float | None = None
    value_max: float | None = None
    horizontal_slices: list[SliceConfiguration] = Field(default_factory=list)
    threshold: ThresholdConfiguration | None = None
    vertical_slice_status: str = "unverified"
    isosurface_status: str = "failed"
    external_open_info: dict[str, Any] = Field(default_factory=dict)

    @field_validator("vertical_slice_status")
    @classmethod
    def check_vertical_status(cls, value: str) -> str:
        if value not in {"unverified", "unsupported", "verified"}:
            raise ValueError("vertical slice status must be unverified, unsupported, or verified")
        return value

    @field_validator("isosurface_status")
    @classmethod
    def check_isosurface_status(cls, value: str) -> str:
        if value not in {"failed", "unverified", "verified"}:
            raise ValueError("isosurface status must be failed, unverified, or verified")
        return value


class ResultInventoryItem(ContractModel):
    name: str
    category: ResultCategory
    status: ModelStatus
    path: str | None = None
    supermap_dataset: str | None = None
    evidence_level: EvidenceLevel = EvidenceLevel.DECLARED
    trace: dict[str, Any] = Field(default_factory=dict)
