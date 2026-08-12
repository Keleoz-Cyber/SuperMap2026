"""v0.9.0 成果级确定性分析：统计、深度分层、连通区预览与结构化发现。

模块职责（design §5.1）：
- 加载已物化规则网格；
- 校验轴、形状、NoData 和有限值；
- 计算完整场统计；
- 计算统一阈值和组成；
- 计算 Z 向分层；
- 调用现有连通区内核生成有界预览；
- 生成受控的结构化发现。

模块不得访问 HTTP，不得写数据库，不得自行物化结果。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from geomodeling.modeling.anomalies import (
    AnomalyExtractionSpec,
    UncertaintyLayer,
    extract_anomalies,
)
from geomodeling.modeling.slices import GridResult
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.result_analysis_contracts import (
    RESULT_ANALYSIS_NO_VALID_CELLS,
    RESULT_ANALYSIS_VERSION,
    Composition,
    CompositionBucket,
    ComponentPreview,
    ComponentsPreview,
    DepthBin,
    DepthProfile,
    DepthProfileStatus,
    Finding,
    FindingConfidence,
    FindingEvidence,
    FindingKind,
    GridStatistics,
    ModelEvidence,
    Provenance,
    ResultAnalysisSummary,
    ResultIdentity,
    SpatialTarget,
    Thresholds,
    ThresholdSource,
    VariableInfo,
)

__all__ = [
    "analyze_result_grid",
    "finite_valid_values",
    "result_thresholds",
    "composition_summary",
    "depth_profile",
]


def finite_valid_values(values: np.ndarray, is_nodata: np.ndarray) -> np.ndarray:
    """有效体元：``is_nodata == False`` 且值有限（design §5.3）。"""

    mask = ~is_nodata & np.isfinite(values)
    return values[mask]


def result_thresholds(valid: np.ndarray) -> tuple[float, float]:
    """默认低/高阈值：完整成果有效体元的 p25/p75，NumPy linear 分位法。"""

    if valid.size == 0:
        raise PlatformError(
            RESULT_ANALYSIS_NO_VALID_CELLS,
            "成果网格无有效体元，无法计算阈值",
            {},
        )
    q25, q75 = np.quantile(valid, [0.25, 0.75], method="linear")
    return float(q25), float(q75)


def composition_summary(
    values: np.ndarray,
    is_nodata: np.ndarray,
    low: float,
    high: float,
) -> Composition:
    """按有效规则网格节点计数，低/正常/高值组成（design §5.3）。

    - low: ``value < p25`` (strictly below low threshold)
    - high: ``value >= p75``
    - normal: between low and high
    """

    valid_mask = ~is_nodata & np.isfinite(values)
    valid_vals = values[valid_mask]
    total = int(valid_vals.size)
    low_count = int((valid_vals < low).sum())
    high_count = int((valid_vals >= high).sum())
    normal_count = total - low_count - high_count
    return Composition(buckets=[
        CompositionBucket(category="low", count=low_count, ratio=low_count / total if total else 0.0),
        CompositionBucket(category="normal", count=normal_count, ratio=normal_count / total if total else 0.0),
        CompositionBucket(category="high", count=high_count, ratio=high_count / total if total else 0.0),
    ])


def _z_coords_3d(grid: GridResult) -> np.ndarray:
    """Broadcast Z axis to full grid shape."""
    z = grid.axes[2]
    shape = [1] * len(grid.axes)
    shape[2] = z.size
    return z.reshape(shape) * np.ones(grid.values.shape, dtype=np.float64)


def depth_profile(
    grid: GridResult,
    valid_mask: np.ndarray,
    high_threshold: float,
    depth_bins: int,
) -> DepthProfile:
    """Z 向分层（design §5.3）。

    - 按 Z 轴坐标范围等距分箱；每个网格节点只进入一个层段；最后一箱包含上界。
    - 2D 结果返回 ``not_applicable``。
    """

    if grid.dimension == "2d":
        return DepthProfile(status=DepthProfileStatus.NOT_APPLICABLE.value, bins=[])

    z_axis = grid.axes[2]
    z_min = float(z_axis.min())
    z_max = float(z_axis.max())
    if z_max <= z_min:
        return DepthProfile(status=DepthProfileStatus.NOT_APPLICABLE.value, bins=[])

    bin_edges = np.linspace(z_min, z_max, depth_bins + 1)
    z_broadcast = _z_coords_3d(grid)

    values = grid.values
    bins: list[DepthBin] = []
    for i in range(depth_bins):
        lower = float(bin_edges[i])
        upper = float(bin_edges[i + 1])
        if i == depth_bins - 1:
            in_bin = (z_broadcast >= lower) & (z_broadcast <= upper)
        else:
            in_bin = (z_broadcast >= lower) & (z_broadcast < upper)
        bin_valid = in_bin & valid_mask
        bin_values = values[bin_valid]
        valid_count = int(bin_values.size)
        if valid_count == 0:
            bins.append(DepthBin(
                z_lower=lower, z_upper=upper, valid_count=0,
                mean=0.0, high_count=0, high_ratio=0.0,
            ))
            continue
        mean = float(bin_values.mean())
        high_count = int((bin_values >= high_threshold).sum())
        bins.append(DepthBin(
            z_lower=lower, z_upper=upper, valid_count=valid_count,
            mean=mean, high_count=high_count,
            high_ratio=high_count / valid_count,
        ))
    return DepthProfile(status=DepthProfileStatus.APPLICABLE.value, bins=bins)


def _build_components_preview(
    grid: GridResult,
    high_threshold: float,
    component_limit: int,
    min_support_nodes: int,
    empirical_layer: UncertaintyLayer | None = None,
    kriging_layer: UncertaintyLayer | None = None,
) -> ComponentsPreview:
    """调用既有 ``extract_anomalies`` 生成连通区预览（design §5.3）。

    - ``direction=high``, ``threshold=p75``
    - 连通区排序：先按 ``support_measure`` 降序，再按 ``value_max`` 降序，再按原始 component_id 升序
    - 标签：前 26 个按 A-Z
    - 不创建 ``AnomalyExtractionRecord``
    """

    spec = AnomalyExtractionSpec(
        direction="high",
        threshold=high_threshold,
        min_support_nodes=min_support_nodes,
    )
    result = extract_anomalies(
        axes=grid.axes,
        values=grid.values,
        is_nodata=grid.is_nodata,
        spec=spec,
        empirical_error_scale=empirical_layer,
        kriging_std=kriging_layer,
    )

    sorted_components = sorted(
        result.components,
        key=lambda c: (-c.support_measure, -c.value_max, c.component_id),
    )
    capped = sorted_components[:component_limit]
    labels = [chr(ord("A") + i) for i in range(min(26, len(capped)))]

    rows: list[ComponentPreview] = []
    for rank, (comp, label) in enumerate(zip(capped, labels), start=1):
        rows.append(ComponentPreview(
            rank=rank,
            label=label,
            component_id=comp.component_id,
            support_node_count=comp.support_node_count,
            support_measure=comp.support_measure,
            support_unit=comp.support_unit,
            bounds=[list(b) for b in comp.bounds],
            centroid=list(comp.centroid),
            value_min=comp.value_min,
            value_max=comp.value_max,
            value_mean=comp.value_mean,
            touches_grid_boundary=comp.touches_grid_boundary,
            empirical_error_scale_min=comp.empirical_error_scale_min,
            empirical_error_scale_max=comp.empirical_error_scale_max,
            empirical_error_scale_mean=comp.empirical_error_scale_mean,
            kriging_std_min=comp.kriging_std_min,
            kriging_std_max=comp.kriging_std_max,
            kriging_std_mean=comp.kriging_std_mean,
        ))

    return ComponentsPreview(
        threshold=high_threshold,
        connectivity_rule=spec.connectivity_rule,
        total=len(result.components),
        returned=len(rows),
        rows=rows,
    )


def _build_findings(
    depth_prof: DepthProfile,
    components: ComponentsPreview,
    model_ev: ModelEvidence,
    uncertainty_available: bool,
    dimension: str,
) -> list[Finding]:
    """生成受控的结构化发现（design §8）。"""

    findings: list[Finding] = []

    # dominant_depth_interval
    if depth_prof.status == "applicable" and depth_prof.bins:
        best_bin = max(
            depth_prof.bins,
            key=lambda b: b.high_ratio if b.valid_count > 0 else -1,
        )
        best_index = depth_prof.bins.index(best_bin)
        findings.append(Finding(
            id="finding-dominant-depth",
            kind=FindingKind.DOMINANT_DEPTH_INTERVAL.value,
            title="高值占比最高的深度层段",
            statement=(
                f"第 {best_index + 1} 层段（{best_bin.z_lower:.1f}-{best_bin.z_upper:.1f}）"
                f"高值占比 {best_bin.high_ratio:.1%}，为所有层段最高"
            ),
            evidence=[
                FindingEvidence(name="depth_bin_index", value=best_index),
                FindingEvidence(name="high_ratio", value=best_bin.high_ratio),
                FindingEvidence(name="valid_count", value=best_bin.valid_count),
            ],
            confidence=FindingConfidence.MEDIUM.value,
            limitations=["局部坐标系"],
            spatial_target=SpatialTarget(kind="depth_bin", depth_bin_index=best_index),
        ))

    # largest_high_component
    if components.rows:
        top = components.rows[0]
        findings.append(Finding(
            id="finding-largest-component",
            kind=FindingKind.LARGEST_HIGH_COMPONENT.value,
            title="网格支持量最大的高值连通区",
            statement=(
                f"{top.label} 区网格支持量 {top.support_measure:.1f}"
                f"（{top.support_unit}），为最大连通区"
            ),
            evidence=[
                FindingEvidence(name="label", value=top.label),
                FindingEvidence(name="support_measure", value=top.support_measure),
                FindingEvidence(name="value_max", value=top.value_max),
            ],
            confidence=FindingConfidence.HIGH.value,
            limitations=["网格支持量非真实地质体积/面积"],
            spatial_target=SpatialTarget(kind="component", component_id=top.component_id),
        ))

    # boundary_contact
    boundary_labels = [r.label for r in components.rows if r.touches_grid_boundary]
    if boundary_labels:
        findings.append(Finding(
            id="finding-boundary-contact",
            kind=FindingKind.BOUNDARY_CONTACT.value,
            title="主要连通区接触网格边界",
            statement=(
                f"{'、'.join(boundary_labels)} 区接触网格边界，需注意外推影响"
            ),
            evidence=[FindingEvidence(name="boundary_components", value=",".join(boundary_labels))],
            confidence=FindingConfidence.HIGH.value,
            limitations=["边界接触不代表异常延伸范围"],
            spatial_target=None,
        ))

    # formal_model
    metrics_parts = []
    for k in ("rmse", "mae", "r2", "coverage"):
        v = model_ev.metrics.get(k)
        if v is not None:
            metrics_parts.append(f"{k.upper()}={v}")
    metrics_str = "，".join(metrics_parts) if metrics_parts else "无可用指标"
    findings.append(Finding(
        id="finding-formal-model",
        kind=FindingKind.FORMAL_MODEL.value,
        title=f"正式模型为 {model_ev.algorithm}",
        statement=(
            f"公共有效点 {model_ev.common_valid_count or '未知'}，{metrics_str}"
        ),
        evidence=[
            FindingEvidence(name="algorithm", value=model_ev.algorithm),
            FindingEvidence(name="common_valid_count", value=model_ev.common_valid_count),
        ],
        confidence=FindingConfidence.HIGH.value,
        limitations=["指标基于交叉验证"],
        spatial_target=None,
    ))

    # uncertainty_availability
    if dimension == "2d":
        avail = "not_applicable"
        statement = "2D 成果无深度分层；不确定性状态为不适用"
    elif uncertainty_available:
        avail = "available"
        statement = "经验误差尺度和 Kriging 标准差均已物化"
    else:
        avail = "missing"
        statement = "该成果未物化专业不确定性层"
    findings.append(Finding(
        id="finding-uncertainty",
        kind=FindingKind.UNCERTAINTY_AVAILABILITY.value,
        title="不确定性证据状态",
        statement=statement,
        evidence=[FindingEvidence(name="availability", value=avail)],
        confidence=FindingConfidence.HIGH.value,
        limitations=[] if avail == "available" else ["不确定性分析不可用"],
        spatial_target=None,
    ))

    return findings


def analyze_result_grid(
    grid: GridResult,
    *,
    result_id: str,
    grid_sha256: str,
    variable_name: str,
    variable_unit: str,
    depth_bins: int = 8,
    component_limit: int = 8,
    min_support_nodes: int = 2,
    algorithm: str = "unknown",
    model_metrics: dict[str, Any] | None = None,
    common_valid_count: int | None = None,
    formal_selection_id: str | None = None,
    formal_selection_note: str | None = None,
    empirical_layer: UncertaintyLayer | None = None,
    kriging_layer: UncertaintyLayer | None = None,
    coordinate_type: str = "local_linear",
) -> ResultAnalysisSummary:
    """对已物化规则网格进行确定性成果分析（design §5）。

    纯函数：不访问 HTTP、不写数据库、不自行物化结果。
    """

    valid = finite_valid_values(grid.values, grid.is_nodata)
    if valid.size == 0:
        raise PlatformError(
            RESULT_ANALYSIS_NO_VALID_CELLS,
            "成果网格无有效体元",
            {"result_id": result_id, "valid_count": 0},
        )

    low, high = result_thresholds(valid)
    valid_mask = ~grid.is_nodata & np.isfinite(grid.values)

    # Grid statistics
    q25, q75 = np.quantile(valid, [0.25, 0.75], method="linear")
    median = float(np.median(valid))
    grid_stats = GridStatistics(
        shape=list(grid.values.shape),
        valid_count=int(valid.size),
        nodata_count=int(grid.is_nodata.sum() + (~np.isfinite(grid.values) & ~grid.is_nodata).sum()),
        min=float(valid.min()),
        max=float(valid.max()),
        mean=float(valid.mean()),
        median=median,
        p25=float(q25),
        p75=float(q75),
    )

    thresholds = Thresholds(
        low=low,
        high=high,
        source=ThresholdSource.FULL_GRID_QUARTILE.value,
        method="numpy_linear_p25_p75",
    )

    composition = composition_summary(grid.values, grid.is_nodata, low, high)

    dp = depth_profile(grid, valid_mask, high, depth_bins)

    components = _build_components_preview(
        grid, high, component_limit, min_support_nodes,
        empirical_layer, kriging_layer,
    )

    # Model evidence
    metrics = model_metrics or {}
    clean_metrics: dict[str, float | int | None] = {}
    for k, v in metrics.items():
        if isinstance(v, (int,)) or (isinstance(v, float) and math.isfinite(v)):
            clean_metrics[k] = v
        elif v is None:
            clean_metrics[k] = None
    model_ev = ModelEvidence(
        algorithm=algorithm,
        metrics=clean_metrics,
        common_valid_count=common_valid_count,
        formal_selection_id=formal_selection_id,
        formal_selection_note=formal_selection_note,
    )

    uncertainty_available = empirical_layer is not None or kriging_layer is not None
    findings = _build_findings(dp, components, model_ev, uncertainty_available, grid.dimension)

    identity = ResultIdentity(
        result_id=result_id,
        grid_sha256=grid_sha256,
        analysis_version=RESULT_ANALYSIS_VERSION,
        dimension=grid.dimension,
        coordinate_type=coordinate_type,
    )

    provenance = Provenance(
        grid_sha256=grid_sha256,
        calculation_version=RESULT_ANALYSIS_VERSION,
        threshold_method="numpy_linear_p25_p75",
    )

    return ResultAnalysisSummary(
        identity=identity,
        variable=VariableInfo(name=variable_name, unit=variable_unit),
        grid=grid_stats,
        thresholds=thresholds,
        composition=composition,
        depth_profile=dp,
        components_preview=components,
        model_evidence=model_ev,
        findings=findings,
        provenance=provenance,
    )
