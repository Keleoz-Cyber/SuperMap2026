"""v0.6.1 Task 7: explicit mutation and pure query APIs for native volume rendering.

设计 §2.3 三组路由：

- 候选：``GET /api/results/{id}/render-capability``、
  ``POST|GET /api/results/{id}/render-assets/netcdf``
- 内置电阻率：``GET /api/cases/resistivity/render-capability``、
  ``POST|GET /api/cases/resistivity/render-assets/netcdf``
- 不可变资产：``GET /api/render-assets/{asset_id}/manifest``、
  ``GET /api/render-assets/{asset_id}/volume.nc``

POST 是唯一显式变异：候选 POST 先显式 ``materialize`` 再解析源创建资产
（首个成功 201、幂等复用 200、``creating`` 行 409、failed/interrupted 无
``retry_failed=true`` 返回持久化失败 409）；legacy POST 只解析已登记源，
绝不重跑 Kriging。所有 GET 都是纯查询：绝不物化、绝不导出、绝不改行。
文件端点只服务 ready 行：render-assets 目录 containment 校验 +
``verify_ready_asset`` 当前文件哈希核验，不符 ``RENDER_ASSET_CORRUPT``
（JSON 错误体，绝不下发字节）。DTO 白名单序列化：``asset_dir`` 绝不外发，
错误 details 经 ``sanitize_public_details`` 脱敏。
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Response
from fastapi.responses import FileResponse

from geomodeling.api import case_service
from geomodeling.api.deps import get_app_config, get_platform_runtime
from geomodeling.config import AppConfig
from geomodeling.platform import PlatformRuntime
from geomodeling.platform import render_assets
from geomodeling.platform import results as platform_results
from geomodeling.platform.errors import PlatformError, sanitize_public_details
from geomodeling.platform.legacy_render_sources import (
    LEGACY_RENDER_SOURCE_NOT_REGISTERED,
    resolve_legacy_render_source,
)
from geomodeling.platform.netcdf_volume import RENDER_ASSET_CORRUPT
from geomodeling.platform.render_contracts import DisplayAnchor
from geomodeling.platform.render_coordinates import display_transform_for_bounds
from geomodeling.platform.repositories import RenderAssetRepository
from geomodeling.platform.schemas import (
    STATUS_READY,
    ContractModel,
    RenderAssetRecord,
)

logger = logging.getLogger("geomodeling.api.rendering")

router = APIRouter(tags=["v0.6.1-rendering"])

LEGACY_SOURCE_KIND = "builtin_legacy"
LEGACY_SOURCE_ID = "resistivity"

RENDER_ASSET_ID_INVALID = "RENDER_ASSET_ID_INVALID"
RENDER_ASSET_NOT_READY = "RENDER_ASSET_NOT_READY"

# 内容寻址资产 ID（设计 §2.2）：``nc-`` + 32 位小写十六进制。
# 形态校验在一切文件访问之前，路径穿越输入在此即被拒。
_ASSET_ID_RE = re.compile(r"^nc-[0-9a-f]{32}$")


class RenderAssetCreateBody(ContractModel):
    """渲染资产创建请求体；空体即首次创建语义（``retry_failed=False``）。"""

    retry_failed: bool = False


# ---------------------------------------------------------------------------
# 序列化白名单
# ---------------------------------------------------------------------------


def _record_payload(record: RenderAssetRecord) -> dict[str, Any]:
    """公共资产记录：``asset_dir`` 本就不在 DTO 内；错误 details 再脱敏一次。"""

    payload = record.model_dump(mode="json")
    if record.error is not None:
        payload["error"]["details"] = sanitize_public_details(record.error.details)
    return payload


# ---------------------------------------------------------------------------
# 资产创建/状态共享语义
# ---------------------------------------------------------------------------


def _create_payload(
    runtime: PlatformRuntime, source, *, retry_failed: bool
) -> tuple[dict[str, Any], int]:
    """创建或幂等复用，返回 ``(payload, status_code)``。

    - 首个成功：201；ready 幂等复用：200；
    - ``creating`` 行由服务层抛 ``RENDER_ASSET_IN_PROGRESS``（409）；
    - failed/interrupted 未显式重试：以 409 返回持久化失败。
    """

    record, created = render_assets.create_render_asset(
        runtime, source, retry_failed=retry_failed
    )
    if created:
        return _record_payload(record), 201
    if record.status == STATUS_READY:
        return _record_payload(record), 200
    if record.error is not None:
        raise PlatformError(
            record.error.code,
            record.error.message,
            dict(record.error.details),
            http_status=409,
        )
    raise PlatformError(
        RENDER_ASSET_NOT_READY,
        "渲染资产尚未就绪",
        {"asset_id": record.id, "status": record.status},
        http_status=409,
    )


def _status_payload(runtime: PlatformRuntime, source_kind: str, source_id: str) -> dict[str, Any]:
    """纯查询：读该源最新资产行；从未创建 404，绝不创建文件或改行。"""

    with runtime.session() as session:
        record = RenderAssetRepository(session).get_for_source(source_kind, source_id)
    return _record_payload(record)


# ---------------------------------------------------------------------------
# 候选成果路由
# ---------------------------------------------------------------------------


@router.get("/api/results/{result_id}/render-capability")
def get_result_render_capability(
    result_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    # 纯查询：不物化、不建文件、不改行
    return dataclasses.asdict(render_assets.candidate_render_capability(runtime, result_id))


@router.post("/api/results/{result_id}/render-assets/netcdf", status_code=201)
def create_result_render_asset(
    result_id: str,
    response: Response,
    body: RenderAssetCreateBody | None = None,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    # POST 是显式变异：先显式物化（幂等），再解析源创建资产
    platform_results.materialize(runtime, result_id)
    source = render_assets.resolve_candidate_render_source(runtime, result_id)
    payload, status_code = _create_payload(
        runtime, source, retry_failed=body.retry_failed if body is not None else False
    )
    response.status_code = status_code
    return payload


@router.get("/api/results/{result_id}/render-assets/netcdf")
def get_result_render_asset(
    result_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    return _status_payload(runtime, "candidate_result", result_id)


# ---------------------------------------------------------------------------
# 内置电阻率案例路由
# ---------------------------------------------------------------------------


def _legacy_points_probe(config: AppConfig) -> dict[str, Any] | None:
    """只读探测测点 CSV：可读返回点数据，任何不可读情形按 None 处理。"""

    try:
        return case_service.resistivity_points(config)
    except FileNotFoundError:
        return None
    except Exception as exc:  # CSV 存在但列不可读：点云模式同样不可用
        logger.warning("legacy resistivity points probe failed: %s", exc)
        return None


def _legacy_capability(runtime: PlatformRuntime, config: AppConfig) -> dict[str, Any]:
    """legacy 渲染能力（纯查询：绝不创建文件、绝不改写登记状态）。

    已登记网格 → 从网格派生 display_transform；未登记但测点 CSV 可读 →
    从测点 X/Y 范围派生同形 transform 供 iframe 点云模式；都不可读 →
    ``supported=false`` + ``LEGACY_RENDER_SOURCE_NOT_REGISTERED`` +
    ``display_transform=null``。
    """

    anchor = DisplayAnchor()
    base: dict[str, Any] = {
        "source_kind": LEGACY_SOURCE_KIND,
        "source_id": LEGACY_SOURCE_ID,
        "geolocation_status": anchor.geolocation_status,
    }
    try:
        source = resolve_legacy_render_source(runtime, LEGACY_SOURCE_ID)
        grid = render_assets.validate_regular_grid(source.grid_path, source.grid_sha256)
    except PlatformError as exc:
        unsupported: dict[str, Any] = {
            **base,
            "supported": False,
            "reason_code": exc.code,
            "reason": exc.message,
            "dimension": None,
            "grid_kind": None,
            "property_name": None,
            "units": None,
            "display_transform": None,
        }
        if exc.code != LEGACY_RENDER_SOURCE_NOT_REGISTERED:
            return unsupported
        points = _legacy_points_probe(config)
        if points is None:
            return unsupported
        transform = display_transform_for_bounds(
            (float(points["x_range"][0]), float(points["x_range"][1])),
            (float(points["y_range"][0]), float(points["y_range"][1])),
            anchor,
        )
        return {
            **unsupported,
            "dimension": "3d",
            "property_name": "RHO",
            "units": "unknown",
            "display_transform": transform,
        }
    x_axis, y_axis = grid.axes[0], grid.axes[1]
    return {
        **base,
        "supported": True,
        "reason_code": None,
        "reason": None,
        "dimension": "3d",
        "grid_kind": "regular",
        "property_name": source.property_name,
        "units": source.units,
        "display_transform": display_transform_for_bounds(
            (float(x_axis[0]), float(x_axis[-1])),
            (float(y_axis[0]), float(y_axis[-1])),
            anchor,
        ),
    }


@router.get("/api/cases/resistivity/render-capability")
def get_legacy_render_capability(
    runtime: PlatformRuntime = Depends(get_platform_runtime),
    config: AppConfig = Depends(get_app_config),
) -> dict[str, Any]:
    return _legacy_capability(runtime, config)


@router.post("/api/cases/resistivity/render-assets/netcdf", status_code=201)
def create_legacy_render_asset(
    response: Response,
    body: RenderAssetCreateBody | None = None,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    # legacy POST 只解析已登记源：绝不重跑 Kriging、绝不从散点重建网格
    source = resolve_legacy_render_source(runtime, LEGACY_SOURCE_ID)
    payload, status_code = _create_payload(
        runtime, source, retry_failed=body.retry_failed if body is not None else False
    )
    response.status_code = status_code
    return payload


@router.get("/api/cases/resistivity/render-assets/netcdf")
def get_legacy_render_asset(
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    return _status_payload(runtime, LEGACY_SOURCE_KIND, LEGACY_SOURCE_ID)


# ---------------------------------------------------------------------------
# 不可变资产文件路由
# ---------------------------------------------------------------------------


def _verified_ready_package(runtime: PlatformRuntime, asset_id: str) -> tuple[RenderAssetRecord, Path]:
    """文件下发门禁：ID 形态 → ready 行 → containment → 当前文件哈希核验。

    任一环失败都 fail-closed：非法 ID 400、缺席 404、非 ready 409、
    哈希/身份不符 ``RENDER_ASSET_CORRUPT``（409）——绝不返回字节。
    """

    if not _ASSET_ID_RE.fullmatch(asset_id):
        raise PlatformError(
            RENDER_ASSET_ID_INVALID,
            "渲染资产 ID 形态非法",
            {"asset_id": asset_id},
            http_status=400,
        )
    with runtime.session() as session:
        record = RenderAssetRepository(session).get_ready(asset_id)
    base = runtime.settings.render_assets_dir.resolve()
    package_dir = (base / record.id).resolve()
    if not package_dir.is_relative_to(base):
        raise PlatformError(
            RENDER_ASSET_CORRUPT,
            "渲染资产目录越出受控 render-assets 目录",
            {"asset_id": asset_id},
            http_status=409,
        )
    render_assets.verify_ready_asset(runtime, record)
    return record, package_dir


@router.get("/api/render-assets/{asset_id}/manifest")
def get_render_asset_manifest(
    asset_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    _, package_dir = _verified_ready_package(runtime, asset_id)
    return json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))


@router.get("/api/render-assets/{asset_id}/volume.nc")
def get_render_asset_volume(
    asset_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> FileResponse:
    record, package_dir = _verified_ready_package(runtime, asset_id)
    return FileResponse(
        package_dir / "volume.nc",
        media_type="application/x-netcdf",
        filename=f"{record.id}.nc",
        headers={
            "ETag": f'"sha256-{record.netcdf_sha256}"',
            "Cache-Control": "public, immutable",
        },
    )
