from __future__ import annotations

import numpy as np

from geomodeling.modeling.spatial_features import FEATURE_VERSION, SpatialFeatureTransform


def test_three_dimensional_feature_columns_are_stable_and_finite():
    training = np.array([[0.0, 10.0, 2.0], [4.0, 14.0, 6.0], [8.0, 18.0, 10.0]])

    transform = SpatialFeatureTransform.fit(training)
    features = transform.transform(training)

    assert FEATURE_VERSION == "spatial_features.v1"
    assert transform.feature_names == (
        "x",
        "y",
        "z",
        "radius",
        "xy",
        "xz",
        "yz",
        "x2",
        "y2",
        "z2",
    )
    assert features.shape == (3, 10)
    assert np.isfinite(features).all()


def test_two_dimensional_feature_columns_omit_z_terms():
    transform = SpatialFeatureTransform.fit(np.array([[0.0, 0.0], [2.0, 4.0]]))

    assert transform.feature_names == ("x", "y", "radius", "xy", "x2", "y2")
    assert transform.transform(np.array([[1.0, 2.0]])).shape == (1, 6)


def test_zero_span_axis_is_safe_and_deterministic():
    training = np.array([[1.0, 0.0, 5.0], [1.0, 2.0, 5.0], [1.0, 4.0, 5.0]])

    first = SpatialFeatureTransform.fit(training)
    second = SpatialFeatureTransform.fit(training.copy())

    assert np.array_equal(first.center, second.center)
    assert np.array_equal(first.scale, second.scale)
    assert np.array_equal(first.transform(training), second.transform(training))
    assert np.isfinite(first.transform(training)).all()


def test_query_coordinates_do_not_change_training_normalization():
    training = np.array([[0.0, 0.0, 0.0], [10.0, 20.0, 30.0]])
    transform = SpatialFeatureTransform.fit(training)
    center_before = transform.center.copy()
    scale_before = transform.scale.copy()

    far_query = transform.transform(np.array([[1_000_000.0, -1_000_000.0, 500_000.0]]))

    assert np.array_equal(transform.center, center_before)
    assert np.array_equal(transform.scale, scale_before)
    assert abs(far_query[0, 0]) > 1000


def test_invalid_shape_or_nonfinite_coordinates_are_rejected():
    for coordinates in (
        np.array([1.0, 2.0, 3.0]),
        np.array([[0.0, np.nan]]),
        np.empty((0, 3)),
        np.zeros((2, 4)),
    ):
        try:
            SpatialFeatureTransform.fit(coordinates)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid coordinates must be rejected")

