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

v0.6 专业候选（Task 14，设计 §4.2）：实验携带专业上下文（确认快照/搜索
邻域/经验不确定性）时，折证据建成后以「标准化数据 SHA-256 + 折分计划
指纹」补全候选指纹并重新展开；成功候选额外落盘逐折实际预测诊断
（``prediction_diagnostics.json``），清单声明的全部文件哈希校验通过后
才创建唯一的 ``ProfessionalResultArtifacts`` 行（pending→succeeded，
能力按算法能力矩阵填写）。候选失败保留结构化错误且绝不写成功行；
legacy 运行（无专业上下文）行为逐位不变。
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
from geomodeling.modeling.dsi_like import DSILikeInterpolator
from geomodeling.modeling.fold_artifacts import (
    FOLD_ARTIFACT_WRITE_FAILED,
    build_fold_assignments,
    build_oof_predictions,
    sha256_file,
    write_artifact_parquet,
)
from geomodeling.modeling.idw import IDWInterpolator
from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator
from geomodeling.modeling.kriging_rf_residual import KrigingRFResidualInterpolator
from geomodeling.modeling.random_forest import RandomForestSpatialInterpolator
from geomodeling.modeling.metrics import common_valid_mask, compute_metrics
from geomodeling.modeling.professional_contracts import capabilities_for
from geomodeling.modeling.provenance import (
    compute_group_diagnostics,
    ensure_provenance_coverage,
    load_optional_provenance,
)
from geomodeling.modeling.splits import build_spatial_splits
from geomodeling.platform import tables
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.experiments import (
    PROFESSIONAL_CONFIRMATION_REQUIRED,
    expand_candidates,
)
from geomodeling.platform.professional import verify_manifest
from geomodeling.platform.repositories import (
    ProfessionalResultArtifactsRepository,
    RunRepository,
)
from geomodeling.platform.schemas import Algorithm, SpatialValidationSpec
from geomodeling.platform.settings import PlatformSettings

RUN_CANCELED = "RUN_CANCELED"
METRICS_EMPTY_COMMON_VALID = "METRICS_EMPTY_COMMON_VALID"
PROFESSIONAL_ARTIFACT_WRITE_FAILED = "PROFESSIONAL_ARTIFACT_WRITE_FAILED"

_INTERPOLATORS = {
    Algorithm.IDW.value: IDWInterpolator(),
    Algorithm.ORDINARY_KRIGING.value: OrdinaryKrigingInterpolator(),
    Algorithm.DSI_LIKE.value: DSILikeInterpolator(),
    Algorithm.RANDOM_FOREST_SPATIAL.value: RandomForestSpatialInterpolator(),
    Algorithm.KRIGING_RF_RESIDUAL.value: KrigingRFResidualInterpolator(),
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


def _finite_valid_mask(frame: pd.DataFrame) -> np.ndarray:
    """「声明有效且值有限」的行掩膜。

    有效行口径在 ``is_numeric_valid`` 之外再查 ``value`` 有限性：标记有效
    但值为 NaN/inf 的行（未声明的非有限值）绝不进入建模与真值。折分构建
    与候选评估必须使用同一口径，两处统一走此函数。
    """

    declared = frame["is_numeric_valid"].to_numpy(dtype=bool)
    finite = np.isfinite(frame["value"].to_numpy(dtype="float64"))
    return declared & finite


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
    valid = frame.loc[_finite_valid_mask(frame)].reset_index(drop=True)
    coord_cols = ["x", "y"] + (["z"] if dimension == "3d" else [])
    points = valid[coord_cols].to_numpy(dtype="float64")
    values = valid["value"].to_numpy(dtype="float64")
    source_rows = valid["source_row"].to_numpy(dtype="int64")

    validated = interpolator.validate_parameters(parameters, dimension)

    started = time.perf_counter()
    records: list[pd.DataFrame] = []
    fold_metrics: list[dict[str, float]] = []
    fold_diagnostics: list[dict[str, Any]] = []
    for fold in folds:
        if cancel.is_set():
            raise PlatformError(RUN_CANCELED, "任务已被取消", {"fold": fold.index}, http_status=409)
        train_coords = points[fold.training_indices]
        train_values = values[fold.training_indices]
        query = points[fold.validation_indices]
        fitted = interpolator.fit(train_coords, train_values, validated)
        batch = fitted.predict(query, cancel=cancel.is_set)
        # 逐折实际预测诊断（有界聚合）：仅专业候选落盘，legacy 不持久化
        fold_diagnostics.append({"fold": fold.index, "diagnostics": batch.diagnostics})
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
    if interpolator.algorithm in {
        Algorithm.RANDOM_FOREST_SPATIAL,
        Algorithm.KRIGING_RF_RESIDUAL,
    }:
        diagnostics = [entry["diagnostics"] for entry in fold_diagnostics]
        first = diagnostics[0] if diagnostics else {}
        ml_diagnostics: dict[str, Any] = {
            "feature_version": first.get("feature_version"),
            "sklearn_version": first.get("sklearn_version")
            or (first.get("residual_model") or {}).get("sklearn_version"),
            "outer_fold_count": len(diagnostics),
        }
        if interpolator.algorithm == Algorithm.KRIGING_RF_RESIDUAL:
            ml_diagnostics.update(
                {
                    "residual_target_semantics": first.get("residual_target_semantics"),
                    "inner_fold_count": first.get("inner_fold_count"),
                    "inner_validation_fingerprints": [
                        item.get("inner_validation_fingerprint") for item in diagnostics
                    ],
                    "oof_residual_count": sum(
                        int(item.get("oof_residual_count") or 0) for item in diagnostics
                    ),
                    "oof_residual_coverage_min": min(
                        (float(item.get("oof_residual_coverage") or 0.0) for item in diagnostics),
                        default=0.0,
                    ),
                }
            )
        else:
            ml_diagnostics.update(
                {
                    "tree_count": first.get("tree_count"),
                    "dispersion_semantics": first.get("dispersion_semantics"),
                }
            )
        metrics["ml_diagnostics"] = ml_diagnostics
    return {"predictions": predictions, "metrics": metrics, "fold_diagnostics": fold_diagnostics}


def _persist_progress(runtime, run_id: str, progress: dict[str, Any]) -> None:
    with runtime.session() as session:
        row = session.get(tables.Run, run_id)
        row.metrics_json = tables.dumps_canonical(progress)
        session.commit()


def _manifest_entry(directory: Path, name: str, sha256: str) -> dict[str, Any]:
    return {"file": name, "sha256": sha256, "bytes": (directory / name).stat().st_size}


def _write_professional_candidate_evidence(
    *,
    professional_dir: Path,
    result_id: str,
    candidate,
    outcome: dict[str, Any],
    professional: dict[str, Any],
    assignments_sha256: str,
    oof_sha256: str,
) -> dict[str, Any]:
    """落盘逐折实际预测诊断并构建候选专业清单（Task 14，设计 §4.2/§5.3）。

    清单声明 fold/OOF/诊断三件工件；``verify_manifest`` 重算全部声明文件
    的 SHA-256 与大小，任何不匹配以 ``MANIFEST_VERIFICATION_FAILED``
    fail-closed——校验通过的 manifest 才会随工件行提交。
    """

    import os

    diagnostics_payload = {
        "candidate_fingerprint": candidate.fingerprint,
        "algorithm": candidate.algorithm,
        "fold_diagnostics": outcome["fold_diagnostics"],
    }
    blob = tables.dumps_canonical(diagnostics_payload).encode("utf-8")
    diagnostics_path = professional_dir / "prediction_diagnostics.json"
    tmp = diagnostics_path.with_suffix(".tmp.json")
    tmp.write_bytes(blob)
    if tmp.read_bytes() != blob:
        tmp.unlink(missing_ok=True)
        raise PlatformError(
            PROFESSIONAL_ARTIFACT_WRITE_FAILED,
            "专业工件回读校验失败",
            {"file": diagnostics_path.name},
        )
    os.replace(tmp, diagnostics_path)
    manifest = {
        "version": 1,
        "candidate_result_id": result_id,
        "confirmation_id": professional.get("confirmation_id"),
        "fingerprint": candidate.fingerprint,
        "directory": str(professional_dir),
        "artifacts": {
            "fold_assignments": _manifest_entry(
                professional_dir, "fold_assignments.parquet", assignments_sha256
            ),
            "out_of_fold_predictions": _manifest_entry(
                professional_dir, "out_of_fold_predictions.parquet", oof_sha256
            ),
            "prediction_diagnostics": _manifest_entry(
                professional_dir,
                "prediction_diagnostics.json",
                sha256_file(diagnostics_path),
            ),
        },
        "config": {
            "neighborhood": professional.get("neighborhood"),
            "empirical_uncertainty": professional.get("empirical_uncertainty"),
        },
        "created_at": tables.utc_now_iso(),
    }
    verify_manifest(manifest)
    return manifest


def execute_run(runtime, run_id: str, cancel: Event) -> RunOutcome:
    """Execute one queued run end-to-end (called by the worker thread)."""

    experiment, params = _load_experiment(runtime, run_id)
    # v0.6：实验携带的规范化专业上下文（确认快照/邻域/不确定性）；legacy 为 None
    professional = params.get("professional") or None
    search = {
        "algorithm": params["algorithm"],
        "search_mode": params.get("search_mode", "manual"),
        "parameters": params.get("parameters") or {},
        "validation": params.get("validation"),
        "grid": params.get("grid"),
    }
    if professional is not None:
        search["professional"] = professional
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

    if (
        professional is not None
        and params["algorithm"] == Algorithm.ORDINARY_KRIGING.value
        and not professional.get("confirmation_id")
    ):
        # 专业 Kriging 候选 confirmation_id 必填（§5.1）：创建层已拒绝，
        # 此处兜底手工构造的实验记录，fail-closed。
        with runtime.session() as session:
            RunRepository(session).mark_failed(
                run_id, error_code=PROFESSIONAL_CONFIRMATION_REQUIRED, metrics=progress
            )
        return RunOutcome(run_id, "failed", total, 0, 0)

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
    declared_valid_count = int(frame["is_numeric_valid"].to_numpy(dtype=bool).sum())
    valid_frame = frame.loc[_finite_valid_mask(frame)].reset_index(drop=True)
    # 数据质量诊断：披露「标记有效但值非有限」被排除的行数（有界计数），
    # 排除后不足建模下限时由现有折分失败通道（SPLIT_INSUFFICIENT_GROUPS）
    # fail-closed；计数随 progress 落库，成功/失败路径均可见。
    progress["data_quality"] = {
        "nonfinite_valid_value_excluded_count": declared_valid_count - len(valid_frame)
    }
    coord_cols = ["x", "y"] + (["z"] if dimension == "3d" else [])
    valid_points = valid_frame[coord_cols].to_numpy(dtype="float64")
    try:
        folds = build_spatial_splits(valid_points, dimension, validation)
        fold_assignments, validation_fingerprint = build_fold_assignments(
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

    if professional is not None:
        # 设计 §4.2：标准化数据 SHA-256 与折分计划指纹是专业候选指纹的
        # 组成部分——折证据建成后以完整专业上下文重新展开候选（展开是纯
        # 函数，候选数量与参数合并结果不变，仅指纹补全）。
        professional = {
            **professional,
            "dataset_sha256": data_sha256,
            "validation_fingerprint": validation_fingerprint,
        }
        search["professional"] = professional
        candidates = expand_candidates(search)

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

            if professional is not None:
                # Task 14：实际预测诊断落盘 + 清单声明；全部声明文件哈希
                # 校验通过后才创建唯一专业工件行（候选行提交之后）。
                try:
                    professional_manifest = _write_professional_candidate_evidence(
                        professional_dir=professional_dir,
                        result_id=result_id,
                        candidate=candidate,
                        outcome=outcome,
                        professional=professional,
                        assignments_sha256=assignments_sha256,
                        oof_sha256=oof_sha256,
                    )
                except PlatformError as exc:
                    with runtime.session() as session:
                        RunRepository(session).mark_failed(run_id, error_code=exc.code, metrics=progress)
                    return RunOutcome(run_id, "failed", total, completed, failed)
                except Exception:
                    with runtime.session() as session:
                        RunRepository(session).mark_failed(
                            run_id, error_code=PROFESSIONAL_ARTIFACT_WRITE_FAILED, metrics=progress
                        )
                    return RunOutcome(run_id, "failed", total, completed, failed)

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
        if professional is not None and outcome is not None:
            # 唯一专业工件行（candidate_result_id 唯一；pending→succeeded，
            # 能力按算法能力矩阵填写）。创建失败绝不写成功行：整次运行
            # 结构化失败，已落盘文件保留为证据。
            try:
                with runtime.session() as session:
                    artifacts_repo = ProfessionalResultArtifactsRepository(session)
                    artifacts = artifacts_repo.create(
                        result_id,
                        confirmation_id=professional.get("confirmation_id"),
                        capabilities=capabilities_for(candidate.algorithm).model_dump(mode="json"),
                    )
                    artifacts_repo.mark_succeeded(artifacts.id, manifest=professional_manifest)
            except PlatformError as exc:
                with runtime.session() as session:
                    RunRepository(session).mark_failed(run_id, error_code=exc.code, metrics=progress)
                return RunOutcome(run_id, "failed", total, completed, failed)
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
