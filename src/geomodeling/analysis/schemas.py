"""v0.8.0 第二批：统计与空间分析中心 API 响应模型骨架（设计 §6）。

ContractModel 风格（``extra="forbid"``）；统计值字段 Optional 表示
「未计算/不可用」。所有模型在验证层递归拒绝 NaN/Inf——序列化结果绝不
包含非有限值，作为 truth/prediction 双有限规则的模型层兜底。领域
profile 注册表在 ``profiles.py``，本模块不反向依赖之外的层。
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import Field, model_validator

from geomodeling.platform.schemas import ContractModel

__all__ = [
    "AnalysisContractModel",
    "AnalysisModuleResult",
    "AnalysisProvenance",
    "AnalysisSummaryResponse",
    "AnalysisVariable",
    "AnomalyThresholds",
    "AxisTrendSummary",
    "CALCULATION_VERSION",
    "DepthSliceBin",
    "DepthSliceSummary",
    "GradientSummary",
    "HistogramBin",
    "NumericSummary",
    "ProfileSliceBin",
    "ProfileSliceSummary",
    "QualitySummary",
    "QuantileSummary",
    "SpatialAnomalyBin",
    "SpatialAnomalySummary",
    "SpatialBin",
    "SpatialSummary",
]

# 分析计算管线版本：任何统计口径变更必须递增，随 provenance 出站
CALCULATION_VERSION = "analysis.v1"


def _check_finite(payload: Any, path: str) -> None:
    """递归拒绝 NaN/Inf；``bool``/``int`` 不受影响（NaN 只可能是 float）。"""

    if isinstance(payload, float):
        if not math.isfinite(payload):
            raise ValueError(
                f"{path} 含非有限值（NaN/Inf），分析响应禁止序列化非有限统计值"
            )
        return
    if isinstance(payload, dict):
        for key, item in payload.items():
            _check_finite(item, f"{path}.{key}")
    elif isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            _check_finite(item, f"{path}[{index}]")


class AnalysisContractModel(ContractModel):
    """分析响应基类：构造时递归拒绝 NaN/Inf，保证序列化只含有限值。"""

    @model_validator(mode="after")
    def _reject_non_finite(self) -> "AnalysisContractModel":
        _check_finite(self.model_dump(), type(self).__name__)
        return self


class AnalysisVariable(AnalysisContractModel):
    """被分析变量身份；``unit`` 未确认时为 None，禁止伪造语义结论。"""

    name: str
    unit: str | None = None


class QuantileSummary(AnalysisContractModel):
    p05: float | None = None
    p25: float | None = None
    p50: float | None = None
    p75: float | None = None
    p95: float | None = None


class NumericSummary(AnalysisContractModel):
    """基础统计；字段为 None 表示未计算/不可用，绝不以 NaN 占位。"""

    count: int | None = None
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    quantiles: QuantileSummary | None = None


class HistogramBin(AnalysisContractModel):
    lower: float
    upper: float
    count: int


class QualitySummary(AnalysisContractModel):
    """数据质量摘要；``bounds`` 键为坐标轴名（x/y/z），值为 (min, max)。"""

    row_count: int | None = None
    valid_count: int | None = None
    invalid_count: int | None = None
    duplicate_coordinate_count: int | None = None
    bounds: dict[str, tuple[float, float]] | None = None


class SpatialBin(AnalysisContractModel):
    """空间聚合单元（XY 平面规则格网）。"""

    x_lower: float
    x_upper: float
    y_lower: float
    y_upper: float
    count: int = 0
    mean: float | None = None


class SpatialSummary(AnalysisContractModel):
    grid_size: int = 32
    cell_count: int | None = None
    bounds: dict[str, tuple[float, float]] | None = None
    bins: list[SpatialBin] = Field(default_factory=list)


class ProfileSliceBin(AnalysisContractModel):
    lower: float
    upper: float
    count: int = 0
    mean: float | None = None
    median: float | None = None


class ProfileSliceSummary(AnalysisContractModel):
    axis: Literal["x", "y", "z"]
    bins: list[ProfileSliceBin] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Task 6：专属模块载荷模型（微震趋势/梯度、分位阈值、深度层占比、空间异常）
# ---------------------------------------------------------------------------


class AxisTrendSummary(AnalysisContractModel):
    """单轴分箱趋势（``profile_axis`` 口径），附轴身份与样本数。"""

    axis: Literal["x", "y", "z"]
    sample_count: int = 0
    bins: list[ProfileSliceBin] = Field(default_factory=list)


class GradientSummary(AnalysisContractModel):
    """相邻 XY 网格单元均值差分幅值的有限统计（局部变化强度）。

    ``count`` 为参与统计的有限差分幅值数；``count=0`` 时统计字段为
    None（绝不以 NaN 占位）；任一侧为空格的相邻对排除且计数保留在
    ``excluded_pair_count``。
    """

    grid_size: int
    pair_count: int = 0
    excluded_pair_count: int = 0
    count: int = 0
    mean: float | None = None
    p95: float | None = None
    max: float | None = None


class AnomalyThresholds(AnalysisContractModel):
    """高/低值阈值（有效值分位数口径）；``source``/``method`` 明示阈值来源。"""

    high: float
    low: float
    source: str
    method: str


class DepthSliceBin(AnalysisContractModel):
    """单个 Z 层超阈占比；``count=0`` 时占比为 None（绝不以 NaN 占位）。"""

    z_lower: float
    z_upper: float
    count: int = 0
    high_count: int = 0
    low_count: int = 0
    high_ratio: float | None = None
    low_ratio: float | None = None


class DepthSliceSummary(AnalysisContractModel):
    """逐 Z 层异常占比：分位阈值 + 层分箱（占比以层内样本计数为口径）。"""

    thresholds: AnomalyThresholds
    slice_count: int
    slices: list[DepthSliceBin] = Field(default_factory=list)


class SpatialAnomalyBin(SpatialBin):
    """空间异常单元：在 ``SpatialBin``（XY 格网 count/mean）上加区域分类。"""

    region: Literal["high", "low", "normal", "empty"] = "empty"


class SpatialAnomalySummary(AnalysisContractModel):
    """XY 网格高/低值区域聚合：分位阈值 + 逐格区域 + 体积占比（样本计数口径）。"""

    grid_size: int
    cell_count: int | None = None
    bounds: dict[str, tuple[float, float]] | None = None
    thresholds: AnomalyThresholds
    non_empty_cell_count: int = 0
    high_cell_count: int = 0
    low_cell_count: int = 0
    high_point_count: int = 0
    low_point_count: int = 0
    high_volume_ratio: float | None = None
    low_volume_ratio: float | None = None
    bins: list[SpatialAnomalyBin] = Field(default_factory=list)


class AnalysisModuleResult(AnalysisContractModel):
    """单个分析模块的计算状态与载荷骨架；``disabled``/``error`` 必须带
    ``message`` 说明，不得返回空图表伪成功（设计 §8）。"""

    module_id: str
    status: Literal["ok", "disabled", "error"] = "ok"
    payload: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None


class AnalysisProvenance(AnalysisContractModel):
    """结果溯源：源哈希、数据版本、生成时间与计算管线版本。"""

    source_sha256: str
    dataset_version: int
    generated_at: str
    calculation_version: str = CALCULATION_VERSION


class AnalysisSummaryResponse(AnalysisContractModel):
    """``GET /api/datasets/{dataset_id}/analysis-summary`` 响应骨架（设计 §6）。"""

    dataset_id: str
    case_id: str
    analysis_profile: str
    profile_version: int
    variable: AnalysisVariable
    quality: QualitySummary
    statistics: NumericSummary | None = None
    modules: list[AnalysisModuleResult] = Field(default_factory=list)
    provenance: AnalysisProvenance
