"""Generic 2D/3D inverse-distance-weighted interpolation.

Neighborhood queries run on a SciPy cKDTree over linear coordinates.
Sample points are reproduced exactly (distance <= 1e-12); other targets
use 1/d**power weights over at most ``neighbor_count`` neighbors inside
``search_radius``. Targets with fewer than ``min_neighbors`` neighbors are
NoData — values are never fabricated. Prediction runs in bounded chunks
and checks the cooperative cancel flag before each chunk.

``z_scale`` (3D only) scales the z column by a validated factor before the
KD-tree is built and before queries are issued, so distances are computed
on ``(x, y, z × z_scale)``; physical training and grid coordinates are
never written back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from pydantic import Field
from scipy.spatial import cKDTree

from geomodeling.modeling.base import CancelFn, PredictionBatch
from geomodeling.modeling.distance import scale_distance_coordinates
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
    z_scale: float = Field(default=1.0, gt=0, le=20)


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
        dimension = Dimension.THREE_D if coordinates.shape[1] == 3 else Dimension.TWO_D
        # KD-tree 建在缩放副本上；传入的训练坐标保持物理坐标不被改写
        scaled = scale_distance_coordinates(
            coordinates, dimension=dimension, z_scale=parameters.z_scale
        )
        return _IDWFitted(
            tree=cKDTree(scaled), values=values, parameters=parameters, dimension=dimension
        )


@dataclass(frozen=True)
class _IDWFitted:
    tree: cKDTree
    values: np.ndarray
    parameters: IDWParameters
    dimension: Dimension
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
            # 半径搜索下缺失邻居的索引为 tree.n（越界哨兵），取数前先裁剪为合法下标
            gathered = self.values[np.where(finite_mask, indices, 0)]
            estimates = (weights * gathered).sum(axis=1) / totals
            values[usable] = estimates[usable]
        is_nodata = ~np.isfinite(values)
        return values, is_nodata, max_used

    def predict(self, query: np.ndarray, *, cancel: CancelFn) -> PredictionBatch:
        # 查询点按同一规则缩放到距离空间；调用方持有的物理坐标不被改写
        query = scale_distance_coordinates(
            query, dimension=self.dimension, z_scale=self.parameters.z_scale
        )
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
            diagnostics={
                "max_neighbors_used": max_used,
                "n_targets": n,
                "z_scale": self.parameters.z_scale,
            },
        )
