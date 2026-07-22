"""Persistence for browser-load evidence reports.

Reports are appended as JSONL under the platform's ignored ``outputs/``
tree. They are runtime evidence, not source data, so they follow the same
rules as other derived artifacts and are never committed to Git.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .schemas import BrowserLoadEvidenceRecord, BrowserLoadReport

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


def latest_valid_browser_load(
    case_id: str,
    result_id: str,
    store_dir: str | Path,
    *,
    allowed_kinds: set[str],
    allowed_service_prefixes: tuple[str, ...],
) -> BrowserLoadEvidenceRecord | None:
    """Newest report that may move ``browser_loaded`` in the evidence chain.

    A report qualifies only when it succeeds, renders a non-fallback kind,
    validates a positive count, targets the exact ``result_id``, and points
    at one of the expected iServer services for that result.
    """

    latest: BrowserLoadEvidenceRecord | None = None
    for row in _iter_records(store_dir) or []:
        if row.get("case_id") != case_id or row.get("result_id") != result_id:
            continue
        if not row.get("success"):
            continue
        if row.get("render_kind") not in allowed_kinds:
            continue
        if not (row.get("validated_count") or 0) > 0:
            continue
        service_url = str(row.get("service_url") or "")
        if not any(service_url.startswith(prefix) for prefix in allowed_service_prefixes):
            continue
        try:
            record = BrowserLoadEvidenceRecord.model_validate(row)
        except Exception:
            continue
        if latest is None or record.received_at > latest.received_at:
            latest = record
    return latest
