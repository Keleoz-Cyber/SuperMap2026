"""v0.6.1 Task 7: explicit mutation and pure query APIs for native volume rendering.

设计 §2.3 三组路由：

- 候选：``GET /api/results/{id}/render-capability``、
  ``POST|GET /api/results/{id}/render-assets/netcdf``
- 内置电阻率：``GET /api/cases/resistivity/render-capability``、
  ``POST|GET /api/cases/resistivity/render-assets/netcdf``、
  ``POST /api/cases/resistivity/render-sources/import``（产品内显式导入入口）
- 不可变资产：``GET /api/render-assets/{asset_id}/manifest``、
  ``GET /api/render-assets/{asset_id}/volume.nc``

POST 是唯一显式变异：候选 POST 先显式 ``materialize`` 再解析源创建资产
（首个成功 201、幂等复用 200、``creating`` 行 409、failed/interrupted 无
``retry_failed=true`` 返回持久化失败 409）；legacy POST 只解析已登记源，
绝不重跑 Kriging。导入 POST 是产品内唯一的 legacy 网格登记入口：multipart
CSV 流式读入（有界 50 MiB）暂存后调用 ``import_legacy_grid`` 全部校验，
首个登记 201、同网格重导入幂等 200、不同网格覆盖 409、校验失败 422，
暂存文件 finally 清理、失败零残留。所有 GET 都是纯查询：绝不物化、绝不
导出、绝不改行。文件端点只服务 ready 行：render-assets 目录 containment
校验 + ``verify_ready_asset`` 当前文件哈希核验，不符 ``RENDER_ASSET_CORRUPT``
（JSON 错误体，绝不下发字节）。DTO 白名单序列化：``asset_dir`` 绝不外发，
错误 details 经 ``sanitize_public_details`` 脱敏。
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from fastapi.responses import FileResponse

from geomodeling.api import case_service
from geomodeling.api.deps import get_app_config, get_platform_runtime
from geomodeling.config import AppConfig
from geomodeling.platform import PlatformRuntime
from geomodeling.platform import render_assets
from geomodeling.platform import results as platform_results
from geomodeling.platform import slice_analysis
from geomodeling.platform import slice_exports
from geomodeling.platform.errors import PlatformError, sanitize_public_details
from geomodeling.platform.legacy_render_sources import (
    LEGACY_RENDER_SOURCE_NOT_REGISTERED,
    LegacyRenderSourceRecord,
    import_legacy_grid,
    resolve_legacy_render_source,
)
from geomodeling.platform.netcdf_volume import RENDER_ASSET_CORRUPT
from geomodeling.platform.render_contracts import DisplayAnchor
from geomodeling.platform.render_coordinates import display_transform_for_bounds
from geomodeling.platform.render_profiles import build_render_profile
from geomodeling.platform.slice_exports import (
    MAX_SLICE_IMAGE_BYTES,
    SLICE_EXPORT_UPLOAD_TOO_LARGE,
)
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

LEGACY_IMPORT_REQUEST_INVALID = "LEGACY_IMPORT_REQUEST_INVALID"
LEGACY_IMPORT_UPLOAD_TOO_LARGE = "LEGACY_IMPORT_UPLOAD_TOO_LARGE"

# 导入上传硬上限 50 MiB（与平台数据集上传上限同量级）：流式读入即界，
# 超限 413，绝不把无界上传读入内存或落盘。
MAX_LEGACY_IMPORT_BYTES = 50 * 1024 * 1024
_UPLOAD_CHUNK_BYTES = 1024 * 1024

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
            "render_profile": None,
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
        # v0.7.0 第二批：legacy 登记元数据默认 log/native-spectrum；
        # 有效值不全为正时自动降级 linear（不丢弃原始值）
        "render_profile": build_render_profile(
            "builtin_legacy",
            grid.valid_min,
            grid.valid_max,
            property_name=source.property_name,
            unit=source.units,
        ).to_public(),
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
# legacy 渲染源产品内导入（与 render-grid import-csv 同一登记语义）
# ---------------------------------------------------------------------------


def _require_form_value(value: str | None, field: str) -> str:
    """必填表单参数校验：缺失/空白以统一封套 422 拒绝（绝不依赖 500）。"""

    text = (value or "").strip()
    if not text:
        raise PlatformError(
            LEGACY_IMPORT_REQUEST_INVALID,
            f"导入请求缺少必填参数：{field}",
            {"field": field},
            http_status=422,
        )
    return text


async def _stage_legacy_upload(upload: UploadFile | None, stage_dir: Path) -> Path:
    """流式暂存上传 CSV（有界）；客户端文件名绝不用于落盘，固定 upload.csv。"""

    if upload is None:
        raise PlatformError(
            LEGACY_IMPORT_REQUEST_INVALID,
            "导入请求缺少上传文件：file",
            {"field": "file"},
            http_status=422,
        )
    target = stage_dir / "upload.csv"
    size = 0
    try:
        with target.open("wb") as handle:
            while True:
                chunk = await upload.read(_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_LEGACY_IMPORT_BYTES:
                    raise PlatformError(
                        LEGACY_IMPORT_UPLOAD_TOO_LARGE,
                        "上传 CSV 超过大小上限（50 MiB）",
                        {"size_bytes": size, "max_bytes": MAX_LEGACY_IMPORT_BYTES},
                        http_status=413,
                    )
                handle.write(chunk)
    finally:
        await upload.close()
    return target


def _registration_payload(record: LegacyRenderSourceRecord) -> dict[str, Any]:
    """登记身份白名单（与 render_cli 输出同一份）：只有逻辑身份、相对工件
    目录与 SHA-256，绝无绝对输入路径。"""

    return {
        "source_kind": record.source_kind,
        "source_id": record.source_id,
        "grid_sha256": record.grid_sha256,
        "property_name": record.property_name,
        "units": record.units,
        "shape": record.shape,
        "artifact_dir": record.artifact_dir,
        "import_source_sha256": record.import_source_sha256,
    }


@router.post("/api/cases/resistivity/render-sources/import", status_code=201)
async def import_legacy_render_source(
    response: Response,
    file: UploadFile | None = File(None),
    x_column: str | None = Form(None),
    y_column: str | None = Form(None),
    z_column: str | None = Form(None),
    value_column: str | None = Form(None),
    property_name: str | None = Form(None),
    units: str | None = Form(None),
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """产品内显式导入：multipart CSV 经 ``import_legacy_grid`` 全部校验后登记。

    首个登记 201；同网格重导入幂等 200（登记状态不改写）；不同网格覆盖
    409 ``LEGACY_RENDER_SOURCE_CONFLICT``；校验失败 422；上传超限 413。
    任何失败都不留登记状态或暂存残留。
    """

    # 列名/属性名显式传入且必填；单位缺失按 CLI 约定落字面 unknown
    columns = {
        "x_column": _require_form_value(x_column, "x_column"),
        "y_column": _require_form_value(y_column, "y_column"),
        "z_column": _require_form_value(z_column, "z_column"),
        "value_column": _require_form_value(value_column, "value_column"),
        "property_name": _require_form_value(property_name, "property_name"),
        "units": (units or "").strip() or "unknown",
    }

    # 先探测登记状态决定 201/200：纯查询，绝不创建文件或改写登记状态；
    # 登记状态损坏（STATE_INVALID 409）在此 fail-fast，绝不读上传字节
    try:
        resolve_legacy_render_source(runtime, LEGACY_SOURCE_ID)
        already_registered = True
    except PlatformError as exc:
        if exc.code != LEGACY_RENDER_SOURCE_NOT_REGISTERED:
            raise
        already_registered = False

    stage_dir = Path(tempfile.mkdtemp(prefix="geomodeling-legacy-import-"))
    try:
        staged_csv = await _stage_legacy_upload(file, stage_dir)
        record = import_legacy_grid(
            runtime,
            source_id=LEGACY_SOURCE_ID,
            csv_path=staged_csv,
            x_column=columns["x_column"],
            y_column=columns["y_column"],
            z_column=columns["z_column"],
            value_column=columns["value_column"],
            property_name=columns["property_name"],
            units=columns["units"],
        )
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)
    if already_registered:
        response.status_code = 200
    return _registration_payload(record)


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

    return slice_analysis.analyze_render_asset_slice(runtime, asset_id, axis, index)


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
