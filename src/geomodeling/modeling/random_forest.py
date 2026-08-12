"""Random-forest spatial regression using deterministic coordinate features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import sklearn
from pydantic import Field
from sklearn.ensemble import RandomForestRegressor

from geomodeling.modeling.base import CancelFn, PredictionBatch
from geomodeling.modeling.spatial_features import SpatialFeatureTransform
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import Algorithm, ContractModel, Dimension

PREDICTION_CHUNK_SIZE = 20_000
RUN_CANCELED = "RUN_CANCELED"


class RandomForestSpatialParameters(ContractModel):
    n_estimators: int = Field(default=160, ge=40, le=400)
    max_depth: int | None = Field(default=18, ge=4, le=40)
    min_samples_leaf: int = Field(default=2, ge=1, le=20)
    max_features: float = Field(default=0.8, ge=0.3, le=1.0)
    random_state: int = 20260813


class RandomForestSpatialInterpolator:
    algorithm = Algorithm.RANDOM_FOREST_SPATIAL

    def validate_parameters(
        self, parameters: dict[str, Any], dimension: Dimension | str
    ) -> RandomForestSpatialParameters:
        Dimension(dimension)
        return RandomForestSpatialParameters.model_validate(parameters or {})

    def fit(
        self,
        coordinates: np.ndarray,
        values: np.ndarray,
        parameters: RandomForestSpatialParameters,
    ) -> "_RandomForestSpatialFitted":
        points = np.asarray(coordinates, dtype="float64")
        target = np.asarray(values, dtype="float64")
        if points.ndim != 2 or points.shape[1] not in (2, 3):
            raise ValueError("训练坐标必须是 (n, 2) 或 (n, 3) 数组")
        if points.shape[0] != target.shape[0] or target.ndim != 1:
            raise ValueError("训练坐标与属性数量不一致")
        if points.shape[0] == 0 or not np.isfinite(points).all() or not np.isfinite(target).all():
            raise ValueError("随机森林训练数据必须非空且全部有限")
        transform = SpatialFeatureTransform.fit(points)
        model = RandomForestRegressor(
            n_estimators=parameters.n_estimators,
            max_depth=parameters.max_depth,
            min_samples_leaf=parameters.min_samples_leaf,
            max_features=parameters.max_features,
            random_state=parameters.random_state,
            n_jobs=1,
        )
        model.fit(transform.transform(points), target)
        return _RandomForestSpatialFitted(
            model=model,
            transform=transform,
            parameters=parameters,
            training_row_count=len(points),
        )


@dataclass(frozen=True)
class _RandomForestSpatialFitted:
    model: RandomForestRegressor
    transform: SpatialFeatureTransform
    parameters: RandomForestSpatialParameters
    training_row_count: int

    def predict(self, query: np.ndarray, *, cancel: CancelFn) -> PredictionBatch:
        points = np.asarray(query, dtype="float64")
        if points.ndim != 2 or points.shape[1] != len(self.transform.center):
            raise ValueError("查询坐标维度与训练坐标不一致")
        if not np.isfinite(points).all():
            raise ValueError("查询坐标必须全部有限")
        values = np.empty(len(points), dtype="float64")
        dispersion = np.empty(len(points), dtype="float64")
        for start in range(0, len(points), PREDICTION_CHUNK_SIZE):
            if cancel():
                raise PlatformError(
                    RUN_CANCELED,
                    "任务已被取消",
                    {"completed": start},
                    http_status=409,
                )
            stop = min(start + PREDICTION_CHUNK_SIZE, len(points))
            features = self.transform.transform(points[start:stop])
            tree_predictions = np.vstack([tree.predict(features) for tree in self.model.estimators_])
            values[start:stop] = tree_predictions.mean(axis=0)
            dispersion[start:stop] = tree_predictions.std(axis=0)
        is_nodata = ~np.isfinite(values)
        return PredictionBatch(
            values=values,
            is_nodata=is_nodata,
            diagnostics={
                "feature_version": self.transform.version,
                "feature_names": list(self.transform.feature_names),
                "sklearn_version": sklearn.__version__,
                "tree_count": len(self.model.estimators_),
                "training_row_count": self.training_row_count,
                "dispersion_semantics": "tree_prediction_standard_deviation",
            },
            auxiliary={"model_dispersion": dispersion},
        )

