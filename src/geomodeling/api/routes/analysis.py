"""v0.8.0 第二批 Task 3：只读分析摘要与导出路由（设计 §6/§8）。

- ``GET /api/datasets/{dataset_id}/analysis-summary``：按不可变数据版本
  组装 ``AnalysisSummaryResponse``——质量/统计/分布直方图/空间聚合/三轴
  剖面/模型对比 + provenance（source_sha256/dataset_version/generated_at/
  calculation_version）。通用模块（quality/statistics/distribution/
  spatial_extent/profile_slices/model_comparison）与 Task 6 专属模块
  （微震 axis_trends/gradient/spatial_anomaly，电阻率 log 分布/depth_slices/
  spatial_anomaly）全部为真实有限计算，载荷带计算方法/来源字段/阈值来源；
  瓦斯等未实现专属模块仍为 ``disabled`` 骨架。
- ``GET /api/datasets/{dataset_id}/analysis-export?format=json|csv``：
  同一响应组装后导出。json → application/json；csv → text/csv，头部
  provenance 注释行 + 稳定表头 + 轴身份列的明确行模式。两个导出都用
  Content-Disposition 安全文件名（仅含 dataset/profile 逻辑标识）。

只读语义：绝不改行、绝不物化、绝不重算模型指标——model_comparison 仅
读取该数据版本下已有 succeeded 候选记录（算法/参数摘要/公共指标/
result_id/物化状态/是否正式选择）。空公共有效集 fail-closed 抛
``ANALYSIS_EMPTY_COMMON_VALID``（409），绝不返回 null 堆叠面板。
``standardized_path`` 等本机路径绝不写入响应或错误 details。
"""

from __future__ import annotations

import csv
import io
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse

from geomodeling.analysis.profiles import (
    PROFILE_MICROSEISMIC_VELOCITY,
    PROFILE_RESISTIVITY,
    AnalysisProfile,
    resolve_analysis_profile,
)
from geomodeling.analysis.schemas import (
    AnalysisModuleResult,
    AnalysisProvenance,
    AnalysisSummaryResponse,
    AnalysisVariable,
    NumericSummary,
    QualitySummary,
)
from geomodeling.analysis.statistics import (
    aggregate_spatial,
    axis_trends,
    depth_slice_ratios,
    gradient_summary,
    histogram,
    log10_histogram,
    profile_axis,
    spatial_anomaly_summary,
    summarize_numeric,
    summarize_quality,
)
from geomodeling.api.deps import get_platform_runtime
from geomodeling.platform import PlatformRuntime
from geomodeling.platform.errors import (
    DATASET_NOT_FOUND,
    DATASET_NOT_VALIDATED,
    PlatformError,
)
from geomodeling.platform.repositories import DatasetRepository, require_active_dataset
from geomodeling.platform.schemas import DatasetStatus, DatasetVersionRecord
from geomodeling.platform.tables import (
    CandidateResult,
    Experiment,
    FormalSelection,
    Run,
    RunStatus,
    loads_canonical,
)

router = APIRouter(prefix="/api/datasets", tags=["v0.8-analysis"])

#: 导出 format 非法：类型化 422（与 COMPARISON_SELECTION_INVALID 等 422 语义一致）
ANALYSIS_EXPORT_FORMAT_INVALID = "ANALYSIS_EXPORT_FORMAT_INVALID"

_EXPORT_FORMATS = ("json", "csv")
#: 模型对比随记录出站的公共指标白名单（不重算；非有限值一律剔除）
_PUBLIC_METRIC_KEYS = ("rmse", "mae", "r2", "bias")
#: 本批就位的通用模块；Task 6 专属模块由 ``_specialized_payload`` 计算，
#: 未实现的（profile, module）组合（如瓦斯）输出 disabled 骨架
_GENERIC_MODULES = frozenset(
    {
        "quality",
        "statistics",
        "distribution",
        "spatial_extent",
        "profile_slices",
        "model_comparison",
    }
)
_SPECIALIZED_SKELETON_MESSAGE = "专属模块计算将在后续批次就位，本批仅提供能力声明"

#: Task 6 专属模块计算方法文案（随 payload 出站；电阻率单位未确认，
#: 文案只描述数值口径，绝不含水、矿、瓦斯通道等地质语义结论）
_METHOD_DISTRIBUTION = "原始值等宽分箱（数据范围+固定 32 格），计数守恒"
_METHOD_LOG10_DISTRIBUTION = (
    "对数尺度分箱仅使用严格正值有限值（log10 变换后等宽 32 格）；"
    "非正值排除且计数保留，原始值分箱与统计不受影响"
)
_METHOD_AXIS_TRENDS = (
    "X/Y/Z 逐轴等宽分箱（数据范围+固定 32 格），逐格 count/mean/median，"
    "空格为 null；与剖面统计同一确定性口径"
)
_METHOD_GRADIENT = (
    "XY 平面 16×16 网格单元均值 → 相邻（X/Y 向）非空单元差分幅值 |Δmean| "
    "的有限统计（count/mean/p95/max）；任一侧为空格的相邻对排除且计数保留；"
    "仅用有限值"
)
_METHOD_DEPTH_SLICES = (
    "Z 轴等宽 16 层（数据范围+固定层数）；层高值占比=层内 value≥p75 样本数/"
    "层样本数，低值占比=层内 value≤p25 样本数/层样本数（体积占比以样本计数"
    "为口径）；空层为 null；阈值来源见 thresholds"
)
_METHOD_SPATIAL_ANOMALY = (
    "XY 平面 32×32 网格单元均值与有效值 p75/p25 分位阈值比较划分高/低值区域；"
    "体积占比=区域样本计数/有效样本总数（样本计数口径）；阈值来源见 thresholds"
)


# ---------------------------------------------------------------------------
# 数据版本加载与门禁（404/410 先于 409）
# ---------------------------------------------------------------------------


def _load_validated_dataset(
    runtime: PlatformRuntime, dataset_id: str
) -> DatasetVersionRecord:
    """加载数据版本：未知 404 / 案例回收 410 / 未验证 409。"""

    require_active_dataset(runtime, dataset_id)
    with runtime.session() as session:
        record = DatasetRepository(session).get(dataset_id)
    if record.status != DatasetStatus.VALIDATED.value:
        raise PlatformError(
            DATASET_NOT_VALIDATED,
            "数据版本尚未通过验证，分析摘要不可用",
            {"dataset_id": dataset_id, "status": record.status},
            http_status=409,
        )
    return record


def _load_standardized_frame(record: DatasetVersionRecord) -> pd.DataFrame:
    """读取标准化 parquet；路径绝不写入响应或错误 details。"""

    standardized = record.standardized_path or record.profile.get("standardized_path")
    if not standardized or not Path(str(standardized)).is_file():
        raise PlatformError(
            DATASET_NOT_FOUND,
            "标准化数据不存在",
            {"dataset_id": record.id},
            http_status=404,
        )
    return pd.read_parquet(Path(str(standardized)))


def _valid_values(frame: pd.DataFrame) -> np.ndarray:
    """公共有效集属性值（声明有效且有限；与 statistics 有效行口径一致）。"""

    declared = frame["is_numeric_valid"].to_numpy(dtype=bool)
    values = frame["value"].to_numpy(dtype="float64")
    return values[declared & np.isfinite(values)]


# ---------------------------------------------------------------------------
# model_comparison：只读既有 succeeded 候选（绝不重算指标）
# ---------------------------------------------------------------------------


def _succeeded_candidates(
    runtime: PlatformRuntime, record: DatasetVersionRecord
) -> list[dict[str, Any]]:
    """该数据版本下已有 succeeded 候选的只读摘要，确定性排序。"""

    candidates: list[dict[str, Any]] = []
    with runtime.session() as session:
        selected_ids = {
            row.candidate_result_id
            for row in session.query(FormalSelection)
            .filter(FormalSelection.case_id == record.case_id)
            .all()
        }
        experiments = (
            session.query(Experiment)
            .filter(Experiment.case_id == record.case_id)
            .order_by(Experiment.created_at.asc(), Experiment.id.asc())
            .all()
        )
        for experiment in experiments:
            params = loads_canonical(experiment.params_json)
            if params.get("dataset_version_id") != record.id:
                continue
            algorithm = str(params.get("algorithm") or "unknown")
            runs = (
                session.query(Run)
                .filter(
                    Run.experiment_id == experiment.id,
                    Run.status == RunStatus.SUCCEEDED.value,
                )
                .order_by(Run.created_at.asc(), Run.id.asc())
                .all()
            )
            for run in runs:
                rows = (
                    session.query(CandidateResult)
                    .filter(
                        CandidateResult.run_id == run.id,
                        CandidateResult.status == RunStatus.SUCCEEDED.value,
                    )
                    .order_by(CandidateResult.created_at.asc(), CandidateResult.id.asc())
                    .all()
                )
                for candidate in rows:
                    metrics = loads_canonical(candidate.metrics_json)
                    public_metrics = {
                        key: float(metrics[key])
                        for key in _PUBLIC_METRIC_KEYS
                        if isinstance(metrics.get(key), (int, float))
                        and not isinstance(metrics.get(key), bool)
                        and math.isfinite(float(metrics[key]))
                    }
                    candidates.append(
                        {
                            "result_id": candidate.id,
                            "algorithm": algorithm,
                            "parameters": loads_canonical(candidate.params_json),
                            "metrics": public_metrics,
                            "materialized": candidate.grid_path is not None,
                            "formal_selection": candidate.id in selected_ids,
                            "result_url": f"/results/{candidate.id}",
                        }
                    )
    return candidates


# ---------------------------------------------------------------------------
# 摘要组装
# ---------------------------------------------------------------------------


def _source_fields(mapping: dict[str, Any], *roles: str) -> dict[str, str]:
    """模块来源字段：mapping 角色 → 源列名（只含映射中存在的角色）。"""

    fields: dict[str, str] = {}
    for role in roles:
        raw = mapping.get(role)
        if raw:
            fields[role] = str(raw)
    return fields


def _specialized_payload(
    profile_id: str,
    module_id: str,
    frame: pd.DataFrame,
    mapping: dict[str, Any],
) -> dict[str, Any] | None:
    """Task 6 专属模块真实有限计算（载荷带计算方法与来源字段）。

    按 ``(profile_id, module_id)`` 派发；未实现的组合（瓦斯 profile 及
    其他未接线模块）返回 None → 调用方输出 disabled 骨架，绝不伪造成功。
    微震与电阻率的 ``spatial_anomaly`` 共用同一分位阈值机制，语义文案
    由前端按 profile 渲染，载荷保持数值口径中性。
    """

    if profile_id == PROFILE_MICROSEISMIC_VELOCITY:
        if module_id == "axis_trends":
            return {
                "method": _METHOD_AXIS_TRENDS,
                "source_fields": _source_fields(mapping, "x", "y", "z", "value"),
                "axes": [
                    trend.model_dump(mode="json")
                    for trend in axis_trends(frame, mapping)
                ],
            }
        if module_id == "gradient":
            payload = gradient_summary(frame, mapping).model_dump(mode="json")
            payload["method"] = _METHOD_GRADIENT
            payload["source_fields"] = _source_fields(mapping, "x", "y", "value")
            return payload
        if module_id == "spatial_anomaly":
            payload = spatial_anomaly_summary(frame, mapping).model_dump(mode="json")
            payload["method"] = _METHOD_SPATIAL_ANOMALY
            payload["source_fields"] = _source_fields(mapping, "x", "y", "value")
            return payload
    elif profile_id == PROFILE_RESISTIVITY:
        if module_id == "depth_slices":
            payload = depth_slice_ratios(frame, mapping).model_dump(mode="json")
            payload["method"] = _METHOD_DEPTH_SLICES
            payload["source_fields"] = _source_fields(mapping, "z", "value")
            return payload
        if module_id == "spatial_anomaly":
            payload = spatial_anomaly_summary(frame, mapping).model_dump(mode="json")
            payload["method"] = _METHOD_SPATIAL_ANOMALY
            payload["source_fields"] = _source_fields(mapping, "x", "y", "value")
            return payload
    return None


def _build_modules(
    analysis_profile: AnalysisProfile,
    frame: pd.DataFrame,
    mapping: dict[str, Any],
    valid_values: np.ndarray,
    runtime: PlatformRuntime,
    record: DatasetVersionRecord,
) -> tuple[list[AnalysisModuleResult], QualitySummary, NumericSummary]:
    """按 profile.module_specs 生成模块结果：通用模块 + Task 6 专属模块计算。"""

    axes = ["x", "y"] + (["z"] if mapping.get("z") else [])
    quality = summarize_quality(frame, mapping)
    numeric = summarize_numeric(valid_values)  # 空公共有效集在此 fail-closed
    modules: list[AnalysisModuleResult] = []
    for spec in analysis_profile.module_specs:
        module_id = spec.module_id
        if module_id not in _GENERIC_MODULES:
            payload = _specialized_payload(
                analysis_profile.profile_id, module_id, frame, mapping
            )
            if payload is None:
                modules.append(
                    AnalysisModuleResult(
                        module_id=module_id,
                        status="disabled",
                        message=_SPECIALIZED_SKELETON_MESSAGE,
                    )
                )
                continue
            modules.append(AnalysisModuleResult(module_id=module_id, payload=payload))
            continue
        if module_id == "quality":
            payload = quality.model_dump(mode="json")
        elif module_id == "statistics":
            payload = numeric.model_dump(mode="json")
        elif module_id == "distribution":
            bins = histogram(valid_values)
            payload = {
                "bin_count": len(bins),
                "bins": [b.model_dump(mode="json") for b in bins],
                "method": _METHOD_DISTRIBUTION,
                "source_fields": _source_fields(mapping, "value"),
            }
            if analysis_profile.profile_id == PROFILE_RESISTIVITY:
                # Task 6：log10 分箱（仅严格正值）与原始值分箱并存，排除计数保留
                log_bins, log_excluded = log10_histogram(valid_values)
                payload["log10"] = {
                    "bin_count": len(log_bins) if log_bins is not None else 0,
                    "bins": (
                        [b.model_dump(mode="json") for b in log_bins]
                        if log_bins is not None
                        else None
                    ),
                    "excluded_non_positive_count": log_excluded,
                    "method": _METHOD_LOG10_DISTRIBUTION,
                }
        elif module_id == "spatial_extent":
            payload = aggregate_spatial(frame, mapping).model_dump(mode="json")
        elif module_id == "profile_slices":
            payload = {
                "axes": [
                    profile_axis(frame, mapping, axis).model_dump(mode="json")
                    for axis in axes
                ]
            }
        else:  # model_comparison
            payload = {"candidates": _succeeded_candidates(runtime, record)}
        modules.append(AnalysisModuleResult(module_id=module_id, payload=payload))
    return modules, quality, numeric


def build_analysis_summary(
    runtime: PlatformRuntime, dataset_id: str
) -> AnalysisSummaryResponse:
    """组装只读分析摘要（summary 与 export 共用同一组装，口径一致）。"""

    record = _load_validated_dataset(runtime, dataset_id)
    profile_json = dict(record.profile)
    mapping = profile_json.get("mapping") or {}
    frame = _load_standardized_frame(record)
    analysis_profile = resolve_analysis_profile(profile_json)
    valid_values = _valid_values(frame)
    modules, quality, numeric = _build_modules(
        analysis_profile, frame, mapping, valid_values, runtime, record
    )
    unit = mapping.get("value_unit")
    return AnalysisSummaryResponse(
        dataset_id=record.id,
        case_id=record.case_id,
        analysis_profile=analysis_profile.profile_id,
        profile_version=analysis_profile.profile_version,
        variable=AnalysisVariable(
            name=str(mapping.get("value_name") or "value"),
            unit=str(unit) if unit is not None else None,
        ),
        quality=quality,
        statistics=numeric,
        modules=modules,
        provenance=AnalysisProvenance(
            source_sha256=str(profile_json.get("source_sha256") or ""),
            dataset_version=record.version,
            generated_at=datetime.now(timezone.utc).isoformat(),
        ),
    )


# ---------------------------------------------------------------------------
# CSV 导出：provenance 头部注释行 + 稳定表头 + 明确行模式
# ---------------------------------------------------------------------------

_CSV_HEADER = ("section", "axis", "bin_index", "metric", "lower", "upper", "value")
_STATISTIC_METRICS = ("count", "min", "max", "mean", "median", "std")
_QUANTILE_METRICS = ("p05", "p25", "p50", "p75", "p95")
_PROFILE_METRICS = ("count", "mean", "median")


def _cell(value: Any) -> str:
    """单元格文本：None 为空串，其余 str()（同输入逐位确定）。"""

    return "" if value is None else str(value)


def _module_payload(summary: AnalysisSummaryResponse, module_id: str) -> dict[str, Any]:
    for module in summary.modules:
        if module.module_id == module_id:
            return module.payload
    return {}


def _csv_export(summary: AnalysisSummaryResponse) -> str:
    provenance = summary.provenance
    buffer = io.StringIO()
    # provenance 以头部注释行承载（本批锁定形态：注释行而非数据行）
    buffer.write(f"# dataset_id={summary.dataset_id}\n")
    buffer.write(f"# case_id={summary.case_id}\n")
    buffer.write(f"# analysis_profile={summary.analysis_profile}\n")
    buffer.write(f"# source_sha256={provenance.source_sha256}\n")
    buffer.write(f"# dataset_version={provenance.dataset_version}\n")
    buffer.write(f"# calculation_version={provenance.calculation_version}\n")
    buffer.write(f"# generated_at={provenance.generated_at}\n")

    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_CSV_HEADER)

    statistics = summary.statistics
    if statistics is not None:
        for metric in _STATISTIC_METRICS:
            writer.writerow(
                ("statistics", "", "", metric, "", "", _cell(getattr(statistics, metric)))
            )
        quantiles = statistics.quantiles
        for metric in _QUANTILE_METRICS:
            writer.writerow(
                (
                    "statistics",
                    "",
                    "",
                    metric,
                    "",
                    "",
                    _cell(getattr(quantiles, metric) if quantiles is not None else None),
                )
            )

    distribution = _module_payload(summary, "distribution")
    for index, bin_ in enumerate(distribution.get("bins") or []):
        writer.writerow(
            (
                "distribution",
                "",
                index,
                "count",
                _cell(bin_.get("lower")),
                _cell(bin_.get("upper")),
                _cell(bin_.get("count")),
            )
        )

    profile_slices = _module_payload(summary, "profile_slices")
    for axis_summary in profile_slices.get("axes") or []:
        axis = axis_summary.get("axis", "")
        for index, bin_ in enumerate(axis_summary.get("bins") or []):
            for metric in _PROFILE_METRICS:
                writer.writerow(
                    (
                        "profile",
                        axis,
                        index,
                        metric,
                        _cell(bin_.get("lower")),
                        _cell(bin_.get("upper")),
                        _cell(bin_.get(metric)),
                    )
                )
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.get("/{dataset_id}/analysis-summary")
def analysis_summary(
    dataset_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    summary = build_analysis_summary(runtime, dataset_id)
    return summary.model_dump(mode="json")


@router.get("/{dataset_id}/analysis-export")
def analysis_export(
    dataset_id: str,
    format: str = Query(default="json"),
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> Response:
    if format not in _EXPORT_FORMATS:
        raise PlatformError(
            ANALYSIS_EXPORT_FORMAT_INVALID,
            "不支持的导出格式（仅支持 json/csv）",
            {"format": format, "supported": list(_EXPORT_FORMATS)},
            http_status=422,
        )
    summary = build_analysis_summary(runtime, dataset_id)
    filename = f"analysis-{summary.dataset_id}-{summary.analysis_profile}.{format}"
    disposition = f'attachment; filename="{filename}"'
    if format == "json":
        return JSONResponse(
            content=summary.model_dump(mode="json"),
            headers={"Content-Disposition": disposition},
        )
    return Response(
        content=_csv_export(summary),
        media_type="text/csv",
        headers={"Content-Disposition": disposition},
    )
