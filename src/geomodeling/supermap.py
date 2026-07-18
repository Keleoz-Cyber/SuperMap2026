from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig
from .io import read_json, sha256_file, write_json
from .schemas import (
    EvidenceLevel,
    ModelStatus,
    ResultCategory,
    ResultInventoryItem,
    SuperMapResultRegistration,
    SuperMapVerificationReport,
)


class SuperMapRegistry:
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def register(self, registration: SuperMapResultRegistration) -> Path:
        path = self.base_dir / f"{registration.dataset}.json"
        return write_json(path, registration)

    def list(self) -> list[SuperMapResultRegistration]:
        return [SuperMapResultRegistration.model_validate(read_json(path)) for path in sorted(self.base_dir.glob("*.json"))]


def registrations_from_config(config: AppConfig, udbx_path: str | None = None) -> list[SuperMapResultRegistration]:
    records = []
    for entry in config.supermap.get("results", []):
        rows = entry.get("rows")
        columns = entry.get("columns")
        bands = entry.get("bands")
        cell_count = rows * columns * bands if rows is not None and columns is not None and bands is not None else None
        status = ModelStatus(entry["status"])
        object_count = entry.get("object_count")
        if status == ModelStatus.SUCCEEDED and object_count is None:
            object_count = cell_count
        parameters = {
            key: value
            for key, value in entry.items()
            if key
            not in {
                "dataset",
                "model_id",
                "dataset_type",
                "method",
                "status",
                "result_category",
                "rows",
                "columns",
                "bands",
                "value_min",
                "value_max",
                "object_count",
                "openable",
                "error_evidence",
                "manual_evidence",
            }
        }
        records.append(
            SuperMapResultRegistration(
                dataset=entry["dataset"],
                model_id=entry["model_id"],
                dataset_type=entry["dataset_type"],
                method=entry["method"],
                datasource_alias=config.supermap["datasource_alias"],
                udbx_path=udbx_path or config.supermap.get("udbx_path"),
                status=status,
                result_category=entry["result_category"],
                rows=rows,
                columns=columns,
                bands=bands,
                cell_count=cell_count,
                object_count=object_count,
                value_min=entry.get("value_min"),
                value_max=entry.get("value_max"),
                openable=bool(entry.get("openable", False)),
                parameters=parameters,
                error_evidence=entry.get("error_evidence"),
                evidence_level=EvidenceLevel.DECLARED,
                file_verified=False,
                dataset_verified=False,
                dataset_verification_note="dataset-level verification not performed: no supported SuperMap API adapter configured",
                manual_evidence=list(entry.get("manual_evidence", [])),
            )
        )
    return records


def _enum_value(value):
    return getattr(value, "value", value)


def _file_evidence(path: Path | None, compute_hash: bool = True) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"file_verified": False, "file_exists": False}
    stat = path.stat()
    return {
        "file_verified": True,
        "file_exists": True,
        "file_size_bytes": int(stat.st_size),
        "file_mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        "file_sha256": sha256_file(path) if compute_hash else None,
    }


def verify_supermap_results(
    config: AppConfig,
    udbx_path: str | None = None,
    compute_hash: bool = True,
) -> list[SuperMapResultRegistration]:
    configured = udbx_path or config.supermap.get("udbx_path")
    resolved = config.resolve_path(configured) if configured else None
    evidence = _file_evidence(resolved, compute_hash=compute_hash)
    records = []
    for record in registrations_from_config(config, udbx_path=str(resolved) if resolved else configured):
        if evidence["file_verified"]:
            update = {
                "evidence_level": EvidenceLevel.FILE_VERIFIED,
                "file_verified": True,
                "file_size_bytes": evidence["file_size_bytes"],
                "file_mtime": evidence["file_mtime"],
                "file_sha256": evidence["file_sha256"],
                "dataset_verified": False,
                "dataset_verification_note": "dataset-level verification not performed: no supported SuperMap API adapter configured",
            }
        else:
            update = {
                "evidence_level": EvidenceLevel.DECLARED,
                "file_verified": False,
                "file_size_bytes": None,
                "file_mtime": None,
                "file_sha256": None,
                "dataset_verified": False,
                "dataset_verification_note": "dataset-level verification not performed: no supported SuperMap API adapter configured",
            }
        records.append(record.model_copy(update=update))
    return records


def verification_report(
    config: AppConfig,
    records: list[SuperMapResultRegistration],
    udbx_path: str | None = None,
) -> SuperMapVerificationReport:
    configured = udbx_path or config.supermap.get("udbx_path")
    resolved = config.resolve_path(configured) if configured else None
    file_exists = bool(resolved and resolved.is_file())
    return SuperMapVerificationReport(
        udbx_path=str(resolved) if resolved else configured,
        file_exists=file_exists,
        file_verified=file_exists,
        dataset_api=str(config.supermap.get("dataset_api", "none")),
        dataset_verified=False,
        records=records,
    )


def result_inventory(records: list[SuperMapResultRegistration]) -> list[ResultInventoryItem]:
    items = []
    for record in records:
        items.append(
            ResultInventoryItem(
                name=record.dataset,
                category=record.result_category,
                status=record.status,
                path=record.udbx_path,
                supermap_dataset=record.dataset,
                evidence_level=record.evidence_level,
                trace={
                    "model_id": record.model_id,
                    "datasource_alias": record.datasource_alias,
                    "dataset_type": record.dataset_type,
                    "rows": record.rows,
                    "columns": record.columns,
                    "bands": record.bands,
                    "object_count": record.object_count,
                    "error_evidence": record.error_evidence,
                    "file_verified": record.file_verified,
                    "dataset_verified": record.dataset_verified,
                    "manual_evidence": record.manual_evidence,
                },
            )
        )
    return items


def select_supermap_result_for_model(
    records: list[SuperMapResultRegistration], model_id: str
) -> SuperMapResultRegistration | None:
    candidates = [record for record in records if record.model_id == model_id]
    for record in candidates:
        if (
            _enum_value(record.result_category) == ResultCategory.FORMAL.value
            and _enum_value(record.status) == ModelStatus.SUCCEEDED.value
            and record.object_count != 0
            and record.openable
        ):
            return record
    for record in candidates:
        if _enum_value(record.status) == ModelStatus.SUCCEEDED.value and record.object_count != 0 and record.openable:
            return record
    return None


def formal_results(records: list[SuperMapResultRegistration]) -> list[SuperMapResultRegistration]:
    return [
        record
        for record in records
        if _enum_value(record.result_category) == ResultCategory.FORMAL.value
        and _enum_value(record.status) == ModelStatus.SUCCEEDED.value
        and record.object_count != 0
        and record.openable
    ]
