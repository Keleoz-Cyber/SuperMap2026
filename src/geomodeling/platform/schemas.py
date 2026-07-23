"""Shared v0.4 domain contracts: enums, requests, and response records.

API routes, the local worker, and the repositories all import these
models; field meanings are defined exactly once here instead of being
duplicated as ad-hoc dictionaries. All models forbid unknown keys.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from geomodeling.platform.tables import RunStatus

__all__ = [
    "Algorithm",
    "CaseCreateRequest",
    "CaseRecord",
    "CandidateResultRecord",
    "ContractModel",
    "DatasetStatus",
    "DatasetVersionRecord",
    "Dimension",
    "ExperimentCreateRequest",
    "ExperimentRecord",
    "FieldMapping",
    "FormalSelectionRecord",
    "FormalSelectionRequest",
    "GridSpec",
    "RunRecord",
    "RunStatus",
    "SpatialValidationSpec",
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class Dimension(str, Enum):
    TWO_D = "2d"
    THREE_D = "3d"


class DatasetStatus(str, Enum):
    UPLOADED = "uploaded"
    MAPPED = "mapped"
    VALIDATED = "validated"
    BLOCKED = "blocked"


class Algorithm(str, Enum):
    IDW = "idw"
    ORDINARY_KRIGING = "ordinary_kriging"


# ---------------------------------------------------------------------------
# Request contracts
# ---------------------------------------------------------------------------


class FieldMapping(ContractModel):
    """字段映射：把上传列绑定到 x/y/z/value 角色。

    2D 映射要求 ``x``/``y``/``value`` 且必须不选 ``z``；3D 映射额外要求
    ``z``。四个角色不得重复选择同一源列。
    """

    dimension: Dimension
    x: str = Field(min_length=1, max_length=128)
    y: str = Field(min_length=1, max_length=128)
    z: str | None = Field(default=None, min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=128)
    value_name: str = Field(min_length=1, max_length=64)
    value_unit: str | None = Field(default=None, max_length=32)
    coordinate_kind: Literal["local_linear", "projected", "geographic"]
    crs_text: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def _check_dimension_and_distinct_fields(self) -> "FieldMapping":
        if self.dimension == Dimension.TWO_D and self.z is not None:
            raise ValueError("2D 映射不允许选择 z 字段")
        if self.dimension == Dimension.THREE_D and self.z is None:
            raise ValueError("3D 映射必须选择 z 字段")
        selected = [self.x, self.y, self.value]
        if self.z is not None:
            selected.append(self.z)
        if len(set(selected)) != len(selected):
            raise ValueError("x/y/z/value 不得重复选择同一列")
        return self


class SpatialValidationSpec(ContractModel):
    method: Literal["spatial_kfold", "spatial_holdout"] = "spatial_kfold"
    folds: int = Field(default=5, ge=3, le=10)
    seed: int = 20260723
    holdout_fraction: float = Field(default=0.2, ge=0.1, le=0.4)


class GridSpec(ContractModel):
    """规则网格声明；估算节点数不得超过 ``max_cells`` 硬上限。"""

    bounds: list[tuple[float, float]] = Field(min_length=2, max_length=3)
    resolution: list[float] = Field(min_length=2, max_length=3)
    max_cells: int = Field(default=1_000_000, ge=1, le=1_000_000)

    @model_validator(mode="after")
    def _check_grid(self) -> "GridSpec":
        if len(self.bounds) != len(self.resolution):
            raise ValueError("bounds 与 resolution 维度数必须一致")
        cells = 1
        for (lower, upper), step in zip(self.bounds, self.resolution, strict=True):
            if not upper > lower:
                raise ValueError("bounds 下界必须小于上界")
            if step <= 0:
                raise ValueError("resolution 必须为正数")
            cells *= int((upper - lower) / step) + 1
        if cells > self.max_cells:
            raise ValueError(f"估算网格单元数 {cells} 超过上限 {self.max_cells}")
        return self


class CaseCreateRequest(ContractModel):
    """``name`` 仅为展示元数据，永不作为文件系统路径。"""

    name: str = Field(min_length=1, max_length=256)
    case_type: str = Field(default="generic", min_length=1, max_length=64)
    config: dict[str, Any] = Field(default_factory=dict)


class ExperimentCreateRequest(ContractModel):
    name: str = Field(min_length=1, max_length=256)
    algorithm: Algorithm
    dataset_version_id: str = Field(min_length=1, max_length=128)
    validation: SpatialValidationSpec = Field(default_factory=SpatialValidationSpec)
    grid: GridSpec | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class FormalSelectionRequest(ContractModel):
    """正式模型选择；按设计要求必须填写选择理由。"""

    candidate_result_id: str = Field(min_length=1, max_length=128)
    note: str = Field(min_length=1, max_length=2000)
    selected_by: str | None = Field(default=None, max_length=128)


# ---------------------------------------------------------------------------
# Response records (repositories return these, never ORM rows)
# ---------------------------------------------------------------------------


class CaseRecord(ContractModel):
    id: str
    name: str
    case_type: str
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class DatasetVersionRecord(ContractModel):
    """数据版本记录。``source_path``/``standardized_path`` 为服务端内部路径，

    公共 API 序列化时必须脱敏，不得原样回传浏览器。"""

    id: str
    case_id: str
    version: int
    status: DatasetStatus
    source_path: str
    standardized_path: str | None = None
    profile: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class ExperimentRecord(ContractModel):
    id: str
    case_id: str
    name: str
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class RunRecord(ContractModel):
    id: str
    experiment_id: str
    status: RunStatus
    error_code: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    retry_of_run_id: str | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None


class CandidateResultRecord(ContractModel):
    id: str
    run_id: str
    category: str
    grid_path: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class FormalSelectionRecord(ContractModel):
    id: str
    case_id: str
    candidate_result_id: str
    selected_by: str | None = None
    note: str
    created_at: str
