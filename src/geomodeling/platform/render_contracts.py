"""Internal immutable contracts for v0.6.1 native volume rendering.

These frozen dataclasses describe render-source identity, validated regular
grids, and the ``wgs84_display_anchor_v1`` display contract shared by the
NetCDF volume and auxiliary point layers. Public API DTOs live in
``schemas.py``; nothing here serializes directly to HTTP responses.

``DisplayAnchor`` is a display transform only: the UI must show
``geolocation_status == "display_anchor_only"`` and must not claim real
georeferencing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

SourceKind = Literal["candidate_result", "builtin_legacy"]


@dataclass(frozen=True)
class RenderGridSource:
    source_kind: SourceKind
    source_id: str
    grid_path: Path
    grid_sha256: str
    property_name: str
    units: str
    coordinate_kind: str
    dimension: Literal["3d"]
    candidate_result_id: str | None = None
    field_name: str = "prediction"
    palette_intent: str = "property_default"
    validated_grid: ValidatedGrid | None = None


@dataclass(frozen=True)
class ValidatedGrid:
    axes: tuple[np.ndarray, np.ndarray, np.ndarray]
    values: np.ndarray
    is_nodata: np.ndarray
    valid_min: float
    valid_max: float


@dataclass(frozen=True)
class DisplayAnchor:
    longitude: float = 120.0
    latitude: float = 30.0
    height: float = 0.0
    contract: Literal["wgs84_display_anchor_v1"] = "wgs84_display_anchor_v1"
    geolocation_status: Literal["display_anchor_only"] = "display_anchor_only"
