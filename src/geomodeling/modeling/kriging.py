"""Local ordinary Kriging with augmented-system weights and safe fallbacks.

Predictions solve the augmented ordinary-Kriging system (weights sum to
one) over at most ``neighbor_count`` neighbors inside ``search_radius``.
Singular neighborhoods fall back to least squares and are counted;
targets with fewer than ``min_neighbors`` neighbors are NoData. Manual
variogram mode requires a complete nugget/sill/range triple with sill
(total sill) strictly greater than nugget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from pydantic import Field, model_validator
from scipy.spatial import cKDTree

from geomodeling.modeling.base import CancelFn, PredictionBatch
from geomodeling.modeling.variogram import VariogramModel, fit_variogram, semivariance
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import Algorithm, ContractModel, Dimension

PREDICTION_CHUNK_SIZE = 20_000
RUN_CANCELED = "RUN_CANCELED"


class KrigingParameters(ContractModel):
    variogram_model: Literal["spherical", "exponential", "gaussian"] = "spherical"
    variogram_mode: Literal["auto", "manual"] = "auto"
    nugget: float | None = Field(default=None, ge=0)
    sill: float | None = Field(default=None, gt=0)
    range: float | None = Field(default=None, gt=0)
    neighbor_count: int = Field(default=24, ge=4, le=128)
    search_radius: float | None = Field(default=None, gt=0)
    min_neighbors: int = Field(default=4, ge=3, le=32)

    @model_validator(mode="after")
    def _check_manual(self) -> "KrigingParameters":
        if self.variogram_mode == "manual":
            missing = [
                name
                for name, val in (("nugget", self.nugget), ("sill", self.sill), ("range", self.range))
                if val is None
            ]
            if missing:
                raise ValueError(f"manual 变异函数模式要求完整三元组，缺少：{missing}")
            if self.sill is not None and self.nugget is not None and self.sill <= self.nugget:
                raise ValueError("manual 模式要求 sill（总基台值）严格大于 nugget")
        return self


def _ordinary_kriging_weights(
    neighbors: np.ndarray,
    target: np.ndarray,
    model: VariogramModel,
) -> tuple[np.ndarray, bool]:
    """Solve the augmented OK system; returns (weights, used_lstsq)."""

    n = len(neighbors)
    distances = np.linalg.norm(neighbors[None, :, :] - neighbors[:, None, :], axis=2)
    k_mat = semivariance(distances, model.model, model.nugget, model.partial_sill, model.range)
    rhs = semivariance(
        np.linalg.norm(neighbors - target[None, :], axis=1),
        model.model, model.nugget, model.partial_sill, model.range,
    )
    system = np.zeros((n + 1, n + 1))
    system[:n, :n] = k_mat
    system[:n, n] = 1.0
    system[n, :n] = 1.0
    right = np.concatenate([rhs, [1.0]])
    try:
        solution = np.linalg.solve(system, right)
        return solution[:n], False
    except np.linalg.LinAlgError:
        solution, *_ = np.linalg.lstsq(system, right, rcond=None)
        return solution[:n], True


class OrdinaryKrigingInterpolator:
    algorithm = Algorithm.ORDINARY_KRIGING

    def validate_parameters(
        self, parameters: dict[str, Any], dimension: Dimension | str
    ) -> KrigingParameters:
        Dimension(dimension)
        return KrigingParameters.model_validate(parameters or {})

    def fit(
        self,
        coordinates: np.ndarray,
        values: np.ndarray,
        parameters: KrigingParameters,
    ) -> "_KrigingFitted":
        coordinates = np.asarray(coordinates, dtype="float64")
        values = np.asarray(values, dtype="float64")
        if coordinates.shape[0] != values.shape[0]:
            raise PlatformError(
                "INTERPOLATOR_INPUT_MISMATCH",
                "训练坐标与属性数量不一致",
                {"coordinates": coordinates.shape[0], "values": values.shape[0]},
            )
        if parameters.variogram_mode == "auto":
            # 自动拟合只使用传入的训练折数据；调用方（折分 runner）保证不泄验证行
            model = fit_variogram(coordinates, values, parameters.variogram_model)
        else:
            model = VariogramModel(
                model=parameters.variogram_model,
                nugget=float(parameters.nugget),
                partial_sill=float(parameters.sill - parameters.nugget),
                range=float(parameters.range),
            )
        return _KrigingFitted(tree=cKDTree(coordinates), values=values, model=model, parameters=parameters)


@dataclass(frozen=True)
class _KrigingFitted:
    tree: cKDTree
    values: np.ndarray
    model: VariogramModel
    parameters: KrigingParameters
    _canceled: bool = field(default=False, compare=False)

    def _predict_chunk(
        self, query: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, int, int]:
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
        max_used = 0
        singular_fallbacks = 0
        finite_mask = np.isfinite(distances)
        neighbor_counts = finite_mask.sum(axis=1)
        max_used = int(neighbor_counts.max()) if n_targets else 0

        for row in range(n_targets):
            usable = finite_mask[row]
            if usable.sum() < params.min_neighbors:
                continue
            neighbor_idx = indices[row, usable]
            neighbors = self.tree.data[neighbor_idx]
            weights, used_lstsq = _ordinary_kriging_weights(neighbors, query[row], self.model)
            singular_fallbacks += int(used_lstsq)
            estimates = float(np.dot(weights, self.values[neighbor_idx]))
            if np.isfinite(estimates):
                values[row] = estimates
        is_nodata = ~np.isfinite(values)
        return values, is_nodata, max_used, singular_fallbacks

    def predict(self, query: np.ndarray, *, cancel: CancelFn) -> PredictionBatch:
        query = np.asarray(query, dtype="float64")
        n = query.shape[0]
        values = np.full(n, np.nan)
        is_nodata = np.ones(n, dtype=bool)
        max_used = 0
        singular_fallbacks = 0
        for start in range(0, n, PREDICTION_CHUNK_SIZE):
            if cancel():
                raise PlatformError(RUN_CANCELED, "任务已被取消", {"completed": start}, http_status=409)
            end = min(start + PREDICTION_CHUNK_SIZE, n)
            chunk_values, chunk_nodata, chunk_max, chunk_singular = self._predict_chunk(query[start:end])
            values[start:end] = chunk_values
            is_nodata[start:end] = chunk_nodata
            max_used = max(max_used, chunk_max)
            singular_fallbacks += chunk_singular
        return PredictionBatch(
            values=values,
            is_nodata=is_nodata,
            diagnostics={
                "max_neighbors_used": max_used,
                "singular_fallback_count": singular_fallbacks,
                "variogram": {
                    "model": self.model.model,
                    "nugget": self.model.nugget,
                    "partial_sill": self.model.partial_sill,
                    "range": self.model.range,
                },
            },
        )
