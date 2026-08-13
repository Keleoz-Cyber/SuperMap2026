from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from geomodeling.modeling.base import PredictionBatch
from geomodeling.modeling.kriging_rf_residual import (
    KrigingRFResidualParameters,
    fit_kriging_rf_residual,
)
from geomodeling.modeling.random_forest import RandomForestSpatialInterpolator
from geomodeling.platform.errors import PlatformError


def _field(rows: int = 60):
    x = np.arange(rows, dtype="float64")
    points = np.column_stack((x, (x * 7) % 19, (x * 3) % 11))
    values = 0.2 * x + np.sin(x / 4.0)
    return points, values


@dataclass
class _SpyFitted:
    training: np.ndarray
    query_log: list[tuple[np.ndarray, np.ndarray]]

    def predict(self, query, *, cancel):
        query = np.asarray(query, dtype="float64")
        self.query_log.append((self.training.copy(), query.copy()))
        values = query[:, 0] * 0.2
        return PredictionBatch(
            values=values,
            is_nodata=np.zeros(len(query), dtype=bool),
            auxiliary={"kriging_standard_deviation": np.full(len(query), 0.25)},
        )


class _SpyKriging:
    def __init__(self):
        self.query_log: list[tuple[np.ndarray, np.ndarray]] = []

    def validate_parameters(self, parameters, dimension):
        return parameters

    def fit(self, coordinates, values, parameters):
        return _SpyFitted(np.asarray(coordinates), self.query_log)


def test_inner_kriging_oof_never_trains_on_its_residual_target():
    points, values = _field()
    spy = _SpyKriging()
    parameters = KrigingRFResidualParameters.model_validate(
        {"random_forest": {"n_estimators": 40, "random_state": 7}}
    )

    fitted = fit_kriging_rf_residual(
        points,
        values,
        parameters,
        kriging_interpolator=spy,
        residual_interpolator=RandomForestSpatialInterpolator(),
    )

    assert len(spy.query_log) == 3
    for training, validation in spy.query_log:
        training_rows = {tuple(row) for row in training}
        assert all(tuple(row) not in training_rows for row in validation)
    assert fitted.diagnostics["inner_fold_count"] == 3
    assert fitted.diagnostics["oof_residual_count"] == len(points)


def test_prediction_is_baseline_plus_residual_and_exposes_auxiliary_fields():
    points, values = _field()
    fitted = fit_kriging_rf_residual(
        points,
        values,
        KrigingRFResidualParameters.model_validate(
            {"random_forest": {"n_estimators": 40, "random_state": 7}}
        ),
        kriging_interpolator=_SpyKriging(),
        residual_interpolator=RandomForestSpatialInterpolator(),
    )
    query = points[:9] + 0.1

    batch = fitted.predict(query, cancel=lambda: False)

    baseline = batch.auxiliary["kriging_baseline"]
    correction = batch.auxiliary["residual_correction"]
    assert np.allclose(batch.values, baseline + correction)
    assert batch.auxiliary["model_dispersion"].shape == (9,)
    assert batch.auxiliary["kriging_standard_deviation"].shape == (9,)
    assert not batch.is_nodata.any()


def test_residual_fit_is_deterministic_for_fixed_seed():
    points, values = _field()
    parameters = KrigingRFResidualParameters.model_validate(
        {"random_forest": {"n_estimators": 40, "random_state": 19}}
    )
    first = fit_kriging_rf_residual(points, values, parameters, kriging_interpolator=_SpyKriging())
    second = fit_kriging_rf_residual(points, values, parameters, kriging_interpolator=_SpyKriging())
    query = points[10:20] + 0.15

    assert np.array_equal(
        first.predict(query, cancel=lambda: False).values,
        second.predict(query, cancel=lambda: False).values,
    )


def test_insufficient_spatial_groups_fail_closed():
    z = np.arange(60, dtype="float64")
    points = np.column_stack((np.zeros(60), np.zeros(60), z))
    values = z.copy()

    with pytest.raises(PlatformError) as caught:
        fit_kriging_rf_residual(
            points,
            values,
            KrigingRFResidualParameters.model_validate(
                {"random_forest": {"n_estimators": 40}}
            ),
            kriging_interpolator=_SpyKriging(),
        )
    assert caught.value.code == "ML_INNER_SPLIT_FAILED"

