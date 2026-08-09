"""v0.8.0 第二批：统计与空间分析（profile 领域注册表 + API 响应骨架）。"""

from geomodeling.analysis.profiles import (
    AnalysisDisabledReason,
    AnalysisModuleSpec,
    AnalysisProfile,
    resolve_analysis_profile,
)
from geomodeling.analysis.schemas import (
    AnalysisSummaryResponse,
    HistogramBin,
    NumericSummary,
    ProfileSliceSummary,
    QualitySummary,
    SpatialSummary,
)

__all__ = [
    "AnalysisDisabledReason",
    "AnalysisModuleSpec",
    "AnalysisProfile",
    "AnalysisSummaryResponse",
    "HistogramBin",
    "NumericSummary",
    "ProfileSliceSummary",
    "QualitySummary",
    "SpatialSummary",
    "resolve_analysis_profile",
]
