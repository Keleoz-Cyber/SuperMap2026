"""Task 5: canonical kriging anisotropy transforms (design §6.3, §7.2).

约定锚点：行向量右乘 ``apply(x) = x @ matrix.T``，``matrix = S @ R.T``，
与列向量形式 ``x' = S Rᵀ x`` 数值一致；``S = diag(1/a_major, 1/a_minor,
1/a_vertical)``。方位角在 XY 平面内从 +X 朝 +Y，倾角从水平面朝 +Z，3D
滚转绕主轴。legacy ``z_scale`` 归一化为 3D identity 旋转 +
``diag[1, 1, z_scale]``，与专业各向异性形式在同一 spec 内互斥；同一
Kriging 候选的经验半变异函数距离、协方差距离、经验误差距离必须使用
同一变换指纹。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from geomodeling.modeling.anisotropy import (
    ANISOTROPY_INVALID,
    KrigingAnisotropySpec,
    SpatialTransform,
    build_kriging_transform,
)
from geomodeling.modeling.distance import scale_distance_coordinates
from geomodeling.platform.errors import PlatformError

POINTS_2D = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [-3.5, 2.25]])
POINTS_3D = np.array(
    [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        [-3.5, 2.25, 7.75],
    ]
)


def _spec_3d(**overrides) -> KrigingAnisotropySpec:
    base = dict(
        dimension="3d",
        azimuth_deg=0.0,
        dip_deg=0.0,
        roll_deg=0.0,
        major_scale=1.0,
        minor_scale=1.0,
        vertical_scale=1.0,
    )
    return KrigingAnisotropySpec(**{**base, **overrides})


# ---------------------------------------------------------------------------
# 恒等与 2D 锚点（实施计划 Task 5 给定示例）
# ---------------------------------------------------------------------------


def test_identity_transform_matches_physical_coordinates_exactly():
    spec = KrigingAnisotropySpec.isotropic(dimension="3d")
    transform = build_kriging_transform(spec)
    np.testing.assert_array_equal(transform.apply(POINTS_3D), POINTS_3D)


def test_isotropic_2d_transform_matches_physical_coordinates_exactly():
    transform = build_kriging_transform(KrigingAnisotropySpec.isotropic(dimension="2d"))
    np.testing.assert_array_equal(transform.apply(POINTS_2D), POINTS_2D)


def test_2d_ninety_degree_rotation_and_scale():
    spec = KrigingAnisotropySpec(
        dimension="2d", azimuth_deg=90, dip_deg=None, roll_deg=None,
        major_scale=1, minor_scale=2, vertical_scale=None,
    )
    actual = build_kriging_transform(spec).apply(np.array([[1.0, 0.0]]))
    np.testing.assert_allclose(actual, [[0.0, -0.5]], atol=1e-12)


def test_2d_zero_azimuth_scales_axes_without_rotation():
    spec = KrigingAnisotropySpec(
        dimension="2d", azimuth_deg=0.0, major_scale=2.0, minor_scale=4.0
    )
    actual = build_kriging_transform(spec).apply(np.array([[2.0, 8.0]]))
    np.testing.assert_allclose(actual, [[1.0, 2.0]], atol=1e-12)


def test_points_at_one_range_along_each_axis_become_equidistant():
    """沿主/次轴各走一个 range，变换后距离同为 1（各向异性距离的归一化语义）。"""

    spec = KrigingAnisotropySpec(
        dimension="2d", azimuth_deg=45.0, major_scale=3.0, minor_scale=1.0
    )
    transform = build_kriging_transform(spec)
    angle = math.radians(45.0)
    major_point = 3.0 * np.array([[math.cos(angle), math.sin(angle)]])
    minor_point = 1.0 * np.array([[-math.sin(angle), math.cos(angle)]])
    actual = transform.apply(np.vstack([major_point, minor_point]))
    np.testing.assert_allclose(actual, [[1.0, 0.0], [0.0, 1.0]], atol=1e-12)


# ---------------------------------------------------------------------------
# 3D 旋转：正交性、行列式、轴映射语义、复合顺序
# ---------------------------------------------------------------------------


def test_3d_rotation_only_matrix_is_orthonormal_with_unit_determinant():
    identity = np.eye(3)
    for azimuth, dip, roll in (
        (0.0, 0.0, 0.0),
        (30.0, -20.0, 45.0),
        (179.5, 90.0, -180.0),
        (75.0, -90.0, 179.0),
    ):
        spec = _spec_3d(azimuth_deg=azimuth, dip_deg=dip, roll_deg=roll)
        matrix = build_kriging_transform(spec).matrix
        np.testing.assert_allclose(matrix.T @ matrix, identity, atol=1e-12)
        assert float(np.linalg.det(matrix)) == pytest.approx(1.0, abs=1e-12)


def test_3d_dip_ninety_tilts_major_axis_to_positive_z():
    """倾角从水平面朝 +Z：dip=90° 时物理 +Z 成为主轴方向。"""

    transform = build_kriging_transform(_spec_3d(azimuth_deg=0.0, dip_deg=90.0, roll_deg=0.0))
    np.testing.assert_allclose(transform.apply(np.array([[0.0, 0.0, 1.0]])), [[1.0, 0.0, 0.0]], atol=1e-12)
    np.testing.assert_allclose(transform.apply(np.array([[1.0, 0.0, 0.0]])), [[0.0, 0.0, -1.0]], atol=1e-12)
    np.testing.assert_allclose(transform.apply(np.array([[0.0, 1.0, 0.0]])), [[0.0, 1.0, 0.0]], atol=1e-12)


def test_3d_roll_rotates_minor_and_vertical_axes_around_major():
    """滚转绕主轴：azimuth=dip=0 时主轴为 +X，roll=90° 使 +Z 成为次轴方向。"""

    transform = build_kriging_transform(_spec_3d(azimuth_deg=0.0, dip_deg=0.0, roll_deg=90.0))
    np.testing.assert_allclose(transform.apply(np.array([[1.0, 0.0, 0.0]])), [[1.0, 0.0, 0.0]], atol=1e-12)
    np.testing.assert_allclose(transform.apply(np.array([[0.0, 1.0, 0.0]])), [[0.0, 0.0, -1.0]], atol=1e-12)
    np.testing.assert_allclose(transform.apply(np.array([[0.0, 0.0, 1.0]])), [[0.0, 1.0, 0.0]], atol=1e-12)


def test_3d_azimuth_shares_2d_convention():
    """δ=0/ρ=0 时 3D 方位角约定与 2D 一致（主轴 +X→+Y 旋转 90° 后为 +Y）。"""

    spec = _spec_3d(azimuth_deg=90.0, major_scale=1.0, minor_scale=2.0, vertical_scale=4.0)
    actual = build_kriging_transform(spec).apply(np.array([[1.0, 0.0, 8.0]]))
    np.testing.assert_allclose(actual, [[0.0, -0.5, 2.0]], atol=1e-12)


def test_3d_composition_matches_explicit_euler_product():
    """复合顺序锚点：R = Rz(azimuth) · Ry(−dip) · Rx(roll)，matrix = S @ R.T。"""

    azimuth, dip, roll = 30.0, -20.0, 45.0
    spec = _spec_3d(
        azimuth_deg=azimuth, dip_deg=dip, roll_deg=roll,
        major_scale=3.0, minor_scale=1.5, vertical_scale=0.75,
    )
    a, d, r = math.radians(azimuth), math.radians(dip), math.radians(roll)
    rz = np.array(
        [[math.cos(a), -math.sin(a), 0.0], [math.sin(a), math.cos(a), 0.0], [0.0, 0.0, 1.0]]
    )
    ry = np.array(
        [[math.cos(d), 0.0, -math.sin(d)], [0.0, 1.0, 0.0], [math.sin(d), 0.0, math.cos(d)]]
    )
    rx = np.array(
        [[1.0, 0.0, 0.0], [0.0, math.cos(r), -math.sin(r)], [0.0, math.sin(r), math.cos(r)]]
    )
    rotation = rz @ ry @ rx
    expected = np.diag([1.0 / 3.0, 1.0 / 1.5, 1.0 / 0.75]) @ rotation.T
    np.testing.assert_allclose(build_kriging_transform(spec).matrix, expected, atol=1e-12)


def test_transform_matrix_has_finite_nonzero_determinant_and_is_invertible():
    spec = _spec_3d(
        azimuth_deg=30.0, dip_deg=-20.0, roll_deg=45.0,
        major_scale=2.0, minor_scale=0.5, vertical_scale=4.0,
    )
    transform = build_kriging_transform(spec)
    determinant = float(np.linalg.det(transform.matrix))
    assert math.isfinite(determinant) and determinant > 0.0
    assert determinant == pytest.approx(1.0 / (2.0 * 0.5 * 4.0), rel=1e-12)
    inverse = np.linalg.inv(transform.matrix)
    recovered = transform.apply(POINTS_3D) @ inverse.T
    np.testing.assert_allclose(recovered, POINTS_3D, atol=1e-12)


# ---------------------------------------------------------------------------
# apply 纯度与输入保护
# ---------------------------------------------------------------------------


def test_apply_never_mutates_input_coordinates():
    spec = _spec_3d(azimuth_deg=30.0, dip_deg=-20.0, roll_deg=45.0,
                    major_scale=2.0, minor_scale=1.0, vertical_scale=0.5)
    transform = build_kriging_transform(spec)
    int_source = np.array([[1, 2, 3], [4, 5, 6]])
    int_snapshot = int_source.copy()
    transform.apply(int_source)
    np.testing.assert_array_equal(int_source, int_snapshot)
    float_source = POINTS_3D.copy()
    transform.apply(float_source)
    np.testing.assert_array_equal(float_source, POINTS_3D)


def test_apply_returns_new_array_matching_matrix_shape():
    transform = build_kriging_transform(KrigingAnisotropySpec.isotropic(dimension="2d"))
    assert isinstance(transform, SpatialTransform)
    assert transform.matrix.shape == (2, 2)
    result = transform.apply(POINTS_2D)
    assert result is not POINTS_2D
    assert result.shape == POINTS_2D.shape
    assert result.dtype == np.dtype("float64")


def test_spatial_transform_is_frozen():
    transform = build_kriging_transform(KrigingAnisotropySpec.isotropic(dimension="3d"))
    with pytest.raises(AttributeError):
        transform.fingerprint = "tampered"


# ---------------------------------------------------------------------------
# legacy z_scale 归一化（v0.5 语义，仅 3D）
# ---------------------------------------------------------------------------


def test_legacy_z_scale_normalizes_to_identity_rotation_diagonal():
    transform = build_kriging_transform(KrigingAnisotropySpec.from_legacy_z_scale(2.0))
    np.testing.assert_array_equal(transform.matrix, np.diag([1.0, 1.0, 2.0]))
    legacy = scale_distance_coordinates(POINTS_3D, dimension="3d", z_scale=2.0)
    np.testing.assert_array_equal(transform.apply(POINTS_3D), legacy)


def test_legacy_z_scale_one_matches_isotropic_distance_bitwise():
    legacy = build_kriging_transform(KrigingAnisotropySpec.from_legacy_z_scale(1.0))
    isotropic = build_kriging_transform(KrigingAnisotropySpec.isotropic(dimension="3d"))
    np.testing.assert_array_equal(legacy.apply(POINTS_3D), POINTS_3D)
    np.testing.assert_array_equal(legacy.apply(POINTS_3D), isotropic.apply(POINTS_3D))


# ---------------------------------------------------------------------------
# 变换指纹（canonical JSON → sha256 短码）
# ---------------------------------------------------------------------------


def test_fingerprint_is_deterministic_for_identical_specs():
    first = build_kriging_transform(KrigingAnisotropySpec.isotropic(dimension="3d"))
    second = build_kriging_transform(KrigingAnisotropySpec.isotropic(dimension="3d"))
    assert first.fingerprint == second.fingerprint
    assert len(first.fingerprint) == 16
    assert all(char in "0123456789abcdef" for char in first.fingerprint)


def test_fingerprint_changes_with_rotation_or_scale():
    fingerprints = {
        build_kriging_transform(spec).fingerprint
        for spec in (
            _spec_3d(),
            _spec_3d(azimuth_deg=30.0),
            _spec_3d(dip_deg=15.0),
            _spec_3d(roll_deg=15.0),
            _spec_3d(major_scale=2.0),
        )
    }
    assert len(fingerprints) == 5


def test_fingerprint_binds_spec_not_only_matrix():
    """legacy z_scale=0.5 与 vertical_scale=2 矩阵逐位相同，但 spec 不同 → 指纹不同。"""

    legacy = build_kriging_transform(KrigingAnisotropySpec.from_legacy_z_scale(0.5))
    professional = build_kriging_transform(_spec_3d(vertical_scale=2.0))
    np.testing.assert_array_equal(legacy.matrix, professional.matrix)
    assert legacy.fingerprint != professional.fingerprint


# ---------------------------------------------------------------------------
# spec 契约校验（契约边界拒绝不可能的组合）
# ---------------------------------------------------------------------------


def test_isotropic_factory_populates_dimension_defaults():
    iso2 = KrigingAnisotropySpec.isotropic(dimension="2d")
    assert (iso2.dip_deg, iso2.roll_deg, iso2.vertical_scale) == (None, None, None)
    assert iso2.azimuth_deg == 0.0 and iso2.major_scale == 1.0 and iso2.minor_scale == 1.0
    iso3 = KrigingAnisotropySpec.isotropic(dimension="3d")
    assert (iso3.dip_deg, iso3.roll_deg, iso3.vertical_scale) == (0.0, 0.0, 1.0)
    assert iso3.legacy_z_scale is None


def test_2d_rejects_dip_roll_vertical_scale_and_legacy_z_scale():
    base = dict(dimension="2d", azimuth_deg=0.0, major_scale=1.0, minor_scale=1.0)
    for overrides in (
        {"dip_deg": 10.0},
        {"roll_deg": 10.0},
        {"vertical_scale": 2.0},
        {"legacy_z_scale": 2.0},
    ):
        with pytest.raises(ValueError):
            KrigingAnisotropySpec(**base, **overrides)


def test_3d_requires_explicit_dip_roll_and_vertical_scale():
    with pytest.raises(ValueError):
        KrigingAnisotropySpec(dimension="3d", azimuth_deg=0.0, major_scale=1.0, minor_scale=1.0)
    with pytest.raises(ValueError):
        KrigingAnisotropySpec(
            dimension="3d", azimuth_deg=0.0, dip_deg=0.0, roll_deg=0.0,
            major_scale=1.0, minor_scale=1.0,
        )


def test_azimuth_range_is_zero_inclusive_180_exclusive():
    KrigingAnisotropySpec(dimension="2d", azimuth_deg=0.0, major_scale=1.0, minor_scale=1.0)
    KrigingAnisotropySpec(dimension="2d", azimuth_deg=179.999, major_scale=1.0, minor_scale=1.0)
    for bad in (180.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            KrigingAnisotropySpec(
                dimension="2d", azimuth_deg=bad, major_scale=1.0, minor_scale=1.0
            )


def test_dip_and_roll_ranges():
    _spec_3d(dip_deg=90.0, roll_deg=180.0)
    _spec_3d(dip_deg=-90.0, roll_deg=-180.0)
    for overrides in (
        {"dip_deg": 90.5},
        {"dip_deg": -90.5},
        {"roll_deg": 180.5},
        {"roll_deg": -180.5},
    ):
        with pytest.raises(ValueError):
            _spec_3d(**overrides)


def test_scales_must_be_finite_and_positive():
    for field in ("major_scale", "minor_scale", "vertical_scale"):
        for bad in (0.0, -1.0, float("nan"), float("inf")):
            with pytest.raises(ValueError):
                _spec_3d(**{field: bad})


def test_legacy_z_scale_never_combines_with_rotation_or_scales():
    with pytest.raises(ValueError):
        _spec_3d(azimuth_deg=30.0, legacy_z_scale=2.0)
    with pytest.raises(ValueError):
        _spec_3d(dip_deg=10.0, legacy_z_scale=2.0)
    with pytest.raises(ValueError):
        _spec_3d(roll_deg=10.0, legacy_z_scale=2.0)
    with pytest.raises(ValueError):
        _spec_3d(vertical_scale=2.0, legacy_z_scale=2.0)


def test_legacy_z_scale_follows_v05_bounds():
    KrigingAnisotropySpec.from_legacy_z_scale(20.0)
    for bad in (0.0, -1.0, 20.5, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            KrigingAnisotropySpec.from_legacy_z_scale(bad)


# ---------------------------------------------------------------------------
# 结构化失败（绕过契约层时的构造防线）
# ---------------------------------------------------------------------------


def test_non_finite_scale_raises_structured_anisotropy_invalid():
    spec = KrigingAnisotropySpec.model_construct(
        dimension="3d", azimuth_deg=0.0, dip_deg=0.0, roll_deg=0.0,
        major_scale=float("nan"), minor_scale=1.0, vertical_scale=1.0,
        legacy_z_scale=None,
    )
    with pytest.raises(PlatformError) as exc:
        build_kriging_transform(spec)
    assert exc.value.code == ANISOTROPY_INVALID


def test_zero_scale_raises_structured_anisotropy_invalid():
    spec = KrigingAnisotropySpec.model_construct(
        dimension="2d", azimuth_deg=0.0, dip_deg=None, roll_deg=None,
        major_scale=0.0, minor_scale=1.0, vertical_scale=None, legacy_z_scale=None,
    )
    with pytest.raises(PlatformError) as exc:
        build_kriging_transform(spec)
    assert exc.value.code == ANISOTROPY_INVALID
