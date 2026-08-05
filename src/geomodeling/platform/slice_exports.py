"""v0.7.0 Batch 2 Task 5：权威剖面分析 ZIP 导出。

服务端只接受 axis/index/PNG 三个输入；CSV、统计与 manifest 一律从同一
RenderAsset 的权威网格重算（绝不接受客户端提交的矩阵、统计或 manifest）。
PNG 是客户端 ECharts 展示工件（``image_provenance=client_echarts_canvas``），
只校验签名/IHDR 边界，不作为数值来源。

原子合同：受控暂存目录 → 全部文件与 ZIP 完成 → ``os.replace`` → Export 行
插入；任一阶段失败清理暂存目录与最终包，绝不留下半成品；清理异常只记
日志，绝不覆盖最初业务异常。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import struct
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any, Literal

from geomodeling.platform import tables
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.slice_analysis import (
    analyze_render_asset_slice,
    load_ready_asset_grid,
)
from geomodeling.platform.results import _load_candidate

logger = logging.getLogger("geomodeling.platform")

SLICE_EXPORT_IMAGE_INVALID = "SLICE_EXPORT_IMAGE_INVALID"
SLICE_EXPORT_UPLOAD_TOO_LARGE = "SLICE_EXPORT_UPLOAD_TOO_LARGE"

MAX_SLICE_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PNG_DIMENSION = 4096
FORMAT_VERSION = "slice-analysis/v1"
IMAGE_PROVENANCE = "client_echarts_canvas"

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ensure_legacy_case_row(runtime, case_id: str) -> str:
    """legacy 资产导出的 FK 支撑行（幂等 get-or-create）。

    Export.case_id 有外键约束；legacy 案例卡由 adapter 提供、默认无数据库行。
    仅在剖面导出需要时补一行最小 Case（非卡片来源，不改变 adapter 语义）。
    """

    with runtime.session() as session:
        row = session.get(tables.Case, case_id)
        if row is None:
            session.add(
                tables.Case(
                    id=case_id,
                    name="内置电阻率",
                    case_type="legacy",
                    config_json="{}",
                )
            )
            session.commit()
    return case_id


def validate_slice_image(png_bytes: bytes, declared_mime: str | None) -> bytes:
    """校验 PNG 签名、MIME 与 IHDR 尺寸边界；合格返回原字节。"""

    if len(png_bytes) > MAX_SLICE_IMAGE_BYTES:
        raise PlatformError(
            SLICE_EXPORT_UPLOAD_TOO_LARGE,
            "剖面图片超过大小上限（5 MiB）",
            {"size_bytes": len(png_bytes), "max_bytes": MAX_SLICE_IMAGE_BYTES},
            http_status=413,
        )
    mime = (declared_mime or "").split(";")[0].strip().lower()
    if mime != "image/png":
        raise PlatformError(
            SLICE_EXPORT_IMAGE_INVALID,
            "剖面图片必须是 image/png",
            {"content_type": declared_mime},
            http_status=422,
        )
    if len(png_bytes) < 33 or not png_bytes.startswith(_PNG_SIGNATURE):
        raise PlatformError(
            SLICE_EXPORT_IMAGE_INVALID,
            "剖面图片 PNG 签名无效",
            {},
            http_status=422,
        )
    # IHDR：第一个 chunk 必须是 IHDR 且宽高在 1..4096
    (ihdr_len,) = struct.unpack(">I", png_bytes[8:12])
    if png_bytes[12:16] != b"IHDR" or ihdr_len < 8:
        raise PlatformError(
            SLICE_EXPORT_IMAGE_INVALID,
            "剖面图片缺少有效 IHDR",
            {},
            http_status=422,
        )
    width, height = struct.unpack(">II", png_bytes[16:24])
    if not (1 <= width <= MAX_PNG_DIMENSION) or not (1 <= height <= MAX_PNG_DIMENSION):
        raise PlatformError(
            SLICE_EXPORT_IMAGE_INVALID,
            "剖面图片 IHDR 宽高超出 1..4096 边界",
            {"width": width, "height": height},
            http_status=422,
        )
    return png_bytes


def _slice_csv_rows(analysis: dict[str, Any]) -> str:
    """行优先 CSV：外层 row_coordinates，内层 column_coordinates，固定轴重复。"""

    slice_payload = analysis["slice"]
    fixed = slice_payload["coordinate"]
    rows = ["x,y,z,value,is_nodata"]
    for r, row_coord in enumerate(slice_payload["row_coordinates"]):
        for c, col_coord in enumerate(slice_payload["column_coordinates"]):
            if slice_payload["nodata_mask"][r][c]:
                rows.append(f"{col_coord},{row_coord},{fixed},,true")
            else:
                value = slice_payload["values"][r][c]
                rows.append(f"{col_coord},{row_coord},{fixed},{value},false")
    return "\n".join(rows) + "\n"


def build_slice_export(
    runtime,
    asset_id: str,
    axis: Literal["x", "y", "z"],
    index: int,
    png_bytes: bytes,
    declared_mime: str | None,
) -> dict[str, Any]:
    """生成权威剖面分析 ZIP 并登记 Export（原子 + 失败全清理）。"""

    analysis = analyze_render_asset_slice(runtime, asset_id, axis, index)
    validate_slice_image(png_bytes, declared_mime)

    # 归属链：候选资产填 case_id/candidate_result_id；legacy 用稳定案例行
    record, _, _ = load_ready_asset_grid(runtime, asset_id)
    candidate_result_id: str | None = None
    if record.source_kind == "candidate_result":
        _, _, experiment = _load_candidate(runtime, record.source_id)
        case_id = experiment.case_id
        candidate_result_id = record.source_id
    elif record.source_kind == "builtin_legacy":
        case_id = _ensure_legacy_case_row(runtime, record.source_id)
    else:  # pragma: no cover - load_ready_asset_grid 已 fail-closed
        raise PlatformError(
            "RENDER_ASSET_SOURCE_UNSUPPORTED",
            "不支持的渲染源类型",
            {"source_kind": record.source_kind},
            http_status=409,
        )

    export_id = str(uuid.uuid4())
    package_path = runtime.settings.export_package(export_id)
    final_zip = package_path.parent / "slice-analysis.zip"
    package_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="slice-export-", dir=package_path.parent))
    zip_completed = False
    try:
        csv_bytes = _slice_csv_rows(analysis).encode("utf-8")
        stats_bytes = (
            json.dumps(analysis["statistics"], ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")

        manifest: dict[str, Any] = {
            "format_version": FORMAT_VERSION,
            "export_kind": "slice_analysis",
            "image_provenance": IMAGE_PROVENANCE,
            "asset_identity": analysis["asset_identity"],
            "property": analysis["property"],
            "axes": {
                name: {"length": axis_info["length"]}
                for name, axis_info in analysis["axes"].items()
            },
            "slice": {
                "fixed_axis": analysis["slice"]["fixed_axis"],
                "index": analysis["slice"]["index"],
                "coordinate": analysis["slice"]["coordinate"],
            },
            "statistics_contract": {
                "valid_definition": "is_nodata=false 且数值有限",
                "std": "population(ddof=0)",
                "quantiles": "numpy-linear",
                "counts": "valid_count + nodata_count = total_count",
            },
            "statistics": analysis["statistics"],
            "files": {
                "slice.csv": {"sha256": _sha256_bytes(csv_bytes), "size_bytes": len(csv_bytes)},
                "statistics.json": {
                    "sha256": _sha256_bytes(stats_bytes),
                    "size_bytes": len(stats_bytes),
                },
                "slice.png": {"sha256": _sha256_bytes(png_bytes), "size_bytes": len(png_bytes)},
            },
            "created_at": tables.utc_now_iso(),
        }

        (tmp_dir / "slice.csv").write_bytes(csv_bytes)
        (tmp_dir / "statistics.json").write_bytes(stats_bytes)
        (tmp_dir / "slice.png").write_bytes(png_bytes)
        manifest_bytes = (
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        (tmp_dir / "manifest.json").write_bytes(manifest_bytes)

        tmp_zip = tmp_dir / "package.zip"
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in ("slice.csv", "statistics.json", "slice.png", "manifest.json"):
                archive.write(tmp_dir / name, arcname=name)
        os.replace(tmp_zip, final_zip)
        zip_completed = True

        manifest["export_id"] = export_id
        manifest["case_id"] = case_id
        manifest["candidate_result_id"] = candidate_result_id
        with runtime.session() as session:
            session.add(
                tables.Export(
                    id=export_id,
                    case_id=case_id,
                    candidate_result_id=candidate_result_id,
                    package_path=str(final_zip),
                    manifest_json=tables.dumps_canonical(manifest),
                )
            )
            session.commit()
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except BaseException:
        try:
            shutil.rmtree(tmp_dir)
        except Exception:  # noqa: BLE001
            logger.exception("slice export staging cleanup failed: %s", tmp_dir)
        if zip_completed:
            try:
                final_zip.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                logger.exception("slice export final package cleanup failed: %s", final_zip)
        raise

    return {
        "id": export_id,
        "case_id": case_id,
        "candidate_result_id": candidate_result_id,
        "package_sha256": hashlib.sha256(final_zip.read_bytes()).hexdigest(),
        "file_count": 4,
        "files": ["slice.csv", "statistics.json", "slice.png", "manifest.json"],
        "manifest": manifest,
    }
