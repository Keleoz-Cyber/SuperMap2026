"""Shared vertical distance scaling for 3D neighborhood and variogram math.

``z_scale`` is an experimental distance parameter: every distance used by
IDW weights, Kriging neighborhood search, and variogram fitting is computed
on ``(x, y, z × z_scale)`` — 0.5 weakens vertical distance, 2 strengthens
it. The rule applies only in 3D; 2D coordinates pass through untouched.
The helper always returns a copy and callers never persist scaled
coordinates: training data and output grids stay in physical coordinates.
It is an experimental knob compared by spatial validation, not confirmed
geological anisotropy.
"""

from __future__ import annotations

import math

import numpy as np

from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import Dimension

Z_SCALE_INVALID = "Z_SCALE_INVALID"
MAX_Z_SCALE = 20.0


def scale_distance_coordinates(
    coordinates: np.ndarray,
    *,
    dimension: Dimension | str = Dimension.THREE_D,
    z_scale: float,
) -> np.ndarray:
    """Return a copy of ``coordinates`` with the z column × ``z_scale`` (3D only).

    ``z_scale`` must be finite with ``0 < z_scale <= 20``; invalid values
    raise :class:`PlatformError` with code ``Z_SCALE_INVALID``. The input is
    never mutated; in 2D the copy is returned unchanged.
    """

    if isinstance(z_scale, bool) or not isinstance(z_scale, (int, float)):
        raise PlatformError(
            Z_SCALE_INVALID, "z_scale 必须是数值", {"z_scale": repr(z_scale)}
        )
    scale = float(z_scale)
    if not math.isfinite(scale) or scale <= 0.0 or scale > MAX_Z_SCALE:
        raise PlatformError(
            Z_SCALE_INVALID,
            "z_scale 必须为有限值且满足 0 < z_scale ≤ 20",
            {"z_scale": repr(z_scale)},
        )
    result = np.asarray(coordinates, dtype="float64").copy()
    if Dimension(dimension) == Dimension.THREE_D:
        result[:, 2] *= scale
    return result
