"""Shared v0.4 domain contracts: enums, requests, and response records.

API routes, the local worker, and the repositories all import these
models; field meanings are defined exactly once here instead of being
duplicated as ad-hoc dictionaries. All models forbid unknown keys.

记录模型可能携带服务端内部路径字段（``source_path``、
``standardized_path``、``grid_path``）。公共 API 出口必须经白名单 DTO
或脱敏序列化，不得把记录模型原样回传浏览器（责任落点为 API 层）。
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from geomodeling.platform.tables import RunStatus

__all__ = [
    "Algorithm",
    "AnalysisJobRecord",
    "AnomalyExtractionRecord",
    "CaseCreateRequest",
    "CaseRecord",
    "CandidateResultRecord",
    "ContractModel",
    "DatasetStatus",
    "DatasetVersionRecord",
    "Dimension",
    "ExperimentCreateRequest",
    "ExperimentRecord",
    "FORMAT_VERSION",
    "FieldMapping",
    "FormalSelectionRecord",
    "FormalSelectionRequest",
    "GridSpec",
    "ProfessionalConfirmationRecord",
    "ProfessionalConfirmationRequest",
    "ProfessionalDiagnosisRequest",
    "ProfessionalDiagnosticRecord",
    "ProfessionalResultArtifactsRecord",
    "RENDERER",
    "RENDER_ASSET_STATUSES",
    "RenderAssetError",
    "RenderAssetRecord",
    "RunRecord",
    "RunStatus",
    "STATUS_CREATING",
    "STATUS_FAILED",
    "STATUS_INTERRUPTED",
    "STATUS_READY",
    "SpatialValidationSpec",
    "render_asset_id",
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
    """实验创建请求（v0.4）；v0.6 扩展三个可选专业输入。

    ``professional_confirmation_id`` 引用一条不可变确认快照（仅普通
    Kriging；给出即为 Kriging 专业模式）。``neighborhood`` 与
    ``empirical_uncertainty`` 分别是
    ``geomodeling.modeling.professional_contracts.NeighborhoodSpec`` 与
    ``EmpiricalUncertaintySpec`` 的原始载荷：本层只做 ``extra="forbid"``
    浅校验，严格校验由服务层用上述契约执行——分层方式与
    ``parameters``、``ProfessionalDiagnosisRequest.variogram`` 一致（契约
    模块反向依赖本模块，字段类型无法在此直接引用）。三字段全缺时行为与
    v0.5 逐位不变。
    """

    case_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    algorithm: Algorithm
    dataset_version_id: str = Field(min_length=1, max_length=128)
    search_mode: Literal["manual", "grid"] = "manual"
    parameters: dict[str, Any] | list[dict[str, Any]] = Field(default_factory=dict)
    validation: SpatialValidationSpec = Field(default_factory=SpatialValidationSpec)
    grid: GridSpec | None = None
    professional_confirmation_id: str | None = Field(default=None, min_length=1, max_length=128)
    neighborhood: dict[str, Any] | None = None
    empirical_uncertainty: dict[str, Any] | None = None


class FormalSelectionRequest(ContractModel):
    """正式模型选择；按设计要求必须填写选择理由。"""

    candidate_result_id: str = Field(min_length=1, max_length=128)
    note: str = Field(min_length=1, max_length=2000)
    selected_by: str | None = Field(default=None, max_length=128)


class FormalSelectionBody(ContractModel):
    """select-formal 端点请求体；成果身份取自 URL 路径，不允许体内伪造。"""

    note: str = Field(min_length=1, max_length=2000)
    selected_by: str | None = Field(default=None, max_length=128)


class ProfessionalDiagnosisRequest(ContractModel):
    """数据集级专业诊断请求体（v0.6，POST …/professional-diagnostics）。

    ``variogram`` 是
    ``geomodeling.modeling.professional_contracts.VariogramDiagnosticSpec``
    的原始载荷：本层只做 ``extra="forbid"`` 浅校验，严格校验由服务层
    用上述契约执行——分层方式与 ``ExperimentCreateRequest.parameters``
    一致，字段定义不在此处重复。数据集身份取自 URL 路径。
    """

    variogram: dict[str, Any] = Field(default_factory=dict)


class ProfessionalConfirmationRequest(ContractModel):
    """各向异性人工确认请求体（v0.6，POST …/confirm）。

    用户确认一组各向异性参数，或显式选择「保持各向同性」，二者必须
    恰好其一。``anisotropy`` 为建模层各向异性契约的原始载荷（方位角、
    3D 倾角、滚转角、主/次/垂向尺度比与证据引用），严格校验在服务层
    执行；``note`` 为确认说明，按设计要求必填。
    """

    keep_isotropic: bool = False
    anisotropy: dict[str, Any] = Field(default_factory=dict)
    note: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def _check_exactly_one_choice(self) -> "ProfessionalConfirmationRequest":
        has_anisotropy = bool(self.anisotropy)
        if self.keep_isotropic == has_anisotropy:
            raise ValueError("必须恰好选择「保持各向同性」或提供一组各向异性参数")
        return self


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
    """候选结果记录。``grid_path`` 为服务端内部路径，公共 API 序列化时

    必须脱敏，不得原样回传浏览器。"""

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


# ---------------------------------------------------------------------------
# v0.6 professional modeling records (SQLite v5)
# ---------------------------------------------------------------------------


class ProfessionalDiagnosticRecord(ContractModel):
    """数据集级专业诊断记录；状态由持久化分析任务驱动。"""

    id: str
    dataset_version_id: str
    status: RunStatus
    config: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str = ""
    manifest: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    created_at: str
    updated_at: str
    finished_at: str | None = None


class ProfessionalConfirmationRecord(ContractModel):
    """一次性不可变确认快照；创建后没有更新路径。"""

    id: str
    diagnostic_id: str
    config: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str = ""
    note: str = ""
    created_at: str


class ProfessionalResultArtifactsRecord(ContractModel):
    """一个候选唯一的一套专业工件（candidate_result_id 唯一约束）。"""

    id: str
    candidate_result_id: str
    confirmation_id: str | None = None
    status: Literal["pending", "succeeded", "failed"] = "pending"
    capabilities: dict[str, Any] = Field(default_factory=dict)
    manifest: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class AnomalyExtractionRecord(ContractModel):
    """异常提取记录；同成果同配置指纹幂等返回同一成功提取。"""

    id: str
    candidate_result_id: str
    status: Literal["pending", "succeeded", "failed"] = "pending"
    config: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str = ""
    manifest: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    created_at: str


class AnalysisJobRecord(ContractModel):
    """持久化专业分析任务记录（诊断/异常提取）。"""

    id: str
    job_kind: Literal["professional_diagnosis", "anomaly_extraction"]
    subject_type: str
    subject_id: str
    request_fingerprint: str
    status: RunStatus
    retry_of_job_id: str | None = None
    progress: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None


# ---------------------------------------------------------------------------
# v0.6.1 native volume rendering records (SQLite v6)
# ---------------------------------------------------------------------------

RENDERER = "supermap_voxelgrid_netcdf"
FORMAT_VERSION = 2
STATUS_CREATING = "creating"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUS_INTERRUPTED = "interrupted"
RENDER_ASSET_STATUSES = frozenset(
    {STATUS_CREATING, STATUS_READY, STATUS_FAILED, STATUS_INTERRUPTED}
)


def render_asset_id(*, source_kind: str, source_id: str, grid_sha256: str) -> str:
    """渲染资产内容寻址 ID：五元身份（源 + 网格哈希 + 渲染器 + 格式版本）的

    SHA-256 截断（设计 §2.2）。同一身份永远得到同一 ID，是幂等复用与
    唯一约束竞态收敛的基础。
    """

    payload = f"{source_kind}\0{source_id}\0{grid_sha256}\0{RENDERER}\0{FORMAT_VERSION}"
    return f"nc-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]}"


class RenderAssetError(ContractModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class RenderAssetRecord(ContractModel):
    """NetCDF 渲染资产公共记录（设计 §2.4）。

    服务端内部列 ``asset_dir`` 永不进入本 DTO：公共序列化只暴露按
    ``id`` 派生的相对 URL（仅 ready 状态非空），文件位置由服务端按
    设置目录解析。
    """

    id: str
    source_kind: Literal["candidate_result", "builtin_legacy"]
    source_id: str
    renderer: Literal["supermap_voxelgrid_netcdf"]
    status: Literal["creating", "ready", "failed", "interrupted"]
    grid_sha256: str
    netcdf_sha256: str | None = None
    manifest_url: str | None = None
    netcdf_url: str | None = None
    error: RenderAssetError | None = None
