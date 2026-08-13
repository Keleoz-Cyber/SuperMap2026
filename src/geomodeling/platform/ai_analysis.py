"""v0.9.0 AI 辅助研判服务：EvidencePacket 构建、prompt 构造、结果校验与记录管理。

当前合同依据：docs/project-guide.md。

固定顺序：确定性分析 -> EvidencePacket -> DeepSeek -> 严格校验 -> 展示。
AI 未配置/超时/无效输出时，规则分析照常成功。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid
from typing import Any

from geomodeling.integrations.deepseek import (
    DEEPSEEK_NOT_CONFIGURED,
    DeepSeekAdapter,
    DeepSeekResult,
)
from geomodeling.platform.ai_analysis_contracts import (
    PROMPT_VERSION,
    AIAnalysisMode,
    AIAnalysisRecord,
    AIAnalysisStatus,
    AIReview,
    EvidencePacket,
    EvidenceComposition,
    EvidenceCompositionBucket,
    EvidenceComponentSummary,
    EvidenceConstraints,
    EvidenceCurrentSlice,
    EvidenceDepthBin,
    EvidenceDepthProfile,
    EvidenceGridStatistics,
    EvidenceIdentity,
    EvidenceInputQuality,
    EvidenceModelMetrics,
    EvidenceResultGrid,
    EvidenceThresholds,
    EvidenceUncertainty,
    EvidenceVariable,
)
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.result_analysis_contracts import ResultAnalysisSummary
from geomodeling.platform import tables

__all__ = [
    "AI_ANALYSIS_UNAVAILABLE",
    "build_evidence_packet",
    "compute_evidence_hash",
    "build_prompts",
    "validate_ai_review",
    "generate_ai_analysis",
    "get_latest_ai_analysis",
]

AI_ANALYSIS_UNAVAILABLE = "AI_ANALYSIS_UNAVAILABLE"

_PROHIBITED_CLAIMS = [
    "含水性", "含水", "危险性", "危险", "储量", "成矿", "地质体积",
    "工程安全", "安全等级", "资源量",
]

_BOUNDARY_MARKERS = (
    "超出当前证据范围",
    "无法判断", "无法评估", "无法用于", "无法支持", "无法推断", "无法解释为",
    "不能判断", "不能评估", "不能用于", "不能支持", "不能推断", "不能代表",
    "不可用于", "不可视为", "不可解释为", "不可推断",
    "不代表", "不等于", "不是", "并非", "非真实", "不具备", "未知",
)


def _unsupported_claim_term(text: str) -> str | None:
    """Return a prohibited term used as a claim, not a negative boundary.

    The model may state that evidence *cannot* support a domain conclusion.
    Those explicit boundary sentences are safe and useful; positive or bare
    domain assertions remain fail-closed. Sentence-level matching prevents a
    disclaimer elsewhere in the paragraph from laundering an unsafe claim.
    """

    for sentence in re.split(r"[。！？!?；;\n]", text):
        if not sentence:
            continue
        for term in _PROHIBITED_CLAIMS:
            if term in sentence and not any(marker in sentence for marker in _BOUNDARY_MARKERS):
                return term
    return None


def build_evidence_packet(
    summary: ResultAnalysisSummary,
    *,
    current_slice: dict[str, Any] | None = None,
    model_metrics: dict[str, Any] | None = None,
    common_valid_count: int | None = None,
    formal_selection_id: str | None = None,
    uncertainty_available: str = "missing",
    input_quality: dict[str, Any] | None = None,
) -> EvidencePacket:
    """从确定性成果摘要构建有界、脱敏的 EvidencePacket（design §9.3）。

    不包含原始点表、完整体元数组、本机路径或凭据。
    """

    identity = EvidenceIdentity(
        result_id=summary.identity.result_id,
        grid_sha256=summary.identity.grid_sha256,
        calculation_version=summary.identity.analysis_version,
        dimension=summary.identity.dimension,
        coordinate_type=summary.identity.coordinate_type,
    )

    variable = EvidenceVariable(
        name=summary.variable.name,
        unit=summary.variable.unit,
    )

    grid_stats = EvidenceGridStatistics(
        valid_count=summary.grid.valid_count,
        nodata_count=summary.grid.nodata_count,
        min=summary.grid.min,
        max=summary.grid.max,
        mean=summary.grid.mean,
        p25=summary.grid.p25,
        p75=summary.grid.p75,
    )

    thresholds = EvidenceThresholds(
        low=summary.thresholds.low,
        high=summary.thresholds.high,
        method=summary.thresholds.method,
    )

    composition = EvidenceComposition(buckets=[
        EvidenceCompositionBucket(
            category=b.category, count=b.count, ratio=b.ratio,
        ) for b in summary.composition.buckets
    ])

    depth_bins = [
        EvidenceDepthBin(
            z_lower=b.z_lower, z_upper=b.z_upper,
            valid_count=b.valid_count, mean=b.mean,
            high_count=b.high_count, high_ratio=b.high_ratio,
        ) for b in summary.depth_profile.bins
    ]
    depth_profile = EvidenceDepthProfile(
        status=summary.depth_profile.status, bins=depth_bins,
    )

    result_grid = EvidenceResultGrid(
        statistics=grid_stats,
        thresholds=thresholds,
        composition=composition,
        depth_profile=depth_profile,
    )

    components = [
        EvidenceComponentSummary(
            label=c.label,
            component_id=c.component_id,
            support_node_count=c.support_node_count,
            support_measure=c.support_measure,
            value_max=c.value_max,
            value_mean=c.value_mean,
            touches_grid_boundary=c.touches_grid_boundary,
        ) for c in summary.components_preview.rows
    ]

    slice_obj = None
    if current_slice is not None:
        slice_obj = EvidenceCurrentSlice(
            axis=current_slice.get("axis", "z"),
            coordinate=float(current_slice.get("coordinate", 0.0)),
            valid_count=int(current_slice.get("valid_count", 0)),
            mean=float(current_slice.get("mean", 0.0)),
            high_count=int(current_slice.get("high_count", 0)),
            high_ratio=float(current_slice.get("high_ratio", 0.0)),
        )

    raw_metrics = model_metrics or {}
    model_evidence = EvidenceModelMetrics(
        algorithm=summary.model_evidence.algorithm,
        common_valid_count=common_valid_count,
        rmse=raw_metrics.get("rmse"),
        mae=raw_metrics.get("mae"),
        r2=raw_metrics.get("r2"),
        coverage=raw_metrics.get("coverage"),
        formal_selection_id=formal_selection_id,
    )

    uncertainty = EvidenceUncertainty(
        availability=uncertainty_available,
        empirical_error_mean=None,
        kriging_std_mean=None,
    )

    raw_quality = input_quality or {}
    input_quality_obj = EvidenceInputQuality(
        validated_count=raw_quality.get("validated_count"),
        total_count=raw_quality.get("total_count"),
        coverage=raw_quality.get("coverage"),
    )

    constraints = EvidenceConstraints(
        prohibited_claims=_PROHIBITED_CLAIMS,
        known_limitations=[
            "局部坐标系，非地理坐标",
            "属性单位依赖输入数据",
            "网格支持量非真实地质体积/面积",
            "样本覆盖可能不足",
        ],
    )

    return EvidencePacket(
        identity=identity,
        variable=variable,
        result_grid=result_grid,
        spatial_components=components,
        current_slice=slice_obj,
        model_evidence=model_evidence,
        uncertainty=uncertainty,
        input_quality=input_quality_obj,
        constraints=constraints,
    )


def compute_evidence_hash(packet: EvidencePacket) -> str:
    """SHA-256 of canonical JSON of EvidencePacket."""

    canonical = json.dumps(
        packet.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_prompts(packet: EvidencePacket, mode: str) -> tuple[str, str]:
    """Build system and user prompts for the given mode (design §9.2, §9.4)."""

    system = (
        "你是一位地质建模数据分析助手。你只对已提供的结构化证据进行归纳、"
        "矛盾检查和复核建议。你必须返回 JSON 对象。"
        "禁止生成含水性、危险性、储量、成矿、工程安全等级等当前数据不能支持的领域结论。"
        "每条主要判断必须引用合法的 evidence_ref。"
        "输出字段：spatial_pattern, model_reliability, uncertainty_and_risk, "
        "review_and_next_checks（均为 {summary, evidence_refs[]}），"
        "consensus {consensus, disagreements[], recommended_checks[], "
        "decision_options[{label, trigger, benefit, cost, evidence_refs[]}], limitations[]}。"
        "evidence_ref 可选值：identity, variable, result_grid, spatial_components, "
        "component-{id}, depth_profile, depth_bin-{index}, composition, "
        "model_evidence, uncertainty, input_quality, constraints, current_slice。"
        "limitations 可以引用 constraints，但不得复述 prohibited_claims 中的词，"
        "统一表述为‘超出当前证据范围’。"
    )

    if mode == "review":
        system += (
            " 你是复核模式：先生成分析，再检查证据引用和过度结论，"
            "只返回复核后的结果。"
        )

    packet_json = packet.model_dump(mode="json")
    user = (
        f"请分析以下成果证据包并返回 JSON。\n\n"
        f"{json.dumps(packet_json, ensure_ascii=False, indent=2)}\n\n"
        "返回 JSON 对象，包含 spatial_pattern, model_reliability, "
        "uncertainty_and_risk, review_and_next_checks, consensus 五个字段。"
    )
    return system, user


def validate_ai_review(
    content: str,
    packet: EvidencePacket,
    evidence_hash: str,
    provider: str,
    model: str,
    mode: str,
) -> AIReview:
    """Parse and validate AI output against strict contract and evidence refs."""

    try:
        raw = json.loads(content)
    except json.JSONDecodeError:
        raise PlatformError(
            AI_ANALYSIS_UNAVAILABLE,
            "AI 输出不是有效 JSON",
            {"reason": "malformed_json"},
        )

    raw["evidence_hash"] = evidence_hash
    raw["prompt_version"] = PROMPT_VERSION
    raw["provider"] = provider
    raw["model"] = model
    raw["mode"] = mode

    try:
        review = AIReview.model_validate(raw)
    except Exception as exc:
        raise PlatformError(
            AI_ANALYSIS_UNAVAILABLE,
            "AI 输出合同校验失败",
            {"reason": str(exc)},
        )

    valid_ids = packet.valid_evidence_ids
    for perspective in (
        review.spatial_pattern,
        review.model_reliability,
        review.uncertainty_and_risk,
        review.review_and_next_checks,
    ):
        for ref in perspective.evidence_refs:
            if ref not in valid_ids:
                raise PlatformError(
                    AI_ANALYSIS_UNAVAILABLE,
                    f"AI 引用了不存在的证据 ID: {ref}",
                    {"ref": ref, "valid": sorted(valid_ids)},
                )
    for opt in review.consensus.decision_options:
        for ref in opt.evidence_refs:
            if ref not in valid_ids:
                raise PlatformError(
                    AI_ANALYSIS_UNAVAILABLE,
                    f"AI 决策选项引用了不存在的证据 ID: {ref}",
                    {"ref": ref},
                )

    # Explicit negative boundary statements may repeat a domain term (for
    # example, "不可视为真实地质体积"). Positive or bare domain claims remain
    # fail-closed across every analytical and decision surface.
    claim_surfaces = [
        review.spatial_pattern.summary,
        review.model_reliability.summary,
        review.uncertainty_and_risk.summary,
        review.review_and_next_checks.summary,
        review.consensus.consensus,
        *review.consensus.disagreements,
        *review.consensus.recommended_checks,
        *review.consensus.limitations,
    ]
    for option in review.consensus.decision_options:
        claim_surfaces.extend([option.label, option.trigger, option.benefit, option.cost])
    for text in claim_surfaces:
        claim = _unsupported_claim_term(text)
        if claim is not None:
            raise PlatformError(
                AI_ANALYSIS_UNAVAILABLE,
                f"AI 输出包含禁止的领域结论: {claim}",
                {"prohibited": claim},
            )

    return review


def generate_ai_analysis(
    runtime,
    result_id: str,
    *,
    mode: str = "quick",
    regenerate: bool = False,
    adapter: DeepSeekAdapter | None = None,
) -> AIAnalysisRecord:
    """Generate or reuse AI analysis for a result (design §9.5).

    - ``mode=quick|review``
    - Reuse by result/grid/evidence/prompt/model/mode unless ``regenerate=True``
    - Never calls DeepSeek from a GET route
    - Returns typed ``AIAnalysisRecord``
    """

    from geomodeling.platform.results import load_grid, read_materialized_metadata
    from geomodeling.platform.result_analysis import analyze_result_grid, finite_valid_values
    from geomodeling.platform.slice_analysis import analyze_grid_slice
    from geomodeling.modeling.anomalies import UncertaintyLayer

    if adapter is None:
        adapter = DeepSeekAdapter.from_env()
    if adapter is None:
        return AIAnalysisRecord(
            id=str(uuid.uuid4()),
            result_id=result_id,
            grid_sha256="",
            evidence_hash="",
            prompt_version=PROMPT_VERSION,
            provider="deepseek",
            model="not_configured",
            mode=mode,
            status=AIAnalysisStatus.UNAVAILABLE.value,
            error_code=DEEPSEEK_NOT_CONFIGURED,
            error_message="DeepSeek API 未配置",
            created_at=tables.utc_now_iso(),
        )

    metadata = read_materialized_metadata(runtime, result_id)
    grid_sha256 = metadata.get("grid_sha256", "")
    grid = load_grid(runtime, result_id)

    # Reuse the candidate's persisted cross-validation evidence. The rule
    # analysis and AI review must not disagree merely because the AI packet
    # omitted metrics that already exist in the platform database.
    model_metrics: dict[str, float | None] = {}
    common_valid_count: int | None = None
    formal_selection_id: str | None = None
    input_quality: dict[str, int | float | None] = {}
    with runtime.session() as session:
        candidate = session.get(tables.CandidateResult, result_id)
        raw_metrics = (
            tables.loads_canonical(candidate.metrics_json)
            if candidate is not None and candidate.metrics_json
            else {}
        )
        for key in ("rmse", "mae", "r2", "coverage"):
            value = raw_metrics.get(key)
            try:
                parsed = float(value) if value is not None else None
            except (TypeError, ValueError):
                parsed = None
            model_metrics[key] = parsed if parsed is None or math.isfinite(parsed) else None

        def parse_nonnegative_int(value: Any) -> int | None:
            try:
                parsed = int(value) if value is not None else None
            except (TypeError, ValueError):
                return None
            return parsed if parsed is not None and parsed >= 0 else None

        parsed_common_valid = parse_nonnegative_int(raw_metrics.get("common_valid_count"))
        if parsed_common_valid is not None and parsed_common_valid >= 0:
            common_valid_count = parsed_common_valid

        input_quality = {
            "validated_count": parse_nonnegative_int(raw_metrics.get("candidate_valid_count")),
            "total_count": parse_nonnegative_int(raw_metrics.get("total_count")),
            "coverage": model_metrics.get("coverage"),
        }

        run = session.get(tables.Run, candidate.run_id) if candidate is not None else None
        experiment = session.get(tables.Experiment, run.experiment_id) if run is not None else None
        if experiment is not None:
            selection = (
                session.query(tables.FormalSelection)
                .filter(tables.FormalSelection.case_id == experiment.case_id)
                .order_by(tables.FormalSelection.created_at.desc())
                .first()
            )
            if selection is not None:
                formal_selection_id = selection.id

    summary = analyze_result_grid(
        grid,
        result_id=result_id,
        grid_sha256=grid_sha256,
        variable_name=metadata.get("property_name", "value"),
        variable_unit=metadata.get("units", "unknown"),
        depth_bins=8,
        component_limit=8,
        min_support_nodes=2,
        algorithm=metadata.get("algorithm", "unknown"),
        model_metrics=model_metrics,
        common_valid_count=common_valid_count,
        formal_selection_id=formal_selection_id,
        coordinate_type=metadata.get("coordinate_kind", "local_linear"),
    )

    # Current slice (z middle)
    current_slice_data = None
    if grid.dimension == "3d" and len(grid.axes[2]) > 1:
        mid_z = len(grid.axes[2]) // 2
        try:
            slice_analysis = analyze_grid_slice(
                grid.axes, grid.values, grid.is_nodata, "z", mid_z,
            )
            stats = slice_analysis.statistics
            current_slice_data = {
                "axis": "z",
                "coordinate": float(slice_analysis.coordinate),
                "valid_count": stats.get("valid_count", 0),
                "mean": stats.get("mean") or 0.0,
                "high_count": stats.get("high_count") or 0,
                "high_ratio": stats.get("high_ratio") or 0.0,
            }
        except Exception:
            pass

    # Uncertainty availability
    professional_dir = runtime.settings.professional_result_dir(result_id)
    uncertainty_available = "missing"
    if (professional_dir / "empirical_error_scale.npz").is_file():
        uncertainty_available = "available"
    if grid.dimension == "2d":
        uncertainty_available = "not_applicable"

    packet = build_evidence_packet(
        summary,
        current_slice=current_slice_data,
        model_metrics=model_metrics,
        common_valid_count=common_valid_count,
        formal_selection_id=formal_selection_id,
        uncertainty_available=uncertainty_available,
        input_quality=input_quality,
    )
    evidence_hash = compute_evidence_hash(packet)

    # Check for reuse
    if not regenerate:
        with runtime.session() as session:
            existing = (
                session.query(tables.AIAnalysisRecord)
                .filter(
                    tables.AIAnalysisRecord.result_id == result_id,
                    tables.AIAnalysisRecord.evidence_hash == evidence_hash,
                    tables.AIAnalysisRecord.prompt_version == PROMPT_VERSION,
                    tables.AIAnalysisRecord.model == adapter.model,
                    tables.AIAnalysisRecord.mode == mode,
                    tables.AIAnalysisRecord.status == AIAnalysisStatus.SUCCEEDED.value,
                )
                .order_by(tables.AIAnalysisRecord.created_at.desc())
                .first()
            )
            if existing is not None:
                review = AIReview.model_validate(
                    tables.loads_canonical(existing.review_json)
                ) if existing.review_json else None
                return AIAnalysisRecord(
                    id=existing.id,
                    result_id=existing.result_id,
                    grid_sha256=existing.grid_sha256,
                    evidence_hash=existing.evidence_hash,
                    prompt_version=existing.prompt_version,
                    provider=existing.provider,
                    model=existing.model,
                    mode=existing.mode,
                    status=existing.status,
                    review=review,
                    error_code=existing.error_code,
                    error_message=existing.error_message,
                    usage_prompt_tokens=existing.usage_prompt_tokens,
                    usage_completion_tokens=existing.usage_completion_tokens,
                    latency_ms=existing.latency_ms,
                    created_at=existing.created_at,
                )

    # Call DeepSeek
    system_prompt, user_prompt = build_prompts(packet, mode)
    start = time.time()
    result: DeepSeekResult = adapter.chat_json(system_prompt, user_prompt)
    latency_ms = int((time.time() - start) * 1000)

    record_id = str(uuid.uuid4())
    if not result.ok:
        record = AIAnalysisRecord(
            id=record_id,
            result_id=result_id,
            grid_sha256=grid_sha256,
            evidence_hash=evidence_hash,
            prompt_version=PROMPT_VERSION,
            provider="deepseek",
            model=adapter.model,
            mode=mode,
            status=AIAnalysisStatus.ERROR.value,
            error_code=result.error_code,
            error_message=result.error_message,
            usage_prompt_tokens=result.usage_prompt_tokens,
            usage_completion_tokens=result.usage_completion_tokens,
            latency_ms=latency_ms,
            created_at=tables.utc_now_iso(),
        )
    else:
        try:
            review = validate_ai_review(
                result.content or "",
                packet,
                evidence_hash,
                "deepseek",
                adapter.model,
                mode,
            )
            record = AIAnalysisRecord(
                id=record_id,
                result_id=result_id,
                grid_sha256=grid_sha256,
                evidence_hash=evidence_hash,
                prompt_version=PROMPT_VERSION,
                provider="deepseek",
                model=adapter.model,
                mode=mode,
                status=AIAnalysisStatus.SUCCEEDED.value,
                review=review,
                usage_prompt_tokens=result.usage_prompt_tokens,
                usage_completion_tokens=result.usage_completion_tokens,
                latency_ms=latency_ms,
                created_at=tables.utc_now_iso(),
            )
        except PlatformError as exc:
            record = AIAnalysisRecord(
                id=record_id,
                result_id=result_id,
                grid_sha256=grid_sha256,
                evidence_hash=evidence_hash,
                prompt_version=PROMPT_VERSION,
                provider="deepseek",
                model=adapter.model,
                mode=mode,
                status=AIAnalysisStatus.ERROR.value,
                error_code=exc.code,
                error_message=exc.message,
                usage_prompt_tokens=result.usage_prompt_tokens,
                usage_completion_tokens=result.usage_completion_tokens,
                latency_ms=latency_ms,
                created_at=tables.utc_now_iso(),
            )

    # Persist
    with runtime.session() as session:
        if regenerate:
            session.query(tables.AIAnalysisRecord).filter(
                tables.AIAnalysisRecord.result_id == record.result_id,
                tables.AIAnalysisRecord.evidence_hash == record.evidence_hash,
                tables.AIAnalysisRecord.prompt_version == record.prompt_version,
                tables.AIAnalysisRecord.model == record.model,
                tables.AIAnalysisRecord.mode == record.mode,
            ).delete()
        row = tables.AIAnalysisRecord(
            id=record.id,
            result_id=record.result_id,
            grid_sha256=record.grid_sha256,
            evidence_hash=record.evidence_hash,
            prompt_version=record.prompt_version,
            provider=record.provider,
            model=record.model,
            mode=record.mode,
            status=record.status,
            review_json=tables.dumps_canonical(
                record.review.model_dump(mode="json")
            ) if record.review else None,
            error_code=record.error_code,
            error_message=record.error_message,
            usage_prompt_tokens=record.usage_prompt_tokens,
            usage_completion_tokens=record.usage_completion_tokens,
            latency_ms=record.latency_ms,
            created_at=record.created_at,
        )
        session.add(row)
        session.commit()

    return record


def get_latest_ai_analysis(
    runtime,
    result_id: str,
    *,
    mode: str | None = None,
) -> AIAnalysisRecord | None:
    """Get the latest AI analysis record, optionally scoped to one mode."""

    with runtime.session() as session:
        query = session.query(tables.AIAnalysisRecord).filter(
            tables.AIAnalysisRecord.result_id == result_id,
        )
        if mode is not None:
            query = query.filter(tables.AIAnalysisRecord.mode == mode)
        row = query.order_by(tables.AIAnalysisRecord.created_at.desc()).first()
        if row is None:
            return None
        review = None
        if row.review_json:
            try:
                review = AIReview.model_validate(tables.loads_canonical(row.review_json))
            except Exception:
                pass
        return AIAnalysisRecord(
            id=row.id,
            result_id=row.result_id,
            grid_sha256=row.grid_sha256,
            evidence_hash=row.evidence_hash,
            prompt_version=row.prompt_version,
            provider=row.provider,
            model=row.model,
            mode=row.mode,
            status=row.status,
            review=review,
            error_code=row.error_code,
            error_message=row.error_message,
            usage_prompt_tokens=row.usage_prompt_tokens,
            usage_completion_tokens=row.usage_completion_tokens,
            latency_ms=row.latency_ms,
            created_at=row.created_at,
        )
