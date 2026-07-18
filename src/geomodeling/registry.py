from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import read_json, write_json
from .schemas import DatasetRegistration, ValidationReport


class DatasetRegistry:
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def register(self, registration: DatasetRegistration) -> dict[str, Any]:
        path = self.base_dir / f"{registration.dataset_id}.json"
        duplicate_sha256 = False
        if path.exists():
            existing = DatasetRegistration.model_validate(read_json(path))
            duplicate_sha256 = existing.sha256 == registration.sha256
        write_json(path, registration)
        return {"path": str(path), "duplicate_sha256": duplicate_sha256}

    def save_validation_report(self, report: ValidationReport) -> Path:
        path = self.base_dir / f"{report.dataset_id}.validation.json"
        return write_json(path, report)

    def list(self) -> list[DatasetRegistration]:
        records = []
        for path in sorted(self.base_dir.glob("*.json")):
            if path.name.endswith(".validation.json"):
                continue
            records.append(DatasetRegistration.model_validate(read_json(path)))
        return records
