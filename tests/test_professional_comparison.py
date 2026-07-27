"""Task 16 contract tests: compatible two-candidate comparison (设计 §4.3/§13.3).

比较服务只读已登记工件（OOF parquet、fold_assignments parquet、grid.npz、
metadata.json），绝不重跑模型：

- 兼容条件全部满足才 compatible：同一 ``dataset_version_id``、同一验证折
  分指纹（从登记的 fold_assignments 工件重算）、同一 OOF ``source_row``
  集合、同一值单位（value_name/value_unit 来自数据集 profile）；不兼容
  只返回 mismatches，``metric_deltas``/``common_valid_count`` 一律 None，
  绝不显示 RMSE/R²/覆盖率差值。
- 兼容对的指标差只在所选候选的公共有效交集上重算（first − second），
  绝不复用各 run 预存的公共掩膜。
- 场差只在相同网格轴与共同有效节点上给出有界摘要（mean/max_abs）；轴
  不一致或未物化 → ``grid_difference_available=False`` 且不生成差值。
- 同一候选（first == second）以结构化错误拒绝。
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.errors import PlatformError

# ---------------------------------------------------------------------------
# 夹具：runtime / 标准化数据 / 专业候选运行（沿用 test_experiment_runner 模式）
# ---------------------------------------------------------------------------

KRIGING_AUTO_CONFIRMATION_CONFIG = {
    "model": "spherical",
    "parameter_strategy": "automatic_candidate",
    "parameter_origin": "automatic_candidate",
    "fitted_models_sha256": "e" * 64,
    "anisotropy": {"keep_isotropic": True},
}

NEIGHBORHOOD_WIDE = {"radii": [500.0, 500.0], "min_neighbors": 2, "max_neighbors": 8}
NEIGHBORHOOD_NARROW = {"radii": [40.0, 40.0], "min_neighbors": 3, "max_neighbors": 8}
EMPIRICAL_WIDE = {"min_neighbors": 2, "max_neighbors": 8}
VALIDATION_DEFAULT = {"method": "spatial_kfold", "folds": 3, "seed": 11, "holdout_fraction": 0.2}


def make_runtime(tmp_path: Path) -> PlatformRuntime:
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    return runtime


def make_standardized(
    runtime: PlatformRuntime,
    case_id: str,
    dataset_id: str,
    *,
    seed: int = 20260723,
    source_row_offset: int = 0,
):
    """小样本 2D 标准化 parquet（平滑场，与 runner 测试同一生成器）。"""

    rng = np.random.default_rng(seed)
    n = 36
    x = rng.uniform(-160.0, -40.0, n)
    y = rng.uniform(220.0, 660.0, n)
    value = np.sin(x / 40) + np.cos(y / 90) + 10.0
    frame = pd.DataFrame(
        {
            "source_row": np.arange(1, n + 1) + source_row_offset,
            "x": x,
            "y": y,
            "z": np.full(n, np.nan),
            "value": value,
            "is_numeric_valid": True,
        }
    )
    target = runtime.settings.standardized_dataset(case_id, dataset_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(target, index=False)
    return target, frame


def insert_case(runtime: PlatformRuntime, case_id: str = "c1") -> None:
    with runtime.session() as session:
        session.add(tables.Case(id=case_id, name="案例", case_type="generic", config_json="{}"))
        session.commit()


def insert_dataset(
    runtime: PlatformRuntime,
    case_id: str,
    dataset_id: str,
    standardized_path: Path,
    *,
    value_unit: str = "m",
    standardized_sha256: str = "b" * 64,
    version: int = 1,
) -> None:
    with runtime.session() as session:
        session.add(
            tables.DatasetVersion(
                id=dataset_id,
                case_id=case_id,
                version=version,
                status="validated",
                source_path="x.csv",
                profile_json=tables.dumps_canonical(
                    {
                        "mapping": {
                            "dimension": "2d",
                            "x": "x",
                            "y": "y",
                            "z": None,
                            "value": "value",
                            "value_name": "属性",
                            "value_unit": value_unit,
                            "coordinate_kind": "local_linear",
                        },
                        "source_sha256": "a" * 64,
                        "standardized_sha256": standardized_sha256,
                        "standardized_path": str(standardized_path),
                        "quality": {"status": "passed", "confirmed": True},
                    }
                ),
            )
        )
        session.commit()


def make_runtime_with_dataset(tmp_path: Path, *, value_unit: str = "m"):
    runtime = make_runtime(tmp_path)
    insert_case(runtime)
    target, frame = make_standardized(runtime, "c1", "ds1")
    insert_dataset(runtime, "c1", "ds1", target, value_unit=value_unit)
    return runtime, frame


def add_dataset(
    runtime: PlatformRuntime,
    dataset_id: str,
    *,
    seed: int,
    value_unit: str = "m",
    standardized_sha256: str,
    source_row_offset: int = 0,
):
    target, frame = make_standardized(
        runtime, "c1", dataset_id, seed=seed, source_row_offset=source_row_offset
    )
    insert_dataset(
        runtime,
        "c1",
        dataset_id,
        target,
        value_unit=value_unit,
        standardized_sha256=standardized_sha256,
        version=2,
    )
    return frame


def insert_experiment(runtime: PlatformRuntime, case_id: str, dataset_id: str, search: dict) -> str:
    search = dict(search)
    search.pop("dimension", None)
    experiment_id = str(uuid.uuid4())
    with runtime.session() as session:
        session.add(
            tables.Experiment(
                id=experiment_id,
                case_id=case_id,
                name="实验",
                params_json=tables.dumps_canonical(search),
            )
        )
        session.commit()
    return experiment_id


def insert_run(runtime: PlatformRuntime, experiment_id: str) -> str:
    run_id = str(uuid.uuid4())
    with runtime.session() as session:
        session.add(tables.Run(id=run_id, experiment_id=experiment_id, status="queued"))
        session.commit()
    return run_id


def load_candidates(runtime: PlatformRuntime, run_id: str) -> list[dict]:
    with runtime.session() as session:
        rows = session.query(tables.CandidateResult).filter(tables.CandidateResult.run_id == run_id).all()
        return [
            {
                "id": row.id,
                "fingerprint": row.fingerprint,
                "status": row.status,
                "params": tables.loads_canonical(row.params_json),
                "metrics": tables.loads_canonical(row.metrics_json),
            }
            for row in rows
        ]


def insert_professional_confirmation(
    runtime: PlatformRuntime,
    dataset_id: str,
    *,
    diagnosis_id: str = "diag-1",
    confirmation_id: str = "conf-1",
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
                config_json=tables.dumps_canonical(KRIGING_AUTO_CONFIRMATION_CONFIG),
                fingerprint="f" * 64,
                note="确认",
            )
        )
        session.commit()


def resolve_context(runtime: PlatformRuntime, case_id: str, dataset_id: str, **request_kwargs) -> dict:
    """经服务层解析专业上下文（创建校验与参数落地的真实路径）。"""

    from geomodeling.platform.experiments import resolve_professional_context
    from geomodeling.platform.repositories import DatasetRepository
    from geomodeling.platform.schemas import ExperimentCreateRequest

    algorithm = request_kwargs.pop("algorithm")
    request = ExperimentCreateRequest(
        case_id=case_id,
        name="专业实验",
        algorithm=algorithm,
        dataset_version_id=dataset_id,
        **request_kwargs,
    )
    with runtime.session() as session:
        dataset = DatasetRepository(session).get(dataset_id)
        return resolve_professional_context(session, request, dataset)


def attach_professional(runtime: PlatformRuntime, experiment_id: str, professional: dict) -> None:
    with runtime.session() as session:
        row = session.get(tables.Experiment, experiment_id)
        params = tables.loads_canonical(row.params_json)
        params["professional"] = professional
        row.params_json = tables.dumps_canonical(params)
        session.commit()


def run_professional_experiment(
    runtime: PlatformRuntime,
    *,
    case_id: str = "c1",
    dataset_id: str = "ds1",
    algorithm: str = "idw",
    parameters=None,
    search_mode: str = "manual",
    validation: dict | None = None,
    grid: dict | None = None,
    neighborhood: dict | None = NEIGHBORHOOD_WIDE,
    empirical_uncertainty: dict | None = EMPIRICAL_WIDE,
    confirmation_id: str = "conf-1",
) -> tuple[str, list[dict]]:
    """构造专业实验并运行到成功（Task 14 证据链真实路径），返回 (run_id, candidates)。"""

    from geomodeling.modeling.runner import execute_run

    if parameters is None:
        parameters = (
            {"neighbor_count": 8}
            if algorithm == "ordinary_kriging"
            else {"power": 2.0, "neighbor_count": 8}
        )
    search = {
        "dimension": "2d",
        "algorithm": algorithm,
        "dataset_version_id": dataset_id,
        "search_mode": search_mode,
        "parameters": parameters,
        "validation": validation or dict(VALIDATION_DEFAULT),
        "grid": grid,
    }
    experiment_id = insert_experiment(runtime, case_id, dataset_id, search)
    request_kwargs: dict = {
        "algorithm": algorithm,
        "parameters": parameters,
        "search_mode": search_mode,
        "neighborhood": neighborhood,
        "empirical_uncertainty": empirical_uncertainty,
    }
    if algorithm == "ordinary_kriging":
        insert_professional_confirmation(
            runtime, dataset_id, confirmation_id=confirmation_id, diagnosis_id=f"diag-{confirmation_id}"
        )
        request_kwargs["professional_confirmation_id"] = confirmation_id
    professional = resolve_context(runtime, case_id, dataset_id, **request_kwargs)
    attach_professional(runtime, experiment_id, professional)
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    return run_id, load_candidates(runtime, run_id)


def oof_path(runtime: PlatformRuntime, result_id: str) -> Path:
    return runtime.settings.professional_result_dir(result_id) / "out_of_fold_predictions.parquet"


def load_oof(runtime: PlatformRuntime, result_id: str) -> pd.DataFrame:
    return pd.read_parquet(oof_path(runtime, result_id))


def aligned_pair(first_oof: pd.DataFrame, second_oof: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    first = first_oof.sort_values("source_row").reset_index(drop=True)
    second = second_oof.sort_values("source_row").reset_index(drop=True)
    return first, second


def run_idw_pair_and_kriging(runtime: PlatformRuntime) -> tuple[dict, dict, dict]:
    """run A 两个 IDW 候选（半径 40 部分 NoData / 不限全覆盖）+ run B Kriging 全覆盖。

    返回 (limited, unlimited, kriging)。run A 的 run 内公共掩膜是小半径候
    选的有效子集，与 unlimited × kriging 跨实验交集口径不同——用于锁定
    「比较绝不复用各 run 预存公共掩膜」。
    """

    _, run_a_candidates = run_professional_experiment(
        runtime,
        search_mode="grid",
        parameters=[
            {"power": 2.0, "neighbor_count": 8, "search_radius": 40.0},
            {"power": 2.0, "neighbor_count": 8, "search_radius": None},
        ],
        neighborhood=None,
    )
    _, run_b_candidates = run_professional_experiment(runtime, algorithm="ordinary_kriging")
    by_radius = {c["params"]["search_radius"]: c for c in run_a_candidates}
    return by_radius[40.0], by_radius[None], run_b_candidates[0]


# ---------------------------------------------------------------------------
# 兼容门禁：数据集 / 单位 / 验证折分指纹 / source_row / 自身 / 存在性与状态
# ---------------------------------------------------------------------------


class TestCompatibilityGates:
    def test_different_validation_fingerprints_are_not_comparable(self, tmp_path):
        from geomodeling.platform.professional import compare_candidates

        runtime, _frame = make_runtime_with_dataset(tmp_path)
        _, first = run_professional_experiment(
            runtime, validation={**VALIDATION_DEFAULT, "seed": 11}
        )
        _, second = run_professional_experiment(
            runtime, validation={**VALIDATION_DEFAULT, "seed": 12}
        )

        result = compare_candidates(runtime, first[0]["id"], second[0]["id"])
        assert result.compatible is False
        assert set(result.mismatches) == {"validation_fingerprint"}
        assert result.metric_deltas is None
        assert result.common_valid_count is None
        assert result.grid_difference_available is False
        assert result.grid_difference is None
        assert len(result.comparison_fingerprint) == 64

    def test_different_datasets_are_not_comparable(self, tmp_path):
        from geomodeling.platform.professional import compare_candidates

        runtime, _frame = make_runtime_with_dataset(tmp_path)
        add_dataset(runtime, "ds2", seed=20260724, standardized_sha256="c" * 64)
        _, first = run_professional_experiment(runtime, dataset_id="ds1")
        _, second = run_professional_experiment(runtime, dataset_id="ds2")

        result = compare_candidates(runtime, first[0]["id"], second[0]["id"])
        assert result.compatible is False
        assert "dataset_version_id" in result.mismatches
        assert result.metric_deltas is None
        assert result.common_valid_count is None

    def test_different_value_units_are_not_comparable(self, tmp_path):
        from geomodeling.platform.professional import compare_candidates

        runtime, _frame = make_runtime_with_dataset(tmp_path, value_unit="m")
        # 同一内容、同一 standardized 哈希、同一验证规格：只有数据版本与单位不同
        add_dataset(runtime, "ds2", seed=20260723, value_unit="ft", standardized_sha256="b" * 64)
        _, first = run_professional_experiment(runtime, dataset_id="ds1")
        _, second = run_professional_experiment(runtime, dataset_id="ds2")

        result = compare_candidates(runtime, first[0]["id"], second[0]["id"])
        assert result.compatible is False
        assert set(result.mismatches) == {"dataset_version_id", "value_unit"}
        assert result.metric_deltas is None
        assert result.common_valid_count is None

    def test_different_source_rows_are_not_comparable(self, tmp_path):
        from geomodeling.platform.professional import compare_candidates

        runtime, _frame = make_runtime_with_dataset(tmp_path)
        add_dataset(
            runtime, "ds2", seed=20260723, standardized_sha256="c" * 64, source_row_offset=100
        )
        _, first = run_professional_experiment(runtime, dataset_id="ds1")
        _, second = run_professional_experiment(runtime, dataset_id="ds2")

        result = compare_candidates(runtime, first[0]["id"], second[0]["id"])
        assert result.compatible is False
        assert "source_row" in result.mismatches
        assert result.metric_deltas is None
        assert result.common_valid_count is None

    def test_same_candidate_is_rejected(self, tmp_path):
        from geomodeling.platform.professional import compare_candidates

        runtime, _frame = make_runtime_with_dataset(tmp_path)
        _, candidates = run_professional_experiment(runtime)
        candidate_id = candidates[0]["id"]

        with pytest.raises(PlatformError) as excinfo:
            compare_candidates(runtime, candidate_id, candidate_id)
        assert excinfo.value.code == "COMPARISON_SAME_CANDIDATE"
        assert excinfo.value.http_status == 409

    def test_missing_candidate_is_404(self, tmp_path):
        from geomodeling.platform.professional import compare_candidates

        runtime, _frame = make_runtime_with_dataset(tmp_path)
        _, candidates = run_professional_experiment(runtime)
        real_id = candidates[0]["id"]

        with pytest.raises(PlatformError) as excinfo:
            compare_candidates(runtime, "no-such-candidate", real_id)
        assert excinfo.value.code == "CANDIDATE_NOT_FOUND"
        assert excinfo.value.http_status == 404
        with pytest.raises(PlatformError) as excinfo:
            compare_candidates(runtime, real_id, "no-such-candidate")
        assert excinfo.value.code == "CANDIDATE_NOT_FOUND"

    def test_non_succeeded_candidate_is_409(self, tmp_path):
        from geomodeling.platform.professional import compare_candidates

        runtime, _frame = make_runtime_with_dataset(tmp_path)
        _, candidates = run_professional_experiment(
            runtime,
            search_mode="grid",
            parameters=[
                {"power": 2.0, "neighbor_count": 8},
                {"power": -1.0, "neighbor_count": 8},  # 非法参数 → 该候选失败
            ],
        )
        succeeded = next(c for c in candidates if c["status"] == "succeeded")
        failed = next(c for c in candidates if c["status"] == "failed")

        with pytest.raises(PlatformError) as excinfo:
            compare_candidates(runtime, succeeded["id"], failed["id"])
        assert excinfo.value.code == "CANDIDATE_NOT_SUCCEEDED"
        assert excinfo.value.http_status == 409

    def test_empty_common_valid_intersection_is_not_comparable(self, tmp_path):
        from geomodeling.platform.professional import compare_candidates

        runtime, _frame = make_runtime_with_dataset(tmp_path)
        _, idw_candidates = run_professional_experiment(runtime)
        _, kriging_candidates = run_professional_experiment(runtime, algorithm="ordinary_kriging")
        idw = idw_candidates[0]
        kriging = kriging_candidates[0]
        # 改写已登记 OOF 工件：两方有效行互补 → 公共有效交集为空。
        # 改写后同步重新登记 manifest 哈希（合法再登记，不是篡改）——
        # 比较只读「已登记且哈希吻合」的工件（§4.3/§16）。
        for candidate_id, nodata_below in ((idw["id"], True), (kriging["id"], False)):
            path = oof_path(runtime, candidate_id)
            oof = pd.read_parquet(path)
            below = oof["source_row"] <= 18
            oof["is_nodata"] = below if nodata_below else ~below
            oof.to_parquet(path, index=False)
            reregister_artifact_hash(runtime, candidate_id, "out_of_fold_predictions", path)

        result = compare_candidates(runtime, idw["id"], kriging["id"])
        assert result.compatible is False
        assert set(result.mismatches) == {"common_valid_mask"}
        assert result.metric_deltas is None
        assert result.common_valid_count is None
        assert result.grid_difference_available is False


# ---------------------------------------------------------------------------
# 兼容比较：跨实验交集口径重算（绝不复用 run 内公共掩膜）、差值方向、指纹
# ---------------------------------------------------------------------------


class TestCompatibleComparison:
    def test_cross_experiment_comparison_recomputes_common_valid(self, tmp_path):
        from geomodeling.platform.professional import compare_candidates

        runtime, _frame = make_runtime_with_dataset(tmp_path)
        _limited, unlimited, kriging = run_idw_pair_and_kriging(runtime)

        result = compare_candidates(runtime, unlimited["id"], kriging["id"])
        assert result.compatible is True
        assert result.mismatches == []

        idw_oof, krig_oof = aligned_pair(
            load_oof(runtime, unlimited["id"]), load_oof(runtime, kriging["id"])
        )
        assert (idw_oof["source_row"].to_numpy() == krig_oof["source_row"].to_numpy()).all()
        expected = (~idw_oof["is_nodata"].to_numpy()) & (~krig_oof["is_nodata"].to_numpy())
        assert result.common_valid_count == int(expected.sum()) == 36
        # 绝不复用 run 内预存的公共掩膜：run A 公共口径是小半径候选的有效子集
        assert unlimited["metrics"]["common_valid_count"] < result.common_valid_count
        assert set(result.metric_deltas) == {"mae", "rmse", "r2", "bias"}
        assert all(np.isfinite(value) for value in result.metric_deltas.values())
        # 未物化网格：场差不可用，但不影响兼容指标差
        assert result.grid_difference_available is False
        assert result.grid_difference is None

    def test_metric_deltas_recomputed_on_pair_intersection_first_minus_second(self, tmp_path):
        from geomodeling.platform.professional import compare_candidates

        runtime, _frame = make_runtime_with_dataset(tmp_path)
        _limited, unlimited, kriging = run_idw_pair_and_kriging(runtime)

        result = compare_candidates(runtime, unlimited["id"], kriging["id"])
        first, second = aligned_pair(
            load_oof(runtime, unlimited["id"]), load_oof(runtime, kriging["id"])
        )
        mask = (~first["is_nodata"].to_numpy()) & (~second["is_nodata"].to_numpy())
        truth = first["observed"].to_numpy(dtype="float64")[mask]

        def metrics(predicted: np.ndarray) -> dict[str, float]:
            errors = predicted[mask] - truth
            ss_res = float((errors**2).sum())
            centered = truth - truth.mean()
            ss_tot = float((centered**2).sum())
            return {
                "mae": float(np.abs(errors).mean()),
                "rmse": float(np.sqrt((errors**2).mean())),
                "bias": float(errors.mean()),
                "r2": 1.0 - ss_res / ss_tot if ss_tot else (1.0 if ss_res == 0.0 else 0.0),
            }

        first_metrics = metrics(first["predicted"].to_numpy(dtype="float64"))
        second_metrics = metrics(second["predicted"].to_numpy(dtype="float64"))
        expected = {
            key: first_metrics[key] - second_metrics[key] for key in ("mae", "rmse", "r2", "bias")
        }
        assert result.metric_deltas == pytest.approx(expected)

        # 差值方向为 first − second：交换顺序后差值取反，交集口径不变
        swapped = compare_candidates(runtime, kriging["id"], unlimited["id"])
        assert swapped.metric_deltas == pytest.approx(
            {key: -value for key, value in result.metric_deltas.items()}
        )
        assert swapped.common_valid_count == result.common_valid_count

    def test_comparison_fingerprint_is_deterministic_and_directional(self, tmp_path):
        from geomodeling.platform.professional import compare_candidates

        runtime, _frame = make_runtime_with_dataset(tmp_path)
        _limited, unlimited, kriging = run_idw_pair_and_kriging(runtime)

        first = compare_candidates(runtime, unlimited["id"], kriging["id"])
        second = compare_candidates(runtime, unlimited["id"], kriging["id"])
        assert first.comparison_fingerprint == second.comparison_fingerprint

        idw_rows = set(load_oof(runtime, unlimited["id"])["source_row"].tolist())
        krig_rows = set(load_oof(runtime, kriging["id"])["source_row"].tolist())
        payload = {
            "first_fingerprint": unlimited["fingerprint"],
            "second_fingerprint": kriging["fingerprint"],
            "common_source_rows": sorted(idw_rows & krig_rows),
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        assert first.comparison_fingerprint == expected

        swapped = compare_candidates(runtime, kriging["id"], unlimited["id"])
        assert swapped.comparison_fingerprint != first.comparison_fingerprint


# ---------------------------------------------------------------------------
# 场差：同一网格轴 + 共同有效节点上的有界摘要；轴不一致不生成差值
# ---------------------------------------------------------------------------


class TestGridDifference:
    def test_identical_grids_compute_difference_on_common_valid_only(self, tmp_path):
        from geomodeling.platform.professional import compare_candidates
        from geomodeling.platform.results import materialize

        runtime, _frame = make_runtime_with_dataset(tmp_path)
        _, idw_candidates = run_professional_experiment(runtime, neighborhood=NEIGHBORHOOD_NARROW)
        _, kriging_candidates = run_professional_experiment(runtime, algorithm="ordinary_kriging")
        idw = idw_candidates[0]
        kriging = kriging_candidates[0]
        materialize(runtime, idw["id"])
        materialize(runtime, kriging["id"])

        result = compare_candidates(runtime, idw["id"], kriging["id"])
        assert result.compatible is True
        assert result.grid_difference_available is True
        summary = result.grid_difference
        assert summary is not None

        with np.load(runtime.settings.result_grid(idw["id"]), allow_pickle=True) as bundle:
            first_values, first_nodata = bundle["values"], bundle["is_nodata"]
        with np.load(runtime.settings.result_grid(kriging["id"]), allow_pickle=True) as bundle:
            second_values, second_nodata = bundle["values"], bundle["is_nodata"]
        common = (~first_nodata) & (~second_nodata)
        # 非平凡：窄邻域 IDW 网格部分 NoData，场差只在共同有效节点上计算
        assert 0 < int(common.sum()) < int(first_values.size)
        difference = first_values[common] - second_values[common]
        assert summary.common_valid_count == int(common.sum())
        assert summary.mean == pytest.approx(float(difference.mean()))
        assert summary.max_abs == pytest.approx(float(np.abs(difference).max()))

    def test_grid_mismatch_disables_field_difference_but_keeps_metric_deltas(self, tmp_path):
        from geomodeling.platform.professional import compare_candidates
        from geomodeling.platform.results import materialize

        runtime, _frame = make_runtime_with_dataset(tmp_path)
        _, idw_candidates = run_professional_experiment(runtime)
        explicit_grid = {
            "bounds": [[-160.0, -40.0], [220.0, 660.0]],
            "resolution": [15.0, 55.0],
        }
        _, kriging_candidates = run_professional_experiment(
            runtime, algorithm="ordinary_kriging", grid=explicit_grid
        )
        idw = idw_candidates[0]
        kriging = kriging_candidates[0]
        materialize(runtime, idw["id"])
        materialize(runtime, kriging["id"])

        result = compare_candidates(runtime, idw["id"], kriging["id"])
        assert result.compatible is True
        assert result.metric_deltas is not None
        assert result.common_valid_count == 36
        # 轴不一致 → 场差不可用且不生成差值（完整场差下载在 Task 17/19 决定）
        assert result.grid_difference_available is False
        assert result.grid_difference is None


# ---------------------------------------------------------------------------
# 验证折分指纹：从登记的 fold_assignments 工件重算，与 run 期定义逐位一致
# ---------------------------------------------------------------------------


class TestValidationFingerprintRecomputation:
    def test_recomputed_fingerprint_matches_run_fingerprint_definition(self, tmp_path):
        from geomodeling.modeling.comparison import validation_fingerprint_from_assignments
        from geomodeling.modeling.fold_artifacts import build_fold_assignments
        from geomodeling.modeling.splits import build_spatial_splits
        from geomodeling.platform.schemas import SpatialValidationSpec

        runtime, frame = make_runtime_with_dataset(tmp_path)
        _, candidates = run_professional_experiment(runtime)
        candidate = candidates[0]

        spec = SpatialValidationSpec.model_validate(VALIDATION_DEFAULT)
        valid = frame.loc[frame["is_numeric_valid"]].reset_index(drop=True)
        folds = build_spatial_splits(valid[["x", "y"]].to_numpy(dtype="float64"), "2d", spec)
        _assignments, expected = build_fold_assignments(
            valid, folds, dimension="2d", validation=spec, data_sha256="b" * 64
        )

        registered = pd.read_parquet(
            runtime.settings.professional_result_dir(candidate["id"]) / "fold_assignments.parquet"
        )
        recomputed = validation_fingerprint_from_assignments(
            registered, validation=spec, data_sha256="b" * 64
        )
        assert recomputed == expected


# ---------------------------------------------------------------------------
# 比较证据链完整性：只读「已登记且哈希吻合」的工件（设计 §4.3/§16，fail-closed）
# ---------------------------------------------------------------------------


def artifacts_row(runtime: PlatformRuntime, candidate_id: str):
    with runtime.session() as session:
        return (
            session.query(tables.ProfessionalResultArtifacts)
            .filter(tables.ProfessionalResultArtifacts.candidate_result_id == candidate_id)
            .one_or_none()
        )


def set_artifacts_status(runtime: PlatformRuntime, candidate_id: str, status: str) -> None:
    """直写工件行状态（手工构造场景；生产路径只有 pending→succeeded/failed）。"""

    with runtime.session() as session:
        row = session.query(tables.ProfessionalResultArtifacts).filter(
            tables.ProfessionalResultArtifacts.candidate_result_id == candidate_id
        ).one()
        row.status = status
        session.commit()


def delete_artifacts_row(runtime: PlatformRuntime, candidate_id: str) -> None:
    with runtime.session() as session:
        row = session.query(tables.ProfessionalResultArtifacts).filter(
            tables.ProfessionalResultArtifacts.candidate_result_id == candidate_id
        ).one()
        session.delete(row)
        session.commit()


def reregister_artifact_hash(
    runtime: PlatformRuntime, candidate_id: str, logical: str, path: Path
) -> None:
    """工件合法改写后同步登记 manifest 哈希（模拟重新登记，而非篡改）。"""

    blob = path.read_bytes()
    with runtime.session() as session:
        row = session.query(tables.ProfessionalResultArtifacts).filter(
            tables.ProfessionalResultArtifacts.candidate_result_id == candidate_id
        ).one()
        manifest = tables.loads_canonical(row.manifest_json)
        manifest["artifacts"][logical] = {
            "file": path.name,
            "sha256": hashlib.sha256(blob).hexdigest(),
            "bytes": len(blob),
        }
        row.manifest_json = tables.dumps_canonical(manifest)
        session.commit()


def tamper_artifact(path: Path) -> None:
    """篡改登记工件：追加字节使登记 SHA-256/大小不再吻合。"""

    with path.open("ab") as handle:
        handle.write(b"tampered-evidence")


def comparison_registry_files(runtime: PlatformRuntime) -> list[Path]:
    directory = runtime.settings.data_dir / "comparisons"
    return sorted(directory.glob("*.json")) if directory.is_dir() else []


def run_legacy_experiment(
    runtime: PlatformRuntime,
    *,
    case_id: str = "c1",
    dataset_id: str = "ds1",
    parameters: dict | None = None,
) -> tuple[str, list[dict]]:
    """构造 legacy 实验（无专业上下文）并运行到成功：不产生专业工件行。"""

    from geomodeling.modeling.runner import execute_run

    search = {
        "dimension": "2d",
        "algorithm": "idw",
        "dataset_version_id": dataset_id,
        "search_mode": "manual",
        "parameters": parameters or {"power": 2.0, "neighbor_count": 8},
        "validation": dict(VALIDATION_DEFAULT),
        "grid": None,
    }
    experiment_id = insert_experiment(runtime, case_id, dataset_id, search)
    run_id = insert_run(runtime, experiment_id)
    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    return run_id, load_candidates(runtime, run_id)


class TestComparisonManifestVerification:
    def test_tampered_oof_parquet_is_rejected(self, tmp_path):
        """篡改 OOF parquet（追加字节）→ 409 fail-closed，details 不含本机路径。"""

        from geomodeling.platform.professional import compare_candidates

        runtime, _frame = make_runtime_with_dataset(tmp_path)
        _limited, unlimited, kriging = run_idw_pair_and_kriging(runtime)
        tamper_artifact(oof_path(runtime, unlimited["id"]))

        with pytest.raises(PlatformError) as excinfo:
            compare_candidates(runtime, unlimited["id"], kriging["id"])
        assert excinfo.value.code == "MANIFEST_VERIFICATION_FAILED"
        assert excinfo.value.http_status == 409
        assert excinfo.value.details["artifact"] == "out_of_fold_predictions"
        assert str(tmp_path) not in json.dumps(excinfo.value.details, ensure_ascii=False)
        # fail-closed：不得留下任何比较登记
        assert comparison_registry_files(runtime) == []

    def test_tampered_fold_assignments_parquet_is_rejected(self, tmp_path):
        """篡改 fold_assignments parquet → 409 fail-closed。"""

        from geomodeling.platform.professional import compare_candidates

        runtime, _frame = make_runtime_with_dataset(tmp_path)
        _limited, unlimited, kriging = run_idw_pair_and_kriging(runtime)
        tamper_artifact(
            runtime.settings.professional_result_dir(kriging["id"]) / "fold_assignments.parquet"
        )

        with pytest.raises(PlatformError) as excinfo:
            compare_candidates(runtime, unlimited["id"], kriging["id"])
        assert excinfo.value.code == "MANIFEST_VERIFICATION_FAILED"
        assert excinfo.value.http_status == 409
        assert excinfo.value.details["artifact"] == "fold_assignments"
        assert str(tmp_path) not in json.dumps(excinfo.value.details, ensure_ascii=False)
        assert comparison_registry_files(runtime) == []

    @pytest.mark.parametrize("status", ["pending", "failed"])
    def test_non_succeeded_artifacts_row_is_rejected(self, tmp_path, status):
        """工件行存在但非 succeeded：登记证据不可信 → 409 fail-closed。"""

        from geomodeling.platform.professional import compare_candidates

        runtime, _frame = make_runtime_with_dataset(tmp_path)
        _limited, unlimited, kriging = run_idw_pair_and_kriging(runtime)
        set_artifacts_status(runtime, kriging["id"], status)

        with pytest.raises(PlatformError) as excinfo:
            compare_candidates(runtime, unlimited["id"], kriging["id"])
        assert excinfo.value.code == "MANIFEST_VERIFICATION_FAILED"
        assert excinfo.value.http_status == 409
        assert str(tmp_path) not in json.dumps(excinfo.value.details, ensure_ascii=False)
        assert comparison_registry_files(runtime) == []

    def test_missing_artifacts_row_for_professional_candidate_is_rejected(self, tmp_path):
        """专业候选缺工件行（登记链断裂）→ 409 fail-closed。"""

        from geomodeling.platform.professional import compare_candidates

        runtime, _frame = make_runtime_with_dataset(tmp_path)
        _limited, unlimited, kriging = run_idw_pair_and_kriging(runtime)
        delete_artifacts_row(runtime, kriging["id"])

        with pytest.raises(PlatformError) as excinfo:
            compare_candidates(runtime, unlimited["id"], kriging["id"])
        assert excinfo.value.code == "MANIFEST_VERIFICATION_FAILED"
        assert excinfo.value.http_status == 409
        assert comparison_registry_files(runtime) == []

    def test_legacy_candidates_compare_without_registered_manifest(self, tmp_path):
        """legacy 候选（无专业工件行）保持现状兼容：行为不变，本修复不强制。

        legacy run 也落 OOF/fold parquet 但从不登记 manifest；比较证据链
        只对专业候选（有工件行）强制哈希校验，legacy 路径沿用既有文件
        存在性检查（COMPARISON_EVIDENCE_INCOMPLETE）。
        """

        from geomodeling.platform.professional import compare_candidates

        runtime, _frame = make_runtime_with_dataset(tmp_path)
        _, first_candidates = run_legacy_experiment(runtime)
        _, second_candidates = run_legacy_experiment(
            runtime, parameters={"power": 3.0, "neighbor_count": 8}
        )
        first, second = first_candidates[0], second_candidates[0]
        # 锁定前提：legacy 候选没有任何专业工件行
        assert artifacts_row(runtime, first["id"]) is None
        assert artifacts_row(runtime, second["id"]) is None

        result = compare_candidates(runtime, first["id"], second["id"])
        assert result.compatible is True
        assert result.metric_deltas is not None
        assert result.common_valid_count == 36

    def test_tampered_evidence_returns_409_and_registers_no_comparison(self, tmp_path):
        """API 级：篡改工件 → 409，且 data_dir/comparisons 下不得出现新文件。"""

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from geomodeling.api.routes import professional as professional_routes
        from geomodeling.platform.errors import platform_error_handler

        runtime, _frame = make_runtime_with_dataset(tmp_path)
        _limited, unlimited, kriging = run_idw_pair_and_kriging(runtime)

        app = FastAPI()
        app.add_exception_handler(PlatformError, platform_error_handler)
        app.include_router(professional_routes.router)
        app.state.platform_runtime = runtime
        client = TestClient(app)

        # 未篡改：正常登记一次，锁定基线文件数
        resp = client.post(
            "/api/professional-comparisons",
            json={"first_result_id": unlimited["id"], "second_result_id": kriging["id"]},
        )
        assert resp.status_code == 201, resp.text
        baseline = comparison_registry_files(runtime)
        assert len(baseline) == 1

        tamper_artifact(oof_path(runtime, unlimited["id"]))
        resp = client.post(
            "/api/professional-comparisons",
            json={"first_result_id": unlimited["id"], "second_result_id": kriging["id"]},
        )
        assert resp.status_code == 409, resp.text
        body = resp.json()
        assert body["error"]["code"] == "MANIFEST_VERIFICATION_FAILED"
        assert str(tmp_path) not in json.dumps(body["error"]["details"], ensure_ascii=False)
        assert comparison_registry_files(runtime) == baseline
