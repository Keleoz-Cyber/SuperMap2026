"""v0.6.1 Task 7: explicit mutation and pure query APIs for native volume rendering.

设计 §2.3 三组路由：

- 候选：``GET /api/results/{id}/render-capability``、
  ``POST|GET /api/results/{id}/render-assets/netcdf``
- 不可变资产：``GET /api/render-assets/{asset_id}/manifest``、
  ``GET /api/render-assets/{asset_id}/volume.nc``
- v0.8.0 Task 6：内置电阻率 legacy 渲染产品入口类型化退役——
  ``GET /api/cases/resistivity/render-capability``、
  ``POST|GET /api/cases/resistivity/render-assets/netcdf``、
  ``POST /api/cases/resistivity/render-sources/import`` 一律 410
  ``LEGACY_RESISTIVITY_RETIRED``，绝不返回旧 S3M 数值。``builtin_legacy``
  通用登记/解析机制（platform.legacy_render_sources、render_cli、
  demo_check）与历史资产的不可变文件路由不受影响；已登记的旧资产记录
  仍在数据库/工件目录，仅产品注册/解析入口退役。

POST 是唯一显式变异：候选 POST 先显式 ``materialize`` 再解析源创建资产
（首个成功 201、幂等复用 200、``creating`` 行 409、failed/interrupted 无
``retry_failed=true`` 返回持久化失败 409）。所有 GET 都是纯查询：绝不物化、
绝不导出、绝不改行。文件端点只服务 ready 行：render-assets 目录 containment
校验 + ``verify_ready_asset`` 当前文件哈希核验，不符 ``RENDER_ASSET_CORRUPT``
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

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from fastapi.responses import FileResponse

from geomodeling.api.deps import get_platform_runtime
from geomodeling.platform import PlatformRuntime
from geomodeling.platform import render_assets
from geomodeling.platform import results as platform_results
from geomodeling.platform import slice_analysis
from geomodeling.platform import slice_exports
from geomodeling.platform.errors import (
    LEGACY_RESISTIVITY_RETIRED,
    PlatformError,
    sanitize_public_details,
)
from geomodeling.platform.netcdf_volume import RENDER_ASSET_CORRUPT
from geomodeling.platform.slice_exports import (
    MAX_SLICE_IMAGE_BYTES,
    SLICE_EXPORT_UPLOAD_TOO_LARGE,
)
from geomodeling.platform.repositories import RenderAssetRepository, require_active_candidate, require_active_render_asset
from geomodeling.platform.schemas import (
    STATUS_READY,
    ContractModel,
    RenderAssetRecord,
)

logger = logging.getLogger("geomodeling.api.rendering")

router = APIRouter(tags=["v0.6.1-rendering"])

#: 退役的 legacy 电阻率渲染源身份（v0.8.0 Task 6）；通用机制见
#: ``platform.legacy_render_sources``（render_cli/demo_check/历史资产保留）。
LEGACY_SOURCE_KIND = "builtin_legacy"
LEGACY_SOURCE_ID = "resistivity"

RENDER_ASSET_ID_INVALID = "RENDER_ASSET_ID_INVALID"
RENDER_ASSET_NOT_READY = "RENDER_ASSET_NOT_READY"

# 内容寻址资产 ID（设计 §2.2）：``nc-`` + 32 位小写十六进制。
# 形态校验在一切文件访问之前，路径穿越输入在此即被拒。
_ASSET_ID_RE = re.compile(r"^nc-[0-9a-f]{32}$")


def _validate_asset_id(asset_id: str) -> None:
    """Validate asset ID format before any DB lookup or guard."""
    if not _ASSET_ID_RE.fullmatch(asset_id):
        raise PlatformError(
            RENDER_ASSET_ID_INVALID,
            "渲染资产 ID 形态非法",
            {"asset_id": asset_id},
            http_status=400,
        )


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
    require_active_candidate(runtime, result_id)
    # 纯查询：不物化、不建文件、不改行
    return dataclasses.asdict(render_assets.candidate_render_capability(runtime, result_id))


@router.post("/api/results/{result_id}/render-assets/netcdf", status_code=201)
def create_result_render_asset(
    result_id: str,
    response: Response,
    body: RenderAssetCreateBody | None = None,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    require_active_candidate(runtime, result_id)
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
    require_active_candidate(runtime, result_id)
    return _status_payload(runtime, "candidate_result", result_id)


# ---------------------------------------------------------------------------
# 内置电阻率案例路由（v0.8.0 Task 6：类型化退役，一律 410）
# ---------------------------------------------------------------------------


def _legacy_resistivity_retired() -> None:
    """旧 legacy/S3M 电阻率渲染产品入口的类型化退役响应。

    绝不返回旧 S3M 数值；已登记的旧资产记录仍在数据库，但产品注册/解析
    入口按退役处理（历史资产仍经不可变资产文件路由只读下发）。
    """

    raise PlatformError(
        LEGACY_RESISTIVITY_RETIRED,
        "旧电阻率 legacy 渲染入口已退役：电阻率已迁移为散点预置案例，"
        "体渲染请使用统一案例工作台的候选成果渲染链",
        {
            "source_kind": LEGACY_SOURCE_KIND,
            "source_id": LEGACY_SOURCE_ID,
            "replacement": "/api/cases/resistivity/workspace",
        },
        http_status=410,
    )


@router.get("/api/cases/resistivity/render-capability")
def get_legacy_render_capability() -> dict[str, Any]:
    _legacy_resistivity_retired()


@router.post("/api/cases/resistivity/render-assets/netcdf", status_code=201)
def create_legacy_render_asset() -> dict[str, Any]:
    _legacy_resistivity_retired()


@router.get("/api/cases/resistivity/render-assets/netcdf")
def get_legacy_render_asset() -> dict[str, Any]:
    _legacy_resistivity_retired()


@router.post("/api/cases/resistivity/render-sources/import", status_code=201)
async def import_legacy_render_source() -> dict[str, Any]:
    # 退役判定先于一切表单/上传字节解析：任何请求体都 410
    _legacy_resistivity_retired()


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


@router.post("/api/render-assets/{asset_id}/slice-exports", status_code=201)
async def create_slice_export(
    asset_id: str,
    axis: str = Form(...),
    index: int = Form(...),
    image: UploadFile = File(...),
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """权威剖面分析 ZIP 导出（原子封包；CSV/统计/manifest 全部由服务端重算）。

    客户端只提交 axis/index 与 ECharts PNG（展示工件）；服务端不接受任何
    矩阵、统计或 manifest。失败不留 Export 行、半成品 ZIP 或临时文件。
    """

    require_active_render_asset(runtime, asset_id)
    chunks: list[bytes] = []
    total = 0
    try:
        while chunk := await image.read(1 << 20):
            total += len(chunk)
            if total > MAX_SLICE_IMAGE_BYTES + 1:
                raise PlatformError(
                    SLICE_EXPORT_UPLOAD_TOO_LARGE,
                    "剖面图片超过大小上限（5 MiB）",
                    {"max_bytes": MAX_SLICE_IMAGE_BYTES},
                    http_status=413,
                )
            chunks.append(chunk)
    finally:
        await image.close()
    return slice_exports.build_slice_export(
        runtime, asset_id, axis, index, b"".join(chunks), image.content_type
    )


@router.get("/api/render-assets/{asset_id}/slice-analysis")
def get_render_asset_slice_analysis(
    asset_id: str,
    axis: str = Query(...),
    index: int = Query(...),
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """RenderAsset 权威剖面分析（纯查询：不建文件、不改行、不经浏览器像素）。

    三来源（candidate_result / builtin_legacy / 预置即候选）共用同一权威
    网格口径；轴/索引错误 422，资产缺失 404，非 ready 409。
    """

    require_active_render_asset(runtime, asset_id)
    return slice_analysis.analyze_render_asset_slice(runtime, asset_id, axis, index)


@router.get("/api/render-assets/{asset_id}/manifest")
def get_render_asset_manifest(
    asset_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    require_active_render_asset(runtime, asset_id)
    _, package_dir = _verified_ready_package(runtime, asset_id)
    return json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))


@router.get("/api/render-assets/{asset_id}/volume.nc")
def get_render_asset_volume(
    asset_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> FileResponse:
    require_active_render_asset(runtime, asset_id)
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
