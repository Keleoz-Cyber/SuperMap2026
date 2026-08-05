"""Task 8 runner tests: search expansion, candidate evaluation, common metrics."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from geomodeling.platform import PlatformRuntime, tables


def make_runtime(tmp_path: Path) -> PlatformRuntime:
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    return runtime


def make_standardized(runtime: PlatformRuntime, case_id: str, dataset_id: str, dimension: str = "2d"):
    """直接构造小样本标准化 parquet（平滑场，便于插值验证）。"""
    rng = np.random.default_rng(20260723)
    n = 36
    x = rng.uniform(-160.0, -40.0, n)
    y = rng.uniform(220.0, 660.0, n)
    if dimension == "3d":
        z = rng.uniform(-840.0, 0.0, n)
        value = np.sin(x / 40) + np.cos(y / 90) + 0.001 * z + 10.0
    else:
        z = np.full(n, np.nan)
        value = np.sin(x / 40) + np.cos(y / 90) + 10.0
    frame = pd.DataFrame(
        {
            "source_row": np.arange(1, n + 1),
            "x": x,
            "y": y,
            "z": z,
            "value": value,
            "is_numeric_valid": True,
        }
    )
    target = runtime.settings.standardized_dataset(case_id, dataset_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(target, index=False)
    return target, frame


def insert_experiment(runtime: PlatformRuntime, case_id: str, dataset_id: str, search: dict) -> str:
    import uuid

    experiment_id = str(uuid.uuid4())
    with runtime.session() as session:
        session.add(tables.Case(id=case_id, name="案例", case_type="generic", config_json="{}"))
        session.add(
            tables.DatasetVersion(
                id=dataset_id, case_id=case_id, version=1, status="validated",
                source_path="x.csv", profile_json=tables.dumps_canonical(
                    {"mapping": {"dimension": search.pop("dimension"), "x": "x", "y": "y",
                                 "z": search.pop("z_field", None), "value": "value",
                                 "value_name": "属性", "coordinate_kind": "local_linear"},
                     "source_sha256": "a" * 64, "standardized_sha256": "b" * 64,
                     "quality": {"status": "passed", "confirmed": True}}
                ),
            )
        )
        session.add(
            tables.Experiment(
                id=experiment_id, case_id=case_id, name="实验",
                params_json=tables.dumps_canonical(search),
            )
        )
        session.commit()
    return experiment_id


def insert_run(runtime: PlatformRuntime, experiment_id: str) -> str:
    import uuid

    run_id = str(uuid.uuid4())
    with runtime.session() as session:
        session.add(tables.Run(id=run_id, experiment_id=experiment_id, status="queued"))
        session.commit()
    return run_id


def load_candidates(runtime: PlatformRuntime, run_id: str) -> list[dict]:
    with runtime.session() as session:
        rows = (
            session.query(tables.CandidateResult)
            .filter(tables.CandidateResult.run_id == run_id)
            .all()
        )
        return [
            {
                "id": row.id,
                "fingerprint": row.fingerprint,
                "status": row.status,
                "params": tables.loads_canonical(row.params_json),
                "metrics": tables.loads_canonical(row.metrics_json),
                "error": tables.loads_canonical(row.error_json) if row.error_json else None,
                "predictions_path": row.predictions_path,
            }
            for row in rows
        ]


SEARCH_IDW_MANUAL = {
    "dimension": "2d",
    "algorithm": "idw",
    "dataset_version_id": "ds1",
    "search_mode": "manual",
    "parameters": {"power": 2.0, "neighbor_count": 8},
    "validation": {"method": "spatial_kfold", "folds": 3, "seed": 11, "holdout_fraction": 0.2},
    "grid": None,
}


def test_manual_search_expands_to_exactly_one_candidate():
    from geomodeling.platform.experiments import expand_candidates

    candidates = expand_candidates(SEARCH_IDW_MANUAL)
    assert len(candidates) == 1
    assert candidates[0].parameters["power"] == 2.0
    assert len(candidates[0].fingerprint) == 64


def test_grid_search_expands_cartesian_and_caps():
    from geomodeling.platform.experiments import expand_candidates
    from geomodeling.platform.errors import PlatformError

    search = dict(SEARCH_IDW_MANUAL)
    search["search_mode"] = "grid"
    search["parameters"] = {"power": [1.0, 2.0], "neighbor_count": [4, 8, 16]}
    candidates = expand_candidates(search)
    assert len(candidates) == 6
    fingerprints = {c.fingerprint for c in candidates}
    assert len(fingerprints) == 6

    search["parameters"] = {"power": list(range(60))}
    with pytest.raises(PlatformError) as exc:
        expand_candidates(search)
    assert exc.value.code == "SEARCH_TOO_LARGE"

    search["parameters"] = {"power": []}
    with pytest.raises(PlatformError) as exc:
        expand_candidates(search)
    assert exc.value.code == "SEARCH_TOO_LARGE"


def test_manual_idw_run_succeeds_with_predictions_and_metrics(tmp_path):
    from geomodeling.modeling.runner import execute_run

    runtime = make_runtime(tmp_path)
    target, frame = make_standardized(runtime, "c1", "ds1")
    experiment_id = insert_experiment(runtime, "c1", "ds1", dict(SEARCH_IDW_MANUAL))
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"

    candidates = load_candidates(runtime, run_id)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["status"] == "succeeded"
    metrics = candidate["metrics"]
    assert metrics["rmse"] >= 0
    assert metrics["mae"] >= 0
    assert metrics["coverage"] > 0.9
    assert metrics["common_valid_count"] > 0
    assert metrics["candidate_valid_count"] + metrics["candidate_nodata_count"] == metrics["total_count"]
    assert metrics["runtime_seconds"] >= 0
    # 通用数据集无 provenance 声明：不出现 group_diagnostics；Task 9 起
    # 候选指标固定引用折分与折外预测两个工件的 SHA-256
    assert set(metrics) == {
        "rmse", "mae", "r2", "bias", "coverage",
        "common_valid_count", "candidate_valid_count", "candidate_nodata_count",
        "total_count", "runtime_seconds", "fold_metrics",
        "fold_assignments_sha256", "oof_predictions_sha256",
    }
    assert Path(candidate["predictions_path"]).exists()
    predictions = pd.read_parquet(candidate["predictions_path"])
    assert set(predictions.columns) >= {"source_row", "truth", "prediction", "is_nodata", "fold"}
    assert predictions["is_nodata"].sum() == 0


def test_partial_candidate_failure_keeps_others(tmp_path):
    from geomodeling.modeling.runner import execute_run

    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")
    search = dict(SEARCH_IDW_MANUAL)
    search["search_mode"] = "grid"
    search["parameters"] = [
        {"power": 2.0, "neighbor_count": 8},
        {"power": -1.0, "neighbor_count": 8},  # 非法参数 → 该候选失败
    ]
    experiment_id = insert_experiment(runtime, "c1", "ds1", search)
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"  # 单候选失败不拖垮整个 run
    candidates = load_candidates(runtime, run_id)
    statuses = {c["params"]["power"]: c["status"] for c in candidates}
    assert statuses[2.0] == "succeeded"
    assert statuses[-1.0] == "failed"
    failed = next(c for c in candidates if c["status"] == "failed")
    assert failed["error"] is not None
    assert failed["error"]["code"]


def test_all_candidates_failed_marks_run_failed(tmp_path):
    from geomodeling.modeling.runner import execute_run

    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")
    search = dict(SEARCH_IDW_MANUAL)
    search["search_mode"] = "grid"
    search["parameters"] = [{"power": -1.0}, {"power": -2.0}]
    experiment_id = insert_experiment(runtime, "c1", "ds1", search)
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "failed"


def test_cancellation_before_first_candidate(tmp_path):
    from geomodeling.modeling.runner import execute_run

    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")
    experiment_id = insert_experiment(runtime, "c1", "ds1", dict(SEARCH_IDW_MANUAL))
    run_id = insert_run(runtime, experiment_id)

    event = threading.Event()
    event.set()
    outcome = execute_run(runtime, run_id, event)
    assert outcome.status == "canceled"
    assert load_candidates(runtime, run_id) == []


def test_common_valid_mask_and_coverage_honesty(tmp_path):
    from geomodeling.modeling.runner import execute_run

    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")
    search = dict(SEARCH_IDW_MANUAL)
    search["search_mode"] = "grid"
    search["parameters"] = [
        {"power": 2.0, "neighbor_count": 8, "search_radius": None},
        {"power": 2.0, "neighbor_count": 8, "search_radius": 40.0},  # 中等半径 → 部分 NoData
    ]
    experiment_id = insert_experiment(runtime, "c1", "ds1", search)
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    with runtime.session() as session:
        run = session.get(tables.Run, run_id)
        metrics = tables.loads_canonical(run.metrics_json)
    public = metrics["public_metrics"]
    candidates = load_candidates(runtime, run_id)
    by_radius = {c["params"]["search_radius"]: c for c in candidates}
    unlimited = by_radius[None]["metrics"]
    limited = by_radius[40.0]["metrics"]
    assert by_radius[None]["status"] == "succeeded"
    assert by_radius[40.0]["status"] == "succeeded"
    # 公共掩膜上两者使用同一 common_valid_count；覆盖率独立呈现，小半径候选覆盖率更低
    assert unlimited["common_valid_count"] == limited["common_valid_count"] == public["common_valid_count"]
    assert 0 < limited["candidate_valid_count"] < 36
    assert limited["candidate_valid_count"] + limited["candidate_nodata_count"] == limited["total_count"]
    assert limited["coverage"] < 1.0
    assert unlimited["coverage"] == 1.0
    # 公共指标挂在 run 上，字段齐全
    for key in ("rmse", "mae", "r2", "bias", "common_valid_count", "coverage"):
        assert key in public


def test_zero_common_valid_candidate_cannot_rank(tmp_path):
    from geomodeling.modeling.runner import execute_run

    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")
    search = dict(SEARCH_IDW_MANUAL)
    search["search_mode"] = "grid"
    search["parameters"] = [
        {"power": 2.0, "neighbor_count": 8, "search_radius": None},
        {"power": 2.0, "neighbor_count": 8, "search_radius": 0.001},  # 几乎全覆盖 NoData
    ]
    experiment_id = insert_experiment(runtime, "c1", "ds1", search)
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    candidates = load_candidates(runtime, run_id)
    tiny = next(c for c in candidates if c["params"]["search_radius"] == 0.001)
    assert tiny["status"] == "failed"
    assert tiny["error"]["code"] == "METRICS_EMPTY_COMMON_VALID"


def test_kriging_manual_and_auto_both_run(tmp_path):
    from geomodeling.modeling.runner import execute_run

    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")
    search = dict(SEARCH_IDW_MANUAL)
    search["algorithm"] = "ordinary_kriging"
    search["search_mode"] = "grid"
    search["parameters"] = [
        {"variogram_model": "spherical", "variogram_mode": "auto", "neighbor_count": 8},
        {"variogram_model": "spherical", "variogram_mode": "manual",
         "nugget": 0.0, "sill": 1.0, "range": 100.0, "neighbor_count": 8},
    ]
    experiment_id = insert_experiment(runtime, "c1", "ds1", search)
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    candidates = load_candidates(runtime, run_id)
    assert all(c["status"] == "succeeded" for c in candidates)
    assert any(c["metrics"]["rmse"] >= 0 for c in candidates)


def test_run_persists_fold_and_oof_artifacts(tmp_path):
    from geomodeling.modeling.runner import execute_run

    runtime = make_runtime(tmp_path)
    _target, frame = make_standardized(runtime, "c1", "ds1")
    experiment_id = insert_experiment(runtime, "c1", "ds1", dict(SEARCH_IDW_MANUAL))
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    candidate = load_candidates(runtime, run_id)[0]

    # 设计 §5.3：两个工件都在候选的 professional/ 目录下
    professional_dir = runtime.settings.professional_result_dir(candidate["id"])
    assert professional_dir == runtime.settings.results_dir / candidate["id"] / "professional"
    assignments_path = professional_dir / "fold_assignments.parquet"
    oof_path = professional_dir / "out_of_fold_predictions.parquet"
    assert assignments_path.exists()
    assert oof_path.exists()

    # 候选 metrics 引用两工件 SHA-256
    metrics = candidate["metrics"]
    assert metrics["fold_assignments_sha256"] == hashlib.sha256(
        assignments_path.read_bytes()
    ).hexdigest()
    assert metrics["oof_predictions_sha256"] == hashlib.sha256(
        oof_path.read_bytes()
    ).hexdigest()

    oof = pd.read_parquet(oof_path)
    assert list(oof.columns) == [
        "source_row", "fold_index", "x", "y", "z", "observed",
        "predicted", "residual", "absolute_error", "squared_error", "is_nodata",
    ]
    assert oof["source_row"].is_unique
    assert set(oof["source_row"]) == set(frame["source_row"])
    assert oof["z"].isna().all()  # 2D 数据集 z 为 null
    assert not oof["is_nodata"].any()
    merged = oof.merge(frame[["source_row", "value"]], on="source_row")
    assert merged["observed"].to_numpy() == pytest.approx(merged["value"].to_numpy())
    assert merged["residual"].to_numpy() == pytest.approx(
        merged["predicted"].to_numpy() - merged["value"].to_numpy()
    )
    assert merged["absolute_error"].to_numpy() == pytest.approx(
        np.abs(merged["residual"].to_numpy())
    )
    assert merged["squared_error"].to_numpy() == pytest.approx(
        merged["residual"].to_numpy() ** 2
    )

    assignments = pd.read_parquet(assignments_path)
    assert {"fold_index", "source_row", "group_key", "role", "leakage_detected"} <= set(
        assignments.columns
    )
    assert set(assignments["role"]) == {"training", "validation"}
    assert not assignments["leakage_detected"].any()
    validation = assignments[assignments["role"] == "validation"]
    assert validation.groupby("source_row").size().eq(1).all()
    # OOF 折归属与折分分配表一致
    assert (
        oof.set_index("source_row")["fold_index"].sort_index().to_numpy()
        == validation.set_index("source_row")["fold_index"].sort_index().to_numpy()
    ).all()


def test_fold_leakage_fails_run_before_any_candidate(tmp_path, monkeypatch):
    import geomodeling.modeling.runner as runner_mod
    from geomodeling.modeling.contracts import Fold

    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")
    experiment_id = insert_experiment(runtime, "c1", "ds1", dict(SEARCH_IDW_MANUAL))
    run_id = insert_run(runtime, experiment_id)

    n = 36

    def leaking_splits(points, dimension, spec):
        half = len(points) // 2
        return [
            Fold(
                index=0,
                training_indices=np.arange(0, half + 2),  # 与验证重叠两行 → 泄漏
                validation_indices=np.arange(half, n),
            ),
            Fold(
                index=1,
                training_indices=np.arange(half, n),
                validation_indices=np.arange(0, half),
            ),
        ]

    monkeypatch.setattr(runner_mod, "build_spatial_splits", leaking_splits)
    outcome = runner_mod.execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "failed"
    # 泄漏在候选行持久化之前判失败：没有任何候选记录
    assert load_candidates(runtime, run_id) == []
    with runtime.session() as session:
        run = session.get(tables.Run, run_id)
        assert run.status == "failed"
        assert run.error_code == "FOLD_LEAKAGE_DETECTED"


def test_oof_prediction_mismatch_fails_run_not_candidate(tmp_path, monkeypatch):
    import geomodeling.modeling.runner as runner_mod
    from geomodeling.platform.errors import PlatformError

    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")
    experiment_id = insert_experiment(runtime, "c1", "ds1", dict(SEARCH_IDW_MANUAL))
    run_id = insert_run(runtime, experiment_id)

    def broken_oof(frame, folds, predictions, *, dimension):
        raise PlatformError(
            "OOF_PREDICTION_MISMATCH", "候选预测 source_row 集合与折分计划的验证样本不一致"
        )

    monkeypatch.setattr(runner_mod, "build_oof_predictions", broken_oof)
    outcome = runner_mod.execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "failed"
    assert load_candidates(runtime, run_id) == []
    with runtime.session() as session:
        run = session.get(tables.Run, run_id)
        assert run.status == "failed"
        assert run.error_code == "OOF_PREDICTION_MISMATCH"


# ---------------------------------------------------------------------------
# Task 14：专业候选证据绑定（fold/OOF + 实际预测诊断 + 工件行）
# ---------------------------------------------------------------------------

KRIGING_AUTO_CONFIRMATION_CONFIG = {
    "model": "spherical",
    "parameter_strategy": "automatic_candidate",
    "parameter_origin": "automatic_candidate",
    "fitted_models_sha256": "e" * 64,
    "anisotropy": {"keep_isotropic": True},
}

NEIGHBORHOOD_WIDE = {"radii": [500.0, 500.0], "min_neighbors": 2, "max_neighbors": 8}


def insert_professional_confirmation(
    runtime: PlatformRuntime,
    dataset_id: str,
    *,
    diagnosis_id: str = "diag-1",
    confirmation_id: str = "conf-1",
    config: dict | None = None,
    fingerprint: str = "f" * 64,
) -> None:
    with runtime.session() as session:
        session.add(
            tables.ProfessionalDiagnostic(
                id=diagnosis_id,
                dataset_version_id=dataset_id,
                status="succeeded",
                config_json="{}",
                fingerprint="a" * 64,
                manifest_json="{}",
            )
        )
        session.commit()
        session.add(
            tables.ProfessionalConfirmation(
                id=confirmation_id,
                diagnostic_id=diagnosis_id,
                config_json=tables.dumps_canonical(config or {}),
                fingerprint=fingerprint,
                note="确认",
            )
        )
        session.commit()


def resolve_context(runtime: PlatformRuntime, dataset_id: str, **request_kwargs) -> dict:
    """经服务层解析专业上下文（创建校验与参数落地的真实路径）。"""

    from geomodeling.platform.experiments import resolve_professional_context
    from geomodeling.platform.repositories import DatasetRepository
    from geomodeling.platform.schemas import ExperimentCreateRequest

    algorithm = request_kwargs.pop("algorithm")
    request = ExperimentCreateRequest(
        case_id="c1",
        name="专业实验",
        algorithm=algorithm,
        dataset_version_id=dataset_id,
        **request_kwargs,
    )
    with runtime.session() as session:
        dataset = DatasetRepository(session).get(dataset_id)
        return resolve_professional_context(session, request, dataset)


def attach_professional(runtime: PlatformRuntime, experiment_id: str, professional: dict) -> None:
    """把服务层解析的专业上下文写入实验参数（模拟创建期的落库结果）。"""

    with runtime.session() as session:
        row = session.get(tables.Experiment, experiment_id)
        params = tables.loads_canonical(row.params_json)
        params["professional"] = professional
        row.params_json = tables.dumps_canonical(params)
        session.commit()


def test_professional_kriging_run_persists_result_artifacts(tmp_path):
    import json

    from geomodeling.modeling.runner import execute_run
    from geomodeling.platform.professional import verify_manifest
    from geomodeling.platform.repositories import ProfessionalResultArtifactsRepository

    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")
    # 先建案例+数据集+实验（FK 前提），再挂确认并解析专业上下文
    search = dict(SEARCH_IDW_MANUAL)
    search["algorithm"] = "ordinary_kriging"
    search["parameters"] = {"neighbor_count": 8}
    experiment_id = insert_experiment(runtime, "c1", "ds1", search)
    insert_professional_confirmation(runtime, "ds1", config=KRIGING_AUTO_CONFIRMATION_CONFIG)
    professional = resolve_context(
        runtime,
        "ds1",
        algorithm="ordinary_kriging",
        parameters={"neighbor_count": 8},
        professional_confirmation_id="conf-1",
        neighborhood=NEIGHBORHOOD_WIDE,
        empirical_uncertainty={"min_neighbors": 2, "max_neighbors": 8},
    )
    attach_professional(runtime, experiment_id, professional)
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    candidate = load_candidates(runtime, run_id)[0]
    assert candidate["status"] == "succeeded"

    # 参数落地：确认模型/策略、规范各向同性变换与搜索邻域注入候选参数
    params = candidate["params"]
    assert params["variogram_model"] == "spherical"
    assert params["variogram_mode"] == "auto"
    assert params["anisotropy"]["dimension"] == "2d"
    assert params["anisotropy"]["major_scale"] == 1.0
    assert params["neighborhood"]["radii"] == [500.0, 500.0]

    # 唯一专业工件行：确认引用、能力矩阵与声明文件哈希全部校验通过
    with runtime.session() as session:
        artifacts = ProfessionalResultArtifactsRepository(session).get_for_candidate(
            candidate["id"]
        )
    assert artifacts.status == "succeeded"
    assert artifacts.confirmation_id == "conf-1"
    assert artifacts.capabilities["native_kriging_std"] == "supported"
    assert artifacts.capabilities["empirical_variogram"] == "supported"
    assert verify_manifest(artifacts.manifest)
    assert set(artifacts.manifest["artifacts"]) >= {
        "fold_assignments",
        "out_of_fold_predictions",
        "prediction_diagnostics",
    }
    assert artifacts.manifest["config"]["empirical_uncertainty"]["min_neighbors"] == 2

    # 实际预测诊断随候选落盘：逐折聚合 + 同一变换指纹
    diagnostics_path = (
        runtime.settings.professional_result_dir(candidate["id"])
        / "prediction_diagnostics.json"
    )
    assert diagnostics_path.exists()
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    assert diagnostics["candidate_fingerprint"] == candidate["fingerprint"]
    assert len(diagnostics["fold_diagnostics"]) == 3
    first = diagnostics["fold_diagnostics"][0]
    assert first["diagnostics"]["transform_fingerprint"]


def test_professional_idw_run_persists_artifacts_without_confirmation(tmp_path):
    import json

    from geomodeling.modeling.runner import execute_run
    from geomodeling.platform.professional import verify_manifest
    from geomodeling.platform.repositories import ProfessionalResultArtifactsRepository

    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")
    experiment_id = insert_experiment(runtime, "c1", "ds1", dict(SEARCH_IDW_MANUAL))
    professional = resolve_context(
        runtime,
        "ds1",
        algorithm="idw",
        parameters={"power": 2.0, "neighbor_count": 8},
        neighborhood=NEIGHBORHOOD_WIDE,
        empirical_uncertainty={"min_neighbors": 2, "max_neighbors": 8},
    )
    attach_professional(runtime, experiment_id, professional)
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    candidate = load_candidates(runtime, run_id)[0]
    assert candidate["status"] == "succeeded"
    # IDW 只注入搜索邻域，绝不获得 Kriging 各向异性/变异函数键
    assert candidate["params"]["neighborhood"]["radii"] == [500.0, 500.0]
    assert "anisotropy" not in candidate["params"]

    with runtime.session() as session:
        artifacts = ProfessionalResultArtifactsRepository(session).get_for_candidate(
            candidate["id"]
        )
    assert artifacts.status == "succeeded"
    assert artifacts.confirmation_id is None
    # 能力矩阵：IDW 原生 Kriging 标准差为类型化「不适用」，z_scale 支持
    assert artifacts.capabilities["native_kriging_std"] == "not_applicable"
    assert artifacts.capabilities["z_scale_weight_distance"] == "supported"
    assert verify_manifest(artifacts.manifest)

    diagnostics_path = (
        runtime.settings.professional_result_dir(candidate["id"])
        / "prediction_diagnostics.json"
    )
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    assert len(diagnostics["fold_diagnostics"]) == 3


def test_failed_professional_candidate_never_writes_success_row(tmp_path):
    from geomodeling.modeling.runner import execute_run
    from geomodeling.platform.errors import PlatformError
    from geomodeling.platform.repositories import ProfessionalResultArtifactsRepository

    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")
    parameters = [
        {"power": 2.0, "neighbor_count": 8},
        {"power": -1.0, "neighbor_count": 8},  # 非法参数 → 该候选失败
    ]
    search = dict(SEARCH_IDW_MANUAL)
    search["search_mode"] = "grid"
    search["parameters"] = parameters
    experiment_id = insert_experiment(runtime, "c1", "ds1", search)
    professional = resolve_context(
        runtime,
        "ds1",
        algorithm="idw",
        search_mode="grid",
        parameters=parameters,
        neighborhood=NEIGHBORHOOD_WIDE,
    )
    attach_professional(runtime, experiment_id, professional)
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"  # 单候选失败不拖垮整个 run
    candidates = load_candidates(runtime, run_id)
    failed = next(c for c in candidates if c["status"] == "failed")
    succeeded = next(c for c in candidates if c["status"] == "succeeded")
    # 失败候选保留结构化错误，绝不写专业成功行
    assert failed["error"]["code"]
    with runtime.session() as session:
        repo = ProfessionalResultArtifactsRepository(session)
        with pytest.raises(PlatformError) as excinfo:
            repo.get_for_candidate(failed["id"])
        assert excinfo.value.code == "PROFESSIONAL_ARTIFACTS_NOT_FOUND"
        # 成功候选的专业工件行正常落库
        assert repo.get_for_candidate(succeeded["id"]).status == "succeeded"
    professional_dir = runtime.settings.professional_result_dir(failed["id"])
    assert not professional_dir.exists()


def test_legacy_run_has_no_professional_artifacts_row(tmp_path):
    from geomodeling.modeling.runner import execute_run
    from geomodeling.platform.errors import PlatformError
    from geomodeling.platform.repositories import ProfessionalResultArtifactsRepository

    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")
    experiment_id = insert_experiment(runtime, "c1", "ds1", dict(SEARCH_IDW_MANUAL))
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    candidate = load_candidates(runtime, run_id)[0]
    # 旧候选不补算专业工件（§4.2）
    with runtime.session() as session:
        with pytest.raises(PlatformError) as excinfo:
            ProfessionalResultArtifactsRepository(session).get_for_candidate(candidate["id"])
    assert excinfo.value.code == "PROFESSIONAL_ARTIFACTS_NOT_FOUND"


def make_standardized_with_undeclared_nan(
    runtime: PlatformRuntime, case_id: str, dataset_id: str, nan_rows: int = 4
):
    """构造「is_numeric_valid=true 但 value=NaN」的未声明非有限行数据集。"""

    target, frame = make_standardized(runtime, case_id, dataset_id)
    frame.loc[np.arange(nan_rows), "value"] = np.nan
    frame.to_parquet(target, index=False)
    return target, frame


def load_run_metrics(runtime: PlatformRuntime, run_id: str) -> dict:
    with runtime.session() as session:
        return tables.loads_canonical(session.get(tables.Run, run_id).metrics_json)


def test_undeclared_nan_rows_are_excluded_and_metrics_stay_finite(tmp_path):
    """标记有效但值为 NaN 的行不得进入建模：run 成功、指标有限、排除计数可见。"""

    from geomodeling.modeling.runner import execute_run

    runtime = make_runtime(tmp_path)
    make_standardized_with_undeclared_nan(runtime, "c1", "ds1", nan_rows=4)
    experiment_id = insert_experiment(runtime, "c1", "ds1", dict(SEARCH_IDW_MANUAL))
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"

    candidates = load_candidates(runtime, run_id)
    assert len(candidates) == 1
    metrics = candidates[0]["metrics"]
    assert candidates[0]["status"] == "succeeded"
    # 有公共有效点时 RMSE/MAE/Bias 必须是有限数值（不得为 null/NaN）
    for key in ("rmse", "mae", "bias", "r2"):
        assert metrics[key] is not None
        assert np.isfinite(metrics[key])
    assert metrics["common_valid_count"] > 0
    # 非有限行绝不进入预测真值
    predictions = pd.read_parquet(candidates[0]["predictions_path"])
    assert np.isfinite(predictions["truth"].to_numpy(dtype="float64")).all()
    assert len(predictions) == 32  # 36 - 4 行未声明 NaN

    run_metrics = load_run_metrics(runtime, run_id)
    assert run_metrics["data_quality"]["nonfinite_valid_value_excluded_count"] == 4
    public = run_metrics["public_metrics"]
    for key in ("rmse", "mae", "bias"):
        assert public[key] is not None
        assert np.isfinite(public[key])


def test_run_without_undeclared_nan_reports_zero_exclusions(tmp_path):
    """常规全有限数据集的排除计数为零，公开指标行为不变。"""

    from geomodeling.modeling.runner import execute_run

    runtime = make_runtime(tmp_path)
    make_standardized(runtime, "c1", "ds1")
    experiment_id = insert_experiment(runtime, "c1", "ds1", dict(SEARCH_IDW_MANUAL))
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    run_metrics = load_run_metrics(runtime, run_id)
    assert run_metrics["data_quality"]["nonfinite_valid_value_excluded_count"] == 0


def test_all_nonfinite_values_fail_via_existing_split_channel(tmp_path):
    """排除后不足建模下限 → 走现有失败通道（SPLIT_INSUFFICIENT_GROUPS）。"""

    from geomodeling.modeling.runner import execute_run

    runtime = make_runtime(tmp_path)
    make_standardized_with_undeclared_nan(runtime, "c1", "ds1", nan_rows=36)
    experiment_id = insert_experiment(runtime, "c1", "ds1", dict(SEARCH_IDW_MANUAL))
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "failed"
    with runtime.session() as session:
        run = session.get(tables.Run, run_id)
        assert run.error_code == "SPLIT_INSUFFICIENT_GROUPS"
        run_metrics = tables.loads_canonical(run.metrics_json)
    assert run_metrics["data_quality"]["nonfinite_valid_value_excluded_count"] == 36
    assert load_candidates(runtime, run_id) == []
