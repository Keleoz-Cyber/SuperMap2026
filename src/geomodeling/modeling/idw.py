"""Generic 2D/3D inverse-distance-weighted interpolation.

Neighborhood queries run on a SciPy cKDTree over linear coordinates.
Sample points are reproduced exactly (distance <= 1e-12); other targets
use 1/d**power weights over at most ``neighbor_count`` neighbors inside
``search_radius``. Targets with fewer than ``min_neighbors`` neighbors are
NoData — values are never fabricated. Prediction runs in bounded chunks
and checks the cooperative cancel flag before each chunk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from pydantic import Field
from scipy.spatial import cKDTree

from geomodeling.modeling.base import CancelFn, PredictionBatch
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import Algorithm, ContractModel, Dimension

PREDICTION_CHUNK_SIZE = 20_000
EXACT_DISTANCE = 1e-12
RUN_CANCELED = "RUN_CANCELED"


class IDWParameters(ContractModel):
    power: float = Field(default=2.0, gt=0, le=8)
    neighbor_count: int = Field(default=16, ge=1, le=128)
    search_radius: float | None = Field(default=None, gt=0)
    min_neighbors: int = Field(default=3, ge=1, le=32)


class IDWInterpolator:
    algorithm = Algorithm.IDW

    def validate_parameters(
        self, parameters: dict[str, Any], dimension: Dimension | str
    ) -> IDWParameters:
        Dimension(dimension)  # 维度合法性统一入口（2d/3d 均支持）
        return IDWParameters.model_validate(parameters or {})

    def fit(
        self,
        coordinates: np.ndarray,
        values: np.ndarray,
        parameters: IDWParameters,
    ) -> "_IDWFitted":
        coordinates = np.asarray(coordinates, dtype="float64")
        values = np.asarray(values, dtype="float64")
        if coordinates.shape[0] != values.shape[0]:
            raise PlatformError(
                "INTERPOLATOR_INPUT_MISMATCH",
                "训练坐标与属性数量不一致",
                {"coordinates": coordinates.shape[0], "values": values.shape[0]},
            )
        return _IDWFitted(tree=cKDTree(coordinates), values=values, parameters=parameters)


@dataclass(frozen=True)
class _IDWFitted:
    tree: cKDTree
    values: np.ndarray
    parameters: IDWParameters
    _canceled: bool = field(default=False, compare=False)

    def _predict_chunk(self, query: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
        params = self.parameters
        k = min(params.neighbor_count, len(self.values))
        if params.search_radius is not None:
            distances, indices = self.tree.query(
                query, k=k, distance_upper_bound=params.search_radius
            )
        else:
            distances, indices = self.tree.query(query, k=k)
        if k == 1:
            distances = distances[:, None]
            indices = indices[:, None]

        n_targets = query.shape[0]
        values = np.full(n_targets, np.nan)
        is_nodata = np.zeros(n_targets, dtype=bool)
        max_used = 0

        finite_mask = np.isfinite(distances)
        neighbor_counts = finite_mask.sum(axis=1)
        max_used = int(neighbor_counts.max()) if n_targets else 0

        ok = neighbor_counts >= params.min_neighbors
        exact = ok & (distances[:, 0] <= EXACT_DISTANCE) & finite_mask[:, 0]
        if exact.any():
            values[exact] = self.values[indices[exact, 0]]

        weighted = ok & ~exact
        if weighted.any():
            safe_distances = np.where(finite_mask, distances, np.inf)
            weights = 1.0 / np.power(safe_distances, params.power)
            weights[~finite_mask] = 0.0
            totals = weights.sum(axis=1)
            usable = weighted & (totals > 0)
            gathered = self.values[indices]
            estimates = (weights * gathered).sum(axis=1) / totals
            values[usable] = estimates[usable]
        is_nodata = ~np.isfinite(values)
        return values, is_nodata, max_used

    def predict(self, query: np.ndarray, *, cancel: CancelFn) -> PredictionBatch:
        query = np.asarray(query, dtype="float64")
        n = query.shape[0]
        values = np.full(n, np.nan)
        is_nodata = np.ones(n, dtype=bool)
        max_used = 0
        for start in range(0, n, PREDICTION_CHUNK_SIZE):
            if cancel():
                raise PlatformError(RUN_CANCELED, "任务已被取消", {"completed": start}, http_status=409)
            end = min(start + PREDICTION_CHUNK_SIZE, n)
            chunk_values, chunk_nodata, chunk_max = self._predict_chunk(query[start:end])
            values[start:end] = chunk_values
            is_nodata[start:end] = chunk_nodata
            max_used = max(max_used, chunk_max)
        return PredictionBatch(
            values=values,
            is_nodata=is_nodata,
            diagnostics={"max_neighbors_used": max_used, "n_targets": n},
        )
