"""Leakage-safe ordinary-Kriging plus random-forest residual correction."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from pydantic import Field

from geomodeling.modeling.base import CancelFn, PredictionBatch
from geomodeling.modeling.kriging import KrigingParameters, OrdinaryKrigingInterpolator
from geomodeling.modeling.random_forest import (
    RandomForestSpatialInterpolator,
    RandomForestSpatialParameters,
)
from geomodeling.modeling.splits import build_spatial_splits
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import ContractModel, Dimension, SpatialValidationSpec

ML_INNER_SPLIT_FAILED = "ML_INNER_SPLIT_FAILED"
ML_RESIDUAL_COVERAGE_INSUFFICIENT = "ML_RESIDUAL_COVERAGE_INSUFFICIENT"


class KrigingRFResidualParameters(ContractModel):
    feature_version: Literal["spatial_features.v1"] = "spatial_features.v1"
    kriging: KrigingParameters = Field(default_factory=KrigingParameters)
    random_forest: RandomForestSpatialParameters = Field(
        default_factory=RandomForestSpatialParameters
    )
    inner_folds: int = Field(default=3, ge=3, le=5)
    min_oof_residuals: int = Field(default=30, ge=20, le=10_000)
    min_oof_coverage: float = Field(default=0.8, ge=0.5, le=1.0)
    inner_seed: int = 20260813


def _fingerprint(folds) -> str:
    payload = [
        {
            "fold": int(fold.index),
            "training": [int(value) for value in fold.training_indices],
            "validation": [int(value) for value in fold.validation_indices],
        }
        for fold in folds
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fit_kriging_rf_residual(
    coordinates: np.ndarray,
    values: np.ndarray,
    parameters: KrigingRFResidualParameters,
    *,
    kriging_interpolator=None,
    residual_interpolator=None,
) -> "KrigingRFResidualFitted":
    points = np.asarray(coordinates, dtype="float64")
    target = np.asarray(values, dtype="float64")
    if points.ndim != 2 or points.shape[1] not in (2, 3):
        raise ValueError("训练坐标必须是 (n, 2) 或 (n, 3) 数组")
    if target.ndim != 1 or len(points) != len(target):
        raise ValueError("训练坐标与属性数量不一致")
    if not len(points) or not np.isfinite(points).all() or not np.isfinite(target).all():
        raise ValueError("残差校正训练数据必须非空且全部有限")

    dimension = Dimension.THREE_D if points.shape[1] == 3 else Dimension.TWO_D
    kriging = kriging_interpolator or OrdinaryKrigingInterpolator()
    residual = residual_interpolator or RandomForestSpatialInterpolator()
    validation = SpatialValidationSpec(
        method="spatial_kfold",
        folds=parameters.inner_folds,
        seed=parameters.inner_seed,
    )
    try:
        folds = build_spatial_splits(points, dimension, validation)
    except PlatformError as exc:
        raise PlatformError(
            ML_INNER_SPLIT_FAILED,
            "训练数据的独立空间分组不足，无法生成折外克里金残差",
            {"cause": exc.code},
            http_status=409,
        ) from exc

    baseline_oof = np.full(len(points), np.nan, dtype="float64")
    for fold in folds:
        train = np.asarray(fold.training_indices, dtype="int64")
        validation_rows = np.asarray(fold.validation_indices, dtype="int64")
        kriging_parameters = kriging.validate_parameters(
            parameters.kriging.model_dump(mode="python"), dimension
        )
        fitted = kriging.fit(points[train], target[train], kriging_parameters)
        batch = fitted.predict(points[validation_rows], cancel=lambda: False)
        usable = ~batch.is_nodata & np.isfinite(batch.values)
        baseline_oof[validation_rows[usable]] = batch.values[usable]

    valid_residuals = np.isfinite(baseline_oof)
    residual_count = int(valid_residuals.sum())
    coverage = residual_count / len(points)
    if residual_count < parameters.min_oof_residuals or coverage < parameters.min_oof_coverage:
        raise PlatformError(
            ML_RESIDUAL_COVERAGE_INSUFFICIENT,
            "折外克里金残差覆盖不足，不能训练残差校正模型",
            {
                "oof_residual_count": residual_count,
                "training_row_count": len(points),
                "coverage": coverage,
            },
            http_status=409,
        )

    rf_parameters = residual.validate_parameters(
        parameters.random_forest.model_dump(mode="python"), dimension
    )
    residual_values = target[valid_residuals] - baseline_oof[valid_residuals]
    residual_fitted = residual.fit(points[valid_residuals], residual_values, rf_parameters)
    final_kriging_parameters = kriging.validate_parameters(
        parameters.kriging.model_dump(mode="python"), dimension
    )
    baseline_fitted = kriging.fit(points, target, final_kriging_parameters)
    diagnostics = {
        "inner_fold_count": len(folds),
        "inner_validation_fingerprint": _fingerprint(folds),
        "oof_residual_count": residual_count,
        "oof_residual_coverage": coverage,
        "training_row_count": len(points),
        "residual_target_semantics": "observed_minus_out_of_fold_kriging",
    }
    return KrigingRFResidualFitted(
        baseline=baseline_fitted,
        residual=residual_fitted,
        diagnostics=diagnostics,
    )


@dataclass(frozen=True)
class KrigingRFResidualFitted:
    baseline: Any
    residual: Any
    diagnostics: dict[str, Any]

    def predict(self, query: np.ndarray, *, cancel: CancelFn) -> PredictionBatch:
        baseline = self.baseline.predict(query, cancel=cancel)
        correction = self.residual.predict(query, cancel=cancel)
        values = baseline.values + correction.values
        is_nodata = (
            baseline.is_nodata
            | correction.is_nodata
            | ~np.isfinite(values)
        )
        values = np.where(is_nodata, np.nan, values)
        auxiliary = {
            "kriging_baseline": np.where(is_nodata, np.nan, baseline.values),
            "residual_correction": np.where(is_nodata, np.nan, correction.values),
            "model_dispersion": np.where(
                is_nodata,
                np.nan,
                correction.auxiliary["model_dispersion"],
            ),
        }
        native_std = baseline.auxiliary.get("kriging_standard_deviation")
        if native_std is not None:
            auxiliary["kriging_standard_deviation"] = np.where(
                is_nodata, np.nan, native_std
            )
        return PredictionBatch(
            values=values,
            is_nodata=is_nodata,
            diagnostics={
                **self.diagnostics,
                "baseline": baseline.diagnostics,
                "residual_model": correction.diagnostics,
            },
            auxiliary=auxiliary,
        )
