"""Task 6 tests: generic 2D/3D IDW adapter."""

from __future__ import annotations

import numpy as np
import pytest


def train_2d():
    xs, ys = np.meshgrid(np.linspace(-160, -40, 7), np.linspace(220, 660, 12))
    coords = np.column_stack([xs.ravel(), ys.ravel()])
    values = np.sin(coords[:, 0] / 30) + np.cos(coords[:, 1] / 80) + 10.0
    return coords, values


def train_3d():
    rng = np.random.default_rng(9)
    coords = np.column_stack(
        [
            rng.uniform(-160, -40, 120),
            rng.uniform(220, 660, 120),
            rng.uniform(-840, 0, 120),
        ]
    )
    values = (
        np.sin(coords[:, 0] / 40)
        + np.cos(coords[:, 1] / 90)
        + 0.002 * coords[:, 2]
        + 12.0
    )
    return coords, values


def test_exact_sample_point_reproduction_2d():
    from geomodeling.modeling.idw import IDWInterpolator

    coords, values = train_2d()
    interpolator = IDWInterpolator()
    params = interpolator.validate_parameters({"power": 2.0, "neighbor_count": 8}, "2d")
    fitted = interpolator.fit(coords, values, params)
    batch = fitted.predict(coords, cancel=lambda: False)
    np.testing.assert_allclose(batch.values, values, atol=1e-9)
    assert not batch.is_nodata.any()


def test_2d_smooth_field_interpolation_accuracy():
    from geomodeling.modeling.idw import IDWInterpolator

    coords, values = train_2d()
    interpolator = IDWInterpolator()
    params = interpolator.validate_parameters(
        {"power": 2.0, "neighbor_count": 10, "min_neighbors": 3}, "2d"
    )
    fitted = interpolator.fit(coords, values, params)
    xs, ys = np.meshgrid(np.linspace(-155, -45, 5), np.linspace(230, 650, 5))
    query = np.column_stack([xs.ravel(), ys.ravel()])
    batch = fitted.predict(query, cancel=lambda: False)
    truth = np.sin(query[:, 0] / 30) + np.cos(query[:, 1] / 80) + 10.0
    # IDW 对光滑场的逼近误差有界（样本点精确，样本间平滑衰减；阈值按网格密度标定）
    assert np.abs(batch.values - truth).mean() < 0.2
    assert not batch.is_nodata.any()


def test_3d_field_runs_and_reproduces_samples():
    from geomodeling.modeling.idw import IDWInterpolator

    coords, values = train_3d()
    interpolator = IDWInterpolator()
    params = interpolator.validate_parameters({"power": 2.0, "neighbor_count": 12}, "3d")
    fitted = interpolator.fit(coords, values, params)
    batch = fitted.predict(coords, cancel=lambda: False)
    np.testing.assert_allclose(batch.values, values, atol=1e-9)


def test_parameter_validation_rejects_bad_power():
    from geomodeling.modeling.idw import IDWInterpolator

    interpolator = IDWInterpolator()
    for bad in (0.0, -1.0, 8.5):
        with pytest.raises(Exception):
            interpolator.validate_parameters({"power": bad}, "2d")


def test_neighbor_count_is_honored():
    from geomodeling.modeling.idw import IDWInterpolator

    coords = np.array([[0.0], [1.0], [2.0], [3.0]])
    values = np.array([0.0, 10.0, 20.0, 30.0])
    interpolator = IDWInterpolator()
    params = interpolator.validate_parameters(
        {"neighbor_count": 2, "power": 1.0, "min_neighbors": 2}, "2d"
    )
    fitted = interpolator.fit(coords, values, params)
    batch = fitted.predict(np.array([[2.5]]), cancel=lambda: False)
    # 只用最近 2 个邻居（2.0→20, 3.0→30）的 IDW 均值
    expected = (20.0 / 0.5 + 30.0 / 0.5) / (1 / 0.5 + 1 / 0.5)
    assert batch.values[0] == pytest.approx(expected)
    assert batch.diagnostics["max_neighbors_used"] <= 2


def test_search_radius_produces_nodata_outside():
    from geomodeling.modeling.idw import IDWInterpolator

    coords = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    values = np.array([1.0, 2.0, 3.0])
    interpolator = IDWInterpolator()
    params = interpolator.validate_parameters({"search_radius": 2.0, "neighbor_count": 8}, "2d")
    fitted = interpolator.fit(coords, values, params)
    batch = fitted.predict(np.array([[100.0, 100.0]]), cancel=lambda: False)
    assert batch.is_nodata[0]
    assert np.isnan(batch.values[0])


def test_insufficient_neighbors_produces_nodata():
    from geomodeling.modeling.idw import IDWInterpolator

    coords = np.array([[0.0, 0.0], [1.0, 0.0]])
    values = np.array([1.0, 2.0])
    interpolator = IDWInterpolator()
    params = interpolator.validate_parameters(
        {"neighbor_count": 8, "min_neighbors": 4}, "2d"
    )
    fitted = interpolator.fit(coords, values, params)
    batch = fitted.predict(np.array([[0.5, 0.0]]), cancel=lambda: False)
    assert batch.is_nodata[0]


def test_chunked_prediction_matches_single_pass():
    from geomodeling.modeling.idw import IDWInterpolator, PREDICTION_CHUNK_SIZE

    coords, values = train_2d()
    interpolator = IDWInterpolator()
    params = interpolator.validate_parameters({"power": 2.0, "neighbor_count": 8}, "2d")
    fitted = interpolator.fit(coords, values, params)
    rng = np.random.default_rng(3)
    query = np.column_stack(
        [rng.uniform(-160, -40, PREDICTION_CHUNK_SIZE + 7), rng.uniform(220, 660, PREDICTION_CHUNK_SIZE + 7)]
    )
    first = fitted.predict(query, cancel=lambda: False)
    # 手工单块重算最后 7 个点，应与分块结果一致
    tail = fitted.predict(query[-7:], cancel=lambda: False)
    np.testing.assert_allclose(first.values[-7:], tail.values, atol=1e-12)


def test_cancellation_between_chunks():
    from geomodeling.modeling.idw import IDWInterpolator, PREDICTION_CHUNK_SIZE
    from geomodeling.platform.errors import PlatformError

    coords, values = train_2d()
    interpolator = IDWInterpolator()
    params = interpolator.validate_parameters({"power": 2.0, "neighbor_count": 8}, "2d")
    fitted = interpolator.fit(coords, values, params)
    query = np.zeros((PREDICTION_CHUNK_SIZE + 1, 2))

    calls = {"n": 0}

    def cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    with pytest.raises(PlatformError) as exc:
        fitted.predict(query, cancel=cancel)
    assert exc.value.code == "RUN_CANCELED"


# ---------------------------------------------------------------------------
# Task 8: z_scale 距离缩放参数
# ---------------------------------------------------------------------------


def train_3d_anisotropic():
    # P1：XY 近、垂向远；P2：XY 远、垂向近 → z_scale 改变二者距离权重
    coords = np.array(
        [
            [1.0, 0.0, 10.0],
            [8.0, 0.0, 2.0],
            [200.0, 0.0, 500.0],  # 远点，只用于凑足 min_neighbors
        ]
    )
    values = np.array([100.0, 200.0, 0.0])
    return coords, values


def test_z_scale_changes_3d_prediction():
    from geomodeling.modeling.idw import IDWInterpolator

    coords, values = train_3d_anisotropic()
    interpolator = IDWInterpolator()
    base = {"power": 2.0, "neighbor_count": 2, "min_neighbors": 2}
    weak = interpolator.validate_parameters({**base, "z_scale": 0.5}, "3d")
    strong = interpolator.validate_parameters({**base, "z_scale": 2.0}, "3d")
    query = np.array([[0.0, 0.0, 0.0]])
    pred_weak = interpolator.fit(coords, values, weak).predict(query, cancel=lambda: False)
    pred_strong = interpolator.fit(coords, values, strong).predict(query, cancel=lambda: False)
    assert not pred_weak.is_nodata[0]
    assert not pred_strong.is_nodata[0]
    assert pred_weak.values[0] != pytest.approx(pred_strong.values[0])
    # 0.5 弱化垂向距离 → XY 近的点（值 100）权重更大；2 加强垂向 → 垂向近的点（值 200）权重更大
    assert pred_weak.values[0] < pred_strong.values[0]
    assert pred_weak.diagnostics["z_scale"] == 0.5
    assert pred_strong.diagnostics["z_scale"] == 2.0


def test_z_scale_default_matches_explicit_one_bitwise():
    from geomodeling.modeling.idw import IDWInterpolator

    coords, values = train_3d()
    interpolator = IDWInterpolator()
    base = {"power": 2.0, "neighbor_count": 12}
    default_params = interpolator.validate_parameters(base, "3d")
    explicit_one = interpolator.validate_parameters({**base, "z_scale": 1.0}, "3d")
    rng = np.random.default_rng(31)
    query = np.column_stack(
        [
            rng.uniform(-160, -40, 40),
            rng.uniform(220, 660, 40),
            rng.uniform(-840, 0, 40),
        ]
    )
    batch_default = interpolator.fit(coords, values, default_params).predict(query, cancel=lambda: False)
    batch_one = interpolator.fit(coords, values, explicit_one).predict(query, cancel=lambda: False)
    np.testing.assert_array_equal(batch_default.values, batch_one.values)
    np.testing.assert_array_equal(batch_default.is_nodata, batch_one.is_nodata)
    assert batch_default.diagnostics["z_scale"] == 1.0


def test_z_scale_ignored_in_2d():
    from geomodeling.modeling.idw import IDWInterpolator

    coords, values = train_2d()
    interpolator = IDWInterpolator()
    base = {"power": 2.0, "neighbor_count": 10, "min_neighbors": 3}
    weak = interpolator.validate_parameters({**base, "z_scale": 0.5}, "2d")
    strong = interpolator.validate_parameters({**base, "z_scale": 2.0}, "2d")
    xs, ys = np.meshgrid(np.linspace(-155, -45, 5), np.linspace(230, 650, 5))
    query = np.column_stack([xs.ravel(), ys.ravel()])
    batch_weak = interpolator.fit(coords, values, weak).predict(query, cancel=lambda: False)
    batch_strong = interpolator.fit(coords, values, strong).predict(query, cancel=lambda: False)
    np.testing.assert_array_equal(batch_weak.values, batch_strong.values)
    np.testing.assert_array_equal(batch_weak.is_nodata, batch_strong.is_nodata)


def test_z_scale_does_not_mutate_training_or_query_coordinates():
    from geomodeling.modeling.idw import IDWInterpolator

    coords, values = train_3d_anisotropic()
    coords_before = coords.copy()
    interpolator = IDWInterpolator()
    params = interpolator.validate_parameters(
        {"neighbor_count": 2, "min_neighbors": 2, "z_scale": 2.0}, "3d"
    )
    fitted = interpolator.fit(coords, values, params)
    query = np.array([[0.0, 0.0, 0.0]])
    query_before = query.copy()
    fitted.predict(query, cancel=lambda: False)
    np.testing.assert_array_equal(coords, coords_before)
    np.testing.assert_array_equal(query, query_before)


def test_z_scale_parameter_bounds():
    from geomodeling.modeling.idw import IDWInterpolator

    interpolator = IDWInterpolator()
    for bad in (0.0, -1.0, 20.5, float("inf"), float("nan")):
        with pytest.raises(Exception):
            interpolator.validate_parameters({"z_scale": bad}, "3d")
    ok = interpolator.validate_parameters({"z_scale": 20.0}, "3d")
    assert ok.z_scale == 20.0


# ---------------------------------------------------------------------------
# Task 7: 默认路径（无专业搜索邻域）逐位锁定
# ---------------------------------------------------------------------------


def legacy_reference(points, values, query, *, power, k, z_scale, min_neighbors=3, search_radius=None):
    """Task 7 之前生产实现（向量化 cKDTree 路径）的逐位誊录。

    只用于锁定 ``neighborhood=None`` 时的默认行为：生产代码一旦偏离该
    誊录（缩放、近邻选择、精确点、权重或 NoData 判定任一变化），断言
    即失败。查询点按行分块与单块语义一致，故誊录按单块计算。
    """

    from scipy.spatial import cKDTree

    from geomodeling.modeling.distance import scale_distance_coordinates
    from geomodeling.platform.schemas import Dimension

    points = np.asarray(points, dtype="float64")
    values = np.asarray(values, dtype="float64")
    dimension = Dimension.THREE_D if points.shape[1] == 3 else Dimension.TWO_D
    scaled_points = scale_distance_coordinates(points, dimension=dimension, z_scale=z_scale)
    scaled_query = scale_distance_coordinates(query, dimension=dimension, z_scale=z_scale)
    tree = cKDTree(scaled_points)
    kk = min(k, values.shape[0])
    if search_radius is not None:
        distances, indices = tree.query(scaled_query, k=kk, distance_upper_bound=search_radius)
    else:
        distances, indices = tree.query(scaled_query, k=kk)
    if kk == 1:
        distances = distances[:, None]
        indices = indices[:, None]

    out = np.full(scaled_query.shape[0], np.nan)
    finite_mask = np.isfinite(distances)
    neighbor_counts = finite_mask.sum(axis=1)
    ok = neighbor_counts >= min_neighbors
    exact = ok & (distances[:, 0] <= 1e-12) & finite_mask[:, 0]
    if exact.any():
        out[exact] = values[indices[exact, 0]]
    weighted = ok & ~exact
    if weighted.any():
        safe_distances = np.where(finite_mask, distances, np.inf)
        weights = 1.0 / np.power(safe_distances, power)
        weights[~finite_mask] = 0.0
        totals = weights.sum(axis=1)
        usable = weighted & (totals > 0)
        gathered = values[np.where(finite_mask, indices, 0)]
        estimates = (weights * gathered).sum(axis=1) / totals
        out[usable] = estimates[usable]
    return out, ~np.isfinite(out)


def test_idw_without_professional_neighborhood_is_bitwise_legacy():
    from geomodeling.modeling.idw import IDWInterpolator, IDWParameters

    points, values = train_3d()
    rng = np.random.default_rng(17)
    query = np.column_stack(
        [
            rng.uniform(-160, -40, 64),
            rng.uniform(220, 660, 64),
            rng.uniform(-840, 0, 64),
        ]
    )
    legacy_values, legacy_nodata = legacy_reference(points, values, query, power=2, k=16, z_scale=1)
    current = IDWInterpolator().fit(points, values, IDWParameters()).predict(
        query, cancel=lambda: False
    )
    np.testing.assert_array_equal(current.values, legacy_values)
    np.testing.assert_array_equal(current.is_nodata, legacy_nodata)
    # 默认路径诊断保持原形状，不出现邻域汇总
    assert set(current.diagnostics) == {"max_neighbors_used", "n_targets", "z_scale"}


def test_idw_without_professional_neighborhood_is_bitwise_legacy_with_radius():
    from geomodeling.modeling.idw import IDWInterpolator

    points, values = train_2d()
    query = np.array([[-100.0, 400.0], [1e6, 1e6], [-140.0, 250.0]])
    legacy_values, legacy_nodata = legacy_reference(
        points, values, query, power=2.0, k=8, z_scale=1.0, min_neighbors=4, search_radius=60.0
    )
    assert legacy_nodata.any()  # 誊录确实覆盖了半径外 NoData 分支
    interpolator = IDWInterpolator()
    params = interpolator.validate_parameters(
        {"power": 2.0, "neighbor_count": 8, "min_neighbors": 4, "search_radius": 60.0}, "2d"
    )
    current = interpolator.fit(points, values, params).predict(query, cancel=lambda: False)
    np.testing.assert_array_equal(current.values, legacy_values)
    np.testing.assert_array_equal(current.is_nodata, legacy_nodata)
