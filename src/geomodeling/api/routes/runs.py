"""Run inspection, cancel, and retry routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from geomodeling.api.deps import get_platform_runtime
from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.errors import PlatformError, RUN_NOT_RETRYABLE
from geomodeling.platform.repositories import RunRepository
from geomodeling.platform.schemas import RunRecord

router = APIRouter(prefix="/api/runs", tags=["v0.4-runs"])


def _worker(request: Request):
    return getattr(request.app.state, "job_worker", None)


@router.get("/{run_id}")
def get_run(
    run_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    with runtime.session() as session:
        record = RunRepository(session).get(run_id)
    body = record.model_dump(mode="json")
    return body


RUN_NOT_CANCELABLE = "RUN_NOT_CANCELABLE"


@router.post("/{run_id}/cancel")
def cancel_run(
    run_id: str,
    request: Request,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> RunRecord:
    with runtime.session() as session:
        repo = RunRepository(session)
        record = repo.get(run_id)
        if record.status in tables.RUN_TERMINAL_STATUSES:
            raise PlatformError(
                RUN_NOT_CANCELABLE,
                "终态任务不能取消（已成功/失败/取消/中断的任务不可再变更）",
                {"run_id": run_id, "status": record.status},
                http_status=409,
            )
        if record.status == "queued":
            # 未开始：直接原子转为 canceled（CAS）
            record = repo.cancel(run_id)
        else:
            # running：只原子写取消旗标，由 runner 在候选间协作退出并自行转 canceled
            worker = _worker(request)
            if worker is not None:
                worker.cancel(run_id)
            record = repo.get(run_id)
    return record


@router.post("/{run_id}/retry", status_code=201)
def retry_run(
    run_id: str,
    request: Request,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> RunRecord:
    with runtime.session() as session:
        record = RunRepository(session).retry(run_id)
    worker = _worker(request)
    if worker is not None:
        worker.enqueue(record.id)
    return record
