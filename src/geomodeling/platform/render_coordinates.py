"""Shared display-anchor transforms and identity helpers for v0.6.1 rendering.

The NetCDF volume and auxiliary point layers both map local metric grid
coordinates onto a regular WGS84 display grid anchored at one fixed display
location (``wgs84_display_anchor_v1``). This is a display transform only —
``geolocation_status`` stays ``display_anchor_only`` and never claims real
georeferencing.

The WGS84 curvature formula (prime-vertical and meridian radii at the anchor
latitude) is migrated unchanged from the verified handoff POC
(``supermap_volume._display_anchor_axes`` on
``origin/codex/v0.6.1-supermap-netcdf-handoff``), so the volume axes and point
layers derive lon/lat through one shared code path.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

from geomodeling.platform.errors import (
    RENDER_COORDINATES_INVALID,
    RENDER_DISPLAY_ANCHOR_INVALID,
    PlatformError,
)
from geomodeling.platform.render_contracts import DisplayAnchor

_WGS84_SEMI_MAJOR_M = 6_378_137.0
_WGS84_ECCENTRICITY_SQUARED = 6.6943799901413165e-3
_RENDER_CONTRACT = "wgs84_display_anchor_v1"


def netcdf_variable_name(property_name: str) -> str:
    """Derive a NetCDF-safe variable identifier from a dataset property name."""

    normalized = re.sub(r"[^A-Za-z0-9_]", "_", property_name.strip())
    if not normalized or normalized[0].isdigit():
        normalized = f"value_{normalized}"
    return normalized[:64] or "value"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_anchor(anchor: DisplayAnchor) -> None:
    if not (
        math.isfinite(anchor.longitude)
        and -180.0 <= anchor.longitude <= 180.0
        and math.isfinite(anchor.latitude)
        and -90.0 < anchor.latitude < 90.0
        and math.isfinite(anchor.height)
    ):
        raise PlatformError(
            RENDER_DISPLAY_ANCHOR_INVALID,
            "SuperMap 显示锚点必须是有效的 WGS84 经度、纬度和高程",
            {
                "anchor_lon": anchor.longitude,
                "anchor_lat": anchor.latitude,
                "anchor_height": anchor.height,
            },
            http_status=500,
        )


def _metres_per_degree(anchor: DisplayAnchor) -> tuple[float, float]:
    """WGS84 曲率：锚点纬度处每度经/纬对应的米数（handoff 验证公式）。"""

    latitude_radians = math.radians(anchor.latitude)
    sin_latitude = math.sin(latitude_radians)
    denominator = math.sqrt(
        1.0 - _WGS84_ECCENTRICITY_SQUARED * sin_latitude * sin_latitude
    )
    prime_vertical_radius = _WGS84_SEMI_MAJOR_M / denominator
    meridian_radius = (
        _WGS84_SEMI_MAJOR_M
        * (1.0 - _WGS84_ECCENTRICITY_SQUARED)
        / denominator**3
    )
    metres_per_degree_lon = (
        math.pi
        / 180.0
        * (prime_vertical_radius + anchor.height)
        * math.cos(latitude_radians)
    )
    metres_per_degree_lat = (
        math.pi / 180.0 * (meridian_radius + anchor.height)
    )
    return metres_per_degree_lon, metres_per_degree_lat


def _as_finite_axis(values: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or array.size == 0 or not np.all(np.isfinite(array)):
        raise PlatformError(
            RENDER_COORDINATES_INVALID,
            f"{name} 坐标必须是有限的一维数值",
            {"axis": name},
            http_status=409,
        )
    return array


def _check_wgs84_range(lon: np.ndarray, lat: np.ndarray) -> None:
    if (
        np.any(lon < -180.0)
        or np.any(lon > 180.0)
        or np.any(lat < -90.0)
        or np.any(lat > 90.0)
    ):
        raise PlatformError(
            RENDER_COORDINATES_INVALID,
            "显示锚点转换后的经纬度超出 WGS84 有效范围",
            http_status=409,
        )


def display_anchor_axes(
    x: np.ndarray, y: np.ndarray, anchor: DisplayAnchor
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Map local X/Y metre axes to a regular WGS84 display grid."""

    x = _as_finite_axis(x, "x")
    y = _as_finite_axis(y, "y")
    _validate_anchor(anchor)
    origin_x = float((x[0] + x[-1]) / 2.0)
    origin_y = float((y[0] + y[-1]) / 2.0)
    metres_per_degree_lon, metres_per_degree_lat = _metres_per_degree(anchor)
    render_x = anchor.longitude + (x - origin_x) / metres_per_degree_lon
    render_y = anchor.latitude + (y - origin_y) / metres_per_degree_lat
    _check_wgs84_range(render_x, render_y)

    contract = {
        "name": _RENDER_CONTRACT,
        "epsg": 4326,
        "horizontal_unit": "Degree",
        "vertical_unit": "Meter",
        "geolocation_status": "display_anchor_only",
        "anchor": {
            "longitude": anchor.longitude,
            "latitude": anchor.latitude,
            "height": anchor.height,
        },
        "local_origin": {"x": origin_x, "y": origin_y, "z": 0.0},
        "axis_mapping": {"x": "east", "y": "north", "z": "up"},
        "formula": {
            "longitude": "anchor_lon + (x - origin_x) / metres_per_degree_lon",
            "latitude": "anchor_lat + (y - origin_y) / metres_per_degree_lat",
            "height": "anchor_height + z",
            "metres_per_degree_lon": metres_per_degree_lon,
            "metres_per_degree_lat": metres_per_degree_lat,
        },
    }
    return render_x, render_y, contract


def display_anchor_points(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    anchor: DisplayAnchor,
    *,
    origin_x: float,
    origin_y: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Map local point samples through the same display transform as axes."""

    x = _as_finite_axis(x, "x")
    y = _as_finite_axis(y, "y")
    z = _as_finite_axis(z, "z")
    if not (x.shape == y.shape == z.shape):
        raise PlatformError(
            RENDER_COORDINATES_INVALID,
            "点坐标 x/y/z 形状必须一致",
            {"x_shape": list(x.shape), "y_shape": list(y.shape), "z_shape": list(z.shape)},
            http_status=409,
        )
    _validate_anchor(anchor)
    if not (math.isfinite(origin_x) and math.isfinite(origin_y)):
        raise PlatformError(
            RENDER_COORDINATES_INVALID,
            "局部原点必须是有限数值",
            {"origin_x": origin_x, "origin_y": origin_y},
            http_status=409,
        )
    metres_per_degree_lon, metres_per_degree_lat = _metres_per_degree(anchor)
    lon = anchor.longitude + (x - origin_x) / metres_per_degree_lon
    lat = anchor.latitude + (y - origin_y) / metres_per_degree_lat
    height = anchor.height + z
    _check_wgs84_range(lon, lat)
    return lon, lat, height


def display_transform_for_bounds(
    x_bounds: tuple[float, float],
    y_bounds: tuple[float, float],
    anchor: DisplayAnchor,
) -> dict[str, Any]:
    """Public display-transform summary (capability/manifest contract shape)."""

    _validate_anchor(anchor)
    origin_x = (float(x_bounds[0]) + float(x_bounds[1])) / 2.0
    origin_y = (float(y_bounds[0]) + float(y_bounds[1])) / 2.0
    if not all(
        math.isfinite(value) for value in (origin_x, origin_y)
    ):
        raise PlatformError(
            RENDER_COORDINATES_INVALID,
            "网格边界必须是有限数值",
            {"x_bounds": list(x_bounds), "y_bounds": list(y_bounds)},
            http_status=409,
        )
    metres_per_degree_lon, metres_per_degree_lat = _metres_per_degree(anchor)
    return {
        "contract": _RENDER_CONTRACT,
        "origin_x": origin_x,
        "origin_y": origin_y,
        "anchor_longitude": anchor.longitude,
        "anchor_latitude": anchor.latitude,
        "anchor_height": anchor.height,
        "metres_per_degree_lon": metres_per_degree_lon,
        "metres_per_degree_lat": metres_per_degree_lat,
    }
