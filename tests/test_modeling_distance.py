"""Task 8 tests: shared z_scale distance scaling helper."""

from __future__ import annotations

import numpy as np
import pytest

from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import Dimension


def test_distance_coordinates_scale_only_z_and_do_not_mutate():
    from geomodeling.modeling.distance import scale_distance_coordinates

    source = np.array([[1.0, 2.0, -10.0]])
    scaled = scale_distance_coordinates(source, z_scale=0.5)
    np.testing.assert_allclose(scaled, [[1.0, 2.0, -5.0]])
    np.testing.assert_allclose(source, [[1.0, 2.0, -10.0]])


def test_explicit_3d_dimension_scales_z_for_str_and_enum():
    from geomodeling.modeling.distance import scale_distance_coordinates

    source = np.array([[1.0, 2.0, -10.0], [3.0, 4.0, 5.0]])
    for dimension in ("3d", Dimension.THREE_D):
        scaled = scale_distance_coordinates(source, dimension=dimension, z_scale=2.0)
        np.testing.assert_allclose(scaled, [[1.0, 2.0, -20.0], [3.0, 4.0, 10.0]])


def test_2d_coordinates_ignore_z_scale_entirely():
    from geomodeling.modeling.distance import scale_distance_coordinates

    source = np.array([[1.0, 2.0], [3.0, 4.0]])
    for dimension in ("2d", Dimension.TWO_D):
        scaled = scale_distance_coordinates(source, dimension=dimension, z_scale=0.5)
        np.testing.assert_array_equal(scaled, source)
        assert scaled is not source  # 始终是副本，调用方可在其上继续计算


def test_z_scale_one_returns_equal_values():
    from geomodeling.modeling.distance import scale_distance_coordinates

    source = np.array([[1.0, 2.0, -10.0], [3.0, 4.0, 5.0]])
    scaled = scale_distance_coordinates(source, dimension="3d", z_scale=1.0)
    np.testing.assert_array_equal(scaled, source)


def test_invalid_z_scale_rejected():
    from geomodeling.modeling.distance import scale_distance_coordinates

    source = np.array([[1.0, 2.0, -10.0]])
    for bad in (0.0, -0.5, 20.5, float("inf"), float("-inf"), float("nan"), True, "0.5"):
        with pytest.raises(PlatformError) as exc:
            scale_distance_coordinates(source, dimension="3d", z_scale=bad)
        assert exc.value.code == "Z_SCALE_INVALID"


def test_z_scale_boundary_twenty_accepted():
    from geomodeling.modeling.distance import scale_distance_coordinates

    source = np.array([[1.0, 2.0, -1.0]])
    scaled = scale_distance_coordinates(source, dimension="3d", z_scale=20.0)
    np.testing.assert_allclose(scaled, [[1.0, 2.0, -20.0]])


def test_unknown_dimension_rejected():
    from geomodeling.modeling.distance import scale_distance_coordinates

    source = np.array([[1.0, 2.0, -10.0]])
    with pytest.raises(ValueError):
        scale_distance_coordinates(source, dimension="4d", z_scale=1.0)
