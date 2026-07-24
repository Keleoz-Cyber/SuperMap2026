"""Dataset inspection and field-mapping routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query

from geomodeling.api.deps import get_platform_runtime
from geomodeling.platform import PlatformRuntime, ingest, tables
from geomodeling.platform.repositories import DatasetRepository
from geomodeling.platform.schemas import DatasetStatus, FieldMapping

router = APIRouter(prefix="/api/datasets", tags=["v0.4-datasets"])


@router.get("/{dataset_id}/inspection")
def inspect_dataset(
    dataset_id: str,
    sheet: str | None = Query(default=None),
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    settings = runtime.settings
    with runtime.session() as session:
        record = DatasetRepository(session).get(dataset_id)
    profile = dict(record.profile)
    result = ingest.inspect_source(
        settings, Path(record.source_path), profile.get("suffix", ""), sheet
    )
    result["dataset_id"] = dataset_id
    result["case_id"] = record.case_id
    result["profile"] = profile
    return result


@router.post("/{dataset_id}/mapping")
def map_dataset(
    dataset_id: str,
    mapping: FieldMapping,
    sheet: str | None = Query(default=None),
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    settings = runtime.settings
    with runtime.session() as session:
        repo = DatasetRepository(session)
        record = repo.get(dataset_id)
        profile = dict(record.profile)
        summary = ingest.standardize(
            settings,
            record.case_id,
            record.id,
            Path(record.source_path),
            profile.get("suffix", ""),
            mapping,
            sheet,
        )
        mapped = repo.transition_status(dataset_id, DatasetStatus.MAPPED)

        profile.update(
            {
                "dimension": mapping.dimension,
                "mapping": mapping.model_dump(mode="json"),
                "sheet": summary["sheet"],
                "row_count": summary["row_count"],
                "valid_row_count": summary["valid_row_count"],
                "invalid_row_count": summary["invalid_row_count"],
                "standardized_path": summary["standardized_path"],
                "standardized_sha256": summary["standardized_sha256"],
            }
        )
        row = session.get(tables.DatasetVersion, dataset_id)
        row.standardized_path = summary["standardized_path"]
        row.profile_json = tables.dumps_canonical(profile)
        session.commit()

    result = mapped.model_dump(mode="json")
    result["profile"] = profile
    return result
