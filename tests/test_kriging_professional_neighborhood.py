"""Task 8 tests: canonical anisotropy and professional neighborhoods in Kriging.

契约要点（设计 §7.2 / §8.2 / 实施计划 Task 8）：

- 可选 ``anisotropy: KrigingAnisotropySpec``：变异函数拟合、协方差矩阵、
  权重距离全部用同一 ``SpatialTransform`` 变换后的坐标；诊断披露同一
  变换指纹；
- 非默认 legacy ``z_scale`` 与专业各向异性同时给出 → 参数校验拒绝；
- 可选 ``neighborhood: NeighborhoodSpec``：``select_neighbors`` 按物理
  坐标与物理半径做旋转椭圆/椭球扇区选择（半径是独立的显式参数），
  Kriging 矩阵用选中邻点在变换后坐标下的距离构建；
- 邻点不足 → 该目标 NoData（整批不中断）+ 原因计数；
- 参考值全部由测试内字面变换与字面增广矩阵独立解出。
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest


def _literal_spherical(h, nugget, partial_sill, range_):
    """测试内字面球状模型公式（复制语义而非调用生产 helper）。"""

    h = np.asarray(h, dtype="float64")
    r = np.minimum(h / range_, 1.0)
    return nugget + partial_sill * np.where(r < 1.0, 1.5 * r - 0.5 * r**3, 1.0)


def _literal_ok_estimate(neighbors, target, values, nugget, partial_sill, range_):
    """字面增广矩阵独立解一个目标的普通 Kriging 估计。"""

    neighbors = np.asarray(neighbors, dtype="float64")
    target = np.asarray(target, dtype="float64")
    n = len(neighbors)
    pairwise = np.linalg.norm(neighbors[None, :, :] - neighbors[:, None, :], axis=2)
    gamma_mat = _literal_spherical(pairwise, nugget, partial_sill, range_)
    gamma0 = _literal_spherical(
        np.linalg.norm(neighbors - target[None, :], axis=1), nugget, partial_sill, range_
    )
    system = np.zeros((n + 1, n + 1))
    system[:n, :n] = gamma_mat
    system[:n, n] = 1.0
    system[n, :n] = 1.0
    solution = np.linalg.solve(system, np.concatenate([gamma0, [1.0]]))
    return float(solution[:n] @ np.asarray(values, dtype="float64"))


def _literal_transform_2d(coords, azimuth_deg, major_scale, minor_scale):
    """字面规范变换 x' = S Rᵀ x（S = diag(1/a_major, 1/a_minor)）。"""

    angle = math.radians(azimuth_deg)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    rotation = np.array([[cos_a, -sin_a], [sin_a, cos_a]])
    matrix = np.diag([1.0 / major_scale, 1.0 / minor_scale]) @ rotation.T
    return np.asarray(coords, dtype="float64") @ matrix.T


def _predict(coords, values, query, params, dimension="2d"):
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    interpolator = OrdinaryKrigingInterpolator()
    validated = interpolator.validate_parameters(params, dimension)
    return interpolator.fit(coords, values, validated).predict(query, cancel=lambda: False)


def _axis_fixture():
    # X 轴三点与 Y 轴三点到原点距离完全相同；扁椭圆按方位角只收其中一条轴
    coords = np.array(
        [
            [10.0, 0.0],
            [20.0, 0.0],
            [30.0, 0.0],
            [0.0, 10.0],
            [0.0, 20.0],
            [0.0, 30.0],
        ]
    )
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    return coords, values


MANUAL = {
    "variogram_mode": "manual",
    "variogram_model": "spherical",
    "nugget": 0.0,
    "sill": 1.0,
    "range": 50.0,
}

ANISOTROPY_2D = {"dimension": "2d", "azimuth_deg": 30.0, "major_scale": 2.0, "minor_scale": 0.5}
ANISOTROPY_3D = {
    "dimension": "3d",
    "azimuth_deg": 10.0,
    "dip_deg": 20.0,
    "roll_deg": 5.0,
    "major_scale": 2.0,
    "minor_scale": 1.0,
    "vertical_scale": 0.5,
}


def test_anisotropy_transform_matches_literal_reference():
    coords = np.array([[0.0, 0.0], [5.0, 0.0], [0.0, 4.0], [6.0, 3.0], [2.0, 5.0]])
    values = np.array([10.0, 20.0, 15.0, 30.0, 25.0])
    query = np.array([[1.5, 2.0], [4.5, 4.0]])
    params = {
        **MANUAL,
        "range": 25.0,
        "neighbor_count": 5,
        "min_neighbors": 3,
        "anisotropy": ANISOTROPY_2D,
    }
    batch = _predict(coords, values, query, params)
    assert not batch.is_nodata.any()
    # 独立参考：字面变换后的坐标上做字面增广求解（邻域 = 全部 5 点）
    coords_t = _literal_transform_2d(coords, 30.0, 2.0, 0.5)
    query_t = _literal_transform_2d(query, 30.0, 2.0, 0.5)
    for row in range(len(query)):
        expected = _literal_ok_estimate(coords_t, query_t[row], values, 0.0, 1.0, 25.0)
        assert batch.values[row] == pytest.approx(expected, abs=1e-10)
    # 方差同样建立在变换后距离上：非负且与估计共存
    assert (batch.auxiliary["kriging_variance"] >= 0.0).all()


def test_isotropic_anisotropy_spec_matches_no_anisotropy_bitwise():
    coords = np.array([[0.0, 0.0], [5.0, 0.0], [0.0, 4.0], [6.0, 3.0], [2.0, 5.0]])
    values = np.array([10.0, 20.0, 15.0, 30.0, 25.0])
    query = np.array([[1.5, 2.0], [4.5, 4.0]])
    base = {**MANUAL, "range": 25.0, "neighbor_count": 5, "min_neighbors": 3}
    isotropic = {
        "dimension": "2d",
        "azimuth_deg": 0.0,
        "major_scale": 1.0,
        "minor_scale": 1.0,
    }
    plain = _predict(coords, values, query, base)
    batch = _predict(coords, values, query, {**base, "anisotropy": isotropic})
    np.testing.assert_array_equal(batch.values, plain.values)
    np.testing.assert_array_equal(batch.is_nodata, plain.is_nodata)
    np.testing.assert_array_equal(
        batch.auxiliary["kriging_variance"], plain.auxiliary["kriging_variance"]
    )


def test_anisotropy_changes_prediction_and_discloses_one_fingerprint():
    coords = np.array([[0.0, 0.0], [5.0, 0.0], [0.0, 4.0], [6.0, 3.0], [2.0, 5.0]])
    values = np.array([10.0, 20.0, 15.0, 30.0, 25.0])
    query = np.array([[1.5, 2.0], [4.5, 4.0]])
    base = {**MANUAL, "range": 25.0, "neighbor_count": 5, "min_neighbors": 3}
    isotropic = {
        "dimension": "2d",
        "azimuth_deg": 0.0,
        "major_scale": 1.0,
        "minor_scale": 1.0,
    }
    batch_iso = _predict(coords, values, query, {**base, "anisotropy": isotropic})
    batch_aniso = _predict(coords, values, query, {**base, "anisotropy": ANISOTROPY_2D})
    assert not np.array_equal(batch_iso.values, batch_aniso.values)
    # 同一候选的经验半变异函数距离/协方差距离使用同一变换指纹
    from geomodeling.modeling.anisotropy import (
        KrigingAnisotropySpec,
        build_kriging_transform,
    )

    spec = KrigingAnisotropySpec.model_validate(ANISOTROPY_2D)
    expected_fingerprint = build_kriging_transform(spec).fingerprint
    assert batch_aniso.diagnostics["transform_fingerprint"] == expected_fingerprint


def test_auto_variogram_fit_uses_transformed_coordinates():
    rng = np.random.default_rng(21)
    coords = np.column_stack([rng.uniform(-40, 40, 40), rng.uniform(-40, 40, 40)])
    values = np.sin(coords[:, 0] / 12.0) + 0.5 * coords[:, 1] / 40.0 + 3.0
    query = np.array([[0.0, 0.0], [10.0, -5.0]])
    base = {"variogram_model": "spherical", "neighbor_count": 12, "min_neighbors": 3}
    isotropic = {
        "dimension": "2d",
        "azimuth_deg": 0.0,
        "major_scale": 1.0,
        "minor_scale": 1.0,
    }
    batch_iso = _predict(coords, values, query, {**base, "anisotropy": isotropic})
    batch_aniso = _predict(coords, values, query, {**base, "anisotropy": ANISOTROPY_2D})
    # 自动拟合只拿到 fit 传入的坐标，但距离空间必须是变换后的坐标
    range_iso = batch_iso.diagnostics["variogram"]["range"]
    range_aniso = batch_aniso.diagnostics["variogram"]["range"]
    assert range_iso != pytest.approx(range_aniso, rel=1e-3)
    assert not np.array_equal(batch_iso.values, batch_aniso.values)


def test_legacy_z_scale_and_professional_anisotropy_are_rejected_together():
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    interpolator = OrdinaryKrigingInterpolator()
    with pytest.raises(Exception):
        interpolator.validate_parameters(
            {"z_scale": 2.0, "anisotropy": ANISOTROPY_3D}, "3d"
        )
    # z_scale 保持默认 1 时专业各向异性合法；legacy z_scale 单独使用也合法
    ok = interpolator.validate_parameters({"anisotropy": ANISOTROPY_3D}, "3d")
    assert ok.anisotropy is not None
    legacy = interpolator.validate_parameters({"z_scale": 2.0}, "3d")
    assert legacy.anisotropy is None and legacy.z_scale == 2.0
    # spec 内部的 legacy_z_scale 归一化形式与默认 z_scale=1 共存合法
    normalized = interpolator.validate_parameters(
        {
            "anisotropy": {
                "dimension": "3d",
                "azimuth_deg": 0.0,
                "dip_deg": 0.0,
                "roll_deg": 0.0,
                "major_scale": 1.0,
                "minor_scale": 1.0,
                "vertical_scale": 1.0,
                "legacy_z_scale": 2.0,
            }
        },
        "3d",
    )
    assert normalized.anisotropy.legacy_z_scale == 2.0


def test_anisotropy_dimension_mismatch_rejected_at_validation():
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    interpolator = OrdinaryKrigingInterpolator()
    with pytest.raises(Exception):
        interpolator.validate_parameters({"anisotropy": ANISOTROPY_3D}, "2d")
    with pytest.raises(Exception):
        interpolator.validate_parameters({"anisotropy": ANISOTROPY_2D}, "3d")


def test_rotated_neighborhood_changes_inclusion():
    coords, values = _axis_fixture()
    query = np.array([[0.0, 0.0]])
    neighborhood = {
        "radii": [35.0, 5.0],
        "min_neighbors": 3,
        "sector_count": 1,
        "max_per_sector": 8,
        "max_neighbors": 24,
    }
    base = {**MANUAL, "min_neighbors": 3}
    along_x = _predict(
        coords, values, query,
        {**base, "neighborhood": {**neighborhood, "azimuth_deg": 0.0}},
    )
    along_y = _predict(
        coords, values, query,
        {**base, "neighborhood": {**neighborhood, "azimuth_deg": 90.0}},
    )
    assert not along_x.is_nodata.any() and not along_y.is_nodata.any()
    # 物理距离上的字面增广解：方位角 0 只含 X 轴三点，90 只含 Y 轴三点
    expected_x = _literal_ok_estimate(coords[:3], query[0], values[:3], 0.0, 1.0, 50.0)
    expected_y = _literal_ok_estimate(coords[3:], query[0], values[3:], 0.0, 1.0, 50.0)
    assert along_x.values[0] == pytest.approx(expected_x, abs=1e-10)
    assert along_y.values[0] == pytest.approx(expected_y, abs=1e-10)
    assert along_x.values[0] != pytest.approx(along_y.values[0])
    # 方差同样只建立在选中邻点上
    assert along_x.auxiliary["kriging_variance"][0] >= 0.0
    assert along_y.auxiliary["kriging_variance"][0] >= 0.0


def test_neighborhood_radii_physical_while_matrix_uses_z_scaled_distance():
    # B=(0,0,3) 在物理垂向半径 3.5 内（选择按物理坐标与物理半径）；
    # z_scale=2 后其 Kriging 矩阵距离为 6 —— 选择不被挤出，矩阵用缩放距离
    coords = np.array([[4.0, 0.0, 0.0], [0.0, 0.0, 3.0], [8.0, 0.0, 0.0]])
    values = np.array([0.0, 100.0, 50.0])
    query = np.array([[0.0, 0.0, 0.0]])
    batch = _predict(
        coords,
        values,
        query,
        {
            **MANUAL,
            "min_neighbors": 3,
            "z_scale": 2.0,
            "neighborhood": {
                "radii": [10.0, 10.0, 3.5],
                "azimuth_deg": 0.0,
                "dip_deg": 0.0,
                "roll_deg": 0.0,
                "min_neighbors": 3,
                "sector_count": 1,
                "max_per_sector": 8,
                "max_neighbors": 24,
            },
        },
        "3d",
    )
    assert not batch.is_nodata[0]
    assert batch.diagnostics["search_neighborhood_summary"]["inside_count_total"] == 3
    scaled = coords * np.array([1.0, 1.0, 2.0])
    expected = _literal_ok_estimate(scaled, np.zeros(3), values, 0.0, 1.0, 50.0)
    assert batch.values[0] == pytest.approx(expected, abs=1e-10)
    unscaled = _literal_ok_estimate(coords, np.zeros(3), values, 0.0, 1.0, 50.0)
    assert batch.values[0] != pytest.approx(unscaled, abs=1e-10)


def test_neighborhood_and_anisotropy_compose_with_bounded_diagnostics():
    # 选择按邻域自身旋转与物理半径（X 轴三点）；矩阵按各向异性变换后距离
    coords, values = _axis_fixture()
    query = np.array([[0.0, 0.0]])
    batch = _predict(
        coords,
        values,
        query,
        {
            **MANUAL,
            "min_neighbors": 3,
            "anisotropy": ANISOTROPY_2D,
            "neighborhood": {
                "radii": [35.0, 5.0],
                "azimuth_deg": 0.0,
                "min_neighbors": 3,
                "sector_count": 1,
                "max_per_sector": 8,
                "max_neighbors": 24,
            },
        },
    )
    assert not batch.is_nodata[0]
    coords_t = _literal_transform_2d(coords[:3], 30.0, 2.0, 0.5)
    query_t = _literal_transform_2d(query, 30.0, 2.0, 0.5)
    expected = _literal_ok_estimate(coords_t, query_t[0], values[:3], 0.0, 1.0, 50.0)
    assert batch.values[0] == pytest.approx(expected, abs=1e-10)
    # 诊断是有界聚合且可 JSON 序列化，变换指纹唯一披露
    diagnostics = batch.diagnostics
    summary = diagnostics["search_neighborhood_summary"]
    assert summary["inside_count_total"] == 3
    assert summary["neighbors_used_total"] == 3
    assert diagnostics["nodata_reason_counts"] == {}
    from geomodeling.modeling.anisotropy import (
        KrigingAnisotropySpec,
        build_kriging_transform,
    )

    spec = KrigingAnisotropySpec.model_validate(ANISOTROPY_2D)
    assert diagnostics["transform_fingerprint"] == build_kriging_transform(spec).fingerprint
    json.dumps(diagnostics)


def test_insufficient_neighbors_produce_nodata_with_reason_counts():
    coords, values = _axis_fixture()
    query = np.array([[0.0, 0.0], [1000.0, 1000.0]])  # 第二点远在椭球外
    batch = _predict(
        coords,
        values,
        query,
        {
            **MANUAL,
            "min_neighbors": 3,
            "neighborhood": {
                "radii": [35.0, 5.0],
                "min_neighbors": 3,
                "sector_count": 1,
                "max_per_sector": 8,
                "max_neighbors": 24,
            },
        },
    )
    # 整批不中断：近查询正常，远查询 NoData
    assert batch.is_nodata.tolist() == [False, True]
    assert np.isnan(batch.values[1])
    assert np.isnan(batch.auxiliary["kriging_variance"][1])
    assert np.isnan(batch.auxiliary["kriging_standard_deviation"][1])
    assert not batch.auxiliary["kriging_variance_used_lstsq"][1]
    assert batch.diagnostics["nodata_reason_counts"] == {"neighbors_insufficient": 1}


def test_neighborhood_dimension_mismatch_rejected_at_validation():
    from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator

    interpolator = OrdinaryKrigingInterpolator()
    radii_3d = {"radii": [10.0, 10.0, 10.0], "dip_deg": 0.0, "roll_deg": 0.0}
    with pytest.raises(Exception):
        interpolator.validate_parameters({"neighborhood": radii_3d}, "2d")
    with pytest.raises(Exception):
        interpolator.validate_parameters({"neighborhood": {"radii": [10.0, 10.0]}}, "3d")
