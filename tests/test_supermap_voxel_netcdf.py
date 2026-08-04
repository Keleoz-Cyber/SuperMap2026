from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest
from scipy.io import netcdf_file

from geomodeling.platform import PlatformRuntime
from geomodeling.platform.errors import PlatformError
import geomodeling.platform.supermap_voxel_netcdf as voxel_export

RESULT_ID = "35348bb3-be03-4862-b764-ee165ae0c7dc"


def _make_grid(result_dir, *, shape=(11, 11, 11), asymmetric=False, nodata_count=0):
    nx, ny, nz = shape
    axes = np.array(
        [
            np.linspace(-160.0, -40.0, nx),
            np.linspace(220.0, 660.0, ny),
            np.linspace(-833.0047143, -19.5999, nz),
        ],
        dtype=object,
    )
    if asymmetric:
        values = np.zeros(shape, dtype=np.float64)
        for i in range(nx):
            for j in range(ny):
                for k in range(nz):
                    values[i, j, k] = 10.0 + i * 1.0 + j * 10.0 + k * 100.0
    else:
        rng = np.random.default_rng(20260804)
        values = rng.uniform(6.28, 105.36, size=shape)
    is_nodata = np.zeros(shape, dtype=bool)
    if nodata_count:
        flat = is_nodata.ravel()
        flat[1 : 1 + nodata_count] = True
        is_nodata = flat.reshape(shape)
    result_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(result_dir / "grid.npz", axes=axes, values=values, is_nodata=is_nodata)
    return axes, values, is_nodata


def _runtime(tmp_path, monkeypatch, result_id=RESULT_ID, shape=(11, 11, 11), asymmetric=False, nodata_count=0, dimension="3d"):
    runtime = PlatformRuntime(tmp_path / "runtime")
    axes, values, is_nodata = _make_grid(
        runtime.settings.results_dir / result_id,
        shape=shape,
        asymmetric=asymmetric,
        nodata_count=nodata_count,
    )
    metadata = {
        "result_id": result_id,
        "dimension": dimension,
        "dataset_version_id": "ds-version-1",
    }
    monkeypatch.setattr(voxel_export, "materialize", lambda _runtime, _rid: metadata)
    return runtime, axes, values, is_nodata


def test_export_fixed_result_success(tmp_path, monkeypatch):
    runtime, axes, values, is_nodata = _runtime(tmp_path, monkeypatch, asymmetric=True, nodata_count=3)
    result = voxel_export.export_supermap_voxel_netcdf(runtime, RESULT_ID)
    assert result["export_id"] == f"{RESULT_ID}-{result['grid_sha256'][:16]}-voxelgrid-netcdf-v1"
    manifest = result["manifest"]
    assert manifest["format"] == "supermap-voxel-netcdf"
    assert manifest["variable_name"] == "rho"
    assert manifest["dimension_names"] == ["x", "y", "z"]
    assert manifest["shape"] == [11, 11, 11]
    assert manifest["valid_count"] == 11 * 11 * 11 - 3
    assert manifest["nodata_count"] == 3
    grid_path = runtime.settings.result_grid(RESULT_ID)
    assert manifest["grid_sha256"] == hashlib.sha256(grid_path.read_bytes()).hexdigest()
    assert manifest["netcdf_sha256"] == hashlib.sha256(
        (runtime.settings.supermap_voxel_netcdf_export_dir(result["export_id"]) / "volume.nc").read_bytes()
    ).hexdigest()


def test_netcdf_structure_and_dtype(tmp_path, monkeypatch):
    runtime, *_ = _runtime(tmp_path, monkeypatch, asymmetric=True)
    result = voxel_export.export_supermap_voxel_netcdf(runtime, RESULT_ID)
    nc_path = runtime.settings.supermap_voxel_netcdf_export_dir(result["export_id"]) / "volume.nc"
    with netcdf_file(nc_path, mode="r") as nc:
        assert nc.dimensions == {"x": 11, "y": 11, "z": 11}
        for name in ("x", "y", "z", "rho"):
            var = nc.variables[name]
            assert var.typecode() == "f"
        assert nc.variables["rho"].dimensions == ("x", "y", "z")
        assert isinstance(nc.variables["rho"]._FillValue, np.float32)
        assert nc.variables["rho"]._FillValue == np.float32(-9999.0)
        assert nc.variables["rho"].missing_value == np.float32(-9999.0)
        assert nc.variables["x"].standard_name == b"longitude"
        assert nc.variables["x"].units == b"degrees_east"
        assert nc.variables["y"].standard_name == b"latitude"
        assert nc.variables["z"].positive == b"up"
        assert nc.candidate_result_id == RESULT_ID.encode()
        assert nc.coordinate_contract == b"wgs84_display_anchor_v1"


def test_float32_readback_matches_source_within_tolerance(tmp_path, monkeypatch):
    runtime, axes, values, is_nodata = _runtime(tmp_path, monkeypatch)
    result = voxel_export.export_supermap_voxel_netcdf(runtime, RESULT_ID)
    nc_path = runtime.settings.supermap_voxel_netcdf_export_dir(result["export_id"]) / "volume.nc"
    with netcdf_file(nc_path, mode="r") as nc:
        back = nc.variables["rho"][:].copy()
    valid = values[~is_nodata]
    encoded = back[~is_nodata]
    assert np.allclose(encoded, valid.astype(np.float32), rtol=1e-6, atol=1e-5)
    assert np.max(np.abs(encoded.astype(np.float64) - valid)) < 1e-3


def test_nodata_cells_read_back_exact_fill(tmp_path, monkeypatch):
    runtime, axes, values, is_nodata = _runtime(tmp_path, monkeypatch, nodata_count=17)
    result = voxel_export.export_supermap_voxel_netcdf(runtime, RESULT_ID)
    nc_path = runtime.settings.supermap_voxel_netcdf_export_dir(result["export_id"]) / "volume.nc"
    with netcdf_file(nc_path, mode="r") as nc:
        back = nc.variables["rho"][:].copy()
    assert np.all(back[is_nodata] == np.float32(-9999.0))
    assert np.all(back[~is_nodata] != np.float32(-9999.0))


def test_axes_monotonic_and_bounds_match_manifest(tmp_path, monkeypatch):
    runtime, *_ = _runtime(tmp_path, monkeypatch)
    result = voxel_export.export_supermap_voxel_netcdf(runtime, RESULT_ID)
    manifest = result["manifest"]
    nc_path = runtime.settings.supermap_voxel_netcdf_export_dir(result["export_id"]) / "volume.nc"
    with netcdf_file(nc_path, mode="r") as nc:
        for name in ("x", "y", "z"):
            axis = nc.variables[name][:].copy()
            assert np.all(np.diff(axis) > 0)
        x_back = nc.variables["x"][:].copy()
        y_back = nc.variables["y"][:].copy()
        z_back = nc.variables["z"][:].copy()
    bounds = manifest["layer_bounds_degrees"]
    assert x_back[0] == pytest.approx(bounds["west"], abs=1e-6)
    assert x_back[-1] == pytest.approx(bounds["east"], abs=1e-6)
    assert y_back[0] == pytest.approx(bounds["south"], abs=1e-6)
    assert y_back[-1] == pytest.approx(bounds["north"], abs=1e-6)
    assert z_back[0] == pytest.approx(manifest["z_bounds_metres"][0], abs=1e-3)
    assert z_back[-1] == pytest.approx(manifest["z_bounds_metres"][1], abs=1e-3)
    # 与任务书钉死的 WGS84 显示锚点包围盒一致（Float32 容差）
    assert bounds["west"] == pytest.approx(119.99937814993133, abs=1e-6)
    assert bounds["south"] == pytest.approx(29.998015379769292, abs=1e-6)
    assert bounds["east"] == pytest.approx(120.00062185006867, abs=1e-6)
    assert bounds["north"] == pytest.approx(30.001984620230708, abs=1e-6)


def test_asymmetric_fixture_proves_no_transpose_or_flip(tmp_path, monkeypatch):
    runtime, *_ = _runtime(tmp_path, monkeypatch, asymmetric=True)
    result = voxel_export.export_supermap_voxel_netcdf(runtime, RESULT_ID)
    nc_path = runtime.settings.supermap_voxel_netcdf_export_dir(result["export_id"]) / "volume.nc"
    with netcdf_file(nc_path, mode="r") as nc:
        back = nc.variables["rho"][:].copy()
    # X 步进 1、Y 步进 10、Z 步进 100；任一轴交换/翻转都会破坏这些等式
    assert back[1, 0, 0] - back[0, 0, 0] == pytest.approx(1.0, abs=1e-5)
    assert back[0, 1, 0] - back[0, 0, 0] == pytest.approx(10.0, abs=1e-5)
    assert back[0, 0, 1] - back[0, 0, 0] == pytest.approx(100.0, abs=1e-4)
    assert back[10, 10, 10] == pytest.approx(10.0 + 10 + 100 + 1000, abs=1e-2)
    assert back[0, 0, 0] == pytest.approx(10.0, abs=1e-5)


def test_export_is_deterministic_and_idempotent(tmp_path, monkeypatch):
    runtime, *_ = _runtime(tmp_path, monkeypatch)
    first = voxel_export.export_supermap_voxel_netcdf(runtime, RESULT_ID)
    nc_path = runtime.settings.supermap_voxel_netcdf_export_dir(first["export_id"]) / "volume.nc"
    first_bytes = nc_path.read_bytes()
    second = voxel_export.export_supermap_voxel_netcdf(runtime, RESULT_ID)
    assert first["export_id"] == second["export_id"]
    assert second["netcdf_sha256"] == first["netcdf_sha256"]
    assert nc_path.read_bytes() == first_bytes
    assert second["manifest"] == first["manifest"]


def test_rejects_non_3d_result(tmp_path, monkeypatch):
    runtime, *_ = _runtime(tmp_path, monkeypatch, dimension="2d")
    with pytest.raises(PlatformError) as exc:
        voxel_export.export_supermap_voxel_netcdf(runtime, RESULT_ID)
    assert exc.value.code == "VOXEL_NC_REQUIRES_3D"


def test_rejects_irregular_and_non_monotonic_axes(tmp_path, monkeypatch):
    runtime, axes, values, is_nodata = _runtime(tmp_path, monkeypatch)
    result_dir = runtime.settings.results_dir / RESULT_ID
    bad_axes = np.array([axes[0].copy(), axes[1].copy(), axes[2].copy()], dtype=object)
    bad_axes[2] = np.sort(np.random.default_rng(7).uniform(-833.0, -19.0, size=len(axes[2])))
    np.savez_compressed(result_dir / "grid.npz", axes=bad_axes, values=values, is_nodata=is_nodata)
    with pytest.raises(PlatformError) as exc:
        voxel_export.export_supermap_voxel_netcdf(runtime, RESULT_ID)
    assert exc.value.code == "VOXEL_NC_GRID_IRREGULAR"

    bad_axes[2] = axes[2][::-1].copy()
    np.savez_compressed(result_dir / "grid.npz", axes=bad_axes, values=values, is_nodata=is_nodata)
    with pytest.raises(PlatformError) as exc:
        voxel_export.export_supermap_voxel_netcdf(runtime, RESULT_ID)
    assert exc.value.code == "VOXEL_NC_AXIS_NOT_MONOTONIC"


def test_rejects_shape_mismatch_and_all_nodata(tmp_path, monkeypatch):
    runtime, axes, values, is_nodata = _runtime(tmp_path, monkeypatch)
    result_dir = runtime.settings.results_dir / RESULT_ID
    np.savez_compressed(
        result_dir / "grid.npz",
        axes=axes,
        values=values[1:, :, :],
        is_nodata=is_nodata[1:, :, :],
    )
    with pytest.raises(PlatformError) as exc:
        voxel_export.export_supermap_voxel_netcdf(runtime, RESULT_ID)
    assert exc.value.code == "VOXEL_NC_SHAPE_MISMATCH"

    np.savez_compressed(result_dir / "grid.npz", axes=axes, values=values, is_nodata=np.ones_like(is_nodata))
    with pytest.raises(PlatformError) as exc:
        voxel_export.export_supermap_voxel_netcdf(runtime, RESULT_ID)
    assert exc.value.code == "VOXEL_NC_NO_VALID_VALUES"


def test_rejects_invalid_result_id(tmp_path, monkeypatch):
    runtime, *_ = _runtime(tmp_path, monkeypatch)
    with pytest.raises(PlatformError) as exc:
        voxel_export.export_supermap_voxel_netcdf(runtime, "../escape")
    assert exc.value.code == "VOXEL_NC_RESULT_INVALID"


def test_checksums_cover_volume_and_manifest(tmp_path, monkeypatch):
    runtime, *_ = _runtime(tmp_path, monkeypatch)
    result = voxel_export.export_supermap_voxel_netcdf(runtime, RESULT_ID)
    export_dir = runtime.settings.supermap_voxel_netcdf_export_dir(result["export_id"])
    lines = (export_dir / "checksums.sha256").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    entries = {}
    for line in lines:
        digest, rel = line.split("  ", 1)
        entries[rel] = digest
    assert entries["volume.nc"] == result["netcdf_sha256"]
    assert entries["manifest.json"] == hashlib.sha256((export_dir / "manifest.json").read_bytes()).hexdigest()
