"""The single CacheContract for the formal resistivity S3M voxel cache.

Built once from the platform's formal registry (``config/default.yaml``):
value range from the formal SuperMap result, expected cell count from its
rows × columns × bands, z envelope from the formal model's slice
parameters, and x/y envelope from the registered standardized dataset.
Every cache-side validation (scp value range, cell weights, count, bbox,
result identity) consumes this object — no duplicated hardcoded constants.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CacheContract:
    """Registry-derived contract for one published voxel cache."""

    result_id: str
    value_min: float
    value_max: float
    expected_count: int
    x_range: tuple[float, float]
    y_range: tuple[float, float]
    z_range: tuple[float, float]
    value_tolerance: float = 1e-3
    count_ratio: tuple[float, float] = (0.5, 2.0)
    bbox_tolerance: float = 5.0
    max_count: int = 200_000
    max_decompressed_bytes: int = 64 * 1024 * 1024

    @classmethod
    def build(
        cls,
        *,
        result_id: str,
        value_min: float,
        value_max: float,
        rows: int,
        columns: int,
        bands: int,
        x_range: tuple[float, float],
        y_range: tuple[float, float],
        z_range: tuple[float, float],
    ) -> "CacheContract":
        return cls(
            result_id=result_id,
            value_min=float(value_min),
            value_max=float(value_max),
            expected_count=int(rows) * int(columns) * int(bands),
            x_range=(float(x_range[0]), float(x_range[1])),
            y_range=(float(y_range[0]), float(y_range[1])),
            z_range=(float(z_range[0]), float(z_range[1])),
        )


def formal_result(config: Any) -> dict[str, Any]:
    """The single formal SuperMap result from the registry config."""

    for result in config.supermap.get("results", []):
        if result.get("result_category") == "formal":
            return result
    raise KeyError("no formal SuperMap result registered in config")


def formal_model(config: Any, model_id: str | None) -> dict[str, Any]:
    """Model definition backing the formal result (slice parameters)."""

    for model in config.models:
        if model.get("model_id") == model_id:
            return model
    return {}


def contract_from_config(config: Any, *, xy_extent: tuple[tuple[float, float], tuple[float, float]]) -> CacheContract:
    """Build the CacheContract from the registry config.

    ``xy_extent`` carries the registered standardized dataset's (x, y)
    ranges; the API layer derives them from the registered standardized CSV
    so the contract stays registry-sourced even though the config does not
    inline planar bounds.
    """

    result = formal_result(config)
    model = formal_model(config, result.get("model_id"))
    params = model.get("parameters", {})
    z_min = float(params.get("slice_min_z_m", 0.0))
    z_max = z_min + float(params.get("slice_count", 0)) * float(params.get("slice_interval_m", 0))
    return CacheContract.build(
        result_id=result["dataset"],
        value_min=result["value_min"],
        value_max=result["value_max"],
        rows=result["rows"],
        columns=result["columns"],
        bands=result["bands"],
        x_range=xy_extent[0],
        y_range=xy_extent[1],
        z_range=(z_min, z_max),
    )
