"""Task 7 ordinary Kriging tests: system, accuracy gate, constraints, fallbacks."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

REFERENCE_PATH = Path(__file__).parent / "fixtures" / "kriging_reference.json"


def plane_field_2d():
    xs, ys = np.meshgrid(np.linspace(-160, -40, 6), np.linspace(220, 660, 11))
    coords = np.column_stack([xs.ravel(), ys.ravel()])
    values = 0.02 * coords[:, 0] - 0.01 * coords[:, 1] + 5.0
    return coords, values


def smooth_field_3d():
    rng = np.random.default_rng(20260723)
    coords = np.column_stack(
        [
            rng.uniform(-160, -40, 150),
            rng.uniform(220, 660, 150),
            rng.uniform(-840, 0, 150),
        ]
    )
    values = (
        np.sin(coords[:, 0] / 60)
        + np.cos(coords[:, 1] / 120)
        + 0.001 * coords[:, 2]
        + 8.0
    )
    return coords, values


def test_constant_field_reproduced_exactly():
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    coords = np.random.default_rng(1).uniform(-100, 100, size=(30, 2))
    values = np.full(30, 7.5)
    interpolator = OrdinaryKrigingInterpolator()
    params = interpolator.validate_parameters({"variogram_model": "spherical"}, "2d")
    fitted = interpolator.fit(coords, values, params)
    query = np.random.default_rng(2).uniform(-100, 100, size=(10, 2))
    batch = fitted.predict(query, cancel=lambda: False)
    np.testing.assert_allclose(batch.values, 7.5, atol=1e-9)
    assert not batch.is_nodata.any()


def test_weights_sum_to_one_via_augmented_system():
    from geomodeling.modeling.kriging import _ordinary_kriging_weights

    coords = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    target = np.array([0.5, 0.5])
    from geomodeling.modeling.variogram import VariogramModel

    model = VariogramModel(model="spherical", nugget=0.0, partial_sill=1.0, range=2.0)
    weights, _ = _ordinary_kriging_weights(coords, target, model)
    assert weights.sum() == pytest.approx(1.0)


def test_2d_plane_meets_reference_tolerance():
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    tolerance = reference["cases"]["plane_2d"]["tolerance_mae"]
    coords, values = plane_field_2d()
    interpolator = OrdinaryKrigingInterpolator()
    params = interpolator.validate_parameters(
        {"variogram_model": "spherical", "neighbor_count": 12}, "2d"
    )
    fitted = interpolator.fit(coords, values, params)
    query = np.column_stack(
        [np.array([-150.0, -100.0, -50.0]), np.array([300.0, 440.0, 600.0])]
    )
    batch = fitted.predict(query, cancel=lambda: False)
    truth = 0.02 * query[:, 0] - 0.01 * query[:, 1] + 5.0
    mae = float(np.abs(batch.values - truth).mean())
    assert mae <= tolerance


def test_3d_smooth_field_meets_reference_tolerance():
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    tolerance = reference["cases"]["smooth_3d"]["tolerance_mae"]
    coords, values = smooth_field_3d()
    interpolator = OrdinaryKrigingInterpolator()
    params = interpolator.validate_parameters(
        {"variogram_model": "spherical", "neighbor_count": 16}, "3d"
    )
    fitted = interpolator.fit(coords, values, params)
    # 留一法抽样验证（用训练点子集评价泛化）
    rng = np.random.default_rng(77)
    query_idx = rng.choice(len(coords), size=25, replace=False)
    query = coords[query_idx] + rng.normal(0, 1.0, size=(len(query_idx), 3))
    batch = fitted.predict(query, cancel=lambda: False)
    truth = (
        np.sin(query[:, 0] / 60)
        + np.cos(query[:, 1] / 120)
        + 0.001 * query[:, 2]
        + 8.0
    )
    mae = float(np.abs(batch.values - truth).mean())
    assert not batch.is_nodata.any()
    assert mae <= tolerance


def test_neighbor_count_and_radius_constraints():
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    coords = np.random.default_rng(3).uniform(-50, 50, size=(40, 2))
    values = np.sin(coords[:, 0] / 20) + 3.0
    interpolator = OrdinaryKrigingInterpolator()
    params = interpolator.validate_parameters(
        {"neighbor_count": 6, "search_radius": 30.0, "min_neighbors": 3}, "2d"
    )
    fitted = interpolator.fit(coords, values, params)
    batch = fitted.predict(np.array([[0.0, 0.0], [500.0, 500.0]]), cancel=lambda: False)
    assert not batch.is_nodata[0]
    assert batch.is_nodata[1]  # 半径外无邻居
    assert batch.diagnostics["max_neighbors_used"] <= 6


def test_singular_neighborhood_falls_back_to_lstsq():
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    # 邻域内含多个完全重合点 → 增广方程组奇异（行完全相同）
    coords = np.array(
        [
            [0.0, 0.0],
            [0.0, 0.0],
            [0.0, 0.0],
            [10.0, 0.0],
            [0.0, 10.0],
            [10.0, 10.0],
        ]
    )
    values = np.array([1.0, 1.0, 1.0, 2.0, 3.0, 4.0])
    interpolator = OrdinaryKrigingInterpolator()
    params = interpolator.validate_parameters(
        {"neighbor_count": 6, "min_neighbors": 3,
         "variogram_mode": "manual", "variogram_model": "spherical",
         "nugget": 0.0, "sill": 1.0, "range": 15.0},
        "2d",
    )
    fitted = interpolator.fit(coords, values, params)
    batch = fitted.predict(np.array([[1.0, 1.0]]), cancel=lambda: False)
    assert np.isfinite(batch.values[0])
    assert batch.diagnostics["singular_fallback_count"] >= 1


def test_insufficient_neighbors_returns_nodata():
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    coords = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    values = np.array([1.0, 2.0, 3.0])
    interpolator = OrdinaryKrigingInterpolator()
    params = interpolator.validate_parameters(
        {"neighbor_count": 8, "min_neighbors": 5}, "2d"
    )
    fitted = interpolator.fit(coords, values, params)
    batch = fitted.predict(np.array([[0.5, 0.5]]), cancel=lambda: False)
    assert batch.is_nodata[0]


def test_manual_parameters_require_complete_triple_and_sill_gt_nugget():
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    interpolator = OrdinaryKrigingInterpolator()
    with pytest.raises(Exception):
        interpolator.validate_parameters(
            {"variogram_mode": "manual", "variogram_model": "spherical", "nugget": 0.1, "sill": 1.0},
            "2d",
        )
    with pytest.raises(Exception):
        interpolator.validate_parameters(
            {"variogram_mode": "manual", "variogram_model": "spherical",
             "nugget": 1.5, "sill": 1.0, "range": 10.0},
            "2d",
        )


def test_predictions_are_deterministic():
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    coords, values = smooth_field_3d()
    interpolator = OrdinaryKrigingInterpolator()
    params = interpolator.validate_parameters({"neighbor_count": 16}, "3d")
    fitted_a = interpolator.fit(coords, values, params)
    fitted_b = interpolator.fit(coords, values, params)
    query = coords[:10]
    batch_a = fitted_a.predict(query, cancel=lambda: False)
    batch_b = fitted_b.predict(query, cancel=lambda: False)
    np.testing.assert_array_equal(batch_a.values, batch_b.values)


# ---------------------------------------------------------------------------
# Task 8: z_scale 距离缩放参数
# ---------------------------------------------------------------------------


def anisotropic_train_3d():
    # XY 近/垂向远与 XY 远/垂向近的点混合，z_scale 改变邻域距离结构
    coords = np.array(
        [
            [1.0, 0.0, 10.0],
            [8.0, 0.0, 2.0],
            [0.0, 9.0, 8.0],
            [-6.0, -6.0, 0.0],
        ]
    )
    values = np.array([100.0, 200.0, 150.0, 50.0])
    return coords, values


def test_z_scale_changes_3d_prediction_manual_mode():
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    coords, values = anisotropic_train_3d()
    interpolator = OrdinaryKrigingInterpolator()
    base = {
        "variogram_mode": "manual",
        "variogram_model": "spherical",
        "nugget": 0.0,
        "sill": 1.0,
        "range": 50.0,
        "neighbor_count": 4,
        "min_neighbors": 3,
    }
    weak = interpolator.validate_parameters({**base, "z_scale": 0.5}, "3d")
    strong = interpolator.validate_parameters({**base, "z_scale": 2.0}, "3d")
    query = np.array([[0.0, 0.0, 0.0]])
    pred_weak = interpolator.fit(coords, values, weak).predict(query, cancel=lambda: False)
    pred_strong = interpolator.fit(coords, values, strong).predict(query, cancel=lambda: False)
    assert not pred_weak.is_nodata[0]
    assert not pred_strong.is_nodata[0]
    assert pred_weak.values[0] != pytest.approx(pred_strong.values[0])
    assert pred_weak.diagnostics["z_scale"] == 0.5
    assert pred_strong.diagnostics["z_scale"] == 2.0


def test_z_scale_changes_auto_variogram_fit():
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    coords, values = smooth_field_3d()
    interpolator = OrdinaryKrigingInterpolator()
    base = {"variogram_model": "spherical", "neighbor_count": 16}
    weak = interpolator.validate_parameters({**base, "z_scale": 0.5}, "3d")
    strong = interpolator.validate_parameters({**base, "z_scale": 2.0}, "3d")
    # 查询点不能取训练点本身：Kriging 在样本点精确插值，与变异函数无关
    rng = np.random.default_rng(77)
    query = coords[:5] + rng.normal(0, 1.0, size=(5, 3))
    batch_weak = interpolator.fit(coords, values, weak).predict(query, cancel=lambda: False)
    batch_strong = interpolator.fit(coords, values, strong).predict(query, cancel=lambda: False)
    # 变异函数在缩放后的训练坐标上拟合 → range 随 z_scale 改变
    range_weak = batch_weak.diagnostics["variogram"]["range"]
    range_strong = batch_strong.diagnostics["variogram"]["range"]
    assert range_weak != pytest.approx(range_strong, rel=1e-3)
    assert not np.array_equal(batch_weak.values, batch_strong.values)


def test_z_scale_default_matches_explicit_one_bitwise():
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    coords, values = smooth_field_3d()
    interpolator = OrdinaryKrigingInterpolator()
    base = {"variogram_model": "spherical", "neighbor_count": 16}
    default_params = interpolator.validate_parameters(base, "3d")
    explicit_one = interpolator.validate_parameters({**base, "z_scale": 1.0}, "3d")
    # 非样本查询点，确保逐位比较经过完整的邻域与权重求解路径
    rng = np.random.default_rng(77)
    query = coords[:10] + rng.normal(0, 1.0, size=(10, 3))
    batch_default = interpolator.fit(coords, values, default_params).predict(query, cancel=lambda: False)
    batch_one = interpolator.fit(coords, values, explicit_one).predict(query, cancel=lambda: False)
    np.testing.assert_array_equal(batch_default.values, batch_one.values)
    np.testing.assert_array_equal(batch_default.is_nodata, batch_one.is_nodata)
    assert batch_default.diagnostics["z_scale"] == 1.0


def test_z_scale_ignored_in_2d():
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    coords, values = plane_field_2d()
    interpolator = OrdinaryKrigingInterpolator()
    base = {"variogram_model": "spherical", "neighbor_count": 12}
    weak = interpolator.validate_parameters({**base, "z_scale": 0.5}, "2d")
    strong = interpolator.validate_parameters({**base, "z_scale": 2.0}, "2d")
    query = np.column_stack(
        [np.array([-150.0, -100.0, -50.0]), np.array([300.0, 440.0, 600.0])]
    )
    batch_weak = interpolator.fit(coords, values, weak).predict(query, cancel=lambda: False)
    batch_strong = interpolator.fit(coords, values, strong).predict(query, cancel=lambda: False)
    np.testing.assert_array_equal(batch_weak.values, batch_strong.values)
    np.testing.assert_array_equal(batch_weak.is_nodata, batch_strong.is_nodata)


def test_z_scale_does_not_mutate_training_or_query_coordinates():
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    coords, values = anisotropic_train_3d()
    coords_before = coords.copy()
    interpolator = OrdinaryKrigingInterpolator()
    params = interpolator.validate_parameters(
        {
            "variogram_mode": "manual",
            "variogram_model": "spherical",
            "nugget": 0.0,
            "sill": 1.0,
            "range": 50.0,
            "neighbor_count": 4,
            "min_neighbors": 3,
            "z_scale": 2.0,
        },
        "3d",
    )
    fitted = interpolator.fit(coords, values, params)
    query = np.array([[0.0, 0.0, 0.0]])
    query_before = query.copy()
    fitted.predict(query, cancel=lambda: False)
    np.testing.assert_array_equal(coords, coords_before)
    np.testing.assert_array_equal(query, query_before)


def test_z_scale_parameter_bounds():
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    interpolator = OrdinaryKrigingInterpolator()
    for bad in (0.0, -1.0, 20.5, float("inf"), float("nan")):
        with pytest.raises(Exception):
            interpolator.validate_parameters({"z_scale": bad}, "3d")
    ok = interpolator.validate_parameters({"z_scale": 20.0}, "3d")
    assert ok.z_scale == 20.0


# ---------------------------------------------------------------------------
# v0.6 Task 3: legacy 兼容 pin —— empirical_semivariogram 重构为共享分箱核心
# 后，12-bin 数值与 v0.5 参考输出逐位一致（参考值取自重构前实现）
# ---------------------------------------------------------------------------


def test_empirical_semivariogram_matches_legacy_12_bin_reference_bitwise():
    from geomodeling.modeling.variogram import empirical_semivariogram

    coords, values = plane_field_2d()
    centers, gammas, counts = empirical_semivariogram(coords, values)
    np.testing.assert_array_equal(
        counts, [55, 317, 392, 325, 216, 228, 152, 100, 144, 108, 72, 36]
    )
    np.testing.assert_array_equal(
        centers,
        [
            19.0029237516523, 57.0087712549569, 95.01461875826149,
            133.0204662615661, 171.0263137648707, 209.0321612681753,
            247.0380087714799, 285.0438562747845, 323.0497037780891,
            361.0555512813937, 399.0613987846983, 437.06724628800293,
        ],
    )
    np.testing.assert_array_equal(
        gammas,
        [
            0.11520000000000005, 0.3978094637223975, 0.9955183673469388,
            1.6242510769230771, 2.041422222222222, 2.820547368421053,
            3.7822736842105265, 4.636799999999999, 5.4152000000000005,
            6.8672, 8.5128, 10.352000000000002,
        ],
    )


def test_fit_variogram_matches_legacy_reference_within_platform_tolerance():
    from geomodeling.modeling.variogram import fit_variogram

    # 参考值取自重构前实现；least_squares 的 LAPACK/BLAS 路径随平台有末位差异，
    # 故以紧容差钉住数值（rtol=1e-7），仍能捕获算法级漂移。近零 nugget 用 atol。
    coords, values = plane_field_2d()
    model = fit_variogram(coords, values, "spherical")
    assert model.nugget == pytest.approx(7.528834720767456e-20, abs=1e-12)
    assert model.partial_sill == pytest.approx(11.568770768708706, rel=1e-7)
    assert model.range == pytest.approx(874.1344925760058, rel=1e-7)

    coords, values = smooth_field_3d()
    model = fit_variogram(coords, values, "spherical")
    assert model.nugget == pytest.approx(7.708953972850713e-16, abs=1e-12)
    assert model.partial_sill == pytest.approx(1.0302351693326357, rel=1e-7)
    assert model.range == pytest.approx(1652.575581583548, rel=1e-7)


# ---------------------------------------------------------------------------
# v0.6 Task 8: legacy 兼容 pin —— 未给 anisotropy/neighborhood 时现有行为
# 逐位不变（参考值取自引入专业选项之前的实现）
# ---------------------------------------------------------------------------


def test_legacy_2d_prediction_pin_without_professional_options():
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    rng = np.random.default_rng(42)
    coords = np.column_stack([rng.uniform(-50, 50, 24), rng.uniform(100, 200, 24)])
    values = np.sin(coords[:, 0] / 15.0) + 0.5 * np.cos(coords[:, 1] / 25.0) + 3.0
    query = np.array([[-30.0, 120.0], [0.0, 150.0], [25.0, 190.0]])
    interpolator = OrdinaryKrigingInterpolator()
    params = interpolator.validate_parameters(
        {"variogram_mode": "manual", "variogram_model": "spherical",
         "nugget": 0.05, "sill": 1.2, "range": 80.0, "neighbor_count": 8},
        "2d",
    )
    assert params.anisotropy is None and params.neighborhood is None
    batch = interpolator.fit(coords, values, params).predict(query, cancel=lambda: False)
    # 参考值取自引入专业选项之前的实现；LAPACK 求解随平台有末位差异，用紧容差锁定
    np.testing.assert_allclose(
        batch.values, [2.522227095913784, 3.398996313035415, 4.048265800991689],
        rtol=1e-9, atol=1e-12,
    )
    np.testing.assert_array_equal(batch.is_nodata, [False, False, False])


def test_legacy_3d_z_scale_prediction_pin_without_professional_options():
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    rng = np.random.default_rng(7)
    coords = np.column_stack(
        [rng.uniform(-40, 40, 20), rng.uniform(0, 80, 20), rng.uniform(-200, 0, 20)]
    )
    values = np.cos(coords[:, 0] / 20.0) + 0.001 * coords[:, 2] + 5.0
    query = np.array([[-10.0, 30.0, -80.0], [15.0, 60.0, -40.0]])
    interpolator = OrdinaryKrigingInterpolator()
    params = interpolator.validate_parameters(
        {"variogram_mode": "manual", "variogram_model": "exponential",
         "nugget": 0.02, "sill": 0.9, "range": 60.0, "neighbor_count": 10,
         "z_scale": 2.0},
        "3d",
    )
    assert params.anisotropy is None and params.neighborhood is None
    batch = interpolator.fit(coords, values, params).predict(query, cancel=lambda: False)
    # 参考值取自引入专业选项之前的实现；LAPACK 求解随平台有末位差异，用紧容差锁定
    np.testing.assert_allclose(
        batch.values, [5.429593345184889, 5.343671085767241], rtol=1e-9, atol=1e-12
    )
    np.testing.assert_array_equal(batch.is_nodata, [False, False])
