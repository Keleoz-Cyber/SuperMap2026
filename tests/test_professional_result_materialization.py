"""Task 15 contract tests: professional value/uncertainty grid materialization.

专业候选物化（设计 §5.3/§6.4/§9/§10）：

- 最终模型在全部有效建模数据上重新拟合并标记 ``final_full_data_fit``；
  人工固定参数策略继续用已确认参数（``manual_confirmed``，用户先验）；
  折内参数只用于验证指标，两类参数在 metadata 中分别展示。
- Kriging 原生标准差与全算法经验误差尺度落盘为与值网格同一物理轴的
  ``.npz`` 工件（NaN 处理与值网格一致）；IDW 的 ``native_kriging_std``
  以 capability ``not_applicable`` 明示，绝不生成空文件占位。
- 经验误差尺度来自候选 OOF 工件，与候选同一空间变换指纹；邻点不足即
  NoData，绝不用全局 RMSE 填充空间场。
- 同级临时目录写齐 → 回读校验 shape/hash → 原子替换 → 替换成功后才更
  新数据库工件行；失败逐步清理且清理异常不覆盖业务异常。
- 重复 materialize 重读既有工件并验证（manifest 哈希 + 网格形状），不
  盲目重算；哈希不匹配 fail-closed。
- preview 接受 ``layer=value|empirical_error|kriging_std``：算法不适用
  的层 409，未物化的层 404，绝不返回 0 场。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
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

KRIGING_MANUAL_CONFIRMATION_CONFIG = {
    "model": "spherical",
    "parameter_strategy": "manual",
    "parameter_origin": "manual_confirmed",
    "prior": "user_prior",
    "manual_parameters": {"nugget": 0.05, "sill": 3.0, "range": 120.0},
    "anisotropy": {"keep_isotropic": True},
}

NEIGHBORHOOD_WIDE = {"radii": [500.0, 500.0], "min_neighbors": 2, "max_neighbors": 8}
EMPIRICAL_WIDE = {"min_neighbors": 2, "max_neighbors": 8}

SEARCH_KRIGING_PRO = {
    "dimension": "2d",
    "algorithm": "ordinary_kriging",
    "dataset_version_id": "ds1",
    "search_mode": "manual",
    "parameters": {"neighbor_count": 8},
    "validation": {"method": "spatial_kfold", "folds": 3, "seed": 11, "holdout_fraction": 0.2},
    "grid": None,
}

SEARCH_IDW_PRO = {
    **SEARCH_KRIGING_PRO,
    "algorithm": "idw",
    "parameters": {"power": 2.0, "neighbor_count": 8},
}


def make_runtime(tmp_path: Path) -> PlatformRuntime:
    runtime = PlatformRuntime(tmp_path / "runtime")
    runtime.initialize()
    return runtime


def make_standardized(runtime: PlatformRuntime, case_id: str, dataset_id: str):
    """小样本 2D 标准化 parquet（平滑场，与 runner 测试同一生成器）。"""

    rng = np.random.default_rng(20260723)
    n = 36
    x = rng.uniform(-160.0, -40.0, n)
    y = rng.uniform(220.0, 660.0, n)
    value = np.sin(x / 40) + np.cos(y / 90) + 10.0
    frame = pd.DataFrame(
        {
            "source_row": np.arange(1, n + 1),
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


def insert_experiment(
    runtime: PlatformRuntime,
    case_id: str,
    dataset_id: str,
    search: dict,
    standardized_path: Path,
) -> str:
    import uuid

    search = dict(search)
    experiment_id = str(uuid.uuid4())
    with runtime.session() as session:
        session.add(tables.Case(id=case_id, name="案例", case_type="generic", config_json="{}"))
        session.add(
            tables.DatasetVersion(
                id=dataset_id,
                case_id=case_id,
                version=1,
                status="validated",
                source_path="x.csv",
                profile_json=tables.dumps_canonical(
                    {
                        "mapping": {
                            "dimension": search.pop("dimension"),
                            "x": "x",
                            "y": "y",
                            "z": None,
                            "value": "value",
                            "value_name": "属性",
                            "coordinate_kind": "local_linear",
                        },
                        "source_sha256": "a" * 64,
                        "standardized_sha256": "b" * 64,
                        "standardized_path": str(standardized_path),
                        "quality": {"status": "passed", "confirmed": True},
                    }
                ),
            )
        )
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
    import uuid

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
    config: dict,
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
                config_json=tables.dumps_canonical(config),
                fingerprint="f" * 64,
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
    with runtime.session() as session:
        row = session.get(tables.Experiment, experiment_id)
        params = tables.loads_canonical(row.params_json)
        params["professional"] = professional
        row.params_json = tables.dumps_canonical(params)
        session.commit()


def run_professional_candidate(
    runtime: PlatformRuntime,
    *,
    algorithm: str = "ordinary_kriging",
    confirmation: str = "auto",
    neighborhood: dict | None = NEIGHBORHOOD_WIDE,
    empirical_uncertainty: dict | None = EMPIRICAL_WIDE,
) -> dict:
    """构造专业实验并运行到成功候选（Task 14 证据链真实路径）。"""

    from geomodeling.modeling.runner import execute_run

    target, _frame = make_standardized(runtime, "c1", "ds1")
    search = dict(SEARCH_KRIGING_PRO if algorithm == "ordinary_kriging" else SEARCH_IDW_PRO)
    experiment_id = insert_experiment(runtime, "c1", "ds1", search, target)
    request_kwargs: dict = {
        "algorithm": algorithm,
        "parameters": search["parameters"],
        "neighborhood": neighborhood,
        "empirical_uncertainty": empirical_uncertainty,
    }
    if algorithm == "ordinary_kriging":
        config = (
            KRIGING_AUTO_CONFIRMATION_CONFIG
            if confirmation == "auto"
            else KRIGING_MANUAL_CONFIRMATION_CONFIG
        )
        insert_professional_confirmation(runtime, "ds1", config=config)
        request_kwargs["professional_confirmation_id"] = "conf-1"
    professional = resolve_context(runtime, "ds1", **request_kwargs)
    attach_professional(runtime, experiment_id, professional)
    run_id = insert_run(runtime, experiment_id)

    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    candidate = load_candidates(runtime, run_id)[0]
    assert candidate["status"] == "succeeded"
    return candidate


def run_legacy_candidate(runtime: PlatformRuntime) -> dict:
    """legacy（无专业上下文）IDW 成功候选。"""

    from geomodeling.modeling.runner import execute_run

    target, _frame = make_standardized(runtime, "c1", "ds1")
    experiment_id = insert_experiment(runtime, "c1", "ds1", dict(SEARCH_IDW_PRO), target)
    run_id = insert_run(runtime, experiment_id)
    outcome = execute_run(runtime, run_id, threading.Event())
    assert outcome.status == "succeeded"
    return load_candidates(runtime, run_id)[0]


def load_grid_axes(runtime: PlatformRuntime, result_id: str) -> tuple:
    with np.load(runtime.settings.result_grid(result_id), allow_pickle=True) as bundle:
        return tuple(np.asarray(a, dtype=float) for a in bundle["axes"])


def grid_query(axes: tuple) -> np.ndarray:
    return np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, len(axes))


# ---------------------------------------------------------------------------
# Kriging 物化：原生标准差 / 全数据拟合来源 / 同一物理轴 / 经验误差 / manifest
# ---------------------------------------------------------------------------


class TestKrigingMaterialization:
    def test_kriging_materialization_writes_native_std_grid(self, tmp_path):
        from geomodeling.platform.results import materialize

        runtime = make_runtime(tmp_path)
        candidate = run_professional_candidate(runtime)

        metadata = materialize(runtime, candidate["id"])
        assert metadata["professional"]["kriging_standard_deviation"]["available"] is True
        with np.load(
            runtime.settings.professional_result_dir(candidate["id"])
            / "kriging_standard_deviation.npz"
        ) as f:
            assert f["values"].shape == tuple(metadata["shape"])
            assert np.nanmin(f["values"]) >= 0

    def test_final_grid_originates_from_full_data_fit(self, tmp_path):
        from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator
        from geomodeling.platform.results import materialize

        runtime = make_runtime(tmp_path)
        candidate = run_professional_candidate(runtime)
        metadata = materialize(runtime, candidate["id"])

        provenance = metadata["professional"]["parameter_provenance"]
        # 全数据拟合参数只用于最终空间成果，不得描述成折内交叉验证结果（§6.4 末段）
        assert provenance["final"]["origin"] == "final_full_data_fit"
        assert provenance["final"]["scope"] == "all_valid_rows"
        assert provenance["validation"]["origin"] == "automatic_candidate"
        assert provenance["validation"]["origin"] != provenance["final"]["origin"]

        # 独立重算：全部有效行拟合 → 同一网格查询 → 值与原生标准差逐点一致
        frame = pd.read_parquet(runtime.settings.standardized_dataset("c1", "ds1"))
        valid = frame.loc[frame["is_numeric_valid"]].reset_index(drop=True)
        points = valid[["x", "y"]].to_numpy(dtype="float64")
        values = valid["value"].to_numpy(dtype="float64")
        interpolator = OrdinaryKrigingInterpolator()
        validated = interpolator.validate_parameters(candidate["params"], "2d")
        fitted = interpolator.fit(points, values, validated)
        with np.load(runtime.settings.result_grid(candidate["id"]), allow_pickle=True) as bundle:
            axes = tuple(np.asarray(a, dtype=float) for a in bundle["axes"])
            grid_values = bundle["values"]
            grid_nodata = bundle["is_nodata"]
        expected = fitted.predict(grid_query(axes), cancel=lambda: False)
        assert np.allclose(
            grid_values, expected.values.reshape(grid_values.shape), equal_nan=True
        )
        with np.load(
            runtime.settings.professional_result_dir(candidate["id"])
            / "kriging_standard_deviation.npz"
        ) as f:
            assert np.allclose(
                f["values"],
                expected.auxiliary["kriging_standard_deviation"].reshape(f["values"].shape),
                equal_nan=True,
            )
            # 原生标准差与值网格同一 NoData（NaN 处理一致）
            assert (f["is_nodata"] == grid_nodata).all()

    def test_manual_strategy_final_fit_uses_confirmed_triple(self, tmp_path):
        from geomodeling.platform.results import materialize

        runtime = make_runtime(tmp_path)
        candidate = run_professional_candidate(runtime, confirmation="manual")
        metadata = materialize(runtime, candidate["id"])

        provenance = metadata["professional"]["parameter_provenance"]
        # 人工固定参数策略：继续用已确认参数（用户先验），不标记全数据重拟合
        assert provenance["final"]["origin"] == "manual_confirmed"
        assert provenance["validation"]["origin"] == "manual_confirmed"
        variogram = provenance["final"]["variogram"]
        assert variogram["nugget"] == pytest.approx(0.05)
        assert variogram["partial_sill"] == pytest.approx(2.95)
        assert variogram["range"] == pytest.approx(120.0)
        assert metadata["professional"]["kriging_standard_deviation"]["available"] is True

    def test_uncertainty_layers_share_value_grid_physical_axes(self, tmp_path):
        from geomodeling.platform.results import materialize

        runtime = make_runtime(tmp_path)
        candidate = run_professional_candidate(runtime)
        metadata = materialize(runtime, candidate["id"])
        professional_dir = runtime.settings.professional_result_dir(candidate["id"])

        # 专业 metadata 与结果 metadata 声明同一物理坐标轴
        pro_meta = json.loads((professional_dir / "metadata.json").read_text(encoding="utf-8"))
        assert pro_meta["grid"]["shape"] == metadata["shape"]
        assert pro_meta["grid"]["bounds"] == metadata["bounds"]
        assert pro_meta["grid"]["resolution"] == metadata["resolution"]

        shape = tuple(metadata["shape"])
        with np.load(professional_dir / "empirical_error_scale.npz") as f:
            assert f["scale"].shape == shape
            assert f["is_nodata"].shape == shape
            assert f["neighbor_count"].shape == shape
        with np.load(professional_dir / "kriging_standard_deviation.npz") as f:
            assert f["values"].shape == shape
            assert f["is_nodata"].shape == shape

    def test_empirical_error_scale_matches_oof_recomputation(self, tmp_path):
        from geomodeling.modeling.anisotropy import (
            KrigingAnisotropySpec,
            build_kriging_transform,
        )
        from geomodeling.modeling.professional_contracts import (
            EmpiricalUncertaintySpec,
            NeighborhoodSpec,
        )
        from geomodeling.modeling.uncertainty import empirical_error_scale
        from geomodeling.platform.results import materialize

        runtime = make_runtime(tmp_path)
        candidate = run_professional_candidate(runtime)
        metadata = materialize(runtime, candidate["id"])
        professional_dir = runtime.settings.professional_result_dir(candidate["id"])

        # 从候选 OOF 工件独立重算：残差点 + 候选搜索邻域 + 候选规范变换
        oof = pd.read_parquet(professional_dir / "out_of_fold_predictions.parquet")
        spec = EmpiricalUncertaintySpec.model_validate(EMPIRICAL_WIDE).model_copy(
            update={
                "neighborhood": NeighborhoodSpec.model_validate(
                    candidate["params"]["neighborhood"]
                )
            }
        )
        transform = build_kriging_transform(
            KrigingAnisotropySpec.model_validate(candidate["params"]["anisotropy"])
        )
        expected = empirical_error_scale(
            residual_points=oof[["x", "y"]].to_numpy(dtype="float64"),
            residuals=oof["residual"].to_numpy(dtype="float64"),
            query=grid_query(load_grid_axes(runtime, candidate["id"])),
            spec=spec,
            distance_transform=transform,
        )
        with np.load(professional_dir / "empirical_error_scale.npz") as f:
            shape = f["scale"].shape
            assert np.allclose(f["scale"], expected.scale.reshape(shape), equal_nan=True)
            assert (f["is_nodata"] == expected.is_nodata.reshape(shape)).all()
            assert (f["neighbor_count"] == expected.neighbor_count.reshape(shape)).all()

        # 同一变换指纹：经验误差距离与候选拟合距离共用同一指纹（§7.2/§10.2）
        assert metadata["professional"]["transform_fingerprint"] == transform.fingerprint
        summary = json.loads(
            (professional_dir / "neighborhood_summary.json").read_text(encoding="utf-8")
        )
        assert summary["empirical_error_scale"]["transform_fingerprint"] == transform.fingerprint
        assert summary["final_fit_diagnostics"]["transform_fingerprint"] == transform.fingerprint

    def test_manifest_covers_materialization_artifacts_and_db_row_updated(self, tmp_path):
        from geomodeling.platform.professional import verify_manifest
        from geomodeling.platform.repositories import ProfessionalResultArtifactsRepository
        from geomodeling.platform.results import materialize

        runtime = make_runtime(tmp_path)
        candidate = run_professional_candidate(runtime)
        with runtime.session() as session:
            before = ProfessionalResultArtifactsRepository(session).get_for_candidate(
                candidate["id"]
            )
        assert set(before.manifest["artifacts"]) == {
            "fold_assignments",
            "out_of_fold_predictions",
            "prediction_diagnostics",
        }

        materialize(runtime, candidate["id"])

        with runtime.session() as session:
            after = ProfessionalResultArtifactsRepository(session).get_for_candidate(
                candidate["id"]
            )
        # 替换成功后才更新数据库工件行：物化工件纳入 manifest 身份
        assert set(after.manifest["artifacts"]) == {
            "fold_assignments",
            "out_of_fold_predictions",
            "prediction_diagnostics",
            "empirical_error_scale",
            "kriging_standard_deviation",
            "neighborhood_summary",
            "metadata",
        }
        assert verify_manifest(after.manifest)
        assert after.manifest["capabilities"]["native_kriging_std"] == "supported"
        assert after.manifest["materialization"]["final_fit_origin"] == "final_full_data_fit"
        # fold/OOF 已在 Task 9 落盘：纳入身份但不重写（哈希与 run 期一致）
        assert (
            after.manifest["artifacts"]["fold_assignments"]["sha256"]
            == before.manifest["artifacts"]["fold_assignments"]["sha256"]
        )
        assert (
            after.manifest["artifacts"]["out_of_fold_predictions"]["sha256"]
            == before.manifest["artifacts"]["out_of_fold_predictions"]["sha256"]
        )


# ---------------------------------------------------------------------------
# IDW 物化：原生标准差 capability not_applicable；经验误差照常；NoData 不填充
# ---------------------------------------------------------------------------


class TestIDWMaterialization:
    def test_idw_kriging_std_not_applicable_but_empirical_error_available(self, tmp_path):
        from geomodeling.platform.professional import verify_manifest
        from geomodeling.platform.repositories import ProfessionalResultArtifactsRepository
        from geomodeling.platform.results import materialize

        runtime = make_runtime(tmp_path)
        candidate = run_professional_candidate(runtime, algorithm="idw")
        metadata = materialize(runtime, candidate["id"])

        kriging_std = metadata["professional"]["kriging_standard_deviation"]
        assert kriging_std["available"] is False
        assert kriging_std["capability"] == "not_applicable"

        professional_dir = runtime.settings.professional_result_dir(candidate["id"])
        # 能力不适用：绝不生成空文件占位
        assert not (professional_dir / "kriging_standard_deviation.npz").exists()

        empirical = metadata["professional"]["empirical_error_scale"]
        assert empirical["available"] is True
        with np.load(professional_dir / "empirical_error_scale.npz") as f:
            assert f["scale"].shape == tuple(metadata["shape"])

        with runtime.session() as session:
            artifacts = ProfessionalResultArtifactsRepository(session).get_for_candidate(
                candidate["id"]
            )
        assert "kriging_standard_deviation" not in artifacts.manifest["artifacts"]
        assert artifacts.manifest["capabilities"]["native_kriging_std"] == "not_applicable"
        assert verify_manifest(artifacts.manifest)

    def test_idw_empirical_error_uses_legacy_z_scale_transform(self, tmp_path):
        from geomodeling.modeling.uncertainty import identity_transform
        from geomodeling.platform.results import materialize

        runtime = make_runtime(tmp_path)
        candidate = run_professional_candidate(runtime, algorithm="idw")
        metadata = materialize(runtime, candidate["id"])
        # 2D legacy z_scale 距离空间即恒等变换（规范指纹）
        assert metadata["professional"]["transform_fingerprint"] == identity_transform(2).fingerprint

    def test_empirical_error_scale_is_local_not_constant(self, tmp_path):
        from geomodeling.platform.results import materialize

        runtime = make_runtime(tmp_path)
        candidate = run_professional_candidate(runtime, algorithm="idw")
        materialize(runtime, candidate["id"])
        with np.load(
            runtime.settings.professional_result_dir(candidate["id"])
            / "empirical_error_scale.npz"
        ) as f:
            scale = f["scale"]
            is_nodata = f["is_nodata"]
            neighbor_count = f["neighbor_count"]
        finite = scale[~is_nodata]
        assert finite.size > 0
        assert np.isfinite(finite).all()
        # 局部残差汇总：绝不用全局 RMSE 常量填满空间场
        assert np.unique(finite).size > 1
        # NoData 语义：NaN 且邻点计数为 0
        assert np.isnan(scale[is_nodata]).all()
        assert (neighbor_count[is_nodata] == 0).all()

    def test_insufficient_neighbors_are_nodata_never_global_rmse_fill(self, tmp_path):
        from geomodeling.platform.results import materialize

        runtime = make_runtime(tmp_path)
        # 误差邻域可选邻点上限（max_neighbors 默认 24）< min_neighbors 30：
        # 任何查询都不可能满足 → 全部 NoData
        candidate = run_professional_candidate(
            runtime,
            algorithm="idw",
            empirical_uncertainty={
                "min_neighbors": 30,
                "max_neighbors": 36,
                "neighborhood": {"radii": [500.0, 500.0]},
            },
        )
        metadata = materialize(runtime, candidate["id"])
        with np.load(
            runtime.settings.professional_result_dir(candidate["id"])
            / "empirical_error_scale.npz"
        ) as f:
            assert f["is_nodata"].all()
            assert np.isnan(f["scale"]).all()
            assert (f["neighbor_count"] == 0).all()
        # 邻点不足 NoData 也是有效工件（available），但绝不用常量冒充局部不确定性
        assert metadata["professional"]["empirical_error_scale"]["available"] is True
        assert metadata["professional"]["empirical_error_scale"]["coverage"] == 0.0


# ---------------------------------------------------------------------------
# 原子语义：中途失败清理且不更新状态；清理异常不覆盖业务异常；哈希不匹配
# ---------------------------------------------------------------------------


def _flaky_replace(original):
    def replace(src, dst):
        if os.fspath(dst).endswith("neighborhood_summary.json"):
            raise OSError("simulated replace failure")
        return original(src, dst)

    return replace


class TestAtomicMaterialization:
    def test_midflight_failure_cleans_staged_files_and_skips_db(self, tmp_path, monkeypatch):
        import geomodeling.platform.results as results_module
        from geomodeling.platform.repositories import ProfessionalResultArtifactsRepository

        runtime = make_runtime(tmp_path)
        candidate = run_professional_candidate(runtime)
        with runtime.session() as session:
            before = ProfessionalResultArtifactsRepository(session).get_for_candidate(
                candidate["id"]
            )

        monkeypatch.setattr(os, "replace", _flaky_replace(os.replace))
        with pytest.raises(PlatformError) as excinfo:
            results_module.materialize(runtime, candidate["id"])
        assert excinfo.value.code == "PROFESSIONAL_ARTIFACT_WRITE_FAILED"

        professional_dir = runtime.settings.professional_result_dir(candidate["id"])
        # 已替换的新工件全部回滚清理；run 期证据原样保留
        assert not (professional_dir / "empirical_error_scale.npz").exists()
        assert not (professional_dir / "kriging_standard_deviation.npz").exists()
        assert not (professional_dir / "neighborhood_summary.json").exists()
        assert not (professional_dir / "metadata.json").exists()
        assert not (professional_dir / "manifest.json").exists()
        assert (professional_dir / "fold_assignments.parquet").exists()
        assert (professional_dir / "out_of_fold_predictions.parquet").exists()
        assert (professional_dir / "prediction_diagnostics.json").exists()
        # 暂存目录不残留
        assert list(runtime.settings.results_dir.rglob("professional-*")) == []
        assert list(runtime.settings.results_dir.rglob("result-*")) == []
        # 数据库状态不更新：grid_path 未登记、工件行 manifest 未改写、grid 未暴露
        with runtime.session() as session:
            row = session.get(tables.CandidateResult, candidate["id"])
            assert row.grid_path is None
            after = ProfessionalResultArtifactsRepository(session).get_for_candidate(
                candidate["id"]
            )
        assert after.manifest == before.manifest
        assert not runtime.settings.result_grid(candidate["id"]).exists()

    def test_cleanup_failure_does_not_mask_business_error(
        self, tmp_path, monkeypatch, caplog
    ):
        import logging

        import geomodeling.platform.results as results_module

        runtime = make_runtime(tmp_path)
        candidate = run_professional_candidate(runtime)

        def denied(*_args, **_kwargs):
            raise PermissionError("cleanup denied")

        monkeypatch.setattr(os, "replace", _flaky_replace(os.replace))
        monkeypatch.setattr(shutil, "rmtree", denied)
        with caplog.at_level(logging.ERROR, logger="geomodeling.platform"):
            with pytest.raises(PlatformError) as excinfo:
                results_module.materialize(runtime, candidate["id"])
        # 清理异常只记日志，绝不覆盖原业务异常
        assert excinfo.value.code == "PROFESSIONAL_ARTIFACT_WRITE_FAILED"
        assert any(
            "cleanup failed" in record.getMessage() and record.exc_info is not None
            for record in caplog.records
        )

    def test_corrupted_artifact_fails_reread_with_structured_error(self, tmp_path):
        import geomodeling.platform.results as results_module

        runtime = make_runtime(tmp_path)
        candidate = run_professional_candidate(runtime)
        results_module.materialize(runtime, candidate["id"])

        target = (
            runtime.settings.professional_result_dir(candidate["id"])
            / "empirical_error_scale.npz"
        )
        blob = bytearray(target.read_bytes())
        blob[-1] ^= 0xFF
        target.write_bytes(bytes(blob))

        with pytest.raises(PlatformError) as excinfo:
            results_module.materialize(runtime, candidate["id"])
        assert excinfo.value.code == "MANIFEST_VERIFICATION_FAILED"
        assert excinfo.value.http_status == 409


# ---------------------------------------------------------------------------
# 幂等：重复 materialize 重读既有工件并验证，不盲目重算
# ---------------------------------------------------------------------------


class TestIdempotentReread:
    def test_second_materialize_verifies_without_recompute(self, tmp_path, monkeypatch):
        import geomodeling.platform.results as results_module
        from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

        runtime = make_runtime(tmp_path)
        candidate = run_professional_candidate(runtime)
        first = results_module.materialize(runtime, candidate["id"])

        professional_dir = runtime.settings.professional_result_dir(candidate["id"])
        hashes_before = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in professional_dir.iterdir()
            if path.is_file()
        }
        grid_sha_before = hashlib.sha256(
            runtime.settings.result_grid(candidate["id"]).read_bytes()
        ).hexdigest()

        def forbidden(*_args, **_kwargs):
            raise AssertionError("idempotent reread must not recompute")

        monkeypatch.setattr(OrdinaryKrigingInterpolator, "fit", forbidden)
        monkeypatch.setattr(results_module, "empirical_error_scale", forbidden)

        second = results_module.materialize(runtime, candidate["id"])
        assert second == first
        hashes_after = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in professional_dir.iterdir()
            if path.is_file()
        }
        assert hashes_after == hashes_before
        assert (
            hashlib.sha256(runtime.settings.result_grid(candidate["id"]).read_bytes()).hexdigest()
            == grid_sha_before
        )


# ---------------------------------------------------------------------------
# preview 扩展：layer=value|empirical_error|kriging_std；能力不适用 409
# ---------------------------------------------------------------------------


class TestProfessionalPreview:
    def test_preview_value_layer_default_unchanged(self, tmp_path):
        from geomodeling.platform.results import materialize, preview

        runtime = make_runtime(tmp_path)
        candidate = run_professional_candidate(runtime)
        materialize(runtime, candidate["id"])

        default = preview(runtime, candidate["id"])
        explicit = preview(runtime, candidate["id"], layer="value")
        assert default == explicit
        assert default["layer"] == "value"
        assert default["served_cell_count"] <= 50_000

    def test_preview_kriging_std_layer_serves_native_std(self, tmp_path):
        from geomodeling.platform.results import materialize, preview

        runtime = make_runtime(tmp_path)
        candidate = run_professional_candidate(runtime)
        materialize(runtime, candidate["id"])

        served = preview(runtime, candidate["id"], layer="kriging_std")
        assert served["layer"] == "kriging_std"
        with np.load(
            runtime.settings.professional_result_dir(candidate["id"])
            / "kriging_standard_deviation.npz"
        ) as f:
            values = f["values"]
            nodata = f["is_nodata"]
        # 小网格 stride=1：逐点与登记工件一致，NoData 透明
        assert served["served_cell_count"] == int(values.size)
        actual = np.array(served["values"], dtype=float)
        assert np.allclose(actual, np.round(values.reshape(-1), 5), equal_nan=True)
        assert served["is_nodata"] == nodata.reshape(-1).tolist()

    def test_preview_empirical_error_layer(self, tmp_path):
        from geomodeling.platform.results import materialize, preview

        runtime = make_runtime(tmp_path)
        candidate = run_professional_candidate(runtime)
        materialize(runtime, candidate["id"])

        served = preview(runtime, candidate["id"], layer="empirical_error")
        assert served["layer"] == "empirical_error"
        with np.load(
            runtime.settings.professional_result_dir(candidate["id"])
            / "empirical_error_scale.npz"
        ) as f:
            scale = f["scale"]
            nodata = f["is_nodata"]
        assert served["served_cell_count"] == int(scale.size)
        actual = np.array(served["values"], dtype=float)
        assert np.allclose(actual, np.round(scale.reshape(-1), 5), equal_nan=True)
        assert served["is_nodata"] == nodata.reshape(-1).tolist()

    def test_preview_kriging_std_on_idw_is_409_never_zeros(self, tmp_path):
        from geomodeling.platform.results import materialize, preview

        runtime = make_runtime(tmp_path)
        candidate = run_professional_candidate(runtime, algorithm="idw")
        materialize(runtime, candidate["id"])

        with pytest.raises(PlatformError) as excinfo:
            preview(runtime, candidate["id"], layer="kriging_std")
        assert excinfo.value.http_status == 409
        assert excinfo.value.code == "PROFESSIONAL_CAPABILITY_NOT_APPLICABLE"

    def test_preview_unknown_layer_is_400(self, tmp_path):
        from geomodeling.platform.results import materialize, preview

        runtime = make_runtime(tmp_path)
        candidate = run_professional_candidate(runtime)
        materialize(runtime, candidate["id"])

        with pytest.raises(PlatformError) as excinfo:
            preview(runtime, candidate["id"], layer="bogus")
        assert excinfo.value.http_status == 400
        assert excinfo.value.code == "PREVIEW_LAYER_UNKNOWN"

    def test_preview_professional_layer_on_legacy_candidate_is_404(self, tmp_path):
        from geomodeling.platform.results import materialize, preview

        runtime = make_runtime(tmp_path)
        candidate = run_legacy_candidate(runtime)
        materialize(runtime, candidate["id"])

        with pytest.raises(PlatformError) as excinfo:
            preview(runtime, candidate["id"], layer="empirical_error")
        assert excinfo.value.http_status == 404
        assert excinfo.value.code == "PROFESSIONAL_LAYER_NOT_MATERIALIZED"
