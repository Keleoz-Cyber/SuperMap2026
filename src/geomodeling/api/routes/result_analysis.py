"""v0.9.0 Task 4: read-only result analysis summary API.

``GET /api/results/{result_id}/analysis-summary`` 是纯查询：只读已物化
网格，即时计算确定性分析，不创建文件、不改写数据库行、不隐式物化。
"""

from __future__ import annotations

import math
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, Depends, Query

from geomodeling.api.deps import get_platform_runtime
from geomodeling.modeling.anomalies import UncertaintyLayer
from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.repositories import require_active_candidate
from geomodeling.platform.results import load_grid, read_materialized_metadata
from geomodeling.platform.result_analysis import analyze_result_grid

router = APIRouter(tags=["v0.9-result-analysis"])

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
    runtime: PlatformRuntime, result_id: str, filename: str, key: str,
) -> UncertaintyLayer | None:
    """Try to load a professional uncertainty layer; return None if not materialized."""

    from geomodeling.platform.results import _LAYER_ARTIFACTS

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

    cache_key = f"{result_id}:{grid_sha256}:{depth_bins}:{component_limit}:{min_support_nodes}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

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
            runtime, result_id, "kriging_standard_deviation.npz", "kriging_standard_deviation"
        )

    # Get model metrics
    model_metrics: dict[str, Any] = {}
    common_valid_count: int | None = None
    with runtime.session() as session:
        candidate = session.get(tables.CandidateResult, result_id)
        if candidate is not None:
            raw_metrics = tables.loads_canonical(candidate.metrics_json) if candidate.metrics_json else {}
            for k in ("rmse", "mae", "r2", "coverage", "bias"):
                model_metrics[k] = _finite_float(raw_metrics.get(k))
            for k in ("common_valid_count", "candidate_valid_count", "candidate_nodata_count", "total_count"):
                model_metrics[k] = _non_negative_int(raw_metrics.get(k))
            common_valid_count = _non_negative_int(raw_metrics.get("common_valid_count"))

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
    _cache_put(cache_key, result)
    return result
