"""v0.9.0 Task 4: read-only result analysis summary API.

``GET /api/results/{result_id}/analysis-summary`` 是纯查询：只读已物化
网格，即时计算确定性分析，不创建文件、不改写数据库行、不隐式物化。
"""

from __future__ import annotations

import math
import copy
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, Depends, Query

from geomodeling.api.deps import get_platform_runtime
from geomodeling.modeling.anomalies import UncertaintyLayer
from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.repositories import require_active_candidate
from geomodeling.platform.results import load_grid, read_materialized_metadata
from geomodeling.platform.result_analysis import analyze_result_grid
from geomodeling.platform.result_analysis_contracts import RESULT_ANALYSIS_VERSION
from geomodeling.platform.schemas import SpatialValidationSpec

router = APIRouter(tags=["v0.9-result-analysis"])

_ML_ALGORITHMS = {"random_forest_spatial", "kriging_rf_residual"}

_CACHE_MAX_SIZE = 32
_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()


def _cache_get(key: str) -> dict[str, Any] | None:
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    return None


def _cache_put(key: str, value: dict[str, Any]) -> None:
    _cache[key] = value
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX_SIZE:
        _cache.popitem(last=False)


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _non_negative_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    if result < 0:
        return None
    return result


def _try_load_uncertainty_layer(
    runtime: PlatformRuntime,
    result_id: str,
    filename: str,
    key: str,
) -> UncertaintyLayer | None:
    """Try to load a professional uncertainty layer; return None if not materialized."""

    try:
        path = runtime.settings.professional_result_dir(result_id) / filename
        if not path.is_file():
            return None
        with __import__("numpy").load(path) as bundle:
            values = bundle[key]
            is_nodata = bundle["is_nodata"]
        return UncertaintyLayer(values=values, is_nodata=is_nodata)
    except Exception:
        return None


def _candidate_context(session, result_id: str):
    candidate = session.get(tables.CandidateResult, result_id)
    if candidate is None:
        return None
    run = session.get(tables.Run, candidate.run_id)
    if run is None:
        return None
    experiment = session.get(tables.Experiment, run.experiment_id)
    if experiment is None:
        return None
    return candidate, experiment, tables.loads_canonical(experiment.params_json)


def _compatible_kriging_baseline(
    session,
    *,
    result_id: str,
    dataset_version_id: str,
    validation: dict[str, Any],
    metrics: dict[str, Any],
) -> dict[str, Any] | None:
    normalized_validation = SpatialValidationSpec.model_validate(validation).model_dump(
        mode="json"
    )
    target_fold_sha = metrics.get("fold_assignments_sha256")
    target_common_count = _non_negative_int(metrics.get("common_valid_count"))
    if not target_fold_sha or target_common_count is None:
        return None
    matches: list[dict[str, Any]] = []
    rows = (
        session.query(tables.CandidateResult, tables.Experiment)
        .join(tables.Run, tables.CandidateResult.run_id == tables.Run.id)
        .join(tables.Experiment, tables.Run.experiment_id == tables.Experiment.id)
        .filter(
            tables.CandidateResult.id != result_id,
            tables.CandidateResult.status == "succeeded",
        )
        .all()
    )
    for candidate, experiment in rows:
        params = tables.loads_canonical(experiment.params_json)
        if params.get("algorithm") != "ordinary_kriging":
            continue
        if params.get("dataset_version_id") != dataset_version_id:
            continue
        candidate_validation = SpatialValidationSpec.model_validate(
            params.get("validation") or {}
        ).model_dump(mode="json")
        if candidate_validation != normalized_validation:
            continue
        candidate_metrics = tables.loads_canonical(candidate.metrics_json)
        if candidate_metrics.get("fold_assignments_sha256") != target_fold_sha:
            continue
        if (
            _non_negative_int(candidate_metrics.get("common_valid_count"))
            != target_common_count
        ):
            continue
        rmse = _finite_float(candidate_metrics.get("rmse"))
        mae = _finite_float(candidate_metrics.get("mae"))
        if rmse is None or mae is None:
            continue
        matches.append(
            {
                "result_id": candidate.id,
                "algorithm": "ordinary_kriging",
                "rmse": rmse,
                "mae": mae,
                "r2": _finite_float(candidate_metrics.get("r2")),
                "bias": _finite_float(candidate_metrics.get("bias")),
                "common_valid_count": target_common_count,
                "fold_assignments_sha256": target_fold_sha,
            }
        )
    return (
        min(matches, key=lambda item: (item["rmse"], item["result_id"]))
        if matches
        else None
    )


def _machine_learning_evidence(
    runtime: PlatformRuntime, result_id: str, metadata: dict[str, Any]
) -> dict[str, Any] | None:
    algorithm = metadata.get("algorithm")
    if algorithm not in _ML_ALGORITHMS:
        return None
    with runtime.session() as session:
        context = _candidate_context(session, result_id)
        if context is None:
            return None
        candidate, _experiment, params = context
        metrics = tables.loads_canonical(candidate.metrics_json)
        baseline = _compatible_kriging_baseline(
            session,
            result_id=result_id,
            dataset_version_id=params["dataset_version_id"],
            validation=params.get("validation") or {},
            metrics=metrics,
        )

    ml_metadata = metadata.get("ml") or {}
    available_fields = ["prediction", *(metadata.get("ml_fields") or {}).keys()]
    evidence: dict[str, Any] = {
        "algorithm": algorithm,
        "comparison_status": "unavailable",
        "comparison_reason_code": "ML_KRIGING_BASELINE_NOT_COMPARABLE",
        "baseline": None,
        "metric_change": None,
        "improved_over_kriging": None,
        "available_fields": available_fields,
        "dispersion_semantics": "model_dispersion_reference",
        "limitations": list(ml_metadata.get("limitations") or []),
        "technical_details": {
            "feature_version": ml_metadata.get("feature_version"),
            "sklearn_version": ml_metadata.get("sklearn_version"),
            "validation_method": (params.get("validation") or {}).get("method"),
            "common_valid_count": _non_negative_int(metrics.get("common_valid_count")),
            "fold_assignments_sha256": metrics.get("fold_assignments_sha256"),
        },
    }
    current_rmse = _finite_float(metrics.get("rmse"))
    current_mae = _finite_float(metrics.get("mae"))
    if baseline is None or current_rmse is None or current_mae is None:
        return evidence
    rmse_percent = (
        (current_rmse - baseline["rmse"]) / baseline["rmse"] * 100.0
        if baseline["rmse"] != 0
        else None
    )
    mae_percent = (
        (current_mae - baseline["mae"]) / baseline["mae"] * 100.0
        if baseline["mae"] != 0
        else None
    )
    evidence.update(
        {
            "comparison_status": "comparable",
            "comparison_reason_code": None,
            "baseline": baseline,
            "metric_change": {
                "rmse_absolute": current_rmse - baseline["rmse"],
                "rmse_percent": rmse_percent,
                "mae_absolute": current_mae - baseline["mae"],
                "mae_percent": mae_percent,
            },
            "improved_over_kriging": current_rmse < baseline["rmse"],
        }
    )
    return evidence


@router.get("/api/results/{result_id}/analysis-summary")
def get_analysis_summary(
    result_id: str,
    depth_bins: int = Query(default=8, ge=2, le=32),
    component_limit: int = Query(default=8, ge=1, le=20),
    min_support_nodes: int = Query(default=2, ge=1, le=10000),
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    require_active_candidate(runtime, result_id)

    metadata = read_materialized_metadata(runtime, result_id)
    grid_sha256 = metadata.get("grid_sha256", "")
    algorithm = metadata.get("algorithm", "unknown")
    property_name = metadata.get("property_name", "value")
    units = metadata.get("units", "unknown")
    coordinate_kind = metadata.get("coordinate_kind", "local_linear")
    ml_evidence = _machine_learning_evidence(runtime, result_id, metadata)

    cache_key = (
        f"{RESULT_ANALYSIS_VERSION}:{result_id}:{grid_sha256}:"
        f"{depth_bins}:{component_limit}:{min_support_nodes}"
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        result = copy.deepcopy(cached)
        if ml_evidence is not None:
            result["machine_learning"] = ml_evidence
        return result

    grid = load_grid(runtime, result_id)

    # Load uncertainty layers if available
    empirical_layer = None
    kriging_layer = None
    professional_dir = runtime.settings.professional_result_dir(result_id)
    empirical_path = professional_dir / "empirical_error_scale.npz"
    kriging_path = professional_dir / "kriging_standard_deviation.npz"
    if empirical_path.is_file():
        empirical_layer = _try_load_uncertainty_layer(
            runtime, result_id, "empirical_error_scale.npz", "empirical_error_scale"
        )
    if kriging_path.is_file():
        kriging_layer = _try_load_uncertainty_layer(
            runtime,
            result_id,
            "kriging_standard_deviation.npz",
            "kriging_standard_deviation",
        )

    # Get model metrics
    model_metrics: dict[str, Any] = {}
    common_valid_count: int | None = None
    with runtime.session() as session:
        candidate = session.get(tables.CandidateResult, result_id)
        if candidate is not None:
            raw_metrics = (
                tables.loads_canonical(candidate.metrics_json)
                if candidate.metrics_json
                else {}
            )
            for k in ("rmse", "mae", "r2", "coverage", "bias"):
                model_metrics[k] = _finite_float(raw_metrics.get(k))
            for k in (
                "common_valid_count",
                "candidate_valid_count",
                "candidate_nodata_count",
                "total_count",
            ):
                model_metrics[k] = _non_negative_int(raw_metrics.get(k))
            common_valid_count = _non_negative_int(
                raw_metrics.get("common_valid_count")
            )

        # Check for formal selection
        formal_selection_id = None
        formal_selection_note = None
        run = session.get(tables.Run, candidate.run_id) if candidate else None
        if run is not None:
            experiment = session.get(tables.Experiment, run.experiment_id)
            if experiment is not None:
                selection = (
                    session.query(tables.FormalSelection)
                    .filter(tables.FormalSelection.case_id == experiment.case_id)
                    .order_by(tables.FormalSelection.created_at.desc())
                    .first()
                )
                if selection is not None:
                    formal_selection_id = selection.id
                    formal_selection_note = selection.note

    summary = analyze_result_grid(
        grid,
        result_id=result_id,
        grid_sha256=grid_sha256,
        variable_name=property_name,
        variable_unit=units,
        depth_bins=depth_bins,
        component_limit=component_limit,
        min_support_nodes=min_support_nodes,
        algorithm=algorithm,
        model_metrics=model_metrics,
        common_valid_count=common_valid_count,
        formal_selection_id=formal_selection_id,
        formal_selection_note=formal_selection_note,
        empirical_layer=empirical_layer,
        kriging_layer=kriging_layer,
        coordinate_type=coordinate_kind,
    )

    result = summary.model_dump(mode="json")
    _cache_put(cache_key, copy.deepcopy(result))
    if ml_evidence is not None:
        result["machine_learning"] = ml_evidence
    return result
