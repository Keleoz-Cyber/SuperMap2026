"""Candidate render-source resolution and regular-grid validation (v0.6.1 Task 4).

解析候选成果的渲染源：沿归属链 ``candidate -> run -> experiment ->
dataset_version.profile_json`` 取 ``mapping.value_name`` / ``mapping.value_unit``
/ ``mapping.coordinate_kind``——**不固定 rho 语义**；单位缺失才回退字面
``"unknown"``。老 metadata 缺 property 字段仍可解析（语义来自数据集 profile，
绝不改写既有工件）。

除 ``create_render_asset`` 外的查询函数都是纯查询：绝不物化成果、绝不创建文件、
绝不改写数据库行。规则网格校验 fail-closed，错误码稳定（非 3D / 轴非法 /
轴不规则 / 形状不符 / 全 NoData / 登记哈希与实际文件哈希不符）。

``create_render_asset``（Task 6）是唯一变更入口：隐藏 stage
（``render-assets/.{asset_id}-*``）写齐 + fsync → ``os.replace`` 单点改名 →
``mark_ready``。rename 前 final 目录绝不可见、DB 绝不 ready；既存 final 目录
按期望身份核验——有效复用、无效原子隔离为 ``<asset-id>.corrupt-<uuid>``。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from geomodeling.platform import tables
from geomodeling.platform.errors import (
    CANDIDATE_NOT_FOUND,
    DATASET_NOT_FOUND,
    PlatformError,
)
from geomodeling.platform.netcdf_volume import (
    RENDER_ASSET_CORRUPT,
    fsync_tree,
    read_package_manifest,
    write_netcdf_package,
)
from geomodeling.platform.ml_artifacts import (
    load_ml_field,
    read_ml_fields_manifest,
)
from geomodeling.platform.render_contracts import (
    DisplayAnchor,
    RenderGridSource,
    ValidatedGrid,
)
from geomodeling.platform.render_profiles import build_render_profile
from geomodeling.platform.render_coordinates import (
    display_transform_for_bounds,
    sha256_file,
)
from geomodeling.platform.repositories import RenderAssetRepository
from geomodeling.platform.schemas import (
    FORMAT_VERSION,
    RENDERER,
    STATUS_CREATING,
    STATUS_READY,
    RenderAssetRecord,
)

# 同包私有复用（与 professional 复用 results 原子写助手同款约定）
from geomodeling.platform.results import (
    CANDIDATE_NOT_SUCCEEDED,
    RESULT_ARTIFACT_INVALID,
    RESULT_NOT_MATERIALIZED,
    _load_candidate,
    _mapping_property_semantics,
)

RENDER_REQUIRES_3D = "RENDER_REQUIRES_3D"
RENDER_AXIS_INVALID = "RENDER_AXIS_INVALID"
RENDER_GRID_IRREGULAR = "RENDER_GRID_IRREGULAR"
RENDER_GRID_SHAPE_MISMATCH = "RENDER_GRID_SHAPE_MISMATCH"
RENDER_NO_VALID_VALUES = "RENDER_NO_VALID_VALUES"
RENDER_GRID_IDENTITY_MISMATCH = "RENDER_GRID_IDENTITY_MISMATCH"
RENDER_ASSET_IN_PROGRESS = "RENDER_ASSET_IN_PROGRESS"
RENDER_ASSET_PUBLISH_FAILED = "RENDER_ASSET_PUBLISH_FAILED"
ML_FIELD_NOT_AVAILABLE = "ML_FIELD_NOT_AVAILABLE"

ML_RENDER_FIELDS = (
    "prediction",
    "model_dispersion",
    "kriging_baseline",
    "residual_correction",
)

# 近似规则网格判定（与 modeling/grid.py 的 derive_grid 落盘轴一致：节点即
# linspace，允许浮点回算误差）：每轴与首尾等距参考轴比较，容差随轴跨度缩放。
_REGULAR_RTOL = 1e-6
_REGULAR_ATOL_SCALE = 1e-9


@dataclass(frozen=True)
class RenderCapability:
    """候选渲染能力（设计 §2.3 响应的内部形态；路由层再序列化为公共 DTO）。

    ``render_profile``（v0.7.0 第二批）由已验证网格的有效值域与来源类型
    推导；不支持时为 None，绝不由前端猜测。
    """

    source_kind: str
    source_id: str
    supported: bool
    reason_code: str | None
    reason: str | None
    dimension: str | None
    grid_kind: str | None
    property_name: str | None
    units: str | None
    geolocation_status: str
    display_transform: dict[str, Any] | None
    render_profile: dict[str, Any] | None = None


def _validate_axis(axis: np.ndarray, name: str) -> np.ndarray:
    """单轴校验：≥2 节点、有限、严格递增（RENDER_AXIS_INVALID）、近似等距
    （RENDER_GRID_IRREGULAR）。"""

    array = np.asarray(axis, dtype="float64")
    if (
        array.ndim != 1
        or array.size < 2
        or not np.all(np.isfinite(array))
        or not np.all(np.diff(array) > 0)
    ):
        raise PlatformError(
            RENDER_AXIS_INVALID,
            f"渲染网格 {name} 轴必须是不少于 2 个节点、有限且严格递增的一维坐标",
            {"axis": name},
            http_status=409,
        )
    span = float(array[-1] - array[0])
    reference = np.linspace(array[0], array[-1], array.size)
    tolerance = (_REGULAR_RTOL + _REGULAR_ATOL_SCALE) * max(1.0, span)
    if not np.all(np.abs(array - reference) <= tolerance):
        raise PlatformError(
            RENDER_GRID_IRREGULAR,
            f"渲染网格 {name} 轴不是近似等距的规则轴",
            {"axis": name},
            http_status=409,
        )
    return array


def validate_regular_grid(grid_path: Path, expected_sha256: str) -> ValidatedGrid:
    """校验落盘 grid.npz 并返回有效值统计。

    顺序即防线：登记哈希 == 实际文件哈希（RENDER_GRID_IDENTITY_MISMATCH）→
    三轴各自合法且近似规则 → values/is_nodata 形状与轴长度一致
    （RENDER_GRID_SHAPE_MISMATCH）→ 至少一个有限有效值（RENDER_NO_VALID_VALUES）。
    """

    actual_sha256 = sha256_file(grid_path)
    if actual_sha256 != expected_sha256:
        raise PlatformError(
            RENDER_GRID_IDENTITY_MISMATCH,
            "渲染网格实际文件哈希与登记哈希不符",
            {"expected_sha256": expected_sha256, "actual_sha256": actual_sha256},
            http_status=409,
        )
    with np.load(grid_path, allow_pickle=True) as bundle:
        axes = tuple(np.asarray(a, dtype="float64") for a in bundle["axes"])
        values = np.asarray(bundle["values"], dtype="float64")
        is_nodata = np.asarray(bundle["is_nodata"], dtype=bool)
    return validate_grid_arrays(axes, values, is_nodata)


def validate_grid_arrays(
    axes: tuple[np.ndarray, ...], values: np.ndarray, is_nodata: np.ndarray
) -> ValidatedGrid:
    """Validate in-memory arrays using the same regular-grid contract."""

    if len(axes) != 3:
        raise PlatformError(
            RENDER_REQUIRES_3D,
            "原生体渲染要求三维成果网格",
            {"axis_count": len(axes)},
            http_status=409,
        )
    checked_axes = tuple(
        _validate_axis(axis, name)
        for axis, name in zip(axes, ("x", "y", "z"), strict=True)
    )
    expected_shape = tuple(axis.size for axis in checked_axes)
    if values.shape != expected_shape or is_nodata.shape != expected_shape:
        raise PlatformError(
            RENDER_GRID_SHAPE_MISMATCH,
            "渲染网格 values/is_nodata 形状与轴长度不一致",
            {
                "expected_shape": list(expected_shape),
                "values_shape": list(values.shape),
                "is_nodata_shape": list(is_nodata.shape),
            },
            http_status=409,
        )
    valid = values[~is_nodata]
    finite = valid[np.isfinite(valid)]
    if finite.size == 0:
        raise PlatformError(
            RENDER_NO_VALID_VALUES,
            "渲染网格没有任何有限有效值（全 NoData）",
            http_status=409,
        )
    return ValidatedGrid(
        axes=checked_axes,
        values=values,
        is_nodata=is_nodata,
        valid_min=float(finite.min()),
        valid_max=float(finite.max()),
    )


def _trace_candidate(runtime, result_id: str):
    """candidate -> run -> experiment -> dataset_version.profile_json 归属链核验。"""

    candidate, _, experiment = _load_candidate(runtime, result_id)
    params = tables.loads_canonical(experiment.params_json)
    dataset_version_id = params["dataset_version_id"]
    with runtime.session() as session:
        dataset = session.get(tables.DatasetVersion, dataset_version_id)
    if dataset is None:
        raise PlatformError(
            DATASET_NOT_FOUND,
            "成果所属数据版本缺失，归属链不完整",
            {"result_id": result_id, "dataset_version_id": dataset_version_id},
            http_status=409,
        )
    return candidate, experiment, tables.loads_canonical(dataset.profile_json)


def _resolve_candidate_grid(
    runtime, result_id: str
) -> tuple[RenderGridSource, ValidatedGrid]:
    candidate, _, profile = _trace_candidate(runtime, result_id)
    if candidate.status != "succeeded":
        raise PlatformError(
            CANDIDATE_NOT_SUCCEEDED,
            "只有成功候选可以作为渲染源",
            {"result_id": result_id, "status": candidate.status},
            http_status=409,
        )
    semantics = _mapping_property_semantics(profile)
    grid_path = runtime.settings.result_grid(result_id)
    metadata_path = grid_path.parent / "metadata.json"
    if not grid_path.is_file() or not metadata_path.is_file():
        raise PlatformError(
            RESULT_NOT_MATERIALIZED,
            "成果尚未生成，请先调用 materialize",
            {"result_id": result_id},
            http_status=404,
        )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("dimension") != "3d":
        raise PlatformError(
            RENDER_REQUIRES_3D,
            "原生体渲染要求三维成果网格",
            {"result_id": result_id, "dimension": metadata.get("dimension")},
            http_status=409,
        )
    grid_sha256 = metadata.get("grid_sha256")
    if not grid_sha256:
        raise PlatformError(
            RESULT_ARTIFACT_INVALID,
            "成果 metadata 缺少 grid_sha256，网格身份无法核验",
            {"result_id": result_id},
            http_status=409,
        )
    grid = validate_regular_grid(grid_path, grid_sha256)
    source = RenderGridSource(
        source_kind="candidate_result",
        source_id=result_id,
        grid_path=grid_path,
        grid_sha256=grid_sha256,
        property_name=semantics["property_name"],
        units=semantics["units"],
        coordinate_kind=semantics["coordinate_kind"],
        dimension="3d",
        candidate_result_id=result_id,
    )
    return source, grid


def _ml_field_error(field: str, *, unavailable: bool) -> PlatformError:
    return PlatformError(
        ML_FIELD_NOT_AVAILABLE,
        "该成果不提供请求的机器学习字段" if unavailable else "不支持的机器学习字段",
        {"field": field, "available_fields": list(ML_RENDER_FIELDS)},
        http_status=409 if unavailable else 422,
    )


def resolve_candidate_render_source(
    runtime, result_id: str, *, field: str = "prediction"
) -> RenderGridSource:
    """解析候选成果的渲染源（纯查询：绝不物化、绝不创建文件、绝不改行）。"""

    if field not in ML_RENDER_FIELDS:
        raise _ml_field_error(field, unavailable=False)
    source, main_grid = _resolve_candidate_grid(runtime, result_id)
    if field == "prediction":
        return source

    directory = source.grid_path.parent
    try:
        manifest = read_ml_fields_manifest(
            directory, expected_grid_sha256=source.grid_sha256
        )
    except PlatformError as exc:
        if not (directory / "ml_fields.json").is_file():
            raise _ml_field_error(field, unavailable=True) from exc
        raise
    details = manifest.get("fields", {}).get(field)
    if not isinstance(details, dict):
        raise _ml_field_error(field, unavailable=True)
    values, is_nodata = load_ml_field(
        directory, field, expected_grid_sha256=source.grid_sha256
    )
    grid = validate_grid_arrays(main_grid.axes, values, is_nodata)
    property_suffix = {
        "model_dispersion": "模型离散度",
        "kriging_baseline": "克里金基线",
        "residual_correction": "残差校正",
    }[field]
    return RenderGridSource(
        source_kind="candidate_result",
        source_id=f"{result_id}::{field}",
        grid_path=directory / "ml_fields.npz",
        grid_sha256=str(details["sha256"]),
        property_name=f"{source.property_name} {property_suffix}",
        units=str(details.get("unit") or source.units),
        coordinate_kind=source.coordinate_kind,
        dimension="3d",
        candidate_result_id=result_id,
        field_name=field,
        palette_intent=str(details.get("palette_intent") or "property_default"),
        validated_grid=grid,
    )


def _best_effort_semantics(runtime, result_id: str):
    """能力报告的尽力语义回填：归属链可解析则取 profile 维度/属性，否则 None。"""

    try:
        _, _, profile = _trace_candidate(runtime, result_id)
    except PlatformError:
        return None, None, None
    mapping = profile.get("mapping", {}) if isinstance(profile, dict) else {}
    semantics = _mapping_property_semantics(profile)
    return mapping.get("dimension"), semantics["property_name"], semantics["units"]


def candidate_render_capability(
    runtime, result_id: str, *, field: str = "prediction"
) -> RenderCapability:
    """候选渲染能力（纯查询：不物化、不创建文件、不改行）。

    解析失败报告 ``supported=False`` + 稳定 ``reason_code``（2D、未物化、网格
    非法等）；候选不存在仍按 ``CANDIDATE_NOT_FOUND``（404）抛出。
    """

    anchor = DisplayAnchor()
    try:
        source = resolve_candidate_render_source(runtime, result_id, field=field)
        grid = source.validated_grid or validate_regular_grid(
            source.grid_path, source.grid_sha256
        )
    except PlatformError as exc:
        if exc.code == CANDIDATE_NOT_FOUND:
            raise
        dimension, property_name, units = _best_effort_semantics(runtime, result_id)
        return RenderCapability(
            source_kind="candidate_result",
            source_id=result_id if field == "prediction" else f"{result_id}::{field}",
            supported=False,
            reason_code=exc.code,
            reason=exc.message,
            dimension=dimension,
            grid_kind=None,
            property_name=property_name,
            units=units,
            geolocation_status=anchor.geolocation_status,
            display_transform=None,
        )
    x_axis, y_axis = grid.axes[0], grid.axes[1]
    transform = display_transform_for_bounds(
        (float(x_axis[0]), float(x_axis[-1])),
        (float(y_axis[0]), float(y_axis[-1])),
        anchor,
    )
    valid_min, valid_max = grid.valid_min, grid.valid_max
    if source.palette_intent == "diverging_zero_centered":
        magnitude = max(abs(valid_min), abs(valid_max))
        valid_min, valid_max = -magnitude, magnitude
    profile = build_render_profile(
        "candidate_result",
        valid_min,
        valid_max,
        property_name=source.property_name,
        unit=source.units,
    ).to_public()
    if source.palette_intent == "diverging_zero_centered":
        profile["default_palette"] = "coolwarm"
        profile["default_scale"] = "linear"
        profile["log_available"] = False
    elif source.palette_intent == "sequential_nonnegative":
        profile["default_palette"] = "viridis"
        profile["default_scale"] = "linear"
    return RenderCapability(
        source_kind="candidate_result",
        source_id=source.source_id,
        supported=True,
        reason_code=None,
        reason=None,
        dimension=source.dimension,
        grid_kind="regular",
        property_name=source.property_name,
        units=source.units,
        geolocation_status=anchor.geolocation_status,
        display_transform=transform,
        render_profile=profile,
    )


# ---------------------------------------------------------------------------
# Task 6: 原子目录发布（唯一变更入口）
# ---------------------------------------------------------------------------


def _require_package_identity(
    manifest: dict[str, Any],
    *,
    source_kind: str,
    source_id: str,
    grid_sha256: str,
    netcdf_sha256: str | None,
    context: dict[str, Any],
) -> None:
    """manifest 身份字段与期望逐一比对；任何不符按 RENDER_ASSET_CORRUPT 失败。"""

    expected = {
        "format": "supermap-voxel-netcdf",
        "version": FORMAT_VERSION,
        "renderer": RENDERER,
        "source_kind": source_kind,
        "source_id": source_id,
        "grid_sha256": grid_sha256,
        "netcdf_sha256": netcdf_sha256,
    }
    mismatched = sorted(
        key for key, value in expected.items() if manifest.get(key) != value
    )
    if mismatched:
        raise PlatformError(
            RENDER_ASSET_CORRUPT,
            "渲染资产 manifest 身份与期望不符",
            {**context, "mismatched": mismatched},
            http_status=409,
        )


def verify_ready_asset(runtime, record: RenderAssetRecord) -> RenderAssetRecord:
    """ready 行的文件侧复核：重算校验清单 + 期望身份比对，全对才返回记录。

    目录缺失/文件哈希不符/manifest 身份被篡改都 fail-closed，抛
    ``RENDER_ASSET_CORRUPT``（409），绝不返回记录或字节。
    """

    package_dir = runtime.settings.render_assets_dir / record.id
    manifest = read_package_manifest(package_dir)
    _require_package_identity(
        manifest,
        source_kind=record.source_kind,
        source_id=record.source_id,
        grid_sha256=record.grid_sha256,
        netcdf_sha256=record.netcdf_sha256,
        context={"asset_id": record.id},
    )
    return record


def _prepare_final_dir(
    record: RenderAssetRecord, final_dir: Path, manifest: dict[str, Any]
) -> dict[str, Any] | None:
    """``os.replace`` 前核验既存 final 目录。

    - 不存在：返回 None，走正常 rename 发布；
    - 存在且与期望身份一致：复用，返回其 manifest（调用方丢弃 stage）；
    - 存在但无效：原子改名为 ``<asset-id>.corrupt-<uuid>`` 隔离损坏证据
      （绝不自动删除），并让本次请求以 ``RENDER_ASSET_CORRUPT`` 失败。
    """

    if not final_dir.exists():
        return None
    try:
        existing = read_package_manifest(final_dir)
        _require_package_identity(
            existing,
            source_kind=record.source_kind,
            source_id=record.source_id,
            grid_sha256=record.grid_sha256,
            netcdf_sha256=manifest["netcdf_sha256"],
            context={"asset_id": record.id},
        )
    except PlatformError as exc:
        quarantine = final_dir.with_name(f"{record.id}.corrupt-{uuid.uuid4().hex}")
        os.replace(final_dir, quarantine)
        raise PlatformError(
            RENDER_ASSET_CORRUPT,
            "渲染资产目录与期望身份不符，已原子隔离损坏证据",
            {
                "asset_id": record.id,
                "quarantine": quarantine.name,
                "reason": exc.message,
            },
            http_status=409,
        ) from exc
    return existing


def _mark_ready(
    runtime, asset_id: str, *, manifest: dict[str, Any], final_dir: Path
) -> RenderAssetRecord:
    # asset_dir 落库为 data_dir 相对路径：内部列，不含绝对路径
    asset_dir = final_dir.relative_to(runtime.settings.data_dir).as_posix()
    with runtime.session() as session:
        return RenderAssetRepository(session).mark_ready(
            asset_id,
            netcdf_sha256=manifest["netcdf_sha256"],
            asset_dir=asset_dir,
            manifest=manifest,
        )


def _mark_failed(
    runtime, asset_id: str, *, code: str, message: str, details: dict[str, Any]
) -> None:
    with runtime.session() as session:
        RenderAssetRepository(session).mark_failed(
            asset_id, code=code, message=message, details=details
        )


def _failure_identity(exc: Exception) -> tuple[str, str, dict[str, Any]]:
    if isinstance(exc, PlatformError):
        return exc.code, exc.message, dict(exc.details)
    return (
        RENDER_ASSET_PUBLISH_FAILED,
        f"渲染资产发布失败：{exc}",
        {"exception_type": type(exc).__name__},
    )


def create_render_asset(
    runtime, source: RenderGridSource, *, retry_failed: bool = False
) -> tuple[RenderAssetRecord, bool]:
    """创建（或幂等复用）source 的 NetCDF 渲染资产，返回 ``(record, created)``。

    - 已 ready：``verify_ready_asset`` 复核后幂等返回同资产同 SHA（created=False）。
    - 他方持有 creating：``RENDER_ASSET_IN_PROGRESS``（409）。
    - failed/interrupted 且未要求重试：原样返回持久化状态（created=False）。
    - 否则：隐藏 stage 写齐 + fsync → ``os.replace`` 单点改名 → ``mark_ready``；
      任何异常清理 stage 并 ``mark_failed``，清理异常绝不覆盖业务异常。
    """

    grid = source.validated_grid or validate_regular_grid(
        source.grid_path, source.grid_sha256
    )
    with runtime.session() as session:
        record, created = RenderAssetRepository(session).claim(
            source, retry_failed=retry_failed
        )
    if not created:
        if record.status == STATUS_READY:
            return verify_ready_asset(runtime, record), False
        if record.status == STATUS_CREATING:
            raise PlatformError(
                RENDER_ASSET_IN_PROGRESS,
                "该渲染资产正在创建中",
                {"asset_id": record.id},
                http_status=409,
            )
        return record, False

    assets_dir = runtime.settings.render_assets_dir
    assets_dir.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{record.id}-", dir=assets_dir))
    final_dir = assets_dir / record.id
    try:
        manifest = write_netcdf_package(
            stage, source, grid, runtime.settings.display_anchor
        )
        fsync_tree(stage)
        reused = _prepare_final_dir(record, final_dir, manifest)
        if reused is not None:
            shutil.rmtree(stage, ignore_errors=True)
            manifest = reused
        else:
            os.replace(stage, final_dir)
        record = _mark_ready(runtime, record.id, manifest=manifest, final_dir=final_dir)
        return record, True
    except Exception as exc:
        shutil.rmtree(stage, ignore_errors=True)
        code, message, details = _failure_identity(exc)
        try:
            _mark_failed(
                runtime, record.id, code=code, message=message, details=details
            )
        except Exception:
            pass  # 清理/落库异常绝不覆盖业务异常
        raise
