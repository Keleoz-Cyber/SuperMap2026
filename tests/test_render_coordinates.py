"""v0.6.1 shared render contracts and display-anchor coordinate tests.

The NetCDF volume and auxiliary point layers share one display transform
(``wgs84_display_anchor_v1``): local metric grid coordinates are mapped onto a
regular WGS84 grid anchored at a fixed display location. This is a display
transform only — ``geolocation_status`` stays ``display_anchor_only`` and must
never be presented as real georeferencing.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from geomodeling.platform.errors import PlatformError
from geomodeling.platform.render_contracts import DisplayAnchor
from geomodeling.platform.render_coordinates import (
    display_anchor_axes,
    display_anchor_points,
    display_transform_for_bounds,
    netcdf_variable_name,
    sha256_file,
)
from geomodeling.platform.settings import PlatformSettings


def test_variable_name_is_generic_and_netcdf_safe():
    assert netcdf_variable_name("Vx") == "Vx"
    assert netcdf_variable_name("视电阻率 Ω·m") == "_______m"
    assert netcdf_variable_name("123") == "value_123"


def test_variable_name_strips_and_truncates():
    assert netcdf_variable_name("  Vx  ") == "Vx"
    long_name = "a" * 100
    assert netcdf_variable_name(long_name) == "a" * 64


def test_display_anchor_maps_local_center_to_anchor():
    x = np.array([-10.0, 0.0, 10.0])
    y = np.array([20.0, 30.0, 40.0])
    lon, lat, contract = display_anchor_axes(x, y, DisplayAnchor())
    assert lon[1] == pytest.approx(120.0)
    assert lat[1] == pytest.approx(30.0)
    assert contract["geolocation_status"] == "display_anchor_only"


def test_points_and_axes_use_identical_transform():
    anchor = DisplayAnchor()
    x = np.array([-10.0, 0.0, 10.0])
    y = np.array([20.0, 30.0, 40.0])
    z = np.array([1.0, 2.0, 3.0])
    lon_axis, lat_axis, _ = display_anchor_axes(x, y, anchor)
    lon, lat, height = display_anchor_points(x, y, z, anchor, origin_x=0.0, origin_y=30.0)
    np.testing.assert_allclose(lon, lon_axis)
    np.testing.assert_allclose(lat, lat_axis)
    np.testing.assert_allclose(height, z + anchor.height)


def test_display_transform_for_bounds_matches_capability_contract():
    transform = display_transform_for_bounds((-10.0, 10.0), (20.0, 40.0), DisplayAnchor())
    assert transform["contract"] == "wgs84_display_anchor_v1"
    assert transform["origin_x"] == pytest.approx(0.0)
    assert transform["origin_y"] == pytest.approx(30.0)
    assert transform["anchor_longitude"] == pytest.approx(120.0)
    assert transform["anchor_latitude"] == pytest.approx(30.0)
    assert transform["anchor_height"] == pytest.approx(0.0)
    # WGS84 曲率：纬度 30° 处每度经/纬的米数（handoff POC 验证值）。
    assert transform["metres_per_degree_lon"] == pytest.approx(96486.3, rel=1e-4)
    assert transform["metres_per_degree_lat"] == pytest.approx(110852.4, rel=1e-4)


def test_display_anchor_rejects_non_wgs84_anchor():
    with pytest.raises(PlatformError) as excinfo:
        display_anchor_axes(
            np.array([0.0, 1.0]),
            np.array([0.0, 1.0]),
            DisplayAnchor(longitude=200.0),
        )
    assert excinfo.value.code == "RENDER_DISPLAY_ANCHOR_INVALID"


def test_display_anchor_rejects_non_finite_anchor():
    with pytest.raises(PlatformError) as excinfo:
        display_anchor_axes(
            np.array([0.0, 1.0]),
            np.array([0.0, 1.0]),
            DisplayAnchor(latitude=float("nan")),
        )
    assert excinfo.value.code == "RENDER_DISPLAY_ANCHOR_INVALID"


def test_display_anchor_rejects_out_of_range_result():
    anchor = DisplayAnchor(longitude=179.9999, latitude=30.0)
    x = np.array([0.0, 10_000_000.0])
    y = np.array([0.0, 1.0])
    with pytest.raises(PlatformError) as excinfo:
        display_anchor_axes(x, y, anchor)
    assert excinfo.value.code == "RENDER_COORDINATES_INVALID"


def test_display_anchor_rejects_non_finite_axes():
    with pytest.raises(PlatformError) as excinfo:
        display_anchor_axes(
            np.array([0.0, float("inf")]),
            np.array([0.0, 1.0]),
            DisplayAnchor(),
        )
    assert excinfo.value.code == "RENDER_COORDINATES_INVALID"


def test_sha256_file_matches_hashlib(tmp_path):
    payload = b"render-contract-bytes" * 10_000
    path = tmp_path / "blob.bin"
    path.write_bytes(payload)
    assert sha256_file(path) == hashlib.sha256(payload).hexdigest()


def test_settings_expose_render_directories_and_anchor(tmp_path):
    settings = PlatformSettings(data_dir=tmp_path)
    assert settings.render_sources_dir == tmp_path / "render-sources"
    assert settings.render_assets_dir == tmp_path / "render-assets"
    assert settings.display_anchor == DisplayAnchor()
    directories = settings.runtime_directories()
    assert settings.render_sources_dir in directories
    assert settings.render_assets_dir in directories
