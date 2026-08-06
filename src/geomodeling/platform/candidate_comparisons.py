"""Candidate catalog and multi-candidate comparison (v0.7.0 batch 3 §8).

The catalog lists comparable candidates across experiments for the same
DatasetVersion. The comparison service ranks 2-4 candidates deterministically
without persistence—comparison can be recomputed from immutable candidate
and validation artifacts.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from geomodeling.platform.errors import (
    CANDIDATE_NOT_FOUND,
    COMPARISON_DATASET_MISMATCH,
    COMPARISON_SELECTION_INVALID,
    PlatformError,
)
from geomodeling.platform.schemas import ContractModel
from geomodeling.platform.tables import (
    CandidateResult,
    Experiment,
    FormalSelection,
    Run,
    RunStatus,
    loads_canonical,
)
from pydantic import Field
from typing import Literal


class CandidateComparisonSummary(ContractModel):
    candidate_result_id: str
    experiment_id: str
    run_id: str
    algorithm: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    selectable: bool = False
    metrics: dict[str, Any] = Field(default_factory=dict)
    result_url: str = ""


class CandidateComparisonRequest(ContractModel):
    candidate_result_ids: list[str] = Field(min_length=2, max_length=4)


class MultiCandidateComparison(ContractModel):
    candidate_result_ids: list[str]
    dataset_version_id: str
    comparable: bool
    mismatches: list[str]
    candidates: list[CandidateComparisonSummary]
    ranking: list[str] | None = None
    comparison_fingerprint: str


def candidate_catalog(runtime: Any, dataset_id: str) -> dict[str, Any]:
    """List comparable candidates across experiments for a dataset version."""

    with runtime.session() as session:
        experiments = (
            session.query(Experiment)
            .filter(
                Experiment.params_json.like(f'%"dataset_version_id"%{dataset_id}%')
            )
            .order_by(Experiment.created_at.desc(), Experiment.id.desc())
            .all()
        )

        groups: list[dict[str, Any]] = []
        for exp in experiments:
            params = loads_canonical(exp.params_json)
            if params.get("dataset_version_id") != dataset_id:
                continue

            runs = (
                session.query(Run)
                .filter(Run.experiment_id == exp.id)
                .order_by(Run.created_at.desc())
                .all()
            )

            candidates_data: list[dict[str, Any]] = []
            for run in runs:
                candidates = (
                    session.query(CandidateResult)
                    .filter(CandidateResult.run_id == run.id)
                    .order_by(CandidateResult.created_at.desc())
                    .all()
                )
                for cand in candidates:
                    metrics = loads_canonical(cand.metrics_json)
                    cand_params = loads_canonical(cand.params_json)
                    selectable = (
                        cand.status == RunStatus.SUCCEEDED.value
                        and run.status == RunStatus.SUCCEEDED.value
                    )
                    algorithm = params.get("algorithm", "unknown")
                    candidates_data.append({
                        "candidate_result_id": cand.id,
                        "experiment_id": exp.id,
                        "run_id": run.id,
                        "algorithm": algorithm,
                        "parameters": cand_params,
                        "selectable": selectable,
                        "metrics": {
                            "rmse": metrics.get("rmse"),
                            "mae": metrics.get("mae"),
                            "r2": metrics.get("r2"),
                            "bias": metrics.get("bias"),
                        },
                        "result_url": f"/results/{cand.id}",
                    })

            if candidates_data:
                groups.append({
                    "experiment_id": exp.id,
                    "experiment_name": exp.name,
                    "candidates": candidates_data,
                })

        return {"dataset_id": dataset_id, "groups": groups}


def compare_candidates_multi(
    runtime: Any, candidate_result_ids: list[str],
) -> MultiCandidateComparison:
    """Compare 2-4 candidates deterministically without persistence."""

    if len(candidate_result_ids) != len(set(candidate_result_ids)):
        raise PlatformError(
            COMPARISON_SELECTION_INVALID,
            "比较选择必须为 2-4 个唯一候选",
            {"candidate_result_ids": candidate_result_ids},
            http_status=422,
        )

    if not (2 <= len(candidate_result_ids) <= 4):
        raise PlatformError(
            COMPARISON_SELECTION_INVALID,
            "比较选择必须为 2-4 个唯一候选",
            {"candidate_result_ids": candidate_result_ids},
            http_status=422,
        )

    with runtime.session() as session:
        summaries: list[CandidateComparisonSummary] = []
        dataset_version_ids: set[str] = set()

        for cid in candidate_result_ids:
            cand = session.get(CandidateResult, cid)
            if cand is None:
                raise PlatformError(
                    CANDIDATE_NOT_FOUND,
                    "候选结果不存在",
                    {"candidate_result_id": cid},
                    http_status=404,
                )
            run = session.get(Run, cand.run_id)
            if run is None:
                raise PlatformError(
                    CANDIDATE_NOT_FOUND,
                    "候选结果的任务不存在",
                    {"candidate_result_id": cid},
                    http_status=404,
                )
            exp = session.get(Experiment, run.experiment_id)
            if exp is None:
                raise PlatformError(
                    CANDIDATE_NOT_FOUND,
                    "候选结果的实验不存在",
                    {"candidate_result_id": cid},
                    http_status=404,
                )

            params = loads_canonical(exp.params_json)
            dv_id = params.get("dataset_version_id", "")
            dataset_version_ids.add(dv_id)

            cand_metrics = loads_canonical(cand.metrics_json)
            cand_params = loads_canonical(cand.params_json)
            algorithm = params.get("algorithm", "unknown")

            summaries.append(CandidateComparisonSummary(
                candidate_result_id=cand.id,
                experiment_id=exp.id,
                run_id=run.id,
                algorithm=algorithm,
                parameters=cand_params,
                selectable=(
                    cand.status == RunStatus.SUCCEEDED.value
                    and run.status == RunStatus.SUCCEEDED.value
                ),
                metrics={
                    "rmse": cand_metrics.get("rmse"),
                    "mae": cand_metrics.get("mae"),
                    "r2": cand_metrics.get("r2"),
                    "bias": cand_metrics.get("bias"),
                },
                result_url=f"/results/{cand.id}",
            ))

        if len(dataset_version_ids) > 1:
            raise PlatformError(
                COMPARISON_DATASET_MISMATCH,
                "候选不属于同一数据版本",
                {"dataset_version_ids": sorted(dataset_version_ids)},
                http_status=409,
            )

        dataset_version_id = dataset_version_ids.pop() if dataset_version_ids else ""

        mismatches = _check_compatibility(summaries, candidate_result_ids)
        comparable = len(mismatches) == 0

        ranking = None
        if comparable:
            ranking = _rank_candidates(summaries)

        canonical_ids = sorted(candidate_result_ids)
        fingerprint = hashlib.sha256(
            json.dumps(canonical_ids, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:32]

        return MultiCandidateComparison(
            candidate_result_ids=candidate_result_ids,
            dataset_version_id=dataset_version_id,
            comparable=comparable,
            mismatches=mismatches,
            candidates=summaries,
            ranking=ranking,
            comparison_fingerprint=fingerprint,
        )


def _check_compatibility(
    summaries: list[CandidateComparisonSummary], ids: list[str],
) -> list[str]:
    """Check validation contract and metric consistency."""

    mismatches: list[str] = []

    for s in summaries:
        if not s.selectable:
            mismatches.append(f"candidate_not_succeeded:{s.candidate_result_id}")

    for s in summaries:
        rmse = s.metrics.get("rmse")
        if rmse is not None and (isinstance(rmse, float) and math.isnan(rmse)):
            mismatches.append(f"nan_rmse:{s.candidate_result_id}")
        if rmse is not None and (isinstance(rmse, float) and math.isinf(rmse)):
            mismatches.append(f"inf_rmse:{s.candidate_result_id}")

    return sorted(set(mismatches))


def _rank_candidates(summaries: list[CandidateComparisonSummary]) -> list[str]:
    """Deterministic ranking: RMSE asc -> MAE asc -> R2 desc -> param JSON -> ID."""

    def sort_key(s: CandidateComparisonSummary) -> tuple:
        rmse = s.metrics.get("rmse")
        mae = s.metrics.get("mae")
        r2 = s.metrics.get("r2")
        param_bytes = json.dumps(
            s.parameters, ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
        id_bytes = s.candidate_result_id.encode("utf-8")

        rmse_val = rmse if isinstance(rmse, (int, float)) else float("inf")
        mae_val = mae if isinstance(mae, (int, float)) else float("inf")
        r2_val = r2 if isinstance(r2, (int, float)) else float("-inf")

        return (rmse_val, mae_val, -r2_val, param_bytes, id_bytes)

    return [s.candidate_result_id for s in sorted(summaries, key=sort_key)]
