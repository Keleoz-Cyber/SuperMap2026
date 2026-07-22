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
    """Append one browser-load report to the JSONL evidence store."""

    record = BrowserLoadEvidenceRecord(
        case_id=report.case_id,
        result_id=report.result_id,
        service_url=report.service_url,
        scene_name=report.scene_name,
        layer_count=report.layer_count,
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


def latest_browser_load(case_id: str, result_id: str, store_dir: str | Path) -> datetime | None:
    """Return the newest report timestamp for a case/result pair, if any."""

    file_path = Path(store_dir) / BROWSER_LOADS_FILENAME
    if not file_path.exists():
        return None
    latest: datetime | None = None
    with file_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
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
