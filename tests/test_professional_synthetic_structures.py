"""Task 22: numerical acceptance over known synthetic professional structures.

纯数学层 + 服务层验收（不依赖浏览器）：

- 2D 30° 拉长场（真值变程 60/20，比例 3.0）：方向诊断建议的主方向与
  主/次变程比必须落在本文件显式声明的容差内（方位 ±15°，比例在
  [真值/1.5, 真值×1.5] 内）；候选恒为 ``diagnostic_suggestion``，平台不自动采用；
- 3D 已知方位 60°/倾角 0° 场（真值 15/5/7.5，主次比 3.0、主垂比 2.0）：
  同一套声明容差；
- 各向同性对照场：无强方向宣称——（a）方向经验 bin 与全向 bin 的相对
  偏差不超过声明阈值 25%（「比例接近 1」的经验证据级形式；拟合变程比
  在各向同性证据上是噪声主导的估计量，不作验收断言）；（b）近各向同
  性拟合输入必须触发 weak_range_contrast 稳定性警告；
- 手工网格：高值/低值各两个连通区，不确定性门槛把其中一个高值连通区
  切成两个；连通区计数与逐节点 Voronoi 支持度量按手算值精确断言；
- 人工确认效应：同一合成场、同一空间折分上，确认各向异性的专业
  Kriging 与 legacy Kriging 的折外 RMSE 必须有差异；本夹具场各向异性
  强，预期专业指标不差于 legacy——这是对**本合成夹具**的断言，绝不
  宣称它必须在所有真实数据集获胜。

合成场全部由 ``tests/fixtures/professional_2d.py`` /
``tests/fixtures/professional_3d.py`` 的确定性生成器（循环嵌入 FFT，固定
种子）现造；CSV 只写在 pytest ``tmp_path`` 下，绝不提交生成的运行时 CSV。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fixtures import professional_2d, professional_3d
from geomodeling.modeling.anisotropy import KrigingAnisotropySpec
from geomodeling.modeling.anomalies import UncertaintyLayer, extract_anomalies
from geomodeling.modeling.directional_variogram import compute_empirical_variogram
from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator
from geomodeling.modeling.professional_contracts import (
    AnomalyExtractionSpec,
    DirectionSpec,
    VariogramDiagnosticSpec,
)
from geomodeling.modeling.professional_diagnosis import (
    STATUS_SUPPORTED,
    WARN_WEAK_RANGE_CONTRAST,
    DirectionalFit,
    suggest_anisotropy,
)
from geomodeling.modeling.splits import build_spatial_splits
from geomodeling.modeling.variogram import (
    MIN_FIT_BINS,
    MODELS,
    VariogramFitEvidence,
    fit_variogram_evidence,
)
from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.analysis_jobs import (
    create_professional_diagnosis,
    get_professional_diagnosis,
)
from geomodeling.platform.schemas import SpatialValidationSpec
from geomodeling.platform.worker import JobWorker

# ---------------------------------------------------------------------------
# 声明容差（验收合同的一部分，先于测量声明）
# ---------------------------------------------------------------------------

#: 主方向无向方位角容差（度）：候选主方向与真值的锐角差不得超过它。
AZIMUTH_TOLERANCE_DEG = 15.0
#: 变程比容差因子：披露比例必须在 [truth / 1.5, truth × 1.5] 内。
RATIO_TOLERANCE_FACTOR = 1.5
#: 各向同性对照的经验证据级判据：每个参与拟合的方向 bin 与同窗全向 bin
#: 的半变异值相对偏差（以全向基台归一）不得超过该阈值。真值各向异性
#: （比例 3）在同窗产生 ≥ 40% 的系统性偏差，本阈值与之清晰分离。
ISOTROPIC_EVIDENCE_MAX_CONTRAST = 0.25


def _undirected_separation(a: float, b: float) -> float:
    """无向方位角夹角（度），范围 [0, 90]。"""

    return abs((a - b + 90.0) % 180.0 - 90.0)


def _run_direction_diagnosis(
    points: np.ndarray,
    values: np.ndarray,
    directions: tuple,
    *,
    lag_count: int,
    min_pairs: int,
    max_pairs: int,
    max_distance: float,
):
    """诊断纯函数链：经验方向半变异 → 逐方向三模型加权拟合取最优 → 候选建议。"""

    spec = VariogramDiagnosticSpec(
        lag_count=lag_count,
        min_pairs_per_bin=min_pairs,
        max_pairs=max_pairs,
        max_distance=max_distance,
        directions=tuple(directions),
    )
    empirical = compute_empirical_variogram(
        points, values, spec, data_sha256="synthetic-acceptance"
    )
    fits = []
    for index, directional_bins in enumerate(empirical.directional):
        direction = spec.directions[index]
        used = [b for b in directional_bins if b.used_for_fit]
        if len(used) < MIN_FIT_BINS:
            fits.append(
                DirectionalFit(
                    direction_id=f"d{index:03d}",
                    direction=direction,
                    status="unsupported_insufficient_pairs",
                    fit=None,
                    used_pair_count=sum(b.pair_count for b in directional_bins),
                )
            )
            continue
        model_fits = [fit_variogram_evidence(directional_bins, model) for model in MODELS]
        best = min(model_fits, key=lambda evidence: evidence.weighted_sse)
        fits.append(
            DirectionalFit(
                direction_id=f"d{index:03d}",
                direction=direction,
                status=STATUS_SUPPORTED,
                fit=best,
                used_pair_count=sum(b.pair_count for b in used),
            )
        )
    return suggest_anisotropy(fits), fits


# ---------------------------------------------------------------------------
# 方向验收：2D 30° 拉长场 / 3D 已知方位场 / 各向同性对照
# ---------------------------------------------------------------------------


class TestDirection2D:
    def test_major_direction_and_range_ratio_within_declared_tolerance(self):
        field = professional_2d.anisotropic_field()
        suggestion, _ = _run_direction_diagnosis(
            field.points,
            field.values,
            professional_2d.directions(),
            lag_count=8,
            min_pairs=30,
            max_pairs=500_000,
            max_distance=100.0,
        )

        assert suggestion.candidates, "结构化 2D 场必须产生至少一个诊断候选"
        top = suggestion.candidates[0]
        # 平台从不自动采用候选：状态恒为诊断建议
        assert top.status == "diagnostic_suggestion"
        separation = _undirected_separation(
            top.major_azimuth_deg, professional_2d.AZIMUTH_DEG
        )
        assert separation <= AZIMUTH_TOLERANCE_DEG, (
            f"主方向 {top.major_azimuth_deg}° 与真值 {professional_2d.AZIMUTH_DEG}° "
            f"的夹角 {separation:.2f}° 超出声明容差 ±{AZIMUTH_TOLERANCE_DEG}°"
        )
        assert top.major_minor_range_ratio is not None, "2D 结构化场必须披露主/次变程比"
        truth = professional_2d.RANGE_RATIO
        assert truth / RATIO_TOLERANCE_FACTOR <= top.major_minor_range_ratio <= (
            truth * RATIO_TOLERANCE_FACTOR
        ), (
            f"主/次变程比 {top.major_minor_range_ratio:.3f} 超出声明容差 "
            f"[{truth / RATIO_TOLERANCE_FACTOR}, {truth * RATIO_TOLERANCE_FACTOR}]（真值 {truth}）"
        )


class TestDirection3D:
    def test_azimuth_dip_and_vertical_ratio_within_declared_tolerance(self):
        field = professional_3d.anisotropic_field()
        suggestion, _ = _run_direction_diagnosis(
            field.points,
            field.values,
            professional_3d.directions(),
            lag_count=8,
            min_pairs=30,
            max_pairs=500_000,
            max_distance=30.0,
        )

        assert suggestion.candidates, "结构化 3D 场必须产生至少一个诊断候选"
        top = suggestion.candidates[0]
        assert top.status == "diagnostic_suggestion"
        separation = _undirected_separation(
            top.major_azimuth_deg, professional_3d.AZIMUTH_DEG
        )
        assert separation <= AZIMUTH_TOLERANCE_DEG, (
            f"主方向 {top.major_azimuth_deg}° 与真值 {professional_3d.AZIMUTH_DEG}° "
            f"的夹角 {separation:.2f}° 超出声明容差 ±{AZIMUTH_TOLERANCE_DEG}°"
        )
        # 真值主方向水平（倾角 0°）：候选不得把主方向指到倾斜方向
        assert top.major_dip_deg is not None
        assert abs(top.major_dip_deg - professional_3d.DIP_DEG) <= AZIMUTH_TOLERANCE_DEG

        ratio_minor = top.major_minor_range_ratio
        assert ratio_minor is not None, "3D 结构化场必须披露主/次变程比"
        assert professional_3d.RATIO_MINOR / RATIO_TOLERANCE_FACTOR <= ratio_minor <= (
            professional_3d.RATIO_MINOR * RATIO_TOLERANCE_FACTOR
        ), f"主/次变程比 {ratio_minor:.3f} 超出声明容差（真值 {professional_3d.RATIO_MINOR}）"

        ratio_vertical = top.major_vertical_range_ratio
        assert ratio_vertical is not None, "3D 结构化场必须披露主/垂变程比"
        assert professional_3d.RATIO_VERTICAL / RATIO_TOLERANCE_FACTOR <= ratio_vertical <= (
            professional_3d.RATIO_VERTICAL * RATIO_TOLERANCE_FACTOR
        ), f"主/垂变程比 {ratio_vertical:.3f} 超出声明容差（真值 {professional_3d.RATIO_VERTICAL}）"


class TestIsotropicControl:
    """各向同性对照：不得产生强方向宣称。

    说明判据选取：方向拟合的「拟合变程比」在各向同性证据上是噪声主导
    的估计量（单一实现对各方向可差 2 倍以上，是变差函数估计的固有方
    差），拿它做验收等于断言噪声。因此本类按合同的两个可判形式验收：
    （a）「比例接近 1」落在平台登记的经验证据上——各方向 bin 与全向
    bin 的相对偏差不超过声明阈值 25%；（b）「稳定性警告」行为——近
    各向同性的拟合输入必须触发 weak_range_contrast 警告。
    """

    def test_directional_empirical_curves_show_no_material_contrast(self):
        field = professional_2d.isotropic_control()
        spec = VariogramDiagnosticSpec(
            lag_count=8,
            min_pairs_per_bin=30,
            max_pairs=500_000,
            max_distance=90.0,
            directions=professional_2d.directions(),
        )
        empirical = compute_empirical_variogram(
            field.points, field.values, spec, data_sha256="synthetic-acceptance"
        )

        omni = [b for b in empirical.omnidirectional if b.used_for_fit]
        assert len(omni) >= MIN_FIT_BINS, "对照场全向拟合证据必须充足"
        sill = float(np.mean([b.semivariance for b in omni[-2:]]))
        assert sill > 0.0
        for direction_bins in empirical.directional:
            direction = direction_bins[0].direction
            for index, bin_ in enumerate(direction_bins):
                omni_bin = empirical.omnidirectional[index]
                if not (bin_.used_for_fit and omni_bin.used_for_fit):
                    continue
                deviation = abs(bin_.semivariance - omni_bin.semivariance) / sill
                assert deviation <= ISOTROPIC_EVIDENCE_MAX_CONTRAST, (
                    f"方向 {direction.azimuth_deg}° bin {index} 与全向偏差 "
                    f"{deviation:.3f} 超过声明阈值 {ISOTROPIC_EVIDENCE_MAX_CONTRAST}："
                    "对照场出现强方向宣称"
                )

    def test_near_isotropic_fits_carry_weak_contrast_warning(self):
        """平台对冲行为：比例接近 1 的候选必须附带 weak_range_contrast 警告。"""

        def synthetic_fit(range_value: float) -> VariogramFitEvidence:
            return VariogramFitEvidence(
                model="spherical",
                nugget=0.02,
                partial_sill=1.0,
                sill=1.02,
                range=range_value,
                weighted_sse=0.001,
                converged=True,
                parameter_origin="automatic_candidate",
                used_bin_indices=[0, 1, 2, 3, 4, 5],
                bounds={
                    "nugget": (0.0, 1.0),
                    "partial_sill": (0.001, 3.0),
                    "range": (0.001, 180.0),
                },
                residuals=[0.0] * 6,
            )

        fits = [
            DirectionalFit(
                direction_id="d000",
                direction=DirectionSpec(dimension="2d", azimuth_deg=0.0, azimuth_tolerance_deg=20.0),
                status=STATUS_SUPPORTED,
                fit=synthetic_fit(30.0),
                used_pair_count=500,
            ),
            DirectionalFit(
                direction_id="d001",
                direction=DirectionSpec(dimension="2d", azimuth_deg=90.0, azimuth_tolerance_deg=20.0),
                status=STATUS_SUPPORTED,
                fit=synthetic_fit(28.5),
                used_pair_count=500,
            ),
        ]
        suggestion = suggest_anisotropy(fits)
        assert suggestion.candidates, "近各向同性拟合输入仍应给出候选披露"
        for candidate in suggestion.candidates:
            ratios = [
                ratio
                for ratio in (
                    candidate.major_minor_range_ratio,
                    candidate.major_vertical_range_ratio,
                )
                if ratio is not None
            ]
            assert ratios, "2D 双方向输入必须披露主/次变程比"
            assert WARN_WEAK_RANGE_CONTRAST in candidate.warnings, (
                "比例接近 1 的候选必须携带 weak_range_contrast 稳定性警告，"
                "不得表现为强方向宣称"
            )


# ---------------------------------------------------------------------------
# 连通区验收：两个高值 + 两个低值连通区；不确定性门槛切分一个高值区
# ---------------------------------------------------------------------------


class TestAnomalyStructures:
    def test_two_high_and_two_low_components_with_exact_support(self):
        grid = professional_2d.anomaly_grid()

        high = extract_anomalies(
            axes=grid.axes,
            values=grid.values,
            is_nodata=grid.is_nodata,
            spec=AnomalyExtractionSpec(direction="high", threshold=9.0),
        )
        assert len(high.components) == 2
        # 手算（均匀间距 2，Voronoi 宽度：端点 1、内部 2）：
        # H1 = (1..2, 1..2) 4 节点 × (2×2) = 16.0；H2 = (7..8, 7..8) +
        # 桥 (9,7) + (10..11, 7..8)：7 个内部节点 ×4 + 2 个末行节点 ×2 = 32.0
        assert [c.support_node_count for c in high.components] == [4, 9]
        assert [c.support_measure for c in high.components] == [16.0, 32.0]
        assert [c.support_unit for c in high.components] == ["area_coordinate_unit2"] * 2
        assert high.components[0].bounds == [(2.0, 4.0), (2.0, 4.0)]
        assert high.components[0].touches_grid_boundary is False
        assert high.components[1].bounds == [(14.0, 22.0), (14.0, 16.0)]
        assert high.components[1].touches_grid_boundary is True
        assert high.components[1].value_min == high.components[1].value_max == 10.0

        low = extract_anomalies(
            axes=grid.axes,
            values=grid.values,
            is_nodata=grid.is_nodata,
            spec=AnomalyExtractionSpec(direction="low", threshold=-9.0),
        )
        # L1 = (1..2, 8..9) 4 节点 ×4 = 16.0；L2 = (8..10, 1) 3 节点 ×4 = 12.0
        assert [c.support_node_count for c in low.components] == [4, 3]
        assert [c.support_measure for c in low.components] == [16.0, 12.0]
        assert low.components[1].bounds == [(16.0, 20.0), (2.0, 2.0)]
        assert low.components[1].touches_grid_boundary is False
        assert low.components[0].value_mean == pytest.approx(-10.0)

    def test_uncertainty_gate_splits_one_component_exactly(self):
        grid = professional_2d.anomaly_grid()
        gated = extract_anomalies(
            axes=grid.axes,
            values=grid.values,
            is_nodata=grid.is_nodata,
            spec=AnomalyExtractionSpec(
                direction="high", threshold=9.0, empirical_error_max=1.0
            ),
            empirical_error_scale=UncertaintyLayer(
                values=grid.empirical_error, is_nodata=grid.empirical_error_nodata
            ),
        )
        # 桥节点 (9,7) 的经验误差 5.0 > 门槛 1.0 → H2 切成两个 2×2 块：
        # 块 A 内部 4 节点 ×4 = 16.0；块 B 含末行 2 节点 ×2 + 2 节点 ×4 = 12.0
        assert [c.support_node_count for c in gated.components] == [4, 4, 4]
        assert [c.support_measure for c in gated.components] == [16.0, 16.0, 12.0]
        assert gated.components[2].bounds == [(20.0, 22.0), (14.0, 16.0)]
        diagnostics = gated.diagnostics
        assert diagnostics["empirical_error_gated"] is True
        assert diagnostics["eligible_node_count"] == 12  # 13 个高值节点 − 桥
        assert diagnostics["labeled_component_count"] == 3
        assert diagnostics["component_count"] == 3


# ---------------------------------------------------------------------------
# 人工确认效应：同一折分上专业（确认各向异性）Kriging 与 legacy 指标有差异
# ---------------------------------------------------------------------------


def _oof_predictions(points, values, folds, parameters: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    interpolator = OrdinaryKrigingInterpolator()
    validated = interpolator.validate_parameters(parameters, "2d")
    truth_parts: list[np.ndarray] = []
    prediction_parts: list[np.ndarray] = []
    nodata_parts: list[np.ndarray] = []
    for fold in folds:
        fitted = interpolator.fit(
            points[fold.training_indices], values[fold.training_indices], validated
        )
        batch = fitted.predict(points[fold.validation_indices], cancel=lambda: False)
        truth_parts.append(values[fold.validation_indices])
        prediction_parts.append(batch.values)
        nodata_parts.append(batch.is_nodata)
    return (
        np.concatenate(truth_parts),
        np.concatenate(prediction_parts),
        np.concatenate(nodata_parts),
    )


def _rmse(truth: np.ndarray, prediction: np.ndarray, is_nodata: np.ndarray) -> float:
    mask = ~is_nodata
    assert mask.any()
    return float(np.sqrt(((prediction[mask] - truth[mask]) ** 2).mean()))


class TestConfirmationEffect:
    def test_confirmed_anisotropy_changes_validation_metrics(self):
        field = professional_2d.cross_validation_field()
        validation = SpatialValidationSpec(
            method="spatial_kfold", folds=5, seed=11, holdout_fraction=0.2
        )
        folds = build_spatial_splits(field.points, "2d", validation)

        legacy_parameters = {
            "variogram_model": "spherical",
            "variogram_mode": "auto",
            "neighbor_count": 16,
        }
        # 人工确认的几何（设计 §7.2 规范变换）：azimuth 30°，主/次变程比 3
        # → 次向尺度取倒数 1/3；这正是确认快照落地到候选参数的形式。
        professional_parameters = {
            **legacy_parameters,
            "anisotropy": KrigingAnisotropySpec(
                dimension="2d",
                azimuth_deg=professional_2d.AZIMUTH_DEG,
                major_scale=1.0,
                minor_scale=1.0 / professional_2d.RANGE_RATIO,
            ).model_dump(mode="json"),
        }

        legacy_truth, legacy_prediction, legacy_nodata = _oof_predictions(
            field.points, field.values, folds, legacy_parameters
        )
        pro_truth, pro_prediction, pro_nodata = _oof_predictions(
            field.points, field.values, folds, professional_parameters
        )
        np.testing.assert_array_equal(legacy_truth, pro_truth)

        legacy_rmse = _rmse(legacy_truth, legacy_prediction, legacy_nodata)
        professional_rmse = _rmse(pro_truth, pro_prediction, pro_nodata)

        # 确认必须改变验证结果（同一数据同一折分，指标不得逐位相同）
        assert professional_rmse != pytest.approx(legacy_rmse, abs=1e-9)
        # 本合成夹具各向异性强且确认几何即真值几何：预期专业指标不差于
        # legacy。这是对本夹具的断言，绝不宣称专业确认在所有真实数据集
        # 都必须获胜。
        assert professional_rmse <= legacy_rmse, (
            f"本夹具预期确认各向异性不差于 legacy：professional={professional_rmse:.6f} "
            f"legacy={legacy_rmse:.6f}"
        )


# ---------------------------------------------------------------------------
# 服务层验收：便携合成数据集 → 持久诊断任务 → 登记候选证据在容差内
# ---------------------------------------------------------------------------

SERVICE_DIAGNOSIS_CONFIG = {
    "variogram": {
        "lag_count": 8,
        "min_pairs_per_bin": 30,
        "max_pairs": 500000,
        "max_distance": 100.0,
        "directions": [
            {"dimension": "2d", "azimuth_deg": float(azimuth), "azimuth_tolerance_deg": 20.0}
            for azimuth in (0, 30, 60, 90, 120, 150)
        ],
    }
}


def _make_service_dataset(
    runtime: PlatformRuntime, csv_path: Path, case_id: str, dataset_id: str
) -> None:
    """把夹具 CSV 注册为已过质量门禁的标准化数据集（与诊断服务合同一致）。"""

    frame = pd.read_csv(csv_path)
    n = len(frame)
    standardized = pd.DataFrame(
        {
            "source_row": np.arange(1, n + 1),
            "x": frame["x"].to_numpy(dtype="float64"),
            "y": frame["y"].to_numpy(dtype="float64"),
            "z": np.nan,
            "value": frame["value"].to_numpy(dtype="float64"),
            "is_numeric_valid": True,
        }
    )
    target = runtime.settings.standardized_dataset(case_id, dataset_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    standardized.to_parquet(target, index=False)
    standardized_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
    with runtime.session() as session:
        session.add(
            tables.Case(id=case_id, name="合成验收案例", case_type="generic", config_json="{}")
        )
        session.add(
            tables.DatasetVersion(
                id=dataset_id,
                case_id=case_id,
                version=1,
                status="validated",
                source_path=str(csv_path),
                standardized_path=str(target),
                profile_json=tables.dumps_canonical(
                    {
                        "mapping": {
                            "dimension": "2d",
                            "x": "x",
                            "y": "y",
                            "value": "value",
                            "value_name": "合成属性",
                            "coordinate_kind": "local_linear",
                        },
                        "source_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                        "standardized_sha256": standardized_sha256,
                        "quality": {"status": "passed", "confirmed": True},
                    }
                ),
            )
        )
        session.commit()


class TestServiceLayerDiagnosis:
    def test_service_recovers_direction_within_declared_tolerance(self, tmp_path):
        field = professional_2d.anisotropic_field()
        csv_path = professional_2d.write_points_csv(field, tmp_path / "synthetic_2d.csv")
        # 夹具 CSV 回读逐位一致（便携合同：CSV 只写在 pytest 临时目录）
        frame = pd.read_csv(csv_path)
        np.testing.assert_allclose(
            frame[["x", "y"]].to_numpy(dtype="float64"), field.points, atol=1e-9
        )
        np.testing.assert_allclose(
            frame["value"].to_numpy(dtype="float64"), field.values, atol=1e-9
        )

        runtime = PlatformRuntime(tmp_path / "runtime")
        runtime.initialize()
        try:
            _make_service_dataset(runtime, csv_path, "case-syn", "ds-syn")
            record = create_professional_diagnosis(
                runtime, "ds-syn", SERVICE_DIAGNOSIS_CONFIG
            )
            worker = JobWorker(runtime)
            try:
                worker.enqueue_analysis(record.job_id)
                worker.wait_idle()
            finally:
                worker.shutdown()
            finished = get_professional_diagnosis(runtime, record.id)
            assert finished.status == "succeeded"

            candidates_path = (
                runtime.settings.professional_diagnosis_dir("case-syn", "ds-syn", finished.id)
                / "anisotropy_candidates.json"
            )
            payload = json.loads(candidates_path.read_text(encoding="utf-8"))
            candidates = payload["candidates"]
            assert candidates, "服务层诊断必须登记至少一个候选"
            top = candidates[0]
            assert top["status"] == "diagnostic_suggestion"
            separation = _undirected_separation(
                float(top["major_azimuth_deg"]), professional_2d.AZIMUTH_DEG
            )
            assert separation <= AZIMUTH_TOLERANCE_DEG, (
                f"服务层主方向 {top['major_azimuth_deg']}° 与真值夹角 {separation:.2f}° "
                f"超出声明容差 ±{AZIMUTH_TOLERANCE_DEG}°"
            )
            ratio = top["major_minor_range_ratio"]
            assert ratio is not None
            assert professional_2d.RANGE_RATIO / RATIO_TOLERANCE_FACTOR <= ratio <= (
                professional_2d.RANGE_RATIO * RATIO_TOLERANCE_FACTOR
            ), f"服务层主/次变程比 {ratio:.3f} 超出声明容差（真值 {professional_2d.RANGE_RATIO}）"
        finally:
            runtime.close()
