"""Bounded trash-list route for trashed cases (v0.7.0 batch 3 §5.3)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from geomodeling.api.deps import get_platform_runtime
from geomodeling.platform import PlatformRuntime
from geomodeling.platform.tables import (
    CandidateResult,
    Case,
    DatasetVersion,
    Experiment,
    Run,
    loads_canonical,
)
from geomodeling.platform.repositories import CaseRepository

router = APIRouter(prefix="/api/trash", tags=["v0.7-trash"])


@router.get("/cases")
def list_trash_cases(
    runtime: PlatformRuntime = Depends(get_platform_runtime),
) -> dict[str, Any]:
    """Bounded trash summaries: name, trashed_at, counts, can_restore, can_purge."""

    items: list[dict[str, Any]] = []
    with runtime.session() as session:
        rows = (
            session.query(Case)
            .filter(Case.lifecycle_state == "trashed")
            .order_by(Case.trashed_at.desc(), Case.id.desc())
            .all()
        )
        for row in rows:
            config = loads_canonical(row.config_json)
            workspace_kind = config.get("workspace_kind", "user_upload")
            is_read_only = config.get("read_only") is True
            can_restore = workspace_kind == "user_upload" and not is_read_only
            can_purge = can_restore

            dataset_count = session.scalar(
                select(DatasetVersion).where(DatasetVersion.case_id == row.id)
            )
            ds_count = (
                session.query(DatasetVersion)
                .filter(DatasetVersion.case_id == row.id)
                .count()
            )
            exp_count = (
                session.query(Experiment)
                .filter(Experiment.case_id == row.id)
                .count()
            )
            result_count = (
                session.query(CandidateResult)
                .join(Run, CandidateResult.run_id == Run.id)
                .join(Experiment, Run.experiment_id == Experiment.id)
                .filter(Experiment.case_id == row.id)
                .count()
            )

            items.append({
                "case_id": row.id,
                "name": row.name,
                "trashed_at": row.trashed_at,
                "counts": {
                    "datasets": ds_count,
                    "experiments": exp_count,
                    "results": result_count,
                },
                "can_restore": can_restore,
                "can_purge": can_purge,
                "reason": None,
            })

    return {"cases": items}
