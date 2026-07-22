"""Case-facing domain assembly for the v0.3 browser API.

All responses derive from the existing platform config, registries and
metric artifacts plus the live iServer probe. Nothing here recomputes
modeling state, and iServer unavailability never marks a model as failed.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from geomodeling.config import AppConfig
from geomodeling.issues import current_issues
from geomodeling.publishing import (
    IServerClient,
    build_publish_evidence_chain,
    latest_browser_load,
    probe_iserver,
    verify_data_service,
    verify_realspace_service,
)
from geomodeling.publishing.probe import (
    DATA_SERVICE_NAME,
    MAP_SERVICE_NAME,
    REALSPACE_SERVICE_NAME,
    RHO_DATASOURCE,
    RHO_FORMAL_DATASET,
    RHO_SCENE_NAME,
    VOLUME_SCENE_NAME,
    VOLUME_SERVICE_NAME,
)
from geomodeling.publishing.s3mb import dedupe_cells, parse_s3mb_bytes

# iDesktopX 体元栅格生成缓存（S3M 2.0）的默认输出位置；可用
# GEOMODELING_VOXEL_CACHE_DIR 覆盖。瓦片字节一律经 iServer REST 获取，
# 本地路径仅用于枚举瓦片相对路径，不作为数据来源。
VOLUME_CACHE_DATA_NAME = "RHO_KRIG_FINAL_20M_40_VOL_S3M2"
DEFAULT_VOXEL_CACHE_DIR = "../Project/cache/RHO_KRIG_FINAL_20M_40_VOL_S3M2"

CASE_RESISTIVITY = "resistivity"
CASE_MICROSEISMIC = "microseismic"
CASE_GAS = "gas"


def list_cases() -> list[dict[str, Any]]:
    """Case cards for the browser home page."""

    return [
        {
            "case_id": CASE_RESISTIVITY,
            "title": "地下电阻率",
            "data_form": "三维 X/Y/Z/RHO（局部工程坐标）",
            "status": "active",
            "coordinate": "局部工程坐标，EPSG 未确认",
            "unit_note": "RHO 单位待来源确认",
            "v03_stage": "iServer 纵向闭环",
            "links": {"detail": "/api/cases/resistivity", "publish_status": "/api/cases/resistivity/publish-status"},
        },
        {
            "case_id": CASE_MICROSEISMIC,
            "title": "微震速度",
            "data_form": "三维 X/Y/Z/Vx（局部测线坐标）",
            "status": "audit_only",
            "coordinate": "局部测线坐标（W16 原点）",
            "unit_note": "Vx 单位 km/s",
            "v03_stage": "第二案例：v0.2a 审计底座已合并，三维接入排期中",
            "links": {"detail": None, "publish_status": None},
        },
        {
            "case_id": CASE_GAS,
            "title": "煤层瓦斯",
            "data_form": "三维候选点（西安1980 / EPSG:2334 工作约定）",
            "status": "parked",
            "coordinate": "西安1980 6°带 第20带（实验假设）",
            "unit_note": "CH4 含量",
            "v03_stage": "暂缓：体元加载触发 iDesktopX 原生崩溃",
            "links": {"detail": None, "publish_status": None},
        },
    ]


def _load_metric_summaries(metrics_json: Path | None) -> tuple[dict[str, Any] | None, str]:
    if metrics_json is None or not metrics_json.exists():
        return None, "config_only"
    with metrics_json.open("r", encoding="utf-8") as fh:
        return json.load(fh), str(metrics_json)


def resistivity_detail(config: AppConfig, metrics_json: Path | None) -> dict[str, Any]:
    """Full resistivity case detail: datasets, models+metrics, results, issues."""

    summaries_doc, metric_source = _load_metric_summaries(metrics_json)
    summaries = (summaries_doc or {}).get("summaries", {})
    baseline = (summaries_doc or {}).get("baseline_comparison")

    models: list[dict[str, Any]] = []
    for model in config.models:
        display = model.get("display_name", model.get("model_id"))
        metrics = summaries.get(display)
        models.append(
            {
                "model_id": model.get("model_id"),
                "display_name": display,
                "method": model.get("method"),
                "resolution_xy_m": model.get("resolution_xy_m"),
                "neighbor_count": model.get("neighbor_count"),
                "role": model.get("role"),
                "parameters": model.get("parameters", {}),
                "metrics": metrics,
            }
        )

    expected = config.expected
    return {
        "case_id": CASE_RESISTIVITY,
        "title": "地下电阻率",
        "coordinate": {
            "type": "local_engineering",
            "epsg": None,
            "note": "局部平面坐标，EPSG 未确认；Z 为负高程（向下为负）",
        },
        "datasets": [
            {"name": "标准化源数据", "rows": expected.get("standardized_rows"), "fields": "X,Y,Z,RHO"},
            {"name": "训练集", "rows": expected.get("training_rows"), "spatial_columns": expected.get("training_columns")},
            {"name": "验证集", "rows": expected.get("validation_rows"), "spatial_columns": expected.get("validation_columns")},
        ],
        "validation_split": {
            "spatial_column_overlap": expected.get("spatial_column_overlap"),
            "seed": "supermap-rho-block-cv-v1",
        },
        "metric_expectations": {
            "common_valid": expected.get("common_valid"),
            "common_nodata": expected.get("common_nodata"),
            "coverage_rate": expected.get("coverage_rate"),
        },
        "models": models,
        "baseline_comparison": baseline,
        "metric_source": metric_source,
        "supermap": {
            "version": config.supermap.get("version"),
            "datasource_alias": config.supermap.get("datasource_alias"),
            "dataset_api": config.supermap.get("dataset_api"),
            "results": config.supermap.get("results", []),
        },
        "views": config.views,
        "issues": [issue.model_dump(mode="json") for issue in current_issues(config)],
    }


def publish_status(config: AppConfig, client: IServerClient, evidence_dir: Path) -> dict[str, Any]:
    """Live publish status for the formal resistivity result.

    Combines registry/config evidence with a live iServer probe. When
    iServer is unreachable the iServer-side states simply report their last
    known or unknown status; modeling states are untouched.
    """

    formal = None
    for result in config.supermap.get("results", []):
        if result.get("result_category") == "formal":
            formal = result
            break
    if formal is None:
        raise KeyError("no formal SuperMap result registered in config")

    result_id = formal["dataset"]

    iserver = probe_iserver(client, [DATA_SERVICE_NAME, MAP_SERVICE_NAME, REALSPACE_SERVICE_NAME])

    data_check = None
    realspace_check = None
    volume_check = None
    live_states: dict[str, tuple[bool, str]] = {}
    if iserver.reachable:
        expected_meta = {
            "type": "VOLUME",
            "value_min": formal.get("value_min"),
            "value_max": formal.get("value_max"),
            "width": formal.get("rows"),
            "height": formal.get("columns"),
        }
        data_check = verify_data_service(
            client, datasource=RHO_DATASOURCE, dataset=result_id, expected=expected_meta
        )
        realspace_check = verify_realspace_service(client, scene_name=RHO_SCENE_NAME)
        volume_check = verify_realspace_service(
            client, scene_name=VOLUME_SCENE_NAME, service_name=VOLUME_SERVICE_NAME
        )

        live_states["iserver_published"] = (
            data_check.reachable and realspace_check.reachable,
            "data/3D services reachable on iServer"
            if data_check.reachable and realspace_check.reachable
            else f"probe errors: data={data_check.error!r} realspace={realspace_check.error!r}",
        )
        metadata_ok = data_check.reachable and not data_check.detail.get("mismatches")
        live_states["service_metadata_verified"] = (
            metadata_ok,
            "dataset metadata matches registry (type VOLUME, bounds, value range)"
            if metadata_ok
            else f"metadata not verified: {data_check.error!r}",
        )
    else:
        live_states["iserver_published"] = (False, f"iServer unreachable: {iserver.error}")
        live_states["service_metadata_verified"] = (False, "iServer unreachable")

    volume_available = bool(volume_check and volume_check.reachable)
    volume_layers = (volume_check.detail.get("layers") or []) if volume_check else []

    browser_latest = latest_browser_load(CASE_RESISTIVITY, result_id, evidence_dir)
    manual_notes = formal.get("manual_evidence") or []
    chain = build_publish_evidence_chain(
        result_id=result_id,
        registry_states={
            "model_succeeded": (
                formal.get("status") == "succeeded",
                f"SuperMap 任务状态: {formal.get('status')}",
            ),
            "artifact_exported": (
                bool(formal.get("openable")),
                "UDBX 文件级验证（dataset_verified=False 保持显式）",
            ),
            "manual_visual_checked": (
                bool(manual_notes),
                manual_notes[0] if manual_notes else "无人工证据",
            ),
        },
        live_states=live_states,
        browser_reported_at=browser_latest,
    )

    failed_results = [
        {
            "dataset": r.get("dataset"),
            "status": r.get("status"),
            "result_category": r.get("result_category"),
            "error_evidence": r.get("error_evidence"),
        }
        for r in config.supermap.get("results", [])
        if r.get("result_category") != "formal"
    ]

    return {
        "case_id": CASE_RESISTIVITY,
        "result_id": result_id,
        "iserver": iserver.model_dump(mode="json"),
        "service_checks": [
            *( [data_check.model_dump(mode="json")] if data_check else [] ),
            *( [realspace_check.model_dump(mode="json")] if realspace_check else [] ),
            *( [volume_check.model_dump(mode="json")] if volume_check else [] ),
        ],
        "evidence_chain": chain.model_dump(mode="json"),
        "failed_results": failed_results,
        "planned_services": {
            "data": f"{client.base_url}/services/{DATA_SERVICE_NAME}/rest",
            "map": f"{client.base_url}/services/{MAP_SERVICE_NAME}/rest",
            "realspace": f"{client.base_url}/services/{REALSPACE_SERVICE_NAME}/rest",
            "scene_name": RHO_SCENE_NAME,
            "volume": {
                "url": f"{client.base_url}/services/{VOLUME_SERVICE_NAME}/rest/realspace",
                "service_name": VOLUME_SERVICE_NAME,
                "scene_name": VOLUME_SCENE_NAME,
                "available": volume_available,
                "layers": volume_layers,
                "note": "iDesktopX「体元栅格生成缓存」(S3M 2.0) 发布后可用的体渲染服务"
                if volume_available
                else "待 iDesktopX 生成体元三维缓存后发布（见运行说明 §8）",
            },
        },
        "iserver_available": iserver.reachable,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=4)
def _read_points_cached(csv_path: str) -> dict[str, Any]:
    """Parse the standardized CSV once per process (read-only source)."""

    import pandas as pd

    path = Path(csv_path)
    frame = pd.read_csv(path)
    xs = frame["X"].astype(float).round(3).tolist()
    ys = frame["Y"].astype(float).round(3).tolist()
    zs = frame["Z"].astype(float).round(3).tolist()
    values = frame["RHO"].astype(float).round(4).tolist()
    return {
        "count": len(frame),
        "x": xs,
        "y": ys,
        "z": zs,
        "values": values,
        "value_range": [float(frame["RHO"].min()), float(frame["RHO"].max())],
        "x_range": [float(frame["X"].min()), float(frame["X"].max())],
        "y_range": [float(frame["Y"].min()), float(frame["Y"].max())],
        "z_range": [float(frame["Z"].min()), float(frame["Z"].max())],
    }


@lru_cache(maxsize=4)
def _voxel_cells_cached(cache_dir: str, service_url: str, timeout: float) -> dict[str, Any]:
    """Fetch every cache tile via iServer REST and parse voxel cells.

    Tile bytes always come from the published iServer 3D cache service; the
    local cache directory is only used to enumerate relative tile paths.
    """

    import os

    from geomodeling.publishing import IServerClient

    root = Path(cache_dir)
    if not root.exists():
        raise FileNotFoundError(f"voxel cache directory not found: {cache_dir}")
    rel_paths = sorted(
        p.relative_to(root).as_posix() for p in root.rglob("*.s3mb")
    )
    if not rel_paths:
        raise FileNotFoundError(f"no .s3mb tiles under {cache_dir}")

    client = IServerClient(
        base_url=os.environ.get("GEOMODELING_ISERVER_URL", "http://localhost:8090/iserver").rstrip("/"),
        timeout=timeout,
    )
    tiles = []
    fetched_bytes = 0
    try:
        for rel in rel_paths:
            resp = client.get_bytes(
                f"services/{VOLUME_SERVICE_NAME}/rest/realspace/datas/{VOLUME_CACHE_DATA_NAME}/data/path/{rel}"
            )
            if not resp.ok:
                raise ConnectionError(f"iServer tile fetch failed for {rel}: {resp.error}")
            fetched_bytes += len(resp.data)
            tiles.append(parse_s3mb_bytes(Path(rel).stem, resp.data))
    finally:
        client.close()

    cells = dedupe_cells(tiles)
    summary = {
        "x_range": [min(c.x for c in cells), max(c.x for c in cells)],
        "y_range": [min(c.y for c in cells), max(c.y for c in cells)],
        "z_range": [min(c.z for c in cells), max(c.z for c in cells)],
        "value_range": [min(c.weight for c in cells), max(c.weight for c in cells)],
    }
    return {
        "cells": cells,
        "tile_files": len(rel_paths),
        "fetched_bytes": fetched_bytes,
        "service_url": service_url,
        "summary": summary,
    }


def voxel_cells(config: AppConfig, client: IServerClient, cache_dir: Path | None) -> dict[str, Any]:
    """Voxel cells from the published S3M cache, for custom browser rendering.

    The S3M cache is SuperMap's renderable sampling of the formal voxel
    (not a cell-exact export); the cell-exact metadata stays with the data
    service VOLUME dataset (see publish-status).
    """

    cache_root = cache_dir or Path(DEFAULT_VOXEL_CACHE_DIR)
    if not cache_root.is_absolute():
        cache_root = (config.resolve_path(str(cache_root)) or cache_root)
    service_url = f"{client.base_url}/services/{VOLUME_SERVICE_NAME}/rest/realspace"
    data = _voxel_cells_cached(str(cache_root), service_url, 30.0)
    cells = data["cells"]
    formal = next(
        (r for r in config.supermap.get("results", []) if r.get("result_category") == "formal"),
        {},
    )
    return {
        "case_id": CASE_RESISTIVITY,
        "result_id": formal.get("dataset", RHO_FORMAL_DATASET),
        "source": "iserver_s3m_cache",
        "cache_dir": str(cache_root),
        "service_url": service_url,
        "tile_files": data["tile_files"],
        "fetched_bytes": data["fetched_bytes"],
        "count": len(cells),
        "value_field": "RHO",
        "unit_note": "RHO 单位待来源确认",
        "x": [round(c.x, 3) for c in cells],
        "y": [round(c.y, 3) for c in cells],
        "z": [round(c.z, 3) for c in cells],
        "values": [round(c.weight, 4) for c in cells],
        **data["summary"],
        "registry_facts": {
            "rows_columns_bands": [formal.get("rows"), formal.get("columns"), formal.get("bands")],
            "cell_exact_value_range": [formal.get("value_min"), formal.get("value_max")],
            "note": "S3M 缓存为 SuperMap 体渲染采样（非逐格导出）；单元精确元数据以数据服务 VOLUME 数据集为准",
        },
    }


def resistivity_points(config: AppConfig, decimate: int = 1) -> dict[str, Any]:
    """Standardized 3D points for the browser scene.

    Source is the platform's registered standardized CSV (the same dataset
    the UDBX point layer was imported from); the SHA-256 is returned so the
    browser can display data lineage.
    """

    csv_path = config.resolve_path(config.paths.get("standardized"))
    if csv_path is None or not csv_path.exists():
        raise FileNotFoundError("standardized CSV not available")
    data = _read_points_cached(str(csv_path))
    step = max(1, int(decimate))
    payload = {
        "case_id": CASE_RESISTIVITY,
        "source": "platform_csv",
        "source_path": str(csv_path),
        "sha256": _sha256(csv_path),
        "decimate": step,
        "count": data["count"],
        "served": len(data["x"][::step]),
        "value_field": "RHO",
        "unit_note": "RHO 单位待来源确认",
        "x": data["x"][::step],
        "y": data["y"][::step],
        "z": data["z"][::step],
        "values": data["values"][::step],
        "value_range": data["value_range"],
        "x_range": data["x_range"],
        "y_range": data["y_range"],
        "z_range": data["z_range"],
    }
    return payload
