"""Task 10: empirical error-scale surfaces (design §10.2).

经验误差尺度是折外残差的距离加权局部 RMSE：只使用有限折外残差点，
在同一专业空间变换（``distance_transform``）与显式误差邻域中选取附近
残差，``scale = sqrt(Σ w_i·r_i² / Σ w_i)``，``w_i = 1/d_i**power``；查询
点恰好落在残差位置（d=0）时直接使用该残差的绝对误差 ``|r_i|``。邻点
不足返回 NoData 并聚合计数，不得用全局 RMSE 填充空间场。
"""

from __future__ import annotations

import numpy as np
import pytest

from geomodeling.modeling.anisotropy import (
    KrigingAnisotropySpec,
    build_kriging_transform,
)
from geomodeling.modeling.distance import scale_distance_coordinates
from geomodeling.modeling.professional_contracts import (
    EmpiricalUncertaintySpec,
    NeighborhoodSpec,
)
from geomodeling.modeling.uncertainty import (
    EMPIRICAL_UNCERTAINTY_INPUT_INVALID,
    QUERY_BATCH_SIZE,
    RUN_CANCELED,
    EmpiricalErrorScale,
    empirical_error_scale,
    identity_transform,
)
from geomodeling.platform.errors import PlatformError


def _spec(**overrides) -> EmpiricalUncertaintySpec:
    base = dict(min_neighbors=2, max_neighbors=2, power=2.0)
    return EmpiricalUncertaintySpec(**{**base, **overrides})


def _weighted_local_rmse(
    points: np.ndarray, residuals: np.ndarray, target: np.ndarray, power: float
) -> float:
    """测试侧独立参考实现：d>0 时按 1/d**power 加权的局部 RMSE。"""

    distances = np.linalg.norm(points - target[None, :], axis=1)
    weights = 1.0 / np.power(distances, power)
    return float(np.sqrt((weights * residuals**2).sum() / weights.sum()))


# ---------------------------------------------------------------------------
# 局部 RMSE 核心语义（实施计划 Task 10 给定示例）
# ---------------------------------------------------------------------------


def test_empirical_error_scale_is_distance_weighted_local_rmse():
    result = empirical_error_scale(
        residual_points=np.array([[0, 0], [2, 0]], dtype=float),
        residuals=np.array([1.0, -3.0]),
        query=np.array([[1, 0]], dtype=float),
        spec=EmpiricalUncertaintySpec(min_neighbors=2, max_neighbors=2, power=2),
        distance_transform=identity_transform(2),
        cancel=lambda: False,
    )
    assert result.scale[0] == pytest.approx(np.sqrt((1**2 + 3**2) / 2))
    assert result.neighbor_count[0] == 2


def test_exact_residual_location_uses_that_residuals_absolute_error():
    """d=0 等价于权重无穷大的极限：尺度直接取该残差的 |r_i|，不做加权。"""

    result = empirical_error_scale(
        residual_points=np.array([[0.0, 0.0], [2.0, 0.0]]),
        residuals=np.array([1.0, -3.0]),
        query=np.array([[2.0, 0.0]]),
        spec=_spec(),
        distance_transform=identity_transform(2),
        cancel=lambda: False,
    )
    assert result.scale[0] == pytest.approx(3.0)
    # 邻域选择照常进行；精确点只改变尺度取值，不改变邻点计数
    assert result.neighbor_count[0] == 2
    assert not result.is_nodata[0]


def test_result_arrays_align_with_query_rows():
    result = empirical_error_scale(
        residual_points=np.array([[0.0, 0.0], [2.0, 0.0]]),
        residuals=np.array([1.0, -3.0]),
        query=np.array([[1.0, 0.0], [0.0, 0.0], [2.0, 0.0]]),
        spec=_spec(),
        distance_transform=identity_transform(2),
        cancel=lambda: False,
    )
    assert isinstance(result, EmpiricalErrorScale)
    assert result.scale.shape == (3,)
    assert result.is_nodata.shape == (3,)
    assert result.neighbor_count.shape == (3,)
    assert result.scale[1] == pytest.approx(1.0)  # 精确点 → |r|
    assert result.scale[2] == pytest.approx(3.0)
    assert not result.is_nodata.any()
    assert result.diagnostics["coverage"] == pytest.approx(1.0)
    assert result.diagnostics["total_queries"] == 3
    assert result.diagnostics["covered_queries"] == 3


# ---------------------------------------------------------------------------
# NoData 语义：邻点不足、折外 NoData 行排除、不得用全局 RMSE 填充
# ---------------------------------------------------------------------------


def test_insufficient_neighbors_yield_nodata_with_reason_counts():
    residuals = np.array([1.0, -3.0])
    result = empirical_error_scale(
        residual_points=np.array([[0.0, 0.0], [2.0, 0.0]]),
        residuals=residuals,
        query=np.array([[1.0, 0.0], [0.0, 0.0]]),
        spec=_spec(min_neighbors=3, max_neighbors=4),
        distance_transform=identity_transform(2),
        cancel=lambda: False,
    )
    # 邻点不足必须是 NoData，而不是用全局 RMSE（sqrt(mean(r²))）填满空间场
    global_rmse = float(np.sqrt((residuals**2).mean()))
    assert not np.isfinite(result.scale).any()
    assert result.is_nodata.all()
    assert (result.neighbor_count == 0).all()
    for value in result.scale:
        assert value != pytest.approx(global_rmse)
    assert result.diagnostics["coverage"] == pytest.approx(0.0)
    assert result.diagnostics["covered_queries"] == 0
    assert result.diagnostics["nodata_reasons"] == {"neighbors_insufficient": 2}


def test_nodata_oof_rows_are_excluded_from_neighbors():
    """is_nodata 的折外行（非有限残差）不得进入邻域与加权。"""

    result = empirical_error_scale(
        residual_points=np.array([[0.0, 0.0], [2.0, 0.0], [1.0, 0.0]]),
        residuals=np.array([1.0, -3.0, np.nan]),
        query=np.array([[1.0, 0.0]]),
        spec=_spec(),
        distance_transform=identity_transform(2),
        cancel=lambda: False,
    )
    # 查询点恰落在被排除的折外行位置上：不得触发精确点语义
    assert result.scale[0] == pytest.approx(np.sqrt((1**2 + 3**2) / 2))
    assert result.neighbor_count[0] == 2
    assert result.diagnostics["residual_point_count"] == 2
    assert result.diagnostics["excluded_residual_count"] == 1


def test_all_nodata_residuals_yield_empty_coverage():
    result = empirical_error_scale(
        residual_points=np.array([[0.0, 0.0], [2.0, 0.0]]),
        residuals=np.array([np.nan, np.nan]),
        query=np.array([[1.0, 0.0], [0.5, 0.0]]),
        spec=_spec(),
        distance_transform=identity_transform(2),
        cancel=lambda: False,
    )
    assert result.is_nodata.all()
    assert (result.neighbor_count == 0).all()
    assert result.diagnostics["coverage"] == pytest.approx(0.0)
    assert result.diagnostics["nodata_reasons"] == {"neighbors_insufficient": 2}
    assert result.diagnostics["residual_point_count"] == 0
    assert result.diagnostics["excluded_residual_count"] == 2


# ---------------------------------------------------------------------------
# 物理坐标只读
# ---------------------------------------------------------------------------


def test_physical_coordinates_are_never_modified():
    points = np.array([[0.0, 0.0], [2.0, 0.0], [1.0, 1.0]])
    residuals = np.array([1.0, -3.0, 2.0])
    query = np.array([[1.0, 0.0], [0.5, 0.5]])
    points_before = points.copy()
    query_before = query.copy()
    transform = build_kriging_transform(
        KrigingAnisotropySpec(
            dimension="2d", azimuth_deg=30.0, major_scale=1.0, minor_scale=2.0
        )
    )
    empirical_error_scale(
        residual_points=points,
        residuals=residuals,
        query=query,
        spec=_spec(
            max_neighbors=3,
            neighborhood=NeighborhoodSpec(
                radii=(5.0, 5.0), min_neighbors=2, max_neighbors=3
            ),
        ),
        distance_transform=transform,
        cancel=lambda: False,
    )
    np.testing.assert_array_equal(points, points_before)
    np.testing.assert_array_equal(query, query_before)


# ---------------------------------------------------------------------------
# 取消语义：分批检查（RUN_CANCELED / http 409）
# ---------------------------------------------------------------------------


def test_cancel_before_first_batch_raises_run_canceled():
    with pytest.raises(PlatformError) as excinfo:
        empirical_error_scale(
            residual_points=np.array([[0.0, 0.0], [2.0, 0.0]]),
            residuals=np.array([1.0, -3.0]),
            query=np.array([[1.0, 0.0]]),
            spec=_spec(),
            distance_transform=identity_transform(2),
            cancel=lambda: True,
        )
    assert excinfo.value.code == RUN_CANCELED
    assert excinfo.value.http_status == 409
    assert excinfo.value.details["completed_queries"] == 0


def test_cancel_is_checked_per_query_batch():
    """cancel 按批检查：第二批触发时已完成数 = 一个完整批的大小。"""

    calls = 0

    def flip_cancel() -> bool:
        nonlocal calls
        calls += 1
        return calls > 1

    with pytest.raises(PlatformError) as excinfo:
        empirical_error_scale(
            residual_points=np.array([[0.0, 0.0], [2.0, 0.0]]),
            residuals=np.array([1.0, -3.0]),
            query=np.zeros((QUERY_BATCH_SIZE + 1, 2)),
            spec=_spec(),
            distance_transform=identity_transform(2),
            cancel=flip_cancel,
        )
    assert excinfo.value.code == RUN_CANCELED
    assert excinfo.value.details["completed_queries"] == QUERY_BATCH_SIZE


# ---------------------------------------------------------------------------
# 距离变换：恒等 / IDW legacy z_scale / Kriging 规范变换与指纹
# ---------------------------------------------------------------------------


def test_identity_transform_returns_physical_coordinates():
    transform = identity_transform(3)
    points = np.array([[1.0, 2.0, 3.0], [-4.0, 0.5, 7.0]])
    np.testing.assert_array_equal(transform.apply(points), points)
    assert isinstance(transform.fingerprint, str) and transform.fingerprint


def test_idw_z_scale_transform_matches_legacy_distance_space():
    """IDW 候选：legacy ``(x, y, z × z_scale)`` 距离空间决定加权距离。"""

    z_scale = 2.0
    transform = build_kriging_transform(
        KrigingAnisotropySpec.from_legacy_z_scale(z_scale)
    )
    points = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 2.0]])
    residuals = np.array([1.0, -3.0])
    query = np.array([[0.0, 0.0, 0.9]])
    combined = np.vstack([points, query])
    # 规范变换与 legacy 缩放助手逐位一致（§7.2 兼容条款）
    np.testing.assert_allclose(
        transform.apply(combined),
        scale_distance_coordinates(combined, dimension="3d", z_scale=z_scale),
        atol=1e-12,
    )
    result = empirical_error_scale(
        residual_points=points,
        residuals=residuals,
        query=query,
        spec=_spec(),
        distance_transform=transform,
        cancel=lambda: False,
    )
    scaled = scale_distance_coordinates(combined, dimension="3d", z_scale=z_scale)
    expected = _weighted_local_rmse(scaled[:2], residuals, scaled[2], power=2.0)
    assert result.scale[0] == pytest.approx(expected)
    # 与未缩放（恒等）距离空间的结果必须不同：z_scale 确实进入加权
    identity_expected = _weighted_local_rmse(points, residuals, query[0], power=2.0)
    assert result.scale[0] != pytest.approx(identity_expected)
    assert result.diagnostics["transform_fingerprint"] == transform.fingerprint


def test_kriging_transform_fingerprint_matches_candidate_transform():
    """Kriging 候选：经验误差距离指纹必须与该候选的 Kriging 变换指纹一致。"""

    kriging_spec = KrigingAnisotropySpec(
        dimension="2d", azimuth_deg=90.0, major_scale=1.0, minor_scale=2.0
    )
    transform = build_kriging_transform(kriging_spec)
    points = np.array([[0.0, 1.0], [2.0, 0.0]])
    residuals = np.array([2.0, -4.0])
    query = np.array([[0.0, 0.0]])
    result = empirical_error_scale(
        residual_points=points,
        residuals=residuals,
        query=query,
        spec=_spec(),
        distance_transform=transform,
        cancel=lambda: False,
    )
    transformed = transform.apply(np.vstack([points, query]))
    expected = _weighted_local_rmse(transformed[:2], residuals, transformed[2], 2.0)
    # 该几何下两个变换距离同为 1：锚定解析值 sqrt((2² + 4²) / 2)
    assert expected == pytest.approx(np.sqrt((2.0**2 + 4.0**2) / 2.0))
    assert result.scale[0] == pytest.approx(expected)
    assert result.diagnostics["transform_fingerprint"] == transform.fingerprint


def test_plain_callable_transform_uses_same_interface_without_fingerprint():
    """普通 callable（apply 返回新数组）与 SpatialTransform 走同一接口。"""

    result = empirical_error_scale(
        residual_points=np.array([[0.0, 0.0], [2.0, 0.0]]),
        residuals=np.array([1.0, -3.0]),
        query=np.array([[1.0, 0.0]]),
        spec=_spec(),
        distance_transform=lambda coordinates: coordinates * 2.0,
        cancel=lambda: False,
    )
    # 整体缩放不改变权重比例：结果与恒等变换一致
    assert result.scale[0] == pytest.approx(np.sqrt((1**2 + 3**2) / 2))
    assert result.diagnostics["transform_fingerprint"] is None


# ---------------------------------------------------------------------------
# 显式误差邻域（复用 select_neighbors 的有界旋转椭圆/扇区选择）
# ---------------------------------------------------------------------------


def test_explicit_error_neighborhood_bounds_selection_by_radii():
    spec = _spec(
        max_neighbors=4,
        neighborhood=NeighborhoodSpec(
            radii=(1.5, 1.5), min_neighbors=2, max_neighbors=4
        ),
    )
    result = empirical_error_scale(
        residual_points=np.array([[0.0, 0.0], [2.0, 0.0]]),
        residuals=np.array([1.0, -3.0]),
        query=np.array([[1.0, 0.0], [10.0, 0.0]]),
        spec=spec,
        distance_transform=identity_transform(2),
        cancel=lambda: False,
    )
    # 半径内两个残差：距离同为 1，等权局部 RMSE
    assert result.scale[0] == pytest.approx(np.sqrt((1**2 + 3**2) / 2))
    assert result.neighbor_count[0] == 2
    # 半径外没有残差：NoData + 原因计数，不扩大半径、不退化全局
    assert result.is_nodata[1]
    assert result.neighbor_count[1] == 0
    assert result.diagnostics["nodata_reasons"] == {"neighbors_insufficient": 1}
    assert result.diagnostics["coverage"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 输入校验
# ---------------------------------------------------------------------------


def test_misaligned_residuals_raise_structured_error():
    with pytest.raises(PlatformError) as excinfo:
        empirical_error_scale(
            residual_points=np.array([[0.0, 0.0], [2.0, 0.0]]),
            residuals=np.array([1.0]),
            query=np.array([[1.0, 0.0]]),
            spec=_spec(),
            distance_transform=identity_transform(2),
            cancel=lambda: False,
        )
    assert excinfo.value.code == EMPIRICAL_UNCERTAINTY_INPUT_INVALID


def test_non_finite_query_raises_structured_error():
    with pytest.raises(PlatformError) as excinfo:
        empirical_error_scale(
            residual_points=np.array([[0.0, 0.0], [2.0, 0.0]]),
            residuals=np.array([1.0, -3.0]),
            query=np.array([[np.nan, 0.0]]),
            spec=_spec(),
            distance_transform=identity_transform(2),
            cancel=lambda: False,
        )
    assert excinfo.value.code == EMPIRICAL_UNCERTAINTY_INPUT_INVALID
