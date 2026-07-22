"""Persistence for browser-load evidence reports.

Reports are appended as JSONL under the platform's ignored ``outputs/``
tree. They are runtime evidence, not source data, so they follow the same
rules as other derived artifacts and are never committed to Git.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .schemas import (
    BrowserLoadEvidenceRecord,
    BrowserLoadReport,
    RenderKind,
    SceneIdentity,
    VoxelCacheIdentity,
)

BROWSER_LOADS_FILENAME = "browser_loads.jsonl"


def record_browser_load(report: BrowserLoadReport, store_dir: str | Path) -> BrowserLoadEvidenceRecord:
    """Append one browser-load report to the JSONL evidence store.

    The server receive time (``received_at``) is the authoritative evidence
    timestamp; the client-reported time is kept for diagnostics only.
    """

    record = BrowserLoadEvidenceRecord(
        case_id=report.case_id,
        result_id=report.result_id,
        service_url=report.service_url,
        scene_name=report.scene_name,
        layer_count=report.layer_count,
        success=report.success,
        render_kind=report.render_kind,
        validated_count=report.validated_count,
        client=report.client,
        note=report.note,
        reported_at=report.reported_at or datetime.now(timezone.utc),
    )
    path = Path(store_dir)
    path.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
    with (path / BROWSER_LOADS_FILENAME).open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return record


def _iter_records(store_dir: str | Path):
    file_path = Path(store_dir) / BROWSER_LOADS_FILENAME
    if not file_path.exists():
        return
    with file_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def latest_browser_load(case_id: str, result_id: str, store_dir: str | Path) -> datetime | None:
    """Return the newest report timestamp for a case/result pair, if any."""

    latest: datetime | None = None
    for row in _iter_records(store_dir) or []:
        if row.get("case_id") != case_id or row.get("result_id") != result_id:
            continue
        raw = row.get("reported_at")
        if not raw:
            continue
        try:
            stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if latest is None or stamp > latest:
            latest = stamp
    return latest


def _normalize_url(url: str) -> str:
    """Normalize a service URL for exact comparison (trailing slashes off)."""

    return url.strip().rstrip("/")


def _report_identity_ok(
    row: dict,
    *,
    scene: SceneIdentity,
    voxel: VoxelCacheIdentity,
) -> bool:
    """Kind-specific identity validation for a browser-load report row.

    Service identity requires an exact (normalized) URL match — a correct
    prefix with a forged suffix is rejected just like any other mismatch.
    """

    kind = row.get("render_kind")
    url = _normalize_url(str(row.get("service_url") or ""))
    if kind == RenderKind.ISERVER_SCENE.value:
        if url != _normalize_url(scene.service_url):
            return False
        if row.get("scene_name") != scene.scene_name:
            return False
        layer_count = row.get("layer_count")
        if not (isinstance(layer_count, int) and layer_count > 0):
            return False
        return row.get("validated_count") == layer_count
    if kind == RenderKind.S3M_VOXEL_CACHE.value:
        if url != _normalize_url(voxel.service_url):
            return False
        if f"3D-local3DCache-{voxel.cache_data_name}" not in url:
            return False
        return (row.get("validated_count") or 0) > 0
    return False


def latest_valid_browser_load(
    case_id: str,
    result_id: str,
    store_dir: str | Path,
    *,
    scene: SceneIdentity,
    voxel: VoxelCacheIdentity,
) -> BrowserLoadEvidenceRecord | None:
    """Newest report that may move ``browser_loaded`` in the evidence chain.

    A report qualifies only when it succeeds, renders a non-fallback kind,
    passes the kind-specific identity checks (scene service + scene name +
    actual layer count, or voxel service + cache data name), validates a
    positive count, and targets the exact ``result_id``.
    """

    latest: BrowserLoadEvidenceRecord | None = None
    for row in _iter_records(store_dir) or []:
        if row.get("case_id") != case_id or row.get("result_id") != result_id:
            continue
        if not row.get("success"):
            continue
        if not _report_identity_ok(row, scene=scene, voxel=voxel):
            continue
        try:
            record = BrowserLoadEvidenceRecord.model_validate(row)
        except Exception:
            continue
        if latest is None or record.received_at > latest.received_at:
            latest = record
    return latest
