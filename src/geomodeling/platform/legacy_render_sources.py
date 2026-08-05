"""Authoritative legacy regular-grid registration and read-only lookup (v0.6.1 Task 5).

仓库不含内置电阻率案例的权威全网格工件；本模块是唯一被接受的桥梁：对供给的
CSV 做哈希与登记，绝不重跑 Kriging、绝不从散点重新推导正式网格。

导入是原子的：

1. pandas 读 CSV，要求每个笛卡尔格点恰好一行；
2. X/Y/Z 唯一轴升序，逐轴校验近似等距（不规则轴拒收）；
3. 按索引填充 ``values[ix, iy, iz]``——无转置、无 Y 翻转；
4. 同级暂存目录写 ``grid.npz`` + ``metadata.json``，回读校验形状/值/哈希；
5. 原子改名为 ``render-sources/builtin_legacy/<source_id>/<grid_sha256>/``；
6. 原子写 ``current.json``——只含 source ID、grid SHA、相对工件目录、
   property、units、shape、导入源 SHA，绝无绝对输入路径。

不同网格覆盖已登记网格一律拒绝（``LEGACY_RENDER_SOURCE_CONFLICT``）；网格
内容相同的重导入幂等返回既有登记。``resolve_legacy_render_source`` 是纯查询：
绝不创建文件、绝不改写登记状态。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from geomodeling.platform.db import PlatformRuntime
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.render_contracts import RenderGridSource
from geomodeling.platform.render_coordinates import sha256_file

LEGACY_IMPORT_PARSE_FAILED = "LEGACY_IMPORT_PARSE_FAILED"
LEGACY_IMPORT_COLUMN_NOT_FOUND = "LEGACY_IMPORT_COLUMN_NOT_FOUND"
LEGACY_IMPORT_COORDINATE_INVALID = "LEGACY_IMPORT_COORDINATE_INVALID"
LEGACY_IMPORT_DUPLICATE_COORDINATES = "LEGACY_IMPORT_DUPLICATE_COORDINATES"
LEGACY_IMPORT_GRID_INCOMPLETE = "LEGACY_IMPORT_GRID_INCOMPLETE"
LEGACY_IMPORT_AXIS_IRREGULAR = "LEGACY_IMPORT_AXIS_IRREGULAR"
LEGACY_RENDER_SOURCE_CONFLICT = "LEGACY_RENDER_SOURCE_CONFLICT"
LEGACY_RENDER_SOURCE_NOT_REGISTERED = "LEGACY_RENDER_SOURCE_NOT_REGISTERED"
LEGACY_RENDER_SOURCE_STATE_INVALID = "LEGACY_RENDER_SOURCE_STATE_INVALID"

SOURCE_KIND = "builtin_legacy"
# 内置 legacy 案例坐标是局部投影平面坐标（与候选 profile 的 local_linear 同义）
LEGACY_COORDINATE_KIND = "local_linear"

# 与 render_assets._validate_axis 同一容差方案：节点即 linspace，允许浮点回算误差
_REGULAR_RTOL = 1e-6
_REGULAR_ATOL_SCALE = 1e-9


@dataclass(frozen=True)
class LegacyRenderSourceRecord:
    """一次 legacy 网格登记的内部记录（序列化白名单见 render_cli 输出）。"""

    source_kind: str
    source_id: str
    grid_sha256: str
    property_name: str
    units: str
    shape: list[int]
    artifact_dir: str
    import_source_sha256: str


def _source_root(runtime: PlatformRuntime, source_id: str) -> Path:
    return runtime.settings.render_sources_dir / SOURCE_KIND / source_id


def _read_csv(csv_path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(csv_path, encoding="utf-8-sig")
    except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise PlatformError(
            LEGACY_IMPORT_PARSE_FAILED,
            f"legacy 网格 CSV 解析失败：{exc}",
            http_status=422,
        ) from exc


def _numeric_column(frame: pd.DataFrame, column: str, role: str) -> np.ndarray:
    if column not in frame.columns:
        raise PlatformError(
            LEGACY_IMPORT_COLUMN_NOT_FOUND,
            f"{role} 列在 CSV 中不存在：{column}",
            {"column": column, "columns": [str(name) for name in frame.columns]},
            http_status=422,
        )
    return pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype="float64")


def _validate_axis(axis: np.ndarray, name: str) -> np.ndarray:
    """单轴校验：≥2 节点、严格递增、近似等距（否则不是规则渲染网格）。"""

    if axis.size < 2 or not np.all(np.diff(axis) > 0):
        raise PlatformError(
            LEGACY_IMPORT_AXIS_IRREGULAR,
            f"legacy 网格 {name} 轴必须不少于 2 个节点且严格递增",
            {"axis": name, "node_count": int(axis.size)},
            http_status=422,
        )
    span = float(axis[-1] - axis[0])
    reference = np.linspace(axis[0], axis[-1], axis.size)
    tolerance = (_REGULAR_RTOL + _REGULAR_ATOL_SCALE) * max(1.0, span)
    if not np.all(np.abs(axis - reference) <= tolerance):
        raise PlatformError(
            LEGACY_IMPORT_AXIS_IRREGULAR,
            f"legacy 网格 {name} 轴不是近似等距的规则轴",
            {"axis": name},
            http_status=422,
        )
    return axis


def _build_grid(
    frame: pd.DataFrame,
    *,
    x_column: str,
    y_column: str,
    z_column: str,
    value_column: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """校验行列完备性并返回 (x_axis, y_axis, z_axis, values[ix,iy,iz])。"""

    x = _numeric_column(frame, x_column, "X 坐标")
    y = _numeric_column(frame, y_column, "Y 坐标")
    z = _numeric_column(frame, z_column, "Z 坐标")
    values = _numeric_column(frame, value_column, "属性值")

    coordinates = np.column_stack([x, y, z])
    if not np.all(np.isfinite(coordinates)):
        raise PlatformError(
            LEGACY_IMPORT_COORDINATE_INVALID,
            "legacy 网格坐标必须全部是有限数值",
            {"row_count": len(frame)},
            http_status=422,
        )
    if frame.duplicated(subset=[x_column, y_column, z_column]).any():
        raise PlatformError(
            LEGACY_IMPORT_DUPLICATE_COORDINATES,
            "legacy 网格存在重复坐标元组",
            {"row_count": len(frame)},
            http_status=422,
        )

    x_axis = _validate_axis(np.unique(x), "x")
    y_axis = _validate_axis(np.unique(y), "y")
    z_axis = _validate_axis(np.unique(z), "z")
    expected_cells = int(x_axis.size * y_axis.size * z_axis.size)
    if len(frame) != expected_cells:
        raise PlatformError(
            LEGACY_IMPORT_GRID_INCOMPLETE,
            "legacy 网格缺失笛卡尔格点：每个格点必须恰好一行",
            {
                "row_count": len(frame),
                "expected_cells": expected_cells,
                "shape": [int(x_axis.size), int(y_axis.size), int(z_axis.size)],
            },
            http_status=422,
        )

    shape = (int(x_axis.size), int(y_axis.size), int(z_axis.size))
    grid = np.full(shape, np.nan, dtype="float64")
    ix = np.searchsorted(x_axis, x)
    iy = np.searchsorted(y_axis, y)
    iz = np.searchsorted(z_axis, z)
    grid[ix, iy, iz] = values
    return x_axis, y_axis, z_axis, grid


def _write_json_atomic(target: Path, payload: dict) -> None:
    """同级临时文件写入后原子替换；目标绝不出现半写状态。"""

    fd, tmp_name = tempfile.mkstemp(prefix=".current-", suffix=".json", dir=target.parent)
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _read_current(source_root: Path, source_id: str) -> dict | None:
    current_path = source_root / "current.json"
    if not current_path.is_file():
        return None
    try:
        payload = json.loads(current_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlatformError(
            LEGACY_RENDER_SOURCE_STATE_INVALID,
            "legacy 渲染源登记状态损坏，请先人工核查 render-sources 目录",
            {"source_id": source_id},
            http_status=409,
        ) from exc
    return payload


def _record_from_current(source_id: str, current: dict) -> LegacyRenderSourceRecord:
    return LegacyRenderSourceRecord(
        source_kind=SOURCE_KIND,
        source_id=source_id,
        grid_sha256=current["grid_sha256"],
        property_name=current["property_name"],
        units=current["units"],
        shape=list(current["shape"]),
        artifact_dir=current["artifact_dir"],
        import_source_sha256=current["import_source_sha256"],
    )


def import_legacy_grid(
    runtime: PlatformRuntime,
    *,
    source_id: str,
    csv_path: Path,
    x_column: str,
    y_column: str,
    z_column: str,
    value_column: str,
    property_name: str,
    units: str,
) -> LegacyRenderSourceRecord:
    """把权威 CSV 原子登记为内置 legacy 规则网格渲染源。

    拒收重复坐标、缺失笛卡尔格点、不规则轴、非有限坐标，以及覆盖不同已登记
    网格；网格内容相同的重导入幂等返回既有登记。任何失败都不留登记状态。
    """

    import_source_sha256 = sha256_file(csv_path)
    frame = _read_csv(csv_path)
    x_axis, y_axis, z_axis, values = _build_grid(
        frame,
        x_column=x_column,
        y_column=y_column,
        z_column=z_column,
        value_column=value_column,
    )
    shape = [int(x_axis.size), int(y_axis.size), int(z_axis.size)]
    is_nodata = ~np.isfinite(values)

    source_root = _source_root(runtime, source_id)
    source_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".import-", dir=source_root))
    try:
        grid_path = stage / "grid.npz"
        np.savez_compressed(
            grid_path,
            axes=np.array((x_axis, y_axis, z_axis), dtype=object),
            values=values,
            is_nodata=is_nodata,
        )
        grid_sha256 = sha256_file(grid_path)
        metadata = {
            "source_kind": SOURCE_KIND,
            "source_id": source_id,
            "property_name": property_name,
            "units": units,
            "coordinate_kind": LEGACY_COORDINATE_KIND,
            "dimension": "3d",
            "shape": shape,
            "grid_sha256": grid_sha256,
            "import_source_sha256": import_source_sha256,
        }
        (stage / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 回读校验：形状/值/哈希必须与暂存写入一致
        with np.load(grid_path, allow_pickle=True) as probe:
            reread_values = np.asarray(probe["values"], dtype="float64")
            if list(reread_values.shape) != shape:
                raise PlatformError(
                    LEGACY_RENDER_SOURCE_STATE_INVALID,
                    "legacy 网格回读形状与写入不一致",
                    {"expected_shape": shape, "actual_shape": list(reread_values.shape)},
                    http_status=500,
                )
            if not np.array_equal(reread_values, values, equal_nan=True):
                raise PlatformError(
                    LEGACY_RENDER_SOURCE_STATE_INVALID,
                    "legacy 网格回读数值与写入不一致",
                    http_status=500,
                )

        current = _read_current(source_root, source_id)
        if current is not None and current.get("grid_sha256") != grid_sha256:
            raise PlatformError(
                LEGACY_RENDER_SOURCE_CONFLICT,
                "已登记不同的 legacy 渲染网格，拒绝覆盖",
                {
                    "source_id": source_id,
                    "registered_grid_sha256": current.get("grid_sha256"),
                    "import_grid_sha256": grid_sha256,
                },
                http_status=409,
            )

        artifact_dir = f"{SOURCE_KIND}/{source_id}/{grid_sha256}"
        final_dir = runtime.settings.render_sources_dir / artifact_dir
        if final_dir.exists():
            # 同网格重导入：内容寻址目录已在位，校验身份后复用
            existing_sha256 = sha256_file(final_dir / "grid.npz")
            if existing_sha256 != grid_sha256:
                raise PlatformError(
                    LEGACY_RENDER_SOURCE_STATE_INVALID,
                    "legacy 渲染源工件目录身份与登记哈希不符",
                    {"source_id": source_id, "grid_sha256": grid_sha256},
                    http_status=409,
                )
        else:
            os.replace(stage, final_dir)

        if current is not None:
            # 同网格重导入幂等：返回既有登记记录，不改写任何登记状态
            return _record_from_current(source_id, current)
        _write_json_atomic(
            source_root / "current.json",
            {
                "source_id": source_id,
                "grid_sha256": grid_sha256,
                "artifact_dir": artifact_dir,
                "property_name": property_name,
                "units": units,
                "shape": shape,
                "import_source_sha256": import_source_sha256,
            },
        )
        return LegacyRenderSourceRecord(
            source_kind=SOURCE_KIND,
            source_id=source_id,
            grid_sha256=grid_sha256,
            property_name=property_name,
            units=units,
            shape=shape,
            artifact_dir=artifact_dir,
            import_source_sha256=import_source_sha256,
        )
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def resolve_legacy_render_source(runtime: PlatformRuntime, source_id: str) -> RenderGridSource:
    """只读解析已登记的 legacy 渲染源；未登记 fail-closed，绝不创建任何文件。"""

    current = _read_current(_source_root(runtime, source_id), source_id)
    if current is None:
        raise PlatformError(
            LEGACY_RENDER_SOURCE_NOT_REGISTERED,
            "内置案例尚未登记权威规则网格，请先运行 render-grid import-csv",
            {"source_id": source_id},
            http_status=404,
        )
    record = _record_from_current(source_id, current)
    return RenderGridSource(
        source_kind=SOURCE_KIND,
        source_id=source_id,
        grid_path=runtime.settings.render_sources_dir / record.artifact_dir / "grid.npz",
        grid_sha256=record.grid_sha256,
        property_name=record.property_name,
        units=record.units,
        coordinate_kind=LEGACY_COORDINATE_KIND,
        dimension="3d",
    )
