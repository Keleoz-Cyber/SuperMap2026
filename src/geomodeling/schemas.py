from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    model_id: str
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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def prevent_false_success(self):
        if self.status == ModelStatus.SUCCEEDED:
            if self.object_count == 0 or not self.openable or self.error_evidence:
                raise ValueError("successful SuperMap result must be openable, non-empty, and free of error evidence")
        if self.result_category == ResultCategory.FAILED_EMPTY and self.status != ModelStatus.FAILED:
            raise ValueError("failed_empty results must use failed status")
        return self


class ResultInventoryItem(ContractModel):
    name: str
    category: ResultCategory
    status: ModelStatus
    path: str | None = None
    supermap_dataset: str | None = None
    trace: dict[str, Any] = Field(default_factory=dict)
