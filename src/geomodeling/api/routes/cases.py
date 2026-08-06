"""Case creation and dataset upload routes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel, Field

from geomodeling.api.deps import get_platform_runtime
from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.case_lifecycle import CaseLifecycleService

logger = logging.getLogger("geomodeling.api")
from geomodeling.platform.public_dto import public_case, public_dataset
from geomodeling.platform.repositories import CaseRepository, DatasetRepository
from geomodeling.platform.schemas import CaseCreateRequest, CaseRecord, DatasetVersionRecord
from geomodeling.platform.uploads import (
    discard_upload,
    finalize_upload,
    store_upload_stream,
)

router = APIRouter(prefix="/api/cases", tags=["v0.4-cases"])


class CasePurgeBody(BaseModel):
    """Strict purge request body: exact case name confirmation."""

    confirmation_name: str = Field(min_length=1, max_length=256)


@router.post("", status_code=201)
def create_case(
    request: CaseCreateRequest,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    with runtime.session() as session:
        return public_case(CaseRepository(session).create(request))


@router.get("/{case_id}")
def get_case(
    case_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    with runtime.session() as session:
        return public_case(CaseRepository(session).get_active(case_id))


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
    created_dataset_id: str | None = None
    final_path: Path | None = None
    try:
        with runtime.session() as session:
            record = DatasetRepository(session).create_version(
                case_id, source_path="pending://upload"
            )
        created_dataset_id = record.id
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
        # 补偿事务：落盘/建档/序列化任何一步失败，删除可能残留的
        # pending://upload 数据集行、final_path 成品文件与 .part 暂存。
        # 每一步清理各自 try/except：清理失败只记日志（含堆栈），
        # 绝不允许清理异常覆盖最初的业务异常。
        if created_dataset_id is not None:
            try:
                with runtime.session() as session:
                    row = session.get(tables.DatasetVersion, created_dataset_id)
                    if row is not None:
                        session.delete(row)
                        session.commit()
            except Exception:  # noqa: BLE001
                logger.exception("upload compensation: row delete failed for %s", created_dataset_id)
        if final_path is not None:
            try:
                final_path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                logger.exception("upload compensation: finalized file cleanup failed: %s", final_path)
        try:
            discard_upload(receipt)
        except Exception:  # noqa: BLE001
            logger.exception("upload compensation: staged file cleanup failed: %s", receipt.part_path)
        raise


@router.delete("/{case_id}")
def trash_case(
    case_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """Move a user-upload case to the trash (DELETE /api/cases/{id})."""

    record = CaseLifecycleService(runtime).trash(case_id)
    return public_case(record)


@router.post("/{case_id}/restore")
def restore_case(
    case_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """Restore a trashed case to active."""

    record = CaseLifecycleService(runtime).restore(case_id)
    return public_case(record)


@router.post("/{case_id}/purge")
def purge_case(
    case_id: str,
    body: CasePurgeBody,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """Permanently purge a trashed case with exact name confirmation."""

    receipt = CaseLifecycleService(runtime).purge(
        case_id, confirmation_name=body.confirmation_name,
    )
    return receipt
