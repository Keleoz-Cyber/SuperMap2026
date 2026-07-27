"""Local ordinary Kriging with augmented-system weights and safe fallbacks.

Predictions solve the augmented ordinary-Kriging system (weights sum to
one) over at most ``neighbor_count`` neighbors inside ``search_radius``.
Singular neighborhoods fall back to least squares and are counted;
targets with fewer than ``min_neighbors`` neighbors are NoData. Manual
variogram mode requires a complete nugget/sill/range triple with sill
(total sill) strictly greater than nugget.

``z_scale`` (3D only) scales the z column by a validated factor before the
KD-tree and the auto variogram are fit and before queries are issued, so
neighborhood distances and semivariogram lags use ``(x, y, z × z_scale)``;
physical training and grid coordinates are never written back. In manual
mode the given nugget/sill/range are interpreted in the scaled space.

原生方差（设计 §9）：增广系统同时返回权重 λ 与拉格朗日乘子 μ，每个目
标的 Kriging 方差按半变异函数形式 ``σ_k² = λᵀγ0 + μ`` 计算（γ0 是目
标点到邻点的半变异函数向量），随 ``PredictionBatch.auxiliary`` 披露
``kriging_variance``、``kriging_standard_deviation``（
``sqrt(max(variance, 0))``）与 per-target ``kriging_variance_used_lstsq``
最小二乘降级标记。仅 ``-1e-10 <= σ² < 0`` 的浮点微负钳到 0 并计入
``kriging_variance_clamped_count``；显著负值或非有限值 → 该目标
NoData，原因聚合计入 ``nodata_reason_counts['kriging_variance_invalid']``。

``anisotropy``（可选，设计 §7.2 的规范各向异性声明）：给出时变异函数
拟合、协方差矩阵与权重距离全部使用同一 ``SpatialTransform`` 变换后的
坐标，诊断披露同一 ``transform_fingerprint``；非默认 legacy ``z_scale``
与专业各向异性互斥（参数校验拒绝）。``anisotropy=None`` 时距离空间保
持 legacy ``(x, y, z × z_scale)`` 逐位不变。

``neighborhood``（可选，设计 §8 的专业搜索邻域）：为 None 时 legacy
cKDTree 路径逐位不动。给出时每个查询点改走
``modeling.neighborhood.select_neighbors`` 的旋转椭圆/椭球扇区选择 —
邻域按物理坐标与物理半径（独立的显式参数）决定哪些点进入候选，Kriging
矩阵用选中邻点在距离空间坐标下的距离构建。邻点不足的查询为 NoData
（整批不中断），原因聚合计入 ``nodata_reason_counts``；
``search_neighborhood_summary`` 保存有界聚合诊断。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from pydantic import Field, model_validator
from scipy.spatial import cKDTree

from geomodeling.modeling.anisotropy import (
    KrigingAnisotropySpec,
    SpatialTransform,
    build_kriging_transform,
)
from geomodeling.modeling.base import CancelFn, PredictionBatch
from geomodeling.modeling.distance import scale_distance_coordinates
from geomodeling.modeling.neighborhood import NEIGHBORS_INSUFFICIENT, select_neighbors
from geomodeling.modeling.professional_contracts import NeighborhoodSpec
from geomodeling.modeling.variogram import VariogramModel, fit_variogram, semivariance
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import Algorithm, ContractModel, Dimension

PREDICTION_CHUNK_SIZE = 20_000
RUN_CANCELED = "RUN_CANCELED"
KRIGING_VARIANCE_INVALID = "KRIGING_VARIANCE_INVALID"

# 原生方差钳制容差（设计 §9）：仅 [-1e-10, 0) 的浮点微负允许钳到 0。
VARIANCE_CLAMP_TOLERANCE = 1e-10


class KrigingParameters(ContractModel):
    variogram_model: Literal["spherical", "exponential", "gaussian"] = "spherical"
    variogram_mode: Literal["auto", "manual"] = "auto"
    nugget: float | None = Field(default=None, ge=0)
    sill: float | None = Field(default=None, gt=0)
    range: float | None = Field(default=None, gt=0)
    neighbor_count: int = Field(default=24, ge=4, le=128)
    search_radius: float | None = Field(default=None, gt=0)
    min_neighbors: int = Field(default=4, ge=3, le=32)
    z_scale: float = Field(default=1.0, gt=0, le=20)
    anisotropy: KrigingAnisotropySpec | None = None
    neighborhood: NeighborhoodSpec | None = None

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

    @model_validator(mode="after")
    def _check_professional(self) -> "KrigingParameters":
        if self.anisotropy is not None and self.z_scale != 1.0:
            raise ValueError(
                "非默认 legacy z_scale 与专业各向异性互斥："
                "使用 anisotropy 时 z_scale 必须保持默认 1"
            )
        return self


def ordinary_kriging_solution(
    neighbors: np.ndarray,
    target: np.ndarray,
    model: VariogramModel,
) -> tuple[np.ndarray, float, bool]:
    """Solve the augmented OK system; returns (weights, mu, used_lstsq).

    增广普通 Kriging 系统（权重和为一）同时给出权重 λ 与拉格朗日乘子
    μ；奇异邻域降级为最小二乘并置 ``used_lstsq=True``。原生方差由调用
    方按 ``σ_k² = λᵀγ0 + μ`` 计算（设计 §9），γ0 是目标点到邻点的半变
    异函数向量。
    """

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
        return solution[:n], float(solution[n]), False
    except np.linalg.LinAlgError:
        solution, *_ = np.linalg.lstsq(system, right, rcond=None)
        return solution[:n], float(solution[n]), True


def _ordinary_kriging_weights(
    neighbors: np.ndarray,
    target: np.ndarray,
    model: VariogramModel,
) -> tuple[np.ndarray, bool]:
    """v0.5 兼容包装：等价于 ``ordinary_kriging_solution`` 丢弃 μ。"""

    weights, _mu, used_lstsq = ordinary_kriging_solution(neighbors, target, model)
    return weights, used_lstsq


def _classify_variance(raw_variance: float) -> tuple[float | None, bool]:
    """原生方差分类（设计 §9）：返回 ``(方差, 是否钳制)``。

    仅 ``-1e-10 <= σ² < 0`` 的浮点微负钳到 0；显著负值（< -1e-10）与
    非有限值无效，返回 ``(None, False)``，由调用方按 NoData 处理。
    """

    if not math.isfinite(raw_variance) or raw_variance < -VARIANCE_CLAMP_TOLERANCE:
        return None, False
    if raw_variance < 0.0:
        return 0.0, True
    return raw_variance, False


def _count_reason(reason_counts: dict[str, int], reason: str) -> None:
    key = reason.lower()
    reason_counts[key] = reason_counts.get(key, 0) + 1


class OrdinaryKrigingInterpolator:
    algorithm = Algorithm.ORDINARY_KRIGING

    def validate_parameters(
        self, parameters: dict[str, Any], dimension: Dimension | str
    ) -> KrigingParameters:
        dimension = Dimension(dimension)
        validated = KrigingParameters.model_validate(parameters or {})
        if validated.anisotropy is not None:
            if Dimension(validated.anisotropy.dimension) != dimension:
                raise ValueError(
                    f"各向异性维度必须为 {dimension.value}，"
                    f"收到 {validated.anisotropy.dimension}"
                )
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
        dimension = Dimension.THREE_D if coordinates.shape[1] == 3 else Dimension.TWO_D
        if parameters.anisotropy is not None:
            # 规范变换（§7.2）：变异函数拟合、协方差与权重距离同一距离空间
            transform: SpatialTransform | None = build_kriging_transform(
                parameters.anisotropy
            )
            scaled = transform.apply(coordinates)
        else:
            transform = None
            # 邻域树与变异函数都建在缩放副本上；传入的训练坐标保持物理坐标不被改写
            scaled = scale_distance_coordinates(
                coordinates, dimension=dimension, z_scale=parameters.z_scale
            )
        if parameters.variogram_mode == "auto":
            # 自动拟合只使用传入的训练折数据；调用方（折分 runner）保证不泄验证行
            model = fit_variogram(scaled, values, parameters.variogram_model)
        else:
            model = VariogramModel(
                model=parameters.variogram_model,
                nugget=float(parameters.nugget),
                partial_sill=float(parameters.sill - parameters.nugget),
                range=float(parameters.range),
            )
        return _KrigingFitted(
            tree=cKDTree(scaled),
            values=values,
            model=model,
            parameters=parameters,
            dimension=dimension,
            training=coordinates,
            transform=transform,
        )


@dataclass(frozen=True)
class _KrigingFitted:
    tree: cKDTree
    values: np.ndarray
    model: VariogramModel
    parameters: KrigingParameters
    dimension: Dimension
    # 物理训练坐标：仅专业搜索邻域路径使用（邻域半径是物理单位）；
    # legacy 路径只读距离空间树上的距离
    training: np.ndarray
    # 规范各向异性变换；None 表示 legacy (x, y, z × z_scale) 距离空间
    transform: SpatialTransform | None
    _canceled: bool = field(default=False, compare=False)

    def _distance_space(self, query: np.ndarray) -> np.ndarray:
        """把查询点映射到距离空间的新数组；调用方持有的物理坐标不被改写。"""

        if self.transform is not None:
            return self.transform.apply(query)
        # 查询点按同一规则缩放到距离空间；调用方持有的物理坐标不被改写
        return scale_distance_coordinates(
            query, dimension=self.dimension, z_scale=self.parameters.z_scale
        )

    def _solve_target(
        self, neighbor_idx: np.ndarray, target_scaled: np.ndarray
    ) -> tuple[float, float, bool, bool, str | None]:
        """解一个目标；返回 ``(估计, 方差, used_lstsq, 钳制, NoData 原因)``。

        矩阵距离取距离空间坐标（树坐标与已映射查询点）。估计非有限时保
        持 legacy 静默 NoData（不占原因计数）；方差显著为负或非有限时
        该目标 NoData 并给出 ``KRIGING_VARIANCE_INVALID`` 原因。
        """

        neighbors = self.tree.data[neighbor_idx]
        weights, mu, used_lstsq = ordinary_kriging_solution(
            neighbors, target_scaled, self.model
        )
        estimate = float(np.dot(weights, self.values[neighbor_idx]))
        if not np.isfinite(estimate):
            return float("nan"), float("nan"), used_lstsq, False, None
        gamma0 = semivariance(
            np.linalg.norm(neighbors - target_scaled[None, :], axis=1),
            self.model.model,
            self.model.nugget,
            self.model.partial_sill,
            self.model.range,
        )
        variance, clamped = _classify_variance(float(weights @ gamma0 + mu))
        if variance is None:
            return float("nan"), float("nan"), used_lstsq, False, KRIGING_VARIANCE_INVALID
        return estimate, variance, used_lstsq, clamped, None

    def _predict_chunk(
        self, query: np.ndarray
    ) -> tuple[
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        int,
        int,
        int,
        dict[str, int],
    ]:
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
        variances = np.full(n_targets, np.nan)
        lstsq_flags = np.zeros(n_targets, dtype=bool)
        singular_fallbacks = 0
        clamped_count = 0
        reason_counts: dict[str, int] = {}
        finite_mask = np.isfinite(distances)
        neighbor_counts = finite_mask.sum(axis=1)
        max_used = int(neighbor_counts.max()) if n_targets else 0

        for row in range(n_targets):
            usable = finite_mask[row]
            if usable.sum() < params.min_neighbors:
                _count_reason(reason_counts, NEIGHBORS_INSUFFICIENT)
                continue
            neighbor_idx = indices[row, usable]
            estimate, variance, used_lstsq, clamped, reason = self._solve_target(
                neighbor_idx, query[row]
            )
            singular_fallbacks += int(used_lstsq)
            lstsq_flags[row] = used_lstsq
            clamped_count += int(clamped)
            if reason is not None:
                _count_reason(reason_counts, reason)
                continue
            values[row] = estimate
            variances[row] = variance
        is_nodata = ~np.isfinite(values)
        return (
            values,
            is_nodata,
            variances,
            lstsq_flags,
            max_used,
            singular_fallbacks,
            clamped_count,
            reason_counts,
        )

    def _predict_with_neighborhood(self, query: np.ndarray, cancel: CancelFn) -> PredictionBatch:
        """专业搜索邻域路径：``select_neighbors`` 按物理坐标与物理半径决定
        候选与扇区；Kriging 矩阵用选中邻点在距离空间坐标下的距离构建。

        逐查询处理，状态有界；邻点不足或方差无效的查询为 NoData 且原因
        聚合计数，整批不中断。诊断只存有界聚合，不存逐查询邻点列表。
        """

        spec = self.parameters.neighborhood
        assert spec is not None  # 仅由 predict 在 neighborhood 非 None 时调用
        physical = np.asarray(query, dtype="float64")
        scaled = self._distance_space(physical)
        n = physical.shape[0]
        values = np.full(n, np.nan)
        variances = np.full(n, np.nan)
        lstsq_flags = np.zeros(n, dtype=bool)
        source_rows = np.arange(self.training.shape[0], dtype=np.int64)
        candidate_total = 0
        inside_total = 0
        sector_totals = [0] * spec.sector_count
        used_total = 0
        used_max = 0
        singular_fallbacks = 0
        clamped_count = 0
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
                _count_reason(reason_counts, selection.rejection_reason)
                continue
            indices = selection.indices
            used_total += int(indices.size)
            used_max = max(used_max, int(indices.size))
            estimate, variance, used_lstsq, clamped, reason = self._solve_target(
                indices, scaled[row]
            )
            singular_fallbacks += int(used_lstsq)
            lstsq_flags[row] = used_lstsq
            clamped_count += int(clamped)
            if reason is not None:
                _count_reason(reason_counts, reason)
                continue
            values[row] = estimate
            variances[row] = variance
        is_nodata = ~np.isfinite(values)
        return PredictionBatch(
            values=values,
            is_nodata=is_nodata,
            diagnostics=self._diagnostics(
                max_used=used_max,
                singular_fallbacks=singular_fallbacks,
                clamped_count=clamped_count,
                reason_counts=reason_counts,
                extra={
                    "n_targets": n,
                    "search_neighborhood_summary": {
                        "candidate_count_total": candidate_total,
                        "inside_count_total": inside_total,
                        "sector_counts_total": sector_totals,
                        "neighbors_used_total": used_total,
                        "neighbors_used_max": used_max,
                    },
                },
            ),
            auxiliary=self._auxiliary(variances, lstsq_flags),
        )

    def _auxiliary(
        self, variances: np.ndarray, lstsq_flags: np.ndarray
    ) -> dict[str, np.ndarray]:
        """方差工件：方差、标准差（``sqrt(max(variance, 0))``）与 lstsq 标记。"""

        std = np.sqrt(
            np.where(np.isfinite(variances), np.maximum(variances, 0.0), np.nan)
        )
        return {
            "kriging_variance": variances,
            "kriging_standard_deviation": std,
            "kriging_variance_used_lstsq": lstsq_flags,
        }

    def _diagnostics(
        self,
        *,
        max_used: int,
        singular_fallbacks: int,
        clamped_count: int,
        reason_counts: dict[str, int],
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        diagnostics: dict[str, Any] = {
            "max_neighbors_used": max_used,
            "singular_fallback_count": singular_fallbacks,
            "z_scale": self.parameters.z_scale,
            "variogram": {
                "model": self.model.model,
                "nugget": self.model.nugget,
                "partial_sill": self.model.partial_sill,
                "range": self.model.range,
            },
            "kriging_variance_clamped_count": clamped_count,
            "nodata_reason_counts": reason_counts,
        }
        if self.transform is not None:
            # 同一候选的经验半变异函数距离/协方差距离共用同一变换指纹
            diagnostics["transform_fingerprint"] = self.transform.fingerprint
        if extra:
            diagnostics.update(extra)
        return diagnostics

    def predict(self, query: np.ndarray, *, cancel: CancelFn) -> PredictionBatch:
        if self.parameters.neighborhood is not None:
            return self._predict_with_neighborhood(query, cancel)
        # 查询点按同一规则映射到距离空间；调用方持有的物理坐标不被改写
        query = self._distance_space(query)
        n = query.shape[0]
        values = np.full(n, np.nan)
        variances = np.full(n, np.nan)
        lstsq_flags = np.zeros(n, dtype=bool)
        max_used = 0
        singular_fallbacks = 0
        clamped_count = 0
        reason_counts: dict[str, int] = {}
        for start in range(0, n, PREDICTION_CHUNK_SIZE):
            if cancel():
                raise PlatformError(RUN_CANCELED, "任务已被取消", {"completed": start}, http_status=409)
            end = min(start + PREDICTION_CHUNK_SIZE, n)
            (
                chunk_values,
                _chunk_nodata,
                chunk_variances,
                chunk_lstsq,
                chunk_max,
                chunk_singular,
                chunk_clamped,
                chunk_reasons,
            ) = self._predict_chunk(query[start:end])
            values[start:end] = chunk_values
            variances[start:end] = chunk_variances
            lstsq_flags[start:end] = chunk_lstsq
            max_used = max(max_used, chunk_max)
            singular_fallbacks += chunk_singular
            clamped_count += chunk_clamped
            for key, count in chunk_reasons.items():
                reason_counts[key] = reason_counts.get(key, 0) + count
        is_nodata = ~np.isfinite(values)
        return PredictionBatch(
            values=values,
            is_nodata=is_nodata,
            diagnostics=self._diagnostics(
                max_used=max_used,
                singular_fallbacks=singular_fallbacks,
                clamped_count=clamped_count,
                reason_counts=reason_counts,
            ),
            auxiliary=self._auxiliary(variances, lstsq_flags),
        )
