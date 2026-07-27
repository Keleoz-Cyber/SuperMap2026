"""Experiment and candidate-listing routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select

from geomodeling.api.deps import get_platform_runtime
from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.errors import PlatformError, RUN_ALREADY_ACTIVE
from geomodeling.platform.experiments import resolve_professional_context
from geomodeling.platform.jobs import assert_quality_gate
from geomodeling.platform.repositories import DatasetRepository, ExperimentRepository, RunRepository
from geomodeling.platform.schemas import ExperimentCreateRequest, ExperimentRecord, RunRecord

router = APIRouter(prefix="/api/experiments", tags=["v0.4-experiments"])


@router.post("", status_code=201)
def create_experiment(
    request: ExperimentCreateRequest,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> ExperimentRecord:
    with runtime.session() as session:
        dataset = DatasetRepository(session).get_for_case(request.case_id, request.dataset_version_id)
        assert_quality_gate(dataset.profile)
        # v0.6：专业输入（确认快照/搜索邻域/经验不确定性）前置校验与解析；
        # legacy 请求（三字段全缺）返回 None，行为逐位不变。
        professional = resolve_professional_context(session, request, dataset)
        return ExperimentRepository(session).create(
            request.case_id, request, professional=professional
        )


@router.get("/{experiment_id}")
def get_experiment(
    experiment_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> ExperimentRecord:
    with runtime.session() as session:
        return ExperimentRepository(session).get(experiment_id)


@router.post("/{experiment_id}/runs", status_code=201)
def create_run(
    experiment_id: str,
    request: Request,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> RunRecord:
    with runtime.session() as session:
        ExperimentRepository(session).get(experiment_id)
        active = session.scalar(
            select(func.count(tables.Run.id)).where(
                tables.Run.experiment_id == experiment_id,
                tables.Run.status.in_(sorted(tables.RUN_INFLIGHT_STATUSES)),
            )
        )
        if active:
            raise PlatformError(
                RUN_ALREADY_ACTIVE,
                "该实验已有排队或运行中的任务",
                {"experiment_id": experiment_id},
                http_status=409,
            )
        record = RunRepository(session).create(experiment_id)
    worker = getattr(request.app.state, "job_worker", None)
    if worker is not None:
        worker.enqueue(record.id)
    return record


@router.get("/{experiment_id}/candidates")
def list_candidates(
    experiment_id: str,
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    with runtime.session() as session:
        ExperimentRepository(session).get(experiment_id)
        runs = (
            session.query(tables.Run)
            .filter(tables.Run.experiment_id == experiment_id)
            .order_by(tables.Run.created_at.desc())
            .all()
        )
        latest = runs[0] if runs else None
        candidates: list[dict[str, Any]] = []
        public_metrics: dict[str, Any] = {}
        if latest is not None:
            rows = (
                session.query(tables.CandidateResult)
                .filter(tables.CandidateResult.run_id == latest.id)
                .order_by(tables.CandidateResult.created_at.asc())
                .all()
            )
            for row in rows:
                candidates.append(
                    {
                        "id": row.id,
                        "fingerprint": row.fingerprint,
                        "status": row.status,
                        "parameters": tables.loads_canonical(row.params_json),
                        "metrics": tables.loads_canonical(row.metrics_json),
                        "error": tables.loads_canonical(row.error_json) if row.error_json else None,
                    }
                )
            public_metrics = tables.loads_canonical(latest.metrics_json).get("public_metrics", {})
    candidates.sort(
        key=lambda c: (
            c["status"] != "succeeded",
            c["metrics"].get("rmse") if c["metrics"].get("rmse") is not None else float("inf"),
        )
    )
    latest_run = None
    if latest is not None:
        latest_run = RunRepository(session).get(latest.id).model_dump(mode="json")
    return {
        "experiment_id": experiment_id,
        "candidates": candidates,
        "public_metrics": public_metrics,
        "latest_run": latest_run,
    }
