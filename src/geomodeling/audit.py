from __future__ import annotations

import getpass
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import sha256_file

SENSITIVE_KEYS = {"password", "passwd", "token", "secret", "cookie", "authorization", "api_key", "apikey"}


def _safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("<redacted>" if key.lower() in SENSITIVE_KEYS else _safe_value(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    return value


def _input_record(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    exists = candidate.is_file()
    return {
        "path": str(candidate),
        "exists": exists,
        "sha256": sha256_file(candidate) if exists else None,
    }


class AuditLogger:
    def __init__(self, log_dir: str | Path):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / "audit.jsonl"

    def log(
        self,
        command: str,
        status: str,
        inputs: list[str | Path] | None = None,
        parameters: dict[str, Any] | None = None,
        supermap_version: str | None = None,
        outputs: list[str | Path] | None = None,
        error: str | None = None,
    ) -> Path:
        record = {
            "command": command,
            "operator": getpass.getuser(),
            "utc_time": datetime.now(timezone.utc).isoformat(),
            "inputs": [_input_record(item) for item in (inputs or [])],
            "parameters": _safe_value(parameters or {}),
            "supermap_version": supermap_version,
            "status": status,
            "outputs": [str(item) for item in (outputs or [])],
            "error": error,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return self.path
