"""经验误差尺度：折外残差的距离加权局部 RMSE（design §10.2）。

流水线（顺序固定）：

1. 只使用有限折外残差点：``is_nodata`` 的折外行（非有限残差或非有限坐
   标）在进入邻域前排除，任何训练内拟合值不得进入；
2. 残差点与查询点经同一专业空间变换（``distance_transform``：
   :class:`~geomodeling.modeling.anisotropy.SpatialTransform` 或返回新
   数组的 callable）映射到距离空间；物理坐标永不改写，只读副本进入变
   换；
3. 邻域选择：``spec.neighborhood`` 为 None 时在距离空间做 cKDTree KNN
   （``max_neighbors``）；非 None 时复用
   ``modeling.neighborhood.select_neighbors`` 的有界旋转椭圆/椭球扇区
   选择（物理坐标、物理半径），加权距离仍在距离空间重算；
4. 距离加权局部 RMSE：``scale = sqrt(Σ w_i·r_i² / Σ w_i)``，
   ``w_i = 1/d_i**power``；查询点恰好落在残差位置（``d ≤ EXACT_DISTANCE``）
   时权重趋于无穷大，极限语义下直接取该残差的绝对误差 ``|r_i|``；
5. 邻点不足（< ``min_neighbors``）的查询为 NoData 并聚合原因计数——不
   扩大半径、不降低 ``min_neighbors``、不得用全局 RMSE 填充空间场。

该场命名为「经验误差尺度」（empirical_error_scale）：它是局部残差的
描述性汇总，不是标准误、置信区间或概率陈述。取消语义与
``modeling.idw`` 一致（``RUN_CANCELED`` / http 409，按查询批检查）。

指纹约定：``distance_transform`` 为 ``SpatialTransform`` 时，诊断中的
``transform_fingerprint`` 原样回传其指纹——同一 Kriging 候选的经验半
变异函数距离、协方差距离与经验误差距离因此共用同一指纹；普通 callable
无规范指纹，记为 None。``identity_transform(dimension)`` 经
``build_kriging_transform(KrigingAnisotropySpec.isotropic(...))`` 构造，
保证恒等变换也携带规范指纹。

当前合同依据：docs/architecture.md 的专业证据边界与 docs/acceptance.md。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
from scipy.spatial import cKDTree

from geomodeling.modeling.anisotropy import (
    KrigingAnisotropySpec,
    SpatialTransform,
    build_kriging_transform,
)
from geomodeling.modeling.base import CancelFn
from geomodeling.modeling.neighborhood import EXACT_DISTANCE, select_neighbors
from geomodeling.modeling.professional_contracts import EmpiricalUncertaintySpec
from geomodeling.platform.errors import PlatformError

__all__ = [
    "EMPIRICAL_UNCERTAINTY_INPUT_INVALID",
    "QUERY_BATCH_SIZE",
    "RUN_CANCELED",
    "EmpiricalErrorScale",
    "empirical_error_scale",
    "identity_transform",
]

RUN_CANCELED = "RUN_CANCELED"
EMPIRICAL_UNCERTAINTY_INPUT_INVALID = "EMPIRICAL_UNCERTAINTY_INPUT_INVALID"

# 邻点不足的 NoData 原因键（select_neighbors 的 NEIGHBORS_INSUFFICIENT 小写）。
_NEIGHBORS_INSUFFICIENT_REASON = "neighbors_insufficient"

# 取消检查粒度：每处理一批查询点检查一次 cancel。
QUERY_BATCH_SIZE = 256

# distance_transform 的统一接口：SpatialTransform（apply + fingerprint）或
# 返回新数组的 callable（如 legacy ``scale_distance_coordinates`` 的闭包）。
DistanceTransform = SpatialTransform | Callable[[np.ndarray], np.ndarray]


@dataclass(frozen=True)
class EmpiricalErrorScale:
    """一次经验误差尺度计算的不可变结果。

    ``scale`` 为逐查询的经验误差尺度（NoData 处为 NaN）；``is_nodata`` 与
    ``neighbor_count``（实际参与加权的局部残差数，NoData 处为 0）与其逐
    行对齐；``diagnostics`` 只存有界聚合：覆盖率、NoData 原因计数、有
    效/排除折外残差数与变换指纹。
    """

    scale: np.ndarray
    is_nodata: np.ndarray
    neighbor_count: np.ndarray
    diagnostics: dict[str, Any]


def _never_canceled() -> bool:
    return False


def identity_transform(dimension: int) -> SpatialTransform:
    """恒等空间变换（``matrix = I``），复用规范各向异性指纹管线。"""

    if dimension == 2:
        return build_kriging_transform(KrigingAnisotropySpec.isotropic("2d"))
    if dimension == 3:
        return build_kriging_transform(KrigingAnisotropySpec.isotropic("3d"))
    raise ValueError(f"dimension 必须为 2 或 3，收到 {dimension!r}")


def _apply_transform(
    distance_transform: DistanceTransform, coordinates: np.ndarray
) -> np.ndarray:
    """把坐标映射到距离空间；输入必须是内部副本，callable 无权改写调用方数据。"""

    apply = getattr(distance_transform, "apply", None)
    if callable(apply):
        return np.asarray(apply(coordinates), dtype=np.float64)
    if callable(distance_transform):
        return np.asarray(distance_transform(coordinates), dtype=np.float64)
    raise PlatformError(
        EMPIRICAL_UNCERTAINTY_INPUT_INVALID,
        "distance_transform 必须是 SpatialTransform 或返回新数组的 callable",
        {"received": type(distance_transform).__name__},
    )


def _validate_inputs(
    residual_points: np.ndarray, residuals: np.ndarray, query: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """统一形状/有限性校验；返回 float64 副本（调用方数组绝不别名）。"""

    points = np.array(residual_points, dtype=np.float64)
    residual_values = np.array(residuals, dtype=np.float64)
    query_points = np.array(query, dtype=np.float64)
    if points.ndim != 2:
        raise PlatformError(
            EMPIRICAL_UNCERTAINTY_INPUT_INVALID,
            "残差点坐标必须为 (n, dim) 二维数组",
            {"shape": list(points.shape)},
        )
    if residual_values.shape != (points.shape[0],):
        raise PlatformError(
            EMPIRICAL_UNCERTAINTY_INPUT_INVALID,
            "残差必须与残差点坐标逐行对齐",
            {
                "residuals": list(residual_values.shape),
                "residual_point_rows": points.shape[0],
            },
        )
    if query_points.ndim != 2 or query_points.shape[1] != points.shape[1]:
        raise PlatformError(
            EMPIRICAL_UNCERTAINTY_INPUT_INVALID,
            "查询坐标必须为 (m, dim) 且与残差点同维度",
            {"shape": list(query_points.shape), "dimension": points.shape[1]},
        )
    if not np.isfinite(query_points).all():
        raise PlatformError(
            EMPIRICAL_UNCERTAINTY_INPUT_INVALID, "查询坐标必须全部为有限值"
        )
    return points, residual_values, query_points


def empirical_error_scale(
    *,
    residual_points: np.ndarray,
    residuals: np.ndarray,
    query: np.ndarray,
    spec: EmpiricalUncertaintySpec,
    distance_transform: DistanceTransform,
    cancel: CancelFn | None = None,
) -> EmpiricalErrorScale:
    """在规则网格查询点上计算经验误差尺度（语义见模块 docstring）。

    ``residual_points``/``query`` 为物理坐标且只读；``residuals`` 中非有
    限行（折外 NoData 行）在进入邻域前排除。返回逐查询尺度、NoData 掩
    膜、局部残差数量与覆盖率诊断。
    """

    cancel_fn = cancel if cancel is not None else _never_canceled
    points, residual_values, query_points = _validate_inputs(
        residual_points, residuals, query
    )
    n_queries = query_points.shape[0]

    # 步骤 1：只使用有限折外残差点（is_nodata 的折外行在此排除）
    finite_rows = np.isfinite(residual_values) & np.isfinite(points).all(axis=1)
    valid_points = points[finite_rows]
    valid_residuals = residual_values[finite_rows]
    n_valid = int(valid_points.shape[0])

    # 步骤 2：同一专业空间变换下的距离空间坐标（物理坐标不被改写）
    fingerprint = getattr(distance_transform, "fingerprint", None)
    transformed_points = _apply_transform(distance_transform, valid_points)
    transformed_query = _apply_transform(distance_transform, query_points)
    if (
        transformed_points.shape != valid_points.shape
        or transformed_query.shape != query_points.shape
    ):
        raise PlatformError(
            EMPIRICAL_UNCERTAINTY_INPUT_INVALID,
            "distance_transform 必须保持坐标形状不变",
            {
                "points_shape": list(transformed_points.shape),
                "query_shape": list(transformed_query.shape),
            },
        )
    if not np.isfinite(transformed_points).all() or not np.isfinite(transformed_query).all():
        raise PlatformError(
            EMPIRICAL_UNCERTAINTY_INPUT_INVALID, "变换后坐标必须全部为有限值"
        )

    neighborhood = spec.neighborhood
    tree = cKDTree(transformed_points) if neighborhood is None and n_valid > 0 else None
    source_rows = np.arange(n_valid, dtype=np.int64)

    scale = np.full(n_queries, np.nan)
    is_nodata = np.zeros(n_queries, dtype=bool)
    neighbor_count = np.zeros(n_queries, dtype=np.int64)
    reason_counts: dict[str, int] = {}

    def _mark_nodata(row: int, reason: str) -> None:
        is_nodata[row] = True
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    for start in range(0, n_queries, QUERY_BATCH_SIZE):
        if cancel_fn():
            raise PlatformError(
                RUN_CANCELED,
                "任务已被取消",
                {"completed_queries": start},
                http_status=409,
            )
        stop = min(start + QUERY_BATCH_SIZE, n_queries)
        for row in range(start, stop):
            # 步骤 3：邻域选择（KNN 或显式误差邻域）
            if neighborhood is None:
                k = min(spec.max_neighbors, n_valid)
                if k == 0:
                    _mark_nodata(row, _NEIGHBORS_INSUFFICIENT_REASON)
                    continue
                distances, indices = tree.query(transformed_query[row], k=k)
                indices = np.atleast_1d(indices).astype(np.int64)
                distances = np.atleast_1d(distances).astype(np.float64)
            else:
                selection = select_neighbors(
                    valid_points, query_points[row], source_rows, neighborhood
                )
                if selection.rejection_reason is not None:
                    _mark_nodata(row, selection.rejection_reason.lower())
                    continue
                indices = selection.indices
                distances = np.linalg.norm(
                    transformed_points[indices] - transformed_query[row], axis=1
                )
            if indices.size < spec.min_neighbors:
                _mark_nodata(row, _NEIGHBORS_INSUFFICIENT_REASON)
                continue

            # 步骤 4：距离加权局部 RMSE；d=0 取该残差的绝对误差（权重极限语义）
            nearest = int(np.argmin(distances))
            if distances[nearest] <= EXACT_DISTANCE:
                scale[row] = abs(valid_residuals[indices[nearest]])
            else:
                weights = 1.0 / np.power(distances, spec.power)
                gathered = valid_residuals[indices]
                scale[row] = math.sqrt(
                    float((weights * gathered**2).sum() / weights.sum())
                )
            neighbor_count[row] = indices.size

    covered = int((~is_nodata).sum())
    diagnostics: dict[str, Any] = {
        "total_queries": n_queries,
        "covered_queries": covered,
        "coverage": covered / n_queries if n_queries else 0.0,
        "nodata_reasons": reason_counts,
        "residual_point_count": n_valid,
        "excluded_residual_count": int(points.shape[0] - n_valid),
        "transform_fingerprint": fingerprint,
    }
    return EmpiricalErrorScale(
        scale=scale,
        is_nodata=is_nodata,
        neighbor_count=neighbor_count,
        diagnostics=diagnostics,
    )
