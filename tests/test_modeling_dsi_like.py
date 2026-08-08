"""v0.8.0 Task 3 tests: deterministic DSI-like interpolator core (3D only)."""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

import geomodeling.modeling.dsi_like as dsi_like_module
from geomodeling.modeling.dsi_like import DSILikeInterpolator, DSIParameters
from geomodeling.modeling.grid import derive_grid
from geomodeling.modeling.idw import IDWInterpolator, IDWParameters
from geomodeling.platform.errors import PlatformError


def make_observations():
    """观测点恰落在派生工作网格节点上（吸附恒等、每观测独占节点）。

    ``_default_grid`` 只依赖逐轴 min/max：先用锚点求轴，再按步长子采样并
    强制包含首末节点，保证子采样点集的包围盒与锚点一致 —— ``fit`` 内部
    推导出的轴与本函数逐位相同，观测点即节点。
    """

    anchors = np.array([[0.0, 0.0, 0.0], [2.0, 3.0, 4.0]])
    axes = tuple(np.asarray(a, dtype="float64") for a in derive_grid(anchors, "3d", None).axes)
    picks = []
    for axis in axes:
        stride = max(1, len(axis) // 5)
        index = np.unique(np.concatenate([np.arange(0, len(axis), stride), [len(axis) - 1]]))
        picks.append(axis[index])
    meshes = np.meshgrid(*picks, indexing="ij")
    coords = np.column_stack([m.ravel() for m in meshes])
    values = (
        np.sin(coords[:, 0] * 3.1)
        + np.cos(coords[:, 1] * 2.3)
        + 0.37 * coords[:, 2]
        + 0.11 * np.sin(coords[:, 0] * 7.7 + coords[:, 1] * 3.3 + coords[:, 2] * 1.9)
        + 12.0
    )
    return coords, values, axes


def interior_midpoints(axes) -> np.ndarray:
    """相邻节点中点：必不是节点，用于非观测位置的采样断言。"""

    mids = []
    for axis in axes:
        idx = np.linspace(0, len(axis) - 2, 3).astype(np.int64)
        mids.append((axis[idx] + axis[idx + 1]) / 2.0)
    meshes = np.meshgrid(*mids, indexing="ij")
    return np.column_stack([m.ravel() for m in meshes])


def make_irregular_observations(n: int = 60, seed: int = 20260808):
    """真实不规则坐标：三轴随机散点，Z 叠加无理数偏移，刻意不对齐任何网格节点。

    固定种子保证确定性；``sqrt(2) * arange`` 使 Z 坐标互异且不可能恰好落在
    任何等间距派生网格节点上 —— 回归审查实测「观测点吸附不是真硬约束」的
    夹具，不再只用恰好落节点的合成点。
    """

    rng = np.random.default_rng(seed)
    x = rng.uniform(-160.0, -40.0, n)
    y = rng.uniform(220.0, 660.0, n)
    z = -(rng.uniform(0.0, 800.0, n) + np.sqrt(2.0) * np.arange(1, n + 1))
    coords = np.column_stack([x, y, z])
    values = (
        np.sin(x / 37.0)
        + np.cos(y / 53.0)
        + 0.4 * np.sin(z / 91.0)
        + 0.07 * np.sin(x / 6.0 + y / 11.0 + z / 23.0)
        + np.sqrt(3.0)
        + 12.0
    )
    return coords, values


@pytest.fixture(scope="module")
def fitted_main():
    coords, values, axes = make_observations()
    interpolator = DSILikeInterpolator()
    params = interpolator.validate_parameters({}, "3d")
    fitted = interpolator.fit(coords, values, params)
    return coords, values, axes, fitted


# ---------------------------------------------------------------------------
# 确定性 + 硬约束（计划 Step 1）
# ---------------------------------------------------------------------------


def test_reproduces_observations_and_is_deterministic(fitted_main):
    coords, values, _axes, fitted = fitted_main
    first = fitted.predict(coords, cancel=lambda: False)
    second = fitted.predict(coords, cancel=lambda: False)
    # 硬约束：恰在观测节点上的查询精确复现观测原值
    np.testing.assert_allclose(first.values, values, atol=1e-10)
    assert not first.is_nodata.any()
    # 同一 fitted 对象两次 predict 字节相同
    np.testing.assert_array_equal(first.values, second.values)
    np.testing.assert_array_equal(first.is_nodata, second.is_nodata)


def test_independent_fit_predict_is_byte_identical(fitted_main):
    coords, values, _axes, fitted = fitted_main
    query = interior_midpoints(_axes)
    reference = fitted.predict(query, cancel=lambda: False)
    refit = DSILikeInterpolator().fit(coords, values, DSIParameters())
    rerun = refit.predict(query, cancel=lambda: False)
    np.testing.assert_array_equal(reference.values, rerun.values)
    np.testing.assert_array_equal(reference.is_nodata, rerun.is_nodata)
    assert reference.diagnostics == rerun.diagnostics


# ---------------------------------------------------------------------------
# 原始观测点硬约束（趋势 + 残差两层结构；审查修复）
# ---------------------------------------------------------------------------


def test_hard_constraint_exact_on_irregular_off_grid_coordinates():
    """原始观测坐标（无理/随机形态、不对齐网格节点）全部精确复现（≤1e-8）。"""

    coords, values = make_irregular_observations()
    interpolator = DSILikeInterpolator()
    fitted = interpolator.fit(coords, values, interpolator.validate_parameters({}, "3d"))
    batch = fitted.predict(coords, cancel=lambda: False)
    assert not batch.is_nodata.any()
    np.testing.assert_allclose(batch.values, values, atol=1e-8)
    assert batch.diagnostics["max_observation_error"] <= 1e-8


def test_held_out_points_are_not_exactly_reproduced():
    """折不泄漏：留出点不在硬约束集合，不得被精确复现；训练点全部精确复现。"""

    coords, values = make_irregular_observations()
    holdout = np.zeros(len(coords), dtype=bool)
    holdout[::5] = True  # 确定性留出 20%（插值器级合同；runner 级另有折分证据）
    train = ~holdout
    interpolator = DSILikeInterpolator()
    fitted = interpolator.fit(coords[train], values[train], DSIParameters())

    at_train = fitted.predict(coords[train], cancel=lambda: False)
    assert not at_train.is_nodata.any()
    np.testing.assert_allclose(at_train.values, values[train], atol=1e-8)

    at_holdout = fitted.predict(coords[holdout], cancel=lambda: False)
    valid = ~at_holdout.is_nodata
    assert valid.any()
    errors = np.abs(at_holdout.values[valid] - values[holdout][valid])
    # 留出点不在约束集合：预测是一般插值结果，绝不精确等于真值
    assert errors.max() > 1e-6


def test_constraint_gate_violation_fails_closed(monkeypatch):
    """输出门：任一训练点复算误差超容差 → 类型化失败（fail-closed）。"""

    coords, values = make_irregular_observations()
    # 把门容差压成负数，强制复算误差违例，验证门本身 fail-closed
    monkeypatch.setattr(dsi_like_module, "_CONSTRAINT_GATE_TOLERANCE", -1.0)
    with pytest.raises(PlatformError) as exc:
        DSILikeInterpolator().fit(coords, values, DSIParameters())
    assert exc.value.code == "DSI_LIKE_CONSTRAINT_VIOLATION"
    assert exc.value.details["max_observation_error"] >= 0.0


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------


def test_parameter_validation_rejects_invalid_values():
    interpolator = DSILikeInterpolator()
    bad_parameters = [
        {"init_power": 0.0},
        {"init_power": 8.5},
        {"neighbor_connectivity": 7},
        {"neighbor_connectivity": 12},
        {"smoothing_strength": 0.0},
        {"smoothing_strength": 1.5},
        {"max_iterations": 30},
        {"max_iterations": 0},
        {"convergence_tolerance": 0.0},
        {"convergence_tolerance": 2.0},
        {"hard_constraints": False},
        {"unknown_key": 1},
    ]
    for bad in bad_parameters:
        with pytest.raises(ValidationError):
            interpolator.validate_parameters(bad, "3d")


def test_parameter_validation_accepts_allowed_values():
    interpolator = DSILikeInterpolator()
    ok = interpolator.validate_parameters(
        {
            "init_power": 1.5,
            "neighbor_connectivity": 18,
            "smoothing_strength": 0.75,
            "max_iterations": 50,
            "convergence_tolerance": 1e-6,
            "hard_constraints": True,
        },
        "3d",
    )
    assert ok.neighbor_connectivity == 18
    assert ok.max_iterations == 50
    defaults = interpolator.validate_parameters({}, "3d")
    assert defaults == DSIParameters()


def test_validate_parameters_rejects_2d():
    interpolator = DSILikeInterpolator()
    with pytest.raises(ValueError):
        interpolator.validate_parameters({}, "2d")


# ---------------------------------------------------------------------------
# 输入失败语义（fail-closed，稳定码）
# ---------------------------------------------------------------------------


def test_non_finite_input_rejected():
    coords, values, _axes = make_observations()
    interpolator = DSILikeInterpolator()
    params = DSIParameters()
    bad_values = values.copy()
    bad_values[3] = np.nan
    with pytest.raises(PlatformError) as exc:
        interpolator.fit(coords, bad_values, params)
    assert exc.value.code == "DSI_LIKE_INPUT_INVALID"
    bad_coords = coords.copy()
    bad_coords[0, 1] = np.inf
    with pytest.raises(PlatformError) as exc:
        interpolator.fit(bad_coords, values, params)
    assert exc.value.code == "DSI_LIKE_INPUT_INVALID"


def test_shape_mismatch_and_empty_input_rejected():
    coords, values, _axes = make_observations()
    interpolator = DSILikeInterpolator()
    params = DSIParameters()
    with pytest.raises(PlatformError) as exc:
        interpolator.fit(coords[:-1], values, params)
    assert exc.value.code == "DSI_LIKE_INPUT_INVALID"
    with pytest.raises(PlatformError) as exc:
        interpolator.fit(coords[:, :2], values, params)
    assert exc.value.code == "DSI_LIKE_INPUT_INVALID"
    with pytest.raises(PlatformError) as exc:
        interpolator.fit(np.zeros((0, 3)), np.zeros(0), params)
    assert exc.value.code == "DSI_LIKE_INPUT_INVALID"


def test_duplicate_coordinates_rejected():
    coords, values, _axes = make_observations()
    interpolator = DSILikeInterpolator()
    duplicated = coords.copy()
    duplicated[5] = duplicated[0]
    with pytest.raises(PlatformError) as exc:
        interpolator.fit(duplicated, values, DSIParameters())
    assert exc.value.code == "DSI_LIKE_DUPLICATE_COORDINATES"


def test_zero_supported_nodes_is_typed_failure():
    # 训练点 < 3 时 3 邻居 IDW 初始化没有任何有效节点 → 受支持节点数为 0
    interpolator = DSILikeInterpolator()
    params = DSIParameters()
    for coords, values in (
        (np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]), np.array([10.0, 20.0])),
        (np.array([[0.0, 0.0, 0.0]]), np.array([10.0])),
    ):
        with pytest.raises(PlatformError) as exc:
            interpolator.fit(coords, values, params)
        assert exc.value.code == "DSI_LIKE_NO_SUPPORTED_NODES"


# ---------------------------------------------------------------------------
# 取消语义（与 IDW 同码同模式）
# ---------------------------------------------------------------------------


def test_fit_cancellation_raises_run_canceled():
    coords, values, _axes = make_observations()
    interpolator = DSILikeInterpolator()
    with pytest.raises(PlatformError) as exc:
        interpolator.fit(coords, values, DSIParameters(), cancel=lambda: True)
    assert exc.value.code == "RUN_CANCELED"


def test_smoothing_loop_checks_cancel_every_iteration():
    coords, values, _axes = make_observations()
    interpolator = DSILikeInterpolator()
    # 不收敛配置（容差逼近 0）：保证取消前迭代不会因收敛停止；
    # IDW 初始化分块检查次数 ≤ 5，第 6 次之后取消 → 必在平滑循环内抛出
    params = DSIParameters(convergence_tolerance=1e-300)
    calls = {"n": 0}

    def cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 6

    with pytest.raises(PlatformError) as exc:
        interpolator.fit(coords, values, params, cancel=cancel)
    assert exc.value.code == "RUN_CANCELED"
    assert exc.value.details["completed"] >= 1  # 已进入平滑迭代


def test_predict_cancellation_between_chunks(fitted_main):
    _coords, _values, _axes, fitted = fitted_main
    query = np.tile(np.array([[0.5, 0.5, 0.5]]), (20_001, 1))
    calls = {"n": 0}

    def cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    with pytest.raises(PlatformError) as exc:
        fitted.predict(query, cancel=cancel)
    assert exc.value.code == "RUN_CANCELED"


# ---------------------------------------------------------------------------
# 连通性、包围盒与平滑语义
# ---------------------------------------------------------------------------


def test_connectivity_6_18_26_all_finite_and_semantically_distinct(fitted_main):
    coords, values, axes, fitted6 = fitted_main
    query = interior_midpoints(axes)
    interpolator = DSILikeInterpolator()
    batches = {6: fitted6.predict(query, cancel=lambda: False)}
    for connectivity in (18, 26):
        params = DSIParameters(neighbor_connectivity=connectivity)
        batches[connectivity] = interpolator.fit(coords, values, params).predict(
            query, cancel=lambda: False
        )
    for connectivity, batch in batches.items():
        assert not batch.is_nodata.any(), connectivity
        assert np.isfinite(batch.values).all(), connectivity
    assert np.abs(batches[6].values - batches[18].values).max() > 1e-9
    assert np.abs(batches[18].values - batches[26].values).max() > 1e-9


def test_query_outside_observed_bounds_is_nodata(fitted_main):
    _coords, _values, _axes, fitted = fitted_main
    query = np.array(
        [
            [-1e-6, 1.5, 2.0],  # x 出界
            [1.0, 3.0 + 1e-6, 2.0],  # y 出界
            [1.0, 1.5, -0.25],  # z 出界
            [10.0, 10.0, 10.0],
            [1.0, 1.5, 2.0],  # 界内
        ]
    )
    batch = fitted.predict(query, cancel=lambda: False)
    assert batch.is_nodata[:4].all()
    assert np.isnan(batch.values[:4]).all()
    assert not batch.is_nodata[4]
    assert np.isfinite(batch.values[4])


def test_smoothing_changes_non_observed_but_keeps_observations(fitted_main):
    coords, values, axes, fitted = fitted_main
    query = interior_midpoints(axes)
    smoothed = fitted.predict(query, cancel=lambda: False)
    # 纯 IDW 初值参考：与实现内部初始化同口径（power=2、min_neighbors=3）
    idw_reference = IDWInterpolator().fit(
        coords, values, IDWParameters(power=2.0, min_neighbors=3)
    ).predict(query, cancel=lambda: False)
    assert not smoothed.is_nodata.any()
    assert np.abs(smoothed.values - idw_reference.values).max() > 1e-6
    # 观测值不被平滑改动
    at_observed = fitted.predict(coords, cancel=lambda: False)
    np.testing.assert_allclose(at_observed.values, values, atol=1e-10)


# ---------------------------------------------------------------------------
# 诊断与收敛门
# ---------------------------------------------------------------------------


def test_diagnostics_are_bounded_and_complete(fitted_main):
    coords, _values, axes, fitted = fitted_main
    batch = fitted.predict(coords[:4], cancel=lambda: False)
    diagnostics = batch.diagnostics
    expected = {
        "iterations",
        "converged",
        "max_delta",
        "supported_count",
        "max_observation_error",
    }
    assert expected <= set(diagnostics)
    assert 1 <= diagnostics["iterations"] <= 25
    assert isinstance(diagnostics["converged"], bool)
    assert np.isfinite(diagnostics["max_delta"])
    assert diagnostics["max_delta"] >= 0.0
    assert np.isfinite(diagnostics["max_observation_error"])
    assert 0.0 <= diagnostics["max_observation_error"] <= 1e-8
    if diagnostics["converged"]:
        assert diagnostics["max_delta"] < 1e-4
    node_count = int(np.prod([len(axis) for axis in axes]))
    assert diagnostics["supported_count"] == node_count
    assert batch.auxiliary == {}


def test_max_iterations_without_convergence_fails_closed(fitted_main):
    """达 max_iterations 仍未收敛 = 类型化失败（fail-closed，绝不物化）。

    审查语义变更：旧口径「未收敛不是失败」作废——收敛门与覆盖率门同级，
    未过收敛门的候选一律 failed。
    """

    coords, values, _axes, _fitted = fitted_main
    params = DSIParameters(convergence_tolerance=1e-300, max_iterations=25)
    with pytest.raises(PlatformError) as exc:
        DSILikeInterpolator().fit(coords, values, params)
    assert exc.value.code == "DSI_LIKE_NOT_CONVERGED"
    assert exc.value.details["iterations"] == 25
    assert exc.value.details["max_delta"] >= 1e-300


def test_default_parameters_converge_within_max_iterations(fitted_main):
    """收敛真实化：稀疏 Krylov 求解在默认 25 次内达到 max_delta < 1e-4。

    纯 Jacobi 在该夹具网格（98,304 节点）上 25 次迭代 max_delta≈6e-3、
    50 次仍不收敛；稀疏求解必须在默认预算内真实收敛。
    """

    _coords, _values, _axes, fitted = fitted_main
    diagnostics = fitted.diagnostics
    assert diagnostics["converged"] is True
    assert 1 <= diagnostics["iterations"] <= 25
    assert diagnostics["max_delta"] < 1e-4
