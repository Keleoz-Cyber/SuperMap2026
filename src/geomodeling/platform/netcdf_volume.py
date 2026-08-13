"""Deterministic NetCDF classic/v3 volume package writer (v0.6.1 Task 6).

把校验过的规则网格（``ValidatedGrid``）写成确定性 NetCDF classic/v3 体包：

```text
volume.nc          NetCDF classic（CDF\\x01）：维度恰 x/y/z，Float32 坐标
                   x(x)/y(y)/z(z)，标量 <安全变量名>(x,y,z) Float32；
                   NoData 在属性与存储单元均为 -9999.0；
                   values[i,j,k] C 序落盘，不转置、不翻轴
manifest.json      manifest v2（身份 + 哈希 + 统计 + 显示契约）
checksums.sha256   卷内各文件 sha256sum 登记
```

同一身份永远得到逐字节相同的三个文件：内容寻址文件不含时间戳与绝对路径；
标量变量名由 ``netcdf_variable_name(property_name)`` 派生，绝不固定 ``rho``。
写入后 fsync 并回读校验（``mmap=False``，绝不触发 SciPy mmap 警告），任何
环节失败都 fail-closed，绝不把半个包交给发布层。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
from scipy.io import netcdf_file

from geomodeling.platform.errors import PlatformError
from geomodeling.platform.render_contracts import (
    DisplayAnchor,
    RenderGridSource,
    ValidatedGrid,
)
from geomodeling.platform.render_coordinates import (
    display_anchor_axes,
    display_transform_for_bounds,
    netcdf_variable_name,
    sha256_file,
)
from geomodeling.platform.schemas import FORMAT_VERSION, RENDERER

PACKAGE_VOLUME = "volume.nc"
PACKAGE_MANIFEST = "manifest.json"
PACKAGE_CHECKSUMS = "checksums.sha256"
PACKAGE_FILES = frozenset({PACKAGE_VOLUME, PACKAGE_MANIFEST})

# 本模块的错误码（与 render_assets 的本地常量同一约定；稳定公共码）
RENDER_NO_VALID_VALUES = "RENDER_NO_VALID_VALUES"
RENDER_FILL_VALUE_COLLISION = "RENDER_FILL_VALUE_COLLISION"
RENDER_NETCDF_WRITE_FAILED = "RENDER_NETCDF_WRITE_FAILED"
RENDER_NETCDF_READBACK_FAILED = "RENDER_NETCDF_READBACK_FAILED"
RENDER_ASSET_CORRUPT = "RENDER_ASSET_CORRUPT"

_FILL_VALUE = np.float32(-9999.0)
_GENERATOR = "geomodeling-platform netcdf_volume v2"
_SDK_TARGET = "SuperMap3D 12.1.0"
_RENDER_CONTRACT = "wgs84_display_anchor_v1"
_GEOLOCATION_STATUS = "display_anchor_only"


def _fsync_file(path: Path) -> None:
    # Windows 的 _commit/FlushFileBuffers 要求可写句柄，O_RDONLY 会 EBADF
    fd = os.open(path, os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_tree(root: Path) -> None:
    """整棵包目录落盘：逐文件 fsync；目录 fsync 尽力而为。

    Windows 不允许以 ``os.open`` 打开目录句柄，目录项落盘在该平台降级为
    尽力而为，绝不因此掩盖已完成的文件级 fsync。
    """

    for path in sorted(root.rglob("*")):
        if path.is_file():
            _fsync_file(path)
    try:
        _fsync_file(root)
    except OSError:
        pass


def _nc_text(value: str) -> bytes:
    """NetCDF 文本属性按 UTF-8 字节写入（scipy 仅接受 ASCII str 或字节）。"""

    return value.encode("utf-8")


def _write_volume_nc(
    nc_path: Path,
    variable_name: str,
    source: RenderGridSource,
    render_axes: tuple[np.ndarray, np.ndarray, np.ndarray],
    encoded: np.ndarray,
    encoded_min: float,
    encoded_max: float,
) -> None:
    """写 classic/v3 卷：维度恰 x/y/z，标量 (x,y,z) Float32，C 序不翻轴。"""

    render_x, render_y, render_z = render_axes
    try:
        with netcdf_file(nc_path, mode="w", version=1) as nc:
            nc.Conventions = "CF-1.8"
            nc.renderer = RENDERER
            nc.format_version = FORMAT_VERSION
            nc.source_kind = source.source_kind
            nc.source_id = _nc_text(source.source_id)
            nc.grid_sha256 = source.grid_sha256
            nc.coordinate_contract = _RENDER_CONTRACT
            nc.geolocation_status = _GEOLOCATION_STATUS
            nc.generator = _GENERATOR
            nc.createDimension("x", len(render_x))
            nc.createDimension("y", len(render_y))
            nc.createDimension("z", len(render_z))
            x_var = nc.createVariable("x", "f", ("x",))
            y_var = nc.createVariable("y", "f", ("y",))
            z_var = nc.createVariable("z", "f", ("z",))
            scalar_var = nc.createVariable(variable_name, "f", ("x", "y", "z"))
            x_var.standard_name = "longitude"
            x_var.units = "degrees_east"
            y_var.standard_name = "latitude"
            y_var.units = "degrees_north"
            z_var.standard_name = "height"
            z_var.units = "m"
            z_var.positive = "up"
            scalar_var.long_name = _nc_text(source.property_name)
            scalar_var.units = _nc_text(source.units)
            scalar_var.valid_min = np.float32(encoded_min)
            scalar_var.valid_max = np.float32(encoded_max)
            scalar_var._FillValue = _FILL_VALUE
            scalar_var.missing_value = _FILL_VALUE
            x_var[:] = np.asarray(render_x, dtype=np.float32)
            y_var[:] = np.asarray(render_y, dtype=np.float32)
            z_var[:] = np.asarray(render_z, dtype=np.float32)
            scalar_var[:] = encoded
    except Exception as exc:
        raise PlatformError(
            RENDER_NETCDF_WRITE_FAILED,
            f"NetCDF 体渲染包写入失败：{exc}",
            {"variable_name": variable_name},
            http_status=500,
        ) from exc


def _readback_verify(
    nc_path: Path,
    variable_name: str,
    encoded: np.ndarray,
    render_axes: tuple[np.ndarray, np.ndarray, np.ndarray],
    valid_mask: np.ndarray,
) -> None:
    """回读校验（``mmap=False``）：结构、填充属性、轴与有效/无效单元全部
    与写入意图一致，否则 fail-closed。"""

    try:
        with netcdf_file(nc_path, mode="r", mmap=False) as nc:
            if set(nc.dimensions) != {"x", "y", "z"}:
                raise PlatformError(
                    RENDER_NETCDF_READBACK_FAILED,
                    "回读维度集合不是恰为 x/y/z",
                    {"dimensions": sorted(map(str, nc.dimensions))},
                    http_status=500,
                )
            scalar_var = nc.variables[variable_name]
            if scalar_var.dimensions != ("x", "y", "z"):
                raise PlatformError(
                    RENDER_NETCDF_READBACK_FAILED,
                    "回读标量变量维度序不是 (x, y, z)",
                    {"dimensions": list(map(str, scalar_var.dimensions))},
                    http_status=500,
                )
            back = scalar_var[:].copy()
            if back.shape != encoded.shape:
                raise PlatformError(
                    RENDER_NETCDF_READBACK_FAILED,
                    f"回读形状 {back.shape} != {encoded.shape}",
                    http_status=500,
                )
            if back.dtype.kind != "f" or back.dtype.itemsize != 4:
                raise PlatformError(
                    RENDER_NETCDF_READBACK_FAILED,
                    f"回读 dtype {back.dtype} 不是 float32",
                    http_status=500,
                )
            fill = scalar_var._FillValue
            if (
                not isinstance(fill, np.generic)
                or fill.dtype.itemsize != 4
                or float(fill) != -9999.0
            ):
                raise PlatformError(
                    RENDER_NETCDF_READBACK_FAILED,
                    f"_FillValue 类型/值异常：{fill!r}",
                    http_status=500,
                )
            for name, axis in zip(("x", "y", "z"), render_axes, strict=True):
                axis_back = np.asarray(nc.variables[name][:], dtype=np.float64)
                reference = np.asarray(axis, dtype=np.float32).astype(np.float64)
                if not np.allclose(axis_back, reference, rtol=1e-6, atol=1e-7):
                    raise PlatformError(
                        RENDER_NETCDF_READBACK_FAILED,
                        f"{name} 轴回读与写入不一致",
                        {"axis": name},
                        http_status=500,
                    )
                if np.any(np.diff(axis_back) <= 0):
                    raise PlatformError(
                        RENDER_NETCDF_READBACK_FAILED,
                        f"{name} 轴回读非严格递增",
                        {"axis": name},
                        http_status=500,
                    )
            if not np.allclose(
                back[valid_mask], encoded[valid_mask], rtol=1e-6, atol=1e-5
            ):
                raise PlatformError(
                    RENDER_NETCDF_READBACK_FAILED,
                    "有效值回读超出容差",
                    http_status=500,
                )
            if not np.all(back[~valid_mask] == _FILL_VALUE):
                raise PlatformError(
                    RENDER_NETCDF_READBACK_FAILED,
                    "无效体元回读后不是 -9999 填充值",
                    http_status=500,
                )
    except PlatformError:
        raise
    except Exception as exc:
        raise PlatformError(
            RENDER_NETCDF_READBACK_FAILED,
            f"NetCDF 体渲染包回读校验失败：{exc}",
            http_status=500,
        ) from exc


def write_netcdf_package(
    stage_dir: Path,
    source: RenderGridSource,
    grid: ValidatedGrid,
    anchor: DisplayAnchor,
) -> dict[str, Any]:
    """Write, fsync, read back, and return the deterministic manifest."""

    values = np.asarray(grid.values, dtype=np.float64)
    is_nodata = np.asarray(grid.is_nodata, dtype=bool)
    nodata_mask = is_nodata | ~np.isfinite(values)
    valid_mask = ~nodata_mask
    valid = values[valid_mask]
    if valid.size == 0:
        raise PlatformError(
            RENDER_NO_VALID_VALUES,
            "渲染网格没有任何有限有效值（全 NoData）",
            http_status=409,
        )
    if np.any(valid.astype(np.float32) == _FILL_VALUE):
        raise PlatformError(
            RENDER_FILL_VALUE_COLLISION,
            "有效值与 -9999 填充值在 Float32 下发生碰撞，无法安全编码",
            {"property_name": source.property_name},
            http_status=409,
        )
    encoded = np.where(nodata_mask, _FILL_VALUE, values).astype(np.float32)
    encoded_valid = encoded[valid_mask]
    value_min, value_max = float(valid.min()), float(valid.max())
    encoded_min = float(encoded_valid.min())
    encoded_max = float(encoded_valid.max())

    render_x, render_y, _contract = display_anchor_axes(
        grid.axes[0], grid.axes[1], anchor
    )
    render_z = np.asarray(grid.axes[2], dtype=np.float64) + anchor.height
    variable_name = netcdf_variable_name(source.property_name)

    stage_dir.mkdir(parents=True, exist_ok=True)
    nc_path = stage_dir / PACKAGE_VOLUME
    _write_volume_nc(
        nc_path,
        variable_name,
        source,
        (render_x, render_y, render_z),
        encoded,
        encoded_min,
        encoded_max,
    )
    _fsync_file(nc_path)
    _readback_verify(
        nc_path, variable_name, encoded, (render_x, render_y, render_z), valid_mask
    )

    netcdf_sha256 = sha256_file(nc_path)
    x_axis = np.asarray(grid.axes[0], dtype=np.float64)
    y_axis = np.asarray(grid.axes[1], dtype=np.float64)
    manifest: dict[str, Any] = {
        "format": "supermap-voxel-netcdf",
        "version": FORMAT_VERSION,
        "renderer": RENDERER,
        "source_kind": source.source_kind,
        "source_id": source.source_id,
        "grid_sha256": source.grid_sha256,
        "netcdf_sha256": netcdf_sha256,
        "variable_name": variable_name,
        "property_name": source.property_name,
        "units": source.units,
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
        "display_transform": display_transform_for_bounds(
            (float(x_axis[0]), float(x_axis[-1])),
            (float(y_axis[0]), float(y_axis[-1])),
            anchor,
        ),
        "render_coordinate_contract": _RENDER_CONTRACT,
        "geolocation_status": _GEOLOCATION_STATUS,
        "sdk_target": _SDK_TARGET,
    }
    if source.field_name != "prediction":
        manifest.update(
            {
                "result_id": source.candidate_result_id,
                "field": source.field_name,
                "palette_intent": source.palette_intent,
            }
        )
    manifest_path = stage_dir / PACKAGE_MANIFEST
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _fsync_file(manifest_path)
    manifest_sha256 = sha256_file(manifest_path)
    checksums_path = stage_dir / PACKAGE_CHECKSUMS
    checksums_path.write_text(
        f"{netcdf_sha256}  {PACKAGE_VOLUME}\n{manifest_sha256}  {PACKAGE_MANIFEST}\n",
        encoding="utf-8",
    )
    _fsync_file(checksums_path)
    return manifest


def _corrupt(message: str, details: dict[str, Any] | None = None) -> PlatformError:
    return PlatformError(RENDER_ASSET_CORRUPT, message, details or {}, http_status=409)


def _parse_checksums(checksums_path: Path) -> dict[str, str]:
    try:
        text = checksums_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _corrupt("渲染资产校验清单缺失或不可读") from exc
    entries: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2:
            raise _corrupt("渲染资产校验清单行格式非法", {"line": line})
        digest, name = parts
        if len(digest) != 64 or name in entries:
            raise _corrupt("渲染资产校验清单摘要非法或条目重复", {"line": line})
        entries[name] = digest
    return entries


def read_package_manifest(package_dir: Path) -> dict[str, Any]:
    """重算 ``checksums.sha256`` 登记的卷内文件哈希并回读 manifest。

    只核验清单登记的文件（额外文件不影响包完整性）；任何缺失、哈希不符、
    manifest 不可解析或与 volume.nc 摘要交叉不一致都 fail-closed，抛
    ``RENDER_ASSET_CORRUPT``（409）。
    """

    entries = _parse_checksums(package_dir / PACKAGE_CHECKSUMS)
    if set(entries) != {PACKAGE_VOLUME, PACKAGE_MANIFEST}:
        raise _corrupt(
            "渲染资产校验清单未恰好登记 volume.nc 与 manifest.json",
            {"entries": sorted(entries)},
        )
    for name, expected in sorted(entries.items()):
        path = package_dir / name
        if not path.is_file():
            raise _corrupt("渲染资产包文件缺失", {"file": name})
        actual = sha256_file(path)
        if actual != expected:
            raise _corrupt(
                "渲染资产包文件哈希与校验清单不符",
                {"file": name, "expected_sha256": expected, "actual_sha256": actual},
            )
    try:
        manifest = json.loads(
            (package_dir / PACKAGE_MANIFEST).read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise _corrupt("渲染资产 manifest 不可解析") from exc
    if not isinstance(manifest, dict):
        raise _corrupt("渲染资产 manifest 不是 JSON 对象")
    if manifest.get("netcdf_sha256") != entries[PACKAGE_VOLUME]:
        raise _corrupt("渲染资产 manifest 的 netcdf_sha256 与校验清单不符")
    return manifest
