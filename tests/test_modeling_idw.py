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
