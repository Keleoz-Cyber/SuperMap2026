"""Export materialized 3D grids to deterministic NetCDF classic/v3 for SuperMap VoxelGridLayer3D.

v0.6.1 POC（`docs/v0.6.1-supermap-voxelgrid-netcdf-poc.md`）：
浏览器经 `scene.addVoxelGridLayer(url, name)` 直读 `volume.nc`，
不经 iDesktopX / iServer / S3M / 载体模型。与 GeoTIFF 的 `supermap_volume`
路线共享成果物化、ID 校验和 WGS84 显示锚点转换，但格式版本与存储目录独立。
"""

from __future__ import annotations

import json
import math
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from scipy.io import netcdf_file

from geomodeling.platform import PlatformRuntime
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.results import materialize
from geomodeling.platform.supermap_volume import _display_anchor_axes, _sha256

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_EXPORTER_VERSION = 1
_EXPORT_SUFFIX = "voxelgrid-netcdf-v1"
_RENDER_CONTRACT = "wgs84_display_anchor_v1"
_FILL_VALUE = np.float32(-9999.0)
_GENERATOR = "geomodeling-platform supermap_voxel_netcdf v1"


def _fail(code: str, message: str, details: dict[str, Any] | None = None, http_status: int = 409) -> None:
    raise PlatformError(code, message, details or {}, http_status=http_status)


def _validate_axis(axis: np.ndarray, name: str) -> float:
    if axis.ndim != 1 or len(axis) < 2 or not np.all(np.isfinite(axis)):
        _fail("VOXEL_NC_AXIS_INVALID", f"{name} 轴必须是一维且含至少两个有限节点", {"axis": name})
    delta = np.diff(axis)
    if np.any(delta <= 0):
        _fail("VOXEL_NC_AXIS_NOT_MONOTONIC", f"{name} 轴必须严格递增", {"axis": name})
    spacing = float(delta[0])
    if not np.allclose(delta, spacing, rtol=1e-8, atol=max(abs(spacing) * 1e-8, 1e-12)):
        _fail("VOXEL_NC_GRID_IRREGULAR", f"{name} 轴必须近似等间距", {"axis": name})
    return spacing


def _load_grid(runtime: PlatformRuntime, result_id: str) -> tuple[dict[str, Any], Path, list[np.ndarray], np.ndarray, np.ndarray]:
    if not _SAFE_ID.fullmatch(result_id):
        _fail("VOXEL_NC_RESULT_INVALID", "成果 ID 格式无效", {"result_id": result_id}, http_status=400)
    metadata = materialize(runtime, result_id)
    if metadata.get("dimension") != "3d":
        _fail("VOXEL_NC_REQUIRES_3D", "只有三维成果可以导出 NetCDF 体素包", {"result_id": result_id})
    grid_path = runtime.settings.result_grid(result_id)
    if not grid_path.is_file():
        _fail("VOXEL_NC_GRID_MISSING", "成果网格不存在", {"result_id": result_id})
    with np.load(grid_path, allow_pickle=True) as bundle:
        axes = [np.asarray(axis, dtype=np.float64) for axis in bundle["axes"]]
        values = np.asarray(bundle["values"], dtype=np.float64)
        is_nodata = np.asarray(bundle["is_nodata"], dtype=bool)
    if len(axes) != 3 or values.ndim != 3 or is_nodata.shape != values.shape:
        _fail(
            "VOXEL_NC_GRID_INVALID",
            "三维网格工件形状无效",
            {"axes": len(axes), "values_shape": list(values.shape), "is_nodata_shape": list(is_nodata.shape)},
        )
    if values.shape != tuple(len(axis) for axis in axes):
        _fail(
            "VOXEL_NC_SHAPE_MISMATCH",
            "网格形状与坐标轴不匹配",
            {"values_shape": list(values.shape), "axis_nodes": [len(axis) for axis in axes]},
        )
    for axis, name in zip(axes, ("x", "y", "z")):
        _validate_axis(axis, name)
    return metadata, grid_path, axes, values, is_nodata


def _write_volume_nc(
    nc_path: Path,
    render_x: np.ndarray,
    render_y: np.ndarray,
    render_z: np.ndarray,
    encoded: np.ndarray,
    *,
    result_id: str,
    grid_sha: str,
    units: str,
    valid_min: float,
    valid_max: float,
) -> None:
    try:
        with netcdf_file(nc_path, mode="w", version=1) as nc:
            nc.Conventions = "CF-1.8"
            nc.title = "RACE v0.6.1 SuperMap VoxelGridLayer3D POC"
            nc.candidate_result_id = result_id
            nc.grid_sha256 = grid_sha
            nc.coordinate_contract = _RENDER_CONTRACT
            nc.geolocation_status = "display_anchor_only"
            nc.generator = _GENERATOR
            nc.createDimension("x", len(render_x))
            nc.createDimension("y", len(render_y))
            nc.createDimension("z", len(render_z))
            x_var = nc.createVariable("x", "f", ("x",))
            y_var = nc.createVariable("y", "f", ("y",))
            z_var = nc.createVariable("z", "f", ("z",))
            rho_var = nc.createVariable("rho", "f", ("x", "y", "z"))
            x_var.standard_name = "longitude"
            x_var.units = "degrees_east"
            y_var.standard_name = "latitude"
            y_var.units = "degrees_north"
            z_var.standard_name = "height"
            z_var.units = "m"
            z_var.positive = "up"
            rho_var.long_name = "resistivity"
            rho_var.units = units
            rho_var.valid_min = np.float32(valid_min)
            rho_var.valid_max = np.float32(valid_max)
            rho_var._FillValue = _FILL_VALUE
            rho_var.missing_value = _FILL_VALUE
            x_var[:] = np.asarray(render_x, dtype=np.float32)
            y_var[:] = np.asarray(render_y, dtype=np.float32)
            z_var[:] = np.asarray(render_z, dtype=np.float32)
            rho_var[:] = encoded
    except PlatformError:
        raise
    except Exception as exc:  # noqa: BLE001 - 统一折算为领域错误码
        _fail("VOXEL_NC_WRITE_FAILED", f"NetCDF 写入失败：{exc}", http_status=500)


def _readback_verify(
    nc_path: Path,
    encoded: np.ndarray,
    render_axes: list[np.ndarray],
    valid_mask: np.ndarray,
) -> None:
    try:
        with netcdf_file(nc_path, mode="r") as nc:
            rho = nc.variables["rho"]
            back = rho[:].copy()
            if back.shape != encoded.shape:
                _fail("VOXEL_NC_READBACK_FAILED", f"读回形状 {back.shape} != {encoded.shape}", http_status=500)
            if back.dtype.kind != "f" or back.dtype.itemsize != 4:
                _fail("VOXEL_NC_READBACK_FAILED", f"读回 dtype {back.dtype} 不是 float32", http_status=500)
            fill = rho._FillValue
            if not isinstance(fill, np.generic) or fill.dtype.itemsize != 4 or float(fill) != -9999.0:
                _fail("VOXEL_NC_READBACK_FAILED", f"_FillValue 类型/值异常：{fill!r}", http_status=500)
            for name, axis in zip(("x", "y", "z"), render_axes):
                axis_back = np.asarray(nc.variables[name][:], dtype=np.float64)
                if not np.allclose(axis_back, axis, rtol=1e-6, atol=1e-7):
                    _fail("VOXEL_NC_READBACK_FAILED", f"{name} 轴读回不一致", http_status=500)
                if np.any(np.diff(axis_back) <= 0):
                    _fail("VOXEL_NC_READBACK_FAILED", f"{name} 轴读回非递增", http_status=500)
            valid_back = back[valid_mask]
            valid_src = encoded[valid_mask]
            if not np.allclose(valid_back, valid_src, rtol=1e-6, atol=1e-5):
                _fail("VOXEL_NC_READBACK_FAILED", "有效值读回超出容差", http_status=500)
            if not np.all(back[~valid_mask] == np.float32(-9999.0)):
                _fail("VOXEL_NC_READBACK_FAILED", "无效体元读回后不是 -9999", http_status=500)
    except PlatformError:
        raise
    except Exception as exc:  # noqa: BLE001
        _fail("VOXEL_NC_READBACK_FAILED", f"NetCDF 读回失败：{exc}", http_status=500)


def export_supermap_voxel_netcdf(runtime: PlatformRuntime, result_id: str) -> dict[str, Any]:
    metadata, grid_path, axes, values, is_nodata = _load_grid(runtime, result_id)
    grid_sha = _sha256(grid_path)
    export_id = f"{result_id}-{grid_sha[:16]}-{_EXPORT_SUFFIX}"
    export_dir = runtime.settings.supermap_voxel_netcdf_export_dir(export_id)

    nodata_mask = is_nodata | ~np.isfinite(values)
    valid_mask = ~nodata_mask
    valid = values[valid_mask]
    if valid.size == 0:
        _fail("VOXEL_NC_NO_VALID_VALUES", "体元没有有效值", {"result_id": result_id})
    if np.any(valid.astype(np.float32) == _FILL_VALUE):
        _fail(
            "VOXEL_NC_FLOAT32_RANGE",
            "有效值与 -9999 填充值发生碰撞，无法安全编码",
            {"result_id": result_id},
        )
    value_min, value_max = float(valid.min()), float(valid.max())
    encoded = np.where(nodata_mask, _FILL_VALUE, values).astype(np.float32)
    encoded_valid = encoded[valid_mask]
    encoded_min, encoded_max = float(encoded_valid.min()), float(encoded_valid.max())

    render_x, render_y, _contract = _display_anchor_axes(
        axes[0],
        axes[1],
        anchor_lon=runtime.settings.supermap_anchor_lon,
        anchor_lat=runtime.settings.supermap_anchor_lat,
        anchor_height=runtime.settings.supermap_anchor_height,
    )
    render_z = axes[2] + runtime.settings.supermap_anchor_height
    render_axes = [render_x, render_y, render_z]
    for axis, name in zip(render_axes, ("render_x", "render_y", "render_z")):
        _validate_axis(axis, name)

    manifest: dict[str, Any] = {
        "format": "supermap-voxel-netcdf",
        "version": _EXPORTER_VERSION,
        "candidate_result_id": result_id,
        "grid_sha256": grid_sha,
        "netcdf_file": "volume.nc",
        "netcdf_version": "classic",
        "variable_name": "rho",
        "dimension_names": ["x", "y", "z"],
        "shape": [int(n) for n in values.shape],
        "dtype": "float32",
        "fill_value": -9999.0,
        "valid_count": int(valid.size),
        "nodata_count": int(nodata_mask.sum()),
        "value_range": [value_min, value_max],
        "encoded_value_range": [encoded_min, encoded_max],
        "layer_bounds_degrees": {
            "west": float(render_x[0]),
            "south": float(render_y[0]),
            "east": float(render_x[-1]),
            "north": float(render_y[-1]),
        },
        "z_bounds_metres": [float(render_z[0]), float(render_z[-1])],
        "render_coordinate_contract": _RENDER_CONTRACT,
        "geolocation_status": "display_anchor_only",
        "sdk_target": "SuperMap3D 12.1.0",
        "exporter_version": _EXPORTER_VERSION,
    }

    # 幂等：身份一致的完整产物直接复用（哈希不符则重建，保持确定性自愈）
    nc_final = export_dir / "volume.nc"
    manifest_final = export_dir / "manifest.json"
    if nc_final.is_file() and manifest_final.is_file():
        try:
            existing = json.loads(manifest_final.read_text(encoding="utf-8"))
            if (
                existing.get("candidate_result_id") == result_id
                and existing.get("grid_sha256") == grid_sha
                and existing.get("exporter_version") == _EXPORTER_VERSION
                and existing.get("netcdf_sha256") == _sha256(nc_final)
            ):
                return _result(export_id, export_dir, existing)
        except (OSError, ValueError):
            pass  # 产物损坏则落入重建分支

    export_dir.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="voxel-netcdf-", dir=export_dir.parent))
    try:
        nc_stage = stage / "volume.nc"
        units = str(metadata.get("units") or "unknown")
        _write_volume_nc(
            nc_stage,
            render_x,
            render_y,
            render_z,
            encoded,
            result_id=result_id,
            grid_sha=grid_sha,
            units=units,
            valid_min=encoded_min,
            valid_max=encoded_max,
        )
        _readback_verify(nc_stage, encoded, render_axes, valid_mask)
        manifest["netcdf_sha256"] = _sha256(nc_stage)
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False), encoding="utf-8"
        )
        manifest_sha = _sha256(stage / "manifest.json")
        (stage / "checksums.sha256").write_text(
            f"{manifest['netcdf_sha256']}  volume.nc\n{manifest_sha}  manifest.json\n",
            encoding="utf-8",
        )
        export_dir.mkdir(parents=True, exist_ok=True)
        for name in ("volume.nc", "manifest.json", "checksums.sha256"):
            shutil.copy2(stage / name, export_dir / name)  # copy2 后再校验，避免半个 .nc 暴露
        if _sha256(export_dir / "volume.nc") != manifest["netcdf_sha256"]:
            _fail("VOXEL_NC_CHECKSUM_MISMATCH", "发布后 volume.nc 校验不一致", http_status=500)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return _result(export_id, export_dir, manifest)


def _result(export_id: str, export_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "export_id": export_id,
        "candidate_result_id": manifest["candidate_result_id"],
        "grid_sha256": manifest["grid_sha256"],
        "netcdf_sha256": manifest["netcdf_sha256"],
        "manifest_url": f"/api/supermap-voxel-netcdf-exports/{export_id}/manifest",
        "netcdf_url": f"/api/supermap-voxel-netcdf-exports/{export_id}/volume.nc",
        "manifest": manifest,
    }
