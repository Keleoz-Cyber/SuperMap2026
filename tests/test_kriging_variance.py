"""Task 8 tests: native ordinary-Kriging variance (design §9).

契约要点（设计 §9 / 实施计划 Task 8）：

- 普通 Kriging 线性系统返回权重 λ 与拉格朗日乘子 μ；原生方差（半变异
  函数形式）σ_k² = λᵀγ0 + μ，γ0 是目标点到邻点的半变异函数向量；
- ``kriging_standard_deviation = sqrt(max(variance, 0))``；
- 精确观测点在零 nugget 下 σ² 接近 0；
- 仅 ``-1e-10 <= variance < 0`` 的浮点微负钳到 0 并计入诊断
  （``kriging_variance_clamped_count``）；显著负值（< -1e-10）与非有
  限值 → 该目标 NoData + 原因计数（``kriging_variance_invalid``）；
- 最小二乘降级（lstsq）时 per-target 在方差工件中标记
  （``auxiliary["kriging_variance_used_lstsq"]``）；
- IDW 不暴露 variance capability（``PredictionBatch.auxiliary`` 为空，
  能力矩阵 ``native_kriging_std == not_applicable``）。

参考系统的 REFERENCE_ESTIMATE / REFERENCE_VARIANCE 由测试内字面 NumPy
增广矩阵独立解出，不调用生产 helper。
"""

from __future__ import annotations

import numpy as np
import pytest

# 非对称五点夹具（所有点对距离都在 range=10 的结构段内，系统非奇异）
NEIGHBORS = np.array([[0.0, 0.0], [5.0, 0.0], [0.0, 4.0], [6.0, 3.0], [2.0, 5.0]])
VALUES = np.array([10.0, 20.0, 15.0, 30.0, 25.0])
TARGET = np.array([1.5, 2.0])


def _literal_spherical(h, nugget, partial_sill, range_):
    """测试内字面球状模型公式（复制语义而非调用生产 helper）。"""

    h = np.asarray(h, dtype="float64")
    r = np.minimum(h / range_, 1.0)
    return nugget + partial_sill * np.where(r < 1.0, 1.5 * r - 0.5 * r**3, 1.0)


def _reference_system():
    """字面增广矩阵 [Γ+μ 系统] 独立解 REFERENCE_ESTIMATE / REFERENCE_VARIANCE。"""

    n = len(NEIGHBORS)
    pairwise = np.linalg.norm(NEIGHBORS[None, :, :] - NEIGHBORS[:, None, :], axis=2)
    gamma_mat = _literal_spherical(pairwise, 0.0, 1.0, 10.0)
    gamma0 = _literal_spherical(
        np.linalg.norm(NEIGHBORS - TARGET[None, :], axis=1), 0.0, 1.0, 10.0
    )
    system = np.zeros((n + 1, n + 1))
    system[:n, :n] = gamma_mat
    system[:n, n] = 1.0
    system[n, :n] = 1.0
    rhs = np.concatenate([gamma0, [1.0]])
    solution = np.linalg.solve(system, rhs)
    weights, mu = solution[:n], solution[n]
    return float(weights @ VALUES), float(weights @ gamma0 + mu)


def _variance_fixture():
    coords = np.array(
        [[0.0, 0.0], [5.0, 0.0], [0.0, 4.0], [6.0, 3.0], [2.0, 5.0], [4.0, 6.0]]
    )
    values = np.array([10.0, 20.0, 15.0, 30.0, 25.0, 18.0])
    query = np.array([[1.5, 2.0], [3.0, 3.5]])
    params = {
        "variogram_mode": "manual",
        "variogram_model": "spherical",
        "nugget": 0.0,
        "sill": 1.0,
        "range": 10.0,
        "neighbor_count": 6,
        "min_neighbors": 3,
    }
    return coords, values, query, params


def _predict(coords, values, query, params, dimension="2d"):
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    interpolator = OrdinaryKrigingInterpolator()
    validated = interpolator.validate_parameters(params, dimension)
    return interpolator.fit(coords, values, validated).predict(query, cancel=lambda: False)


def _force_variance(monkeypatch, forced_value):
    """把 ``ordinary_kriging_solution`` 返回的 μ 平移，使 σ_k² = λᵀγ0 + μ 恰好
    等于 ``forced_value``（确定性触发钳制/无效分支）。"""

    import geomodeling.modeling.kriging as kriging_module
    from geomodeling.modeling.variogram import semivariance

    real = kriging_module.ordinary_kriging_solution

    def fake(neighbors, target, model):
        weights, _mu, used_lstsq = real(neighbors, target, model)
        distances = np.linalg.norm(neighbors - target[None, :], axis=1)
        gamma0 = semivariance(
            distances, model.model, model.nugget, model.partial_sill, model.range
        )
        return weights, float(forced_value - weights @ gamma0), used_lstsq

    monkeypatch.setattr(kriging_module, "ordinary_kriging_solution", fake)


def test_ordinary_kriging_returns_reference_value_and_variance():
    from geomodeling.modeling.kriging import ordinary_kriging_solution
    from geomodeling.modeling.variogram import VariogramModel, semivariance

    reference_estimate, reference_variance = _reference_system()
    # 锚定字面常量，防止参考计算器自身被改坏
    assert reference_estimate == pytest.approx(16.40955417628667, abs=1e-12)
    assert reference_variance == pytest.approx(0.3679112006279616, abs=1e-12)

    model = VariogramModel(model="spherical", nugget=0.0, partial_sill=1.0, range=10.0)
    weights, mu, used_lstsq = ordinary_kriging_solution(NEIGHBORS, TARGET, model)
    estimate = float(weights @ VALUES)
    distances_to_target = np.linalg.norm(NEIGHBORS - TARGET[None, :], axis=1)
    variance = float(
        weights
        @ semivariance(
            distances_to_target, model.model, model.nugget, model.partial_sill, model.range
        )
        + mu
    )
    assert estimate == pytest.approx(reference_estimate, abs=1e-10)
    assert variance == pytest.approx(reference_variance, abs=1e-10)
    assert used_lstsq is False
    assert weights.sum() == pytest.approx(1.0, abs=1e-12)


def test_exact_point_with_zero_nugget_has_near_zero_variance():
    # 查询点与训练点精确重合：零 nugget 下 σ² ≈ 0（允许浮点微负被钳到 0）
    params = {
        "variogram_mode": "manual",
        "variogram_model": "spherical",
        "nugget": 0.0,
        "sill": 1.0,
        "range": 10.0,
        "neighbor_count": 5,
        "min_neighbors": 3,
    }
    batch = _predict(NEIGHBORS, VALUES, NEIGHBORS.copy(), params)
    assert not batch.is_nodata.any()
    np.testing.assert_allclose(batch.values, VALUES, atol=1e-9)
    variance = batch.auxiliary["kriging_variance"]
    std = batch.auxiliary["kriging_standard_deviation"]
    assert variance.shape == std.shape == (len(NEIGHBORS),)
    assert (variance >= 0.0).all()  # 存储值为钳制后结果
    assert (variance <= 1e-12).all()
    np.testing.assert_allclose(std, np.sqrt(variance), atol=0.0)
    assert not batch.auxiliary["kriging_variance_used_lstsq"].any()


@pytest.mark.parametrize("forced", [-5e-11, -9e-11])
def test_tiny_negative_variance_is_clamped_to_zero_and_counted(monkeypatch, forced):
    # 仅 -1e-10 <= σ² < 0 的浮点微负允许钳制（边界语义由
    # test_classify_variance_boundary 在分类器上精确锚定：forcing 路径
    # 自身有尾差，不在集成层贴边界）
    coords, values, query, params = _variance_fixture()
    _force_variance(monkeypatch, forced)
    batch = _predict(coords, values, query, params)
    assert not batch.is_nodata.any()
    np.testing.assert_array_equal(
        batch.auxiliary["kriging_variance"], np.zeros(len(query))
    )
    np.testing.assert_array_equal(
        batch.auxiliary["kriging_standard_deviation"], np.zeros(len(query))
    )
    assert batch.diagnostics["kriging_variance_clamped_count"] == len(query)
    assert batch.diagnostics["nodata_reason_counts"] == {}


def test_classify_variance_boundary():
    # 钳制边界在分类器上精确锚定：-1e-10（含）以上微负钳到 0，
    # 其下一个更小浮点数即判无效；0 与正值原样通过且不计钳制
    from geomodeling.modeling.kriging import _classify_variance

    assert _classify_variance(-1e-10) == (0.0, True)
    assert _classify_variance(float(np.nextafter(-1e-10, -np.inf))) == (None, False)
    assert _classify_variance(-1e-17) == (0.0, True)
    assert _classify_variance(0.0) == (0.0, False)
    assert _classify_variance(0.25) == (0.25, False)
    assert _classify_variance(float("nan")) == (None, False)
    assert _classify_variance(float("inf")) == (None, False)


@pytest.mark.parametrize("forced", [-1e-3, -1.0000001e-10])
def test_materially_negative_variance_becomes_nodata_with_reason(monkeypatch, forced):
    # 显著负值（< -1e-10）→ 该目标 NoData + 原因计数，估计值一并作废
    coords, values, query, params = _variance_fixture()
    _force_variance(monkeypatch, forced)
    batch = _predict(coords, values, query, params)
    assert batch.is_nodata.all()
    assert np.isnan(batch.values).all()
    assert np.isnan(batch.auxiliary["kriging_variance"]).all()
    assert np.isnan(batch.auxiliary["kriging_standard_deviation"]).all()
    assert batch.diagnostics["nodata_reason_counts"] == {"kriging_variance_invalid": len(query)}
    assert batch.diagnostics["kriging_variance_clamped_count"] == 0


@pytest.mark.parametrize("forced", [float("nan"), float("inf")])
def test_non_finite_variance_becomes_nodata_with_reason(monkeypatch, forced):
    coords, values, query, params = _variance_fixture()
    _force_variance(monkeypatch, forced)
    batch = _predict(coords, values, query, params)
    assert batch.is_nodata.all()
    assert np.isnan(batch.auxiliary["kriging_variance"]).all()
    assert batch.diagnostics["nodata_reason_counts"] == {"kriging_variance_invalid": len(query)}


def test_lstsq_fallback_is_flagged_per_target_in_variance_artifact():
    # 邻域内含多个完全重合点 → 增广方程组奇异 → 最小二乘降级；
    # 预测沿用 legacy 语义继续给出，方差工件必须 per-target 标记 used_lstsq
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
    params = {
        "variogram_mode": "manual",
        "variogram_model": "spherical",
        "nugget": 0.0,
        "sill": 1.0,
        "range": 15.0,
        "neighbor_count": 6,
        "min_neighbors": 3,
    }
    batch = _predict(coords, values, np.array([[1.0, 1.0]]), params)
    assert not batch.is_nodata[0]
    assert np.isfinite(batch.values[0])
    assert batch.diagnostics["singular_fallback_count"] >= 1
    flags = batch.auxiliary["kriging_variance_used_lstsq"]
    assert flags.dtype == bool
    assert bool(flags[0]) is True
    variance = batch.auxiliary["kriging_variance"]
    assert np.isfinite(variance[0]) and variance[0] >= 0.0


def test_auxiliary_arrays_cover_all_targets_and_match_values():
    rng = np.random.default_rng(11)
    coords = np.column_stack([rng.uniform(-50, 50, 30), rng.uniform(100, 200, 30)])
    values = np.sin(coords[:, 0] / 15.0) + 3.0
    query = np.array([[-30.0, 120.0], [0.0, 150.0], [25.0, 190.0], [500.0, 500.0]])
    params = {
        "variogram_mode": "manual",
        "variogram_model": "spherical",
        "nugget": 0.05,
        "sill": 1.2,
        "range": 80.0,
        "neighbor_count": 8,
        "search_radius": 120.0,
    }
    batch = _predict(coords, values, query, params)
    assert set(batch.auxiliary) == {
        "kriging_variance",
        "kriging_standard_deviation",
        "kriging_variance_used_lstsq",
    }
    variance = batch.auxiliary["kriging_variance"]
    std = batch.auxiliary["kriging_standard_deviation"]
    flags = batch.auxiliary["kriging_variance_used_lstsq"]
    assert variance.shape == std.shape == flags.shape == batch.values.shape
    assert flags.dtype == bool
    valid = ~batch.is_nodata
    assert batch.is_nodata[-1]  # 搜索半径外无邻居 → NoData
    assert (variance[valid] >= 0.0).all()
    np.testing.assert_allclose(std[valid], np.sqrt(variance[valid]))
    assert np.isnan(variance[~valid]).all() and np.isnan(std[~valid]).all()
    assert batch.diagnostics["nodata_reason_counts"] == {"neighbors_insufficient": 1}
    assert batch.diagnostics["kriging_variance_clamped_count"] == 0
    # legacy 诊断键保持不变
    for key in ("max_neighbors_used", "singular_fallback_count", "z_scale", "variogram"):
        assert key in batch.diagnostics


def test_idw_does_not_expose_kriging_variance_capability():
    from geomodeling.modeling.idw import IDWInterpolator
    from geomodeling.modeling.professional_contracts import (
        CapabilityState,
        capabilities_for,
    )

    coords, values, query, _ = _variance_fixture()
    interpolator = IDWInterpolator()
    params = interpolator.validate_parameters({"neighbor_count": 6, "min_neighbors": 3}, "2d")
    batch = interpolator.fit(coords, values, params).predict(query, cancel=lambda: False)
    assert batch.auxiliary == {}
    assert capabilities_for("idw").native_kriging_std == CapabilityState.NOT_APPLICABLE
    assert capabilities_for("ordinary_kriging").native_kriging_std == CapabilityState.SUPPORTED
