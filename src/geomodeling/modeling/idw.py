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

``neighborhood``（可选，设计 §8 的专业搜索邻域）：为 None 时上述向量化
cKDTree 路径逐位不动。给出时每个查询点改走
``modeling.neighborhood.select_neighbors`` 的旋转椭圆/椭球扇区选择 —
邻域只决定哪些点进入候选集合和扇区（按物理坐标与物理半径），IDW 权重
继续使用 legacy ``(x, y, z × z_scale)`` 距离，绝不用椭球归一化距离
（设计 §7.2 末段）。选择不足 ``min_neighbors`` 的查询为 NoData（整批
不中断），原因聚合计入 ``diagnostics["nodata_reason_counts"]``；
``diagnostics["search_neighborhood_summary"]`` 保存有界聚合（候选数/
椭球内数/各扇区计数/最终使用数），不存逐查询邻点列表。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from pydantic import Field
from scipy.spatial import cKDTree

from geomodeling.modeling.base import CancelFn, PredictionBatch
from geomodeling.modeling.distance import scale_distance_coordinates
from geomodeling.modeling.neighborhood import select_neighbors
from geomodeling.modeling.professional_contracts import NeighborhoodSpec
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
    neighborhood: NeighborhoodSpec | None = None


class IDWInterpolator:
    algorithm = Algorithm.IDW

    def validate_parameters(
        self, parameters: dict[str, Any], dimension: Dimension | str
    ) -> IDWParameters:
        dimension = Dimension(dimension)  # 维度合法性统一入口（2d/3d 均支持）
        validated = IDWParameters.model_validate(parameters or {})
        if validated.neighborhood is not None:
            expected = 3 if dimension == Dimension.THREE_D else 2
            if len(validated.neighborhood.radii) != expected:
                raise ValueError(
                    f"搜索邻域 radii 长度必须为 {expected}（{dimension.value}），"
                    f"收到 {len(validated.neighborhood.radii)}"
                )
        return validated

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
            tree=cKDTree(scaled),
            values=values,
            parameters=parameters,
            dimension=dimension,
            training=coordinates,
        )


@dataclass(frozen=True)
class _IDWFitted:
    tree: cKDTree
    values: np.ndarray
    parameters: IDWParameters
    dimension: Dimension
    # 物理训练坐标：仅专业搜索邻域路径使用（邻域半径是物理单位）；
    # legacy 路径只读缩放树上的距离
    training: np.ndarray
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

    def _predict_with_neighborhood(self, query: np.ndarray, cancel: CancelFn) -> PredictionBatch:
        """专业搜索邻域路径：``select_neighbors`` 决定候选与扇区（物理坐标），
        权重距离仍为 legacy ``(x, y, z × z_scale)``（缩放树坐标上的欧氏距离）。

        逐查询处理，状态有界；邻点不足的查询为 NoData 且原因聚合计数，
        整批不中断。诊断只存有界聚合，不存逐查询邻点列表。
        """

        spec = self.parameters.neighborhood
        assert spec is not None  # 仅由 predict 在 neighborhood 非 None 时调用
        physical = np.asarray(query, dtype="float64")
        scaled = scale_distance_coordinates(
            physical, dimension=self.dimension, z_scale=self.parameters.z_scale
        )
        n = physical.shape[0]
        values = np.full(n, np.nan)
        source_rows = np.arange(self.training.shape[0], dtype=np.int64)
        scaled_training = self.tree.data  # 缩放树坐标，即 legacy 权重距离空间
        candidate_total = 0
        inside_total = 0
        sector_totals = [0] * spec.sector_count
        used_total = 0
        used_max = 0
        reason_counts: dict[str, int] = {}
        for row in range(n):
            if cancel():
                raise PlatformError(RUN_CANCELED, "任务已被取消", {"completed": row}, http_status=409)
            selection = select_neighbors(self.training, physical[row], source_rows, spec)
            candidate_total += selection.candidate_count
            inside_total += selection.inside_count
            for sector_id, sector_count in enumerate(selection.sector_counts):
                sector_totals[sector_id] += sector_count
            if selection.rejection_reason is not None:
                reason = selection.rejection_reason.lower()
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
                continue
            indices = selection.indices
            used_total += int(indices.size)
            used_max = max(used_max, int(indices.size))
            distances = np.linalg.norm(scaled_training[indices] - scaled[row], axis=1)
            nearest = int(np.argmin(distances))
            if distances[nearest] <= EXACT_DISTANCE:
                # 与 legacy 相同的精确点语义：距离 0 直接返回观测值
                values[row] = self.values[indices[nearest]]
                continue
            weights = 1.0 / np.power(distances, self.parameters.power)
            estimate = float((weights * self.values[indices]).sum() / weights.sum())
            if np.isfinite(estimate):
                values[row] = estimate
        is_nodata = ~np.isfinite(values)
        return PredictionBatch(
            values=values,
            is_nodata=is_nodata,
            diagnostics={
                "max_neighbors_used": used_max,
                "n_targets": n,
                "z_scale": self.parameters.z_scale,
                "search_neighborhood_summary": {
                    "candidate_count_total": candidate_total,
                    "inside_count_total": inside_total,
                    "sector_counts_total": sector_totals,
                    "neighbors_used_total": used_total,
                    "neighbors_used_max": used_max,
                },
                "nodata_reason_counts": reason_counts,
            },
        )

    def predict(self, query: np.ndarray, *, cancel: CancelFn) -> PredictionBatch:
        if self.parameters.neighborhood is not None:
            return self._predict_with_neighborhood(query, cancel)
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
