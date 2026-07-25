"""Case creation and dataset upload routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, UploadFile

from geomodeling.api.deps import get_platform_runtime
from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.public_dto import public_case, public_dataset
from geomodeling.platform.repositories import CaseRepository, DatasetRepository
from geomodeling.platform.schemas import CaseCreateRequest, CaseRecord, DatasetVersionRecord
from geomodeling.platform.uploads import (
    discard_upload,
    finalize_upload,
    store_upload_stream,
)

router = APIRouter(prefix="/api/cases", tags=["v0.4-cases"])


@router.post("", status_code=201)
def create_case(
    request: CaseCreateRequest,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> CaseRecord:
    with runtime.session() as session:
        return CaseRepository(session).create(request)


@router.get("/{case_id}")
def get_case(
    case_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    with runtime.session() as session:
        return public_case(CaseRepository(session).get(case_id))


@router.get("/{case_id}/datasets")
def list_case_datasets(
    case_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    with runtime.session() as session:
        CaseRepository(session).get(case_id)
        records = DatasetRepository(session).list_for_case(case_id)
    return {"datasets": [public_dataset(record) for record in records]}


@router.post("/{case_id}/datasets/uploads", status_code=201)
async def upload_dataset(
    case_id: str,
    file: UploadFile,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    settings = runtime.settings
    receipt = store_upload_stream(settings, file.file, file.filename or "")
    try:
        with runtime.session() as session:
            record = DatasetRepository(session).create_version(
                case_id, source_path="pending://upload"
            )
        final_path = settings.upload_source(case_id, record.id, receipt.suffix)
        finalize_upload(receipt, final_path)
        with runtime.session() as session:
            row = session.get(tables.DatasetVersion, record.id)
            row.source_path = str(final_path)
            profile = tables.loads_canonical(row.profile_json)
            profile.update(
                {
                    "original_filename": receipt.original_filename,
                    "suffix": receipt.suffix,
                    "size_bytes": receipt.size_bytes,
                    "source_sha256": receipt.sha256,
                }
            )
            row.profile_json = tables.dumps_canonical(profile)
            session.commit()
            return public_dataset(DatasetRepository(session).get(record.id))
    except BaseException:
        discard_upload(receipt)
        raise
