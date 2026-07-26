"""Leakage-safe experiment runner.

Each candidate is evaluated fold by fold: the interpolator is fit on
training rows only and predicts held-out rows, so validation values never
reach a fit. Predictions are stored by stable ``source_row``. After all
candidates finish, a public common-valid mask is computed across succeeded
candidates and every public metric is recomputed on exactly that mask;
per-candidate coverage stays separate so NoData cannot buy rank.

Fold evidence is run-level (Task 9): the split plan and its leakage check
are built once before any candidate row is persisted — leakage or an
incomplete plan fails the whole run closed. Each succeeded candidate also
persists out-of-fold residual records plus the shared fold assignment
table under ``results/<candidate_id>/professional/``; candidate metrics
reference both artifacts by SHA-256, and inconsistent OOF evidence fails
the run instead of the candidate.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any

import numpy as np
import pandas as pd

from geomodeling.modeling.contracts import Fold
from geomodeling.modeling.fold_artifacts import (
    FOLD_ARTIFACT_WRITE_FAILED,
    build_fold_assignments,
    build_oof_predictions,
    sha256_file,
    write_artifact_parquet,
)
from geomodeling.modeling.idw import IDWInterpolator
from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator
from geomodeling.modeling.metrics import common_valid_mask, compute_metrics
from geomodeling.modeling.provenance import (
    compute_group_diagnostics,
    ensure_provenance_coverage,
    load_optional_provenance,
)
from geomodeling.modeling.splits import build_spatial_splits
from geomodeling.platform import tables
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.experiments import expand_candidates
from geomodeling.platform.repositories import RunRepository
from geomodeling.platform.schemas import Algorithm, SpatialValidationSpec
from geomodeling.platform.settings import PlatformSettings

RUN_CANCELED = "RUN_CANCELED"
METRICS_EMPTY_COMMON_VALID = "METRICS_EMPTY_COMMON_VALID"

_INTERPOLATORS = {
    Algorithm.IDW.value: IDWInterpolator(),
    Algorithm.ORDINARY_KRIGING.value: OrdinaryKrigingInterpolator(),
}


@dataclass(frozen=True)
class RunOutcome:
    run_id: str
    status: str
    total: int
    completed: int
    failed: int


def _interpolator(algorithm: str):
    return _INTERPOLATORS[Algorithm(algorithm).value]


def _load_experiment(runtime, run_id: str) -> tuple[Any, dict[str, Any]]:
    with runtime.session() as session:
        run = session.get(tables.Run, run_id)
        if run is None:
            raise PlatformError("RUN_NOT_FOUND", "任务不存在", {"run_id": run_id}, http_status=404)
        experiment = session.get(tables.Experiment, run.experiment_id)
        params = tables.loads_canonical(experiment.params_json)
        return experiment, params


def _load_frame(runtime: PlatformRuntime, case_id: str, dataset_id: str) -> pd.DataFrame:
    path = runtime.settings.standardized_dataset(case_id, dataset_id)
    if not path.exists():
        raise PlatformError(
            "DATASET_NOT_FOUND",
            "标准化数据不存在",
            {"dataset_id": dataset_id},
            http_status=404,
        )
    return pd.read_parquet(path)


def _evaluate_candidate(
    *,
    interpolator,
    dimension: str,
    frame: pd.DataFrame,
    folds: list[Fold],
    parameters: dict[str, Any],
    predictions_path: Path,
    cancel: Event,
) -> dict[str, Any]:
    valid = frame.loc[frame["is_numeric_valid"]].reset_index(drop=True)
    coord_cols = ["x", "y"] + (["z"] if dimension == "3d" else [])
    points = valid[coord_cols].to_numpy(dtype="float64")
    values = valid["value"].to_numpy(dtype="float64")
    source_rows = valid["source_row"].to_numpy(dtype="int64")

    validated = interpolator.validate_parameters(parameters, dimension)

    started = time.perf_counter()
    records: list[pd.DataFrame] = []
    fold_metrics: list[dict[str, float]] = []
    for fold in folds:
        if cancel.is_set():
            raise PlatformError(RUN_CANCELED, "任务已被取消", {"fold": fold.index}, http_status=409)
        train_coords = points[fold.training_indices]
        train_values = values[fold.training_indices]
        query = points[fold.validation_indices]
        fitted = interpolator.fit(train_coords, train_values, validated)
        batch = fitted.predict(query, cancel=cancel.is_set)
        truth = values[fold.validation_indices]
        mask = ~batch.is_nodata
        part = pd.DataFrame(
            {
                "source_row": source_rows[fold.validation_indices],
                "fold": fold.index,
                "truth": truth,
                "prediction": batch.values,
                "is_nodata": batch.is_nodata,
            }
        )
        records.append(part)
        if mask.any():
            fold_metrics.append(
                {
                    "fold": fold.index,
                    "rmse": float(np.sqrt(((batch.values[mask] - truth[mask]) ** 2).mean())),
                    "valid_count": int(mask.sum()),
                }
            )
    runtime_seconds = time.perf_counter() - started

    predictions = pd.concat(records, ignore_index=True)
    predictions_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = predictions_path.with_suffix(".tmp.parquet")
    predictions.to_parquet(tmp, index=False)
    import os

    os.replace(tmp, predictions_path)

    own_mask = ~predictions["is_nodata"].to_numpy()
    if own_mask.any():
        summary = compute_metrics(
            predictions["truth"].to_numpy(), predictions["prediction"].to_numpy(), own_mask
        )
        metrics = {
            "rmse": summary.rmse,
            "mae": summary.mae,
            "r2": summary.r2,
            "bias": summary.bias,
            "coverage": summary.coverage,
            "common_valid_count": summary.common_valid_count,
            "candidate_valid_count": summary.candidate_valid_count,
            "candidate_nodata_count": summary.candidate_nodata_count,
            "total_count": summary.total_count,
        }
    else:
        metrics = {
            "rmse": None,
            "mae": None,
            "r2": None,
            "bias": None,
            "coverage": 0.0,
            "common_valid_count": 0,
            "candidate_valid_count": 0,
            "candidate_nodata_count": int(own_mask.size),
            "total_count": int(own_mask.size),
        }
    metrics["runtime_seconds"] = runtime_seconds
    metrics["fold_metrics"] = fold_metrics
    return {"predictions": predictions, "metrics": metrics}


def _persist_progress(runtime, run_id: str, progress: dict[str, Any]) -> None:
    with runtime.session() as session:
        row = session.get(tables.Run, run_id)
        row.metrics_json = tables.dumps_canonical(progress)
        session.commit()


def execute_run(runtime, run_id: str, cancel: Event) -> RunOutcome:
    """Execute one queued run end-to-end (called by the worker thread)."""

    experiment, params = _load_experiment(runtime, run_id)
    search = {
        "algorithm": params["algorithm"],
        "search_mode": params.get("search_mode", "manual"),
        "parameters": params.get("parameters") or {},
        "validation": params.get("validation"),
        "grid": params.get("grid"),
    }
    candidates = expand_candidates(search)
    dataset_id = params["dataset_version_id"]
    frame = _load_frame(runtime, experiment.case_id, dataset_id)

    with runtime.session() as session:
        dataset = session.get(tables.DatasetVersion, dataset_id)
        profile = tables.loads_canonical(dataset.profile_json)
    mapping = profile.get("mapping", {})
    dimension = "3d" if mapping.get("dimension") == "3d" else "2d"
    interpolator = _interpolator(params["algorithm"])
    validation = SpatialValidationSpec.model_validate(params.get("validation") or {})

    with runtime.session() as session:
        repo = RunRepository(session)
        current = repo.get(run_id)
        if current.status == "canceled" or current.metrics.get("cancel_requested"):
            if current.status != "canceled":
                repo.cancel(run_id)
            return RunOutcome(run_id, "canceled", 0, 0, 0)
        repo.mark_running(run_id)

    total = len(candidates)
    completed = 0
    failed = 0
    progress = {"current_candidate": None, "completed": 0, "total": total, "failed": 0}
    _persist_progress(runtime, run_id, progress)

    # 可选 provenance sidecar：profile 声明了就必须完整有效，否则 fail closed，
    # run 直接失败且不产生任何候选；未声明则保持通用行为逐位不变。
    try:
        provenance = load_optional_provenance(runtime.settings, experiment.case_id, dataset_id, profile)
        if provenance is not None:
            ensure_provenance_coverage(provenance, frame["source_row"])
    except PlatformError as exc:
        with runtime.session() as session:
            RunRepository(session).mark_failed(run_id, error_code=exc.code, metrics=progress)
        return RunOutcome(run_id, "failed", total, 0, 0)

    # Task 9：折分与泄漏检查是 run 级证据，先于任何候选行持久化。泄漏或
    # 折分结构不完整 → 整次运行结构化失败（fail-closed），不产生候选。
    data_sha256 = profile.get("standardized_sha256") or sha256_file(
        runtime.settings.standardized_dataset(experiment.case_id, dataset_id)
    )
    valid_frame = frame.loc[frame["is_numeric_valid"]].reset_index(drop=True)
    coord_cols = ["x", "y"] + (["z"] if dimension == "3d" else [])
    valid_points = valid_frame[coord_cols].to_numpy(dtype="float64")
    try:
        folds = build_spatial_splits(valid_points, dimension, validation)
        fold_assignments, _fingerprint = build_fold_assignments(
            valid_frame,
            folds,
            dimension=dimension,
            validation=validation,
            data_sha256=data_sha256,
        )
    except PlatformError as exc:
        with runtime.session() as session:
            RunRepository(session).mark_failed(run_id, error_code=exc.code, metrics=progress)
        return RunOutcome(run_id, "failed", total, 0, 0)

    experiment_dir = runtime.settings.experiment_dir(experiment.id)
    succeeded: list[tuple[str, pd.DataFrame, dict[str, Any], str]] = []

    for candidate in candidates:
        if cancel.is_set():
            with runtime.session() as session:
                RunRepository(session).cancel(run_id)
            return RunOutcome(run_id, "canceled", total, completed, failed)

        progress["current_candidate"] = candidate.index
        _persist_progress(runtime, run_id, progress)

        result_id = str(uuid.uuid4())
        predictions_path = experiment_dir / "candidates" / f"{candidate.fingerprint[:12]}.parquet"
        status = "succeeded"
        error: dict[str, Any] | None = None
        try:
            outcome = _evaluate_candidate(
                interpolator=interpolator,
                dimension=dimension,
                frame=frame,
                folds=folds,
                parameters=candidate.parameters,
                predictions_path=predictions_path,
                cancel=cancel,
            )
        except PlatformError as exc:
            if exc.code == RUN_CANCELED:
                with runtime.session() as session:
                    RunRepository(session).cancel(run_id)
                return RunOutcome(run_id, "canceled", total, completed, failed)
            status = "failed"
            error = {"code": exc.code, "message": exc.message}
            outcome = None
        except Exception as exc:  # 单个候选失败保留证据，不拖垮整个 run
            status = "failed"
            error = {"code": "CANDIDATE_EVALUATION_FAILED", "message": str(exc)[:500]}
            outcome = None

        if outcome is not None:
            # Task 9：折外证据（OOF 记录 + run 级折分分配）随候选落盘到
            # results/<candidate_id>/professional/。证据不完整（source_row
            # 不匹配、写入校验失败）→ 整次运行失败，候选行不落盘。
            professional_dir = runtime.settings.professional_result_dir(result_id)
            try:
                oof = build_oof_predictions(
                    valid_frame, folds, outcome["predictions"], dimension=dimension
                )
                oof_sha256 = write_artifact_parquet(
                    professional_dir / "out_of_fold_predictions.parquet", oof
                )
                assignments_sha256 = write_artifact_parquet(
                    professional_dir / "fold_assignments.parquet", fold_assignments
                )
            except PlatformError as exc:
                with runtime.session() as session:
                    RunRepository(session).mark_failed(run_id, error_code=exc.code, metrics=progress)
                return RunOutcome(run_id, "failed", total, completed, failed)
            except Exception:
                with runtime.session() as session:
                    RunRepository(session).mark_failed(
                        run_id, error_code=FOLD_ARTIFACT_WRITE_FAILED, metrics=progress
                    )
                return RunOutcome(run_id, "failed", total, completed, failed)
            outcome["metrics"]["fold_assignments_sha256"] = assignments_sha256
            outcome["metrics"]["oof_predictions_sha256"] = oof_sha256

        with runtime.session() as session:
            session.add(
                tables.CandidateResult(
                    id=result_id,
                    run_id=run_id,
                    category="candidate",
                    fingerprint=candidate.fingerprint,
                    status=status,
                    params_json=tables.dumps_canonical(candidate.parameters),
                    metrics_json=tables.dumps_canonical(outcome["metrics"] if outcome else {}),
                    error_json=tables.dumps_canonical(error) if error else None,
                    predictions_path=str(predictions_path) if outcome else None,
                )
            )
            session.commit()
        if outcome is not None:
            succeeded.append((result_id, outcome["predictions"], outcome["metrics"], candidate.fingerprint))
            completed += 1
        else:
            failed += 1
        progress.update({"completed": completed, "failed": failed})
        _persist_progress(runtime, run_id, progress)

    # ------------------------------------------------------------------
    # 公共有效集合：只在成功候选的交集上复算公共指标
    # ------------------------------------------------------------------
    # 零自身有效点的候选先单独判失败（无法参与公共集合，且不拖垮其他候选）
    contributing: list[tuple[str, pd.DataFrame, dict[str, Any], str]] = []
    with runtime.session() as session:
        for result_id, predictions, metrics, fingerprint in succeeded:
            if int((~predictions["is_nodata"].to_numpy()).sum()) == 0:
                session.query(tables.CandidateResult).filter(
                    tables.CandidateResult.id == result_id
                ).update(
                    {
                        "status": "failed",
                        "error_json": tables.dumps_canonical(
                            {"code": METRICS_EMPTY_COMMON_VALID, "message": "该候选没有有效预测点，公共有效集合为空"}
                        ),
                    }
                )
                failed += 1
                completed -= 1
            else:
                contributing.append((result_id, predictions, metrics, fingerprint))
        session.commit()

    common_mask = None
    public: dict[str, Any] = {"common_valid_count": 0}
    common_valid = 0
    if contributing:
        common_mask = common_valid_mask({fp: (p["prediction"].to_numpy(), p["is_nodata"].to_numpy()) for _id, p, _m, fp in contributing})
        total_count = int(common_mask.size)
        common_valid = int(common_mask.sum())
        public = {
            "common_valid_count": common_valid,
            "total_count": total_count,
            "coverage": common_valid / total_count,
        }

        with runtime.session() as session:
            for result_id, predictions, metrics, fingerprint in contributing:
                if common_valid == 0:
                    session.query(tables.CandidateResult).filter(
                        tables.CandidateResult.id == result_id
                    ).update(
                        {
                            "status": "failed",
                            "error_json": tables.dumps_canonical(
                                {"code": METRICS_EMPTY_COMMON_VALID, "message": "公共有效集合为空"}
                            ),
                        }
                    )
                    failed += 1
                    completed -= 1
                    continue
                truth = predictions["truth"].to_numpy()
                public_summary = compute_metrics(
                    truth,
                    predictions["prediction"].to_numpy(),
                    common_mask,
                    is_nodata=predictions["is_nodata"].to_numpy(),
                )
                metrics.update(
                    {
                        "rmse": public_summary.rmse,
                        "mae": public_summary.mae,
                        "r2": public_summary.r2,
                        "bias": public_summary.bias,
                        "coverage": public_summary.coverage,
                        "common_valid_count": public_summary.common_valid_count,
                        "candidate_valid_count": public_summary.candidate_valid_count,
                        "candidate_nodata_count": public_summary.candidate_nodata_count,
                        "total_count": public_summary.total_count,
                    }
                )
                # 分组诊断只在公共有效掩膜上复算，不参与 best 选择与覆盖率
                if provenance is not None:
                    metrics["group_diagnostics"] = compute_group_diagnostics(
                        predictions, provenance, common_mask
                    )
                session.query(tables.CandidateResult).filter(
                    tables.CandidateResult.id == result_id
                ).update({"metrics_json": tables.dumps_canonical(metrics)})
            session.commit()
    succeeded = contributing if (contributing and common_valid > 0) else []

    final_failed = failed
    final_completed = completed
    progress.update(
        {
            "current_candidate": None,
            "completed": final_completed,
            "failed": final_failed,
            "total": total,
        }
    )
    if final_completed:
        best = min(
            (m for _id, _p, m, _fp in succeeded),
            key=lambda m: (m.get("rmse") if m.get("rmse") is not None else float("inf")),
        )
        public.update(
            {
                "rmse": best.get("rmse"),
                "mae": best.get("mae"),
                "r2": best.get("r2"),
                "bias": best.get("bias"),
            }
        )
        progress["public_metrics"] = public
        with runtime.session() as session:
            RunRepository(session).mark_succeeded(run_id, metrics=progress)
        return RunOutcome(run_id, "succeeded", total, final_completed, final_failed)

    progress["public_metrics"] = public
    with runtime.session() as session:
        RunRepository(session).mark_failed(run_id, error_code="ALL_CANDIDATES_FAILED", metrics=progress)
    return RunOutcome(run_id, "failed", total, final_completed, final_failed)
