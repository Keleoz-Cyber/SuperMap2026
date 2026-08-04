"""Export materialized 3D grids into an iDesktopX DatasetVolume input package."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import struct
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

from geomodeling.platform.errors import PlatformError
from geomodeling.platform.results import materialize
from geomodeling.platform import PlatformRuntime

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_WGS84_SEMI_MAJOR_M = 6_378_137.0
_WGS84_ECCENTRICITY_SQUARED = 6.6943799901413165e-3
_EXPORT_VERSION = 2
_RENDER_CONTRACT = "wgs84_display_anchor_v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_axis(axis: np.ndarray, name: str) -> float:
    if axis.ndim != 1 or len(axis) < 2 or not np.all(np.isfinite(axis)):
        raise PlatformError("VOLUME_AXIS_INVALID", f"{name} 轴无效")
    delta = np.diff(axis)
    if np.any(delta <= 0):
        raise PlatformError("VOLUME_AXIS_NOT_MONOTONIC", f"{name} 轴必须严格递增")
    spacing = float(delta[0])
    if not np.allclose(delta, spacing, rtol=1e-8, atol=max(abs(spacing) * 1e-8, 1e-12)):
        raise PlatformError("VOLUME_GRID_IRREGULAR", f"{name} 轴不是等间距网格")
    return spacing


def _display_anchor_axes(
    x: np.ndarray,
    y: np.ndarray,
    *,
    anchor_lon: float,
    anchor_lat: float,
    anchor_height: float,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Map local X/Y metre offsets to a regular WGS84 display grid."""

    if not (
        math.isfinite(anchor_lon)
        and -180.0 <= anchor_lon <= 180.0
        and math.isfinite(anchor_lat)
        and -90.0 < anchor_lat < 90.0
        and math.isfinite(anchor_height)
    ):
        raise PlatformError(
            "VOLUME_DISPLAY_ANCHOR_INVALID",
            "SuperMap 显示锚点必须是有效的 WGS84 经度、纬度和高程",
            {
                "anchor_lon": anchor_lon,
                "anchor_lat": anchor_lat,
                "anchor_height": anchor_height,
            },
            http_status=500,
        )

    origin_x = float((x[0] + x[-1]) / 2.0)
    origin_y = float((y[0] + y[-1]) / 2.0)
    latitude_radians = math.radians(anchor_lat)
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
        * (prime_vertical_radius + anchor_height)
        * math.cos(latitude_radians)
    )
    metres_per_degree_lat = (
        math.pi / 180.0 * (meridian_radius + anchor_height)
    )
    render_x = anchor_lon + (x - origin_x) / metres_per_degree_lon
    render_y = anchor_lat + (y - origin_y) / metres_per_degree_lat
    if (
        np.any(render_x < -180.0)
        or np.any(render_x > 180.0)
        or np.any(render_y < -90.0)
        or np.any(render_y > 90.0)
    ):
        raise PlatformError(
            "VOLUME_RENDER_COORDINATES_INVALID",
            "显示锚点转换后的经纬度超出 WGS84 有效范围",
            http_status=409,
        )

    contract = {
        "name": _RENDER_CONTRACT,
        "epsg": 4326,
        "horizontal_unit": "Degree",
        "vertical_unit": "Meter",
        "geolocation_status": "display_anchor_only",
        "anchor": {
            "longitude": anchor_lon,
            "latitude": anchor_lat,
            "height": anchor_height,
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


def _write_geotiff(
    path: Path,
    raster: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    z: float,
    nodata: float,
) -> None:
    """Write a small, uncompressed little-endian Float64 GeoTIFF.

    The first pixel is the center at (x[0], y[-1]); half-pixel bounds are
    encoded through the tie point so GIS import does not shift the grid.
    """

    rows, cols = raster.shape
    bits = 64
    data = np.ascontiguousarray(raster.astype("<f8", copy=False))
    description = f"SuperMapDatasetVolumeZ={z:.17g}\0".encode("ascii")
    nodata_text = f"{nodata:.17g}\0".encode("ascii")
    scale = struct.pack("<3d", float(x[1] - x[0]), float(y[1] - y[0]), 1.0)
    tie = struct.pack(
        "<6d",
        0.0,
        0.0,
        0.0,
        float(x[0] - (x[1] - x[0]) / 2),
        float(y[-1] + (y[1] - y[0]) / 2),
        0.0,
    )
    geo_keys = struct.pack(
        "<20H",
        1,
        1,
        0,
        4,
        1024,
        0,
        1,
        2,
        1025,
        0,
        1,
        1,
        2048,
        0,
        1,
        4326,
        2054,
        0,
        1,
        9102,
    )

    # TIFF field type sizes: SHORT, LONG, ASCII, DOUBLE.
    entries: list[tuple[int, int, int, bytes | int]] = [
        (256, 4, 1, cols),
        (257, 4, 1, rows),
        (258, 3, 1, struct.pack("<H", bits) + b"\0\0"),
        (259, 3, 1, struct.pack("<H", 1) + b"\0\0"),
        (262, 3, 1, struct.pack("<H", 1) + b"\0\0"),
        (270, 2, len(description), description),
        (273, 4, 1, 0),  # filled after extra data offsets are known
        (277, 3, 1, struct.pack("<H", 1) + b"\0\0"),
        (278, 4, 1, rows),
        (279, 4, 1, int(data.nbytes)),
        (284, 3, 1, struct.pack("<H", 1) + b"\0\0"),
        (339, 3, 1, struct.pack("<H", 3) + b"\0\0"),  # IEEE floating point
        (33550, 12, 3, scale),
        (33922, 12, 6, tie),
        (34735, 3, 20, geo_keys),
        (42113, 2, len(nodata_text), nodata_text),
    ]
    ifd_offset = 8
    ifd_size = 2 + 12 * len(entries) + 4
    extra_offset = ifd_offset + ifd_size
    extras = bytearray()
    pointers: dict[int, int] = {}
    for tag, typ, count, value in entries:
        inline = (typ == 3 and count == 1) or (typ == 4 and count == 1)
        if inline:
            continue
        if len(extras) % 2:
            extras.extend(b"\0")
        pointers[tag] = extra_offset + len(extras)
        extras.extend(value if isinstance(value, bytes) else b"")
    if len(extras) % 2:
        extras.extend(b"\0")
    data_offset = extra_offset + len(extras)
    for index, (tag, typ, count, value) in enumerate(entries):
        if tag == 273:
            entries[index] = (tag, typ, count, data_offset)

    with path.open("wb") as handle:
        handle.write(b"II")
        handle.write(struct.pack("<H", 42))
        handle.write(struct.pack("<I", ifd_offset))
        handle.write(struct.pack("<H", len(entries)))
        for tag, typ, count, value in entries:
            handle.write(struct.pack("<HHI", tag, typ, count))
            if isinstance(value, int):
                handle.write(struct.pack("<I", value))
            elif typ in (3, 4) and count == 1:
                handle.write(value)
            else:
                handle.write(struct.pack("<I", pointers[tag]))
        handle.write(struct.pack("<I", 0))
        handle.write(extras)
        handle.write(data.tobytes(order="C"))


def _manifest_and_files(runtime: PlatformRuntime, result_id: str) -> tuple[dict[str, Any], Path]:
    if not _SAFE_ID.fullmatch(result_id):
        raise PlatformError("RESULT_ID_INVALID", "成果 ID 格式无效", {"result_id": result_id}, http_status=400)
    metadata = materialize(runtime, result_id)
    if metadata.get("dimension") != "3d":
        raise PlatformError("VOLUME_REQUIRES_3D", "只有三维成果可以导出体元包", http_status=409)
    grid_path = runtime.settings.result_grid(result_id)
    if not grid_path.is_file():
        raise PlatformError("RESULT_NOT_MATERIALIZED", "成果网格不存在", {"result_id": result_id}, http_status=409)
    with np.load(grid_path, allow_pickle=True) as bundle:
        axes = [np.asarray(axis, dtype=np.float64) for axis in bundle["axes"]]
        values = np.asarray(bundle["values"], dtype=np.float64)
        is_nodata = np.asarray(bundle["is_nodata"], dtype=bool)
    if len(axes) != 3 or values.ndim != 3 or is_nodata.shape != values.shape:
        raise PlatformError("VOLUME_GRID_INVALID", "三维网格工件形状无效", http_status=409)
    spacings = [_validate_axis(axis, name) for axis, name in zip(axes, ("x", "y", "z"))]
    if values.shape != tuple(len(axis) for axis in axes):
        raise PlatformError("VOLUME_GRID_SHAPE_MISMATCH", "网格形状与坐标轴不匹配", http_status=409)
    valid = values[~is_nodata & np.isfinite(values)]
    if valid.size == 0:
        raise PlatformError("VOLUME_NO_VALID_VALUES", "体元没有有效值", http_status=409)
    minimum, maximum = float(valid.min()), float(valid.max())
    sentinel = minimum - max(1.0, abs(minimum) * 0.01)
    while sentinel >= minimum:
        sentinel = math.nextafter(sentinel, -math.inf)
    grid_sha = _sha256(grid_path)
    render_x, render_y, render_contract = _display_anchor_axes(
        axes[0],
        axes[1],
        anchor_lon=runtime.settings.supermap_anchor_lon,
        anchor_lat=runtime.settings.supermap_anchor_lat,
        anchor_height=runtime.settings.supermap_anchor_height,
    )
    render_z = axes[2] + runtime.settings.supermap_anchor_height
    render_spacings = [
        _validate_axis(render_x, "render_longitude"),
        _validate_axis(render_y, "render_latitude"),
        spacings[2],
    ]
    manifest: dict[str, Any] = {
        "format": "supermap-volume",
        "version": _EXPORT_VERSION,
        "candidate_result_id": result_id,
        "grid_sha256": grid_sha,
        "dataset_version_id": metadata.get("dataset_version_id"),
        "dimension": 3,
        "axes": ["x", "y", "z"],
        "coordinate_contract": _RENDER_CONTRACT,
        "model_coordinate_contract": {
            "name": "local_engineering_m_v1",
            "horizontal_unit": "Meter",
            "vertical_unit": "Meter",
            "axis_nodes": [len(axis) for axis in axes],
            "axis_min": [float(axis[0]) for axis in axes],
            "axis_max": [float(axis[-1]) for axis in axes],
            "axis_spacing": spacings,
        },
        "render_coordinate_contract": render_contract,
        "geolocation_status": "display_anchor_only",
        "axis_nodes": [len(axis) for axis in axes],
        "axis_min": [float(render_x[0]), float(render_y[0]), float(render_z[0])],
        "axis_max": [float(render_x[-1]), float(render_y[-1]), float(render_z[-1])],
        "axis_spacing": render_spacings,
        "shape": list(values.shape),
        "nodata": sentinel,
        "value_range": [minimum, maximum],
        "pixel_center_semantics": True,
        "slices": [],
    }
    return manifest, (grid_path, [render_x, render_y, render_z], values, is_nodata)


def export_supermap_volume(runtime: PlatformRuntime, result_id: str) -> dict[str, Any]:
    manifest, payload = _manifest_and_files(runtime, result_id)
    grid_path, axes, values, is_nodata = payload
    export_id = (
        f"{result_id}-{manifest['grid_sha256'][:16]}-{_RENDER_CONTRACT}"
    )
    package_path = runtime.settings.supermap_volume_package(export_id)
    package_path.parent.mkdir(parents=True, exist_ok=True)
    if package_path.is_file():
        manifest_path = package_path.parent / "manifest.json"
        if manifest_path.is_file():
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                existing.get("candidate_result_id") == manifest["candidate_result_id"]
                and existing.get("grid_sha256") == manifest["grid_sha256"]
                and existing.get("version") == _EXPORT_VERSION
                and existing.get("coordinate_contract") == _RENDER_CONTRACT
            ):
                return _result(export_id, package_path, existing)

    stage = Path(tempfile.mkdtemp(prefix="supermap-volume-", dir=package_path.parent))
    try:
        slices_dir = stage / "slices"
        slices_dir.mkdir()
        for index, z in enumerate(axes[2]):
            name = f"z_{index:04d}.tif"
            slice_path = slices_dir / name
            raster = values[:, :, index].T[::-1, :]
            mask = is_nodata[:, :, index].T[::-1, :]
            raster = np.where(mask | ~np.isfinite(raster), manifest["nodata"], raster)
            _write_geotiff(slice_path, raster, axes[0], axes[1], float(z), manifest["nodata"])
            manifest["slices"].append(
                {
                    "index": index,
                    "z": float(z),
                    "file": f"slices/{name}",
                    "sha256": _sha256(slice_path),
                    "rows": int(raster.shape[0]),
                    "columns": int(raster.shape[1]),
                }
            )
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        checksums = ["{}  {}".format(_sha256(stage / "manifest.json"), "manifest.json")]
        checksums.extend("{}  {}".format(item["sha256"], item["file"]) for item in manifest["slices"])
        (stage / "checksums.sha256").write_text("\n".join(checksums) + "\n", encoding="utf-8")
        (stage / "README.md").write_text(
            "# SuperMap DatasetVolume 导入包\n\n"
            "按 manifest 的 z 顺序导入 `slices/`，再构建 DatasetVolume。\n"
            "GeoTIFF 已包含 EPSG:4326 坐标标签；不要再次投影，也不要重新插值。\n"
            "该位置由固定 ENU 显示锚点生成，`geolocation_status` 为 "
            "`display_anchor_only`，不代表真实地理配准。\n",
            encoding="utf-8",
        )
        tmp_zip = stage / "supermap-volume.zip"
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in [stage / "manifest.json", stage / "checksums.sha256", stage / "README.md", *sorted(slices_dir.iterdir())]:
                archive.write(path, path.relative_to(stage).as_posix())
        package_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tmp_zip, package_path)
        for source in (stage / "manifest.json", stage / "checksums.sha256"):
            shutil.copy2(source, package_path.parent / source.name)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return _result(export_id, package_path, manifest)


def _result(export_id: str, package_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "export_id": export_id,
        "candidate_result_id": manifest["candidate_result_id"],
        "grid_sha256": manifest["grid_sha256"],
        "manifest_sha256": _sha256(package_path.parent / "manifest.json"),
        "package_sha256": _sha256(package_path),
        "download_url": f"/api/supermap-volume-exports/{export_id}/download",
        "manifest": manifest,
    }
