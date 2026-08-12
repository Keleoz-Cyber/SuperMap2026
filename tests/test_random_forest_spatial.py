from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from geomodeling.modeling.random_forest import RandomForestSpatialInterpolator


def _training():
    rng = np.random.default_rng(17)
    points = rng.uniform(-2.0, 2.0, size=(80, 3))
    values = 2.0 * points[:, 0] - points[:, 1] + 0.5 * points[:, 2] ** 2
    return points, values


@pytest.mark.parametrize(
    "parameters",
    [
        {"n_estimators": 39},
        {"n_estimators": 401},
        {"max_depth": 3},
        {"min_samples_leaf": 0},
        {"max_features": 0.2},
        {"unexpected": True},
    ],
)
def test_random_forest_parameters_reject_out_of_contract_values(parameters):
    with pytest.raises(ValidationError):
        RandomForestSpatialInterpolator().validate_parameters(parameters, "3d")


def test_random_forest_prediction_is_repeatable_and_has_dispersion():
    points, values = _training()
    query = points[:12] + 0.03
    interpolator = RandomForestSpatialInterpolator()
    parameters = interpolator.validate_parameters(
        {"n_estimators": 40, "max_depth": 10, "random_state": 1234}, "3d"
    )

    first = interpolator.fit(points, values, parameters).predict(query, cancel=lambda: False)
    second = interpolator.fit(points, values, parameters).predict(query, cancel=lambda: False)

    assert np.array_equal(first.values, second.values)
    assert np.array_equal(first.auxiliary["model_dispersion"], second.auxiliary["model_dispersion"])
    assert first.values.shape == (12,)
    assert first.is_nodata.shape == (12,)
    assert not first.is_nodata.any()
    assert np.isfinite(first.values).all()
    assert np.isfinite(first.auxiliary["model_dispersion"]).all()
    assert (first.auxiliary["model_dispersion"] >= 0).all()
    assert first.diagnostics["feature_version"] == "spatial_features.v1"
    assert first.diagnostics["tree_count"] == 40
    assert first.diagnostics["training_row_count"] == 80
    assert first.diagnostics["dispersion_semantics"] == "tree_prediction_standard_deviation"


def test_random_forest_rejects_input_mismatch_and_nonfinite_values():
    interpolator = RandomForestSpatialInterpolator()
    params = interpolator.validate_parameters({}, "3d")
    with pytest.raises(ValueError):
        interpolator.fit(np.zeros((3, 3)), np.zeros(2), params)
    with pytest.raises(ValueError):
        interpolator.fit(np.array([[0.0, 0.0, np.nan]]), np.array([1.0]), params)


def test_random_forest_prediction_checks_cancellation_between_chunks():
    points, values = _training()
    interpolator = RandomForestSpatialInterpolator()
    params = interpolator.validate_parameters({"n_estimators": 40}, "3d")
    fitted = interpolator.fit(points, values, params)
    calls = 0

    def canceled():
        nonlocal calls
        calls += 1
        return True

    with pytest.raises(Exception) as caught:
        fitted.predict(np.zeros((25_000, 3)), cancel=canceled)
    assert getattr(caught.value, "code", None) == "RUN_CANCELED"
    assert calls == 1

