"""Bounded rotated ellipse/ellipsoid sector neighborhood selection (design §8).

选择流水线（§8.2，顺序固定）：

1. 以包围椭球的安全外接半径做有界候选查询（cKDTree 只用于这一步）；外接
   半径为 ``max(radii) × (1 + 1e-12)``，相对余量只吸收浮点尾差，任何
   椭球内点的欧氏距离在实数意义下不超过 ``max(radii)``；
2. 在邻域自身旋转坐标中做精确椭圆/椭球判定
   ``(u/r_major)² + (v/r_minor)² [+ (w/r_vertical)²] ≤ 1``，边界包含；
3. 绕主轴方向等分 ``sector_count`` 个扇区：2D 在局部 (u, v) 平面取
   ``θ = atan2(v, u)``（自主轴 +u 朝 +v），3D 在垂直主轴的 (v, w) 平面
   取 ``θ = atan2(w, v)``（绕主轴，+v 朝 +w）；``θ ∈ [0, 2π)`` 内第
   ``floor(θ / (2π/sector_count))`` 个扇区，角度 0（含精确同点）归入
   扇区 0；
4. 每扇区按 ``(weight_distance, source_row)`` 稳定排序并截断到
   ``max_per_sector``；
5. 合并后按同一键稳定排序，限制 ``max_neighbors``；
6. 合并数少于 ``min_neighbors`` 时返回空选择与 ``rejection_reason`` —
   不扩大半径、不降低 ``min_neighbors``、不退化为全局搜索。

旋转约定单一来源：复用 ``modeling.anisotropy`` 的旋转构造（2D 方位角在
XY 平面内从 +X 朝 +Y；3D ``R = Rz(azimuth) · Ry(−dip) · Rx(roll)``，
``R`` 的列依次为主、次、垂向轴的物理方向）。3D spec 的 ``dip_deg`` /
``roll_deg`` 为 None 时按 0（水平、不滚转）处理。

``weight_distances`` 是邻域归一化坐标下的椭圆距离（``sqrt(Σ(local/r)²)``），
只用于选择排序；IDW/Kriging 的权重距离由各自算法用自己的距离计算
（设计 §8 确认记录条款）。``allow_exact`` 是 §8.1「是否允许精确同点直接
返回观测值」的参数位：默认 True 把距离 0 的点正常纳入选择；False 时把
精确同点排除在椭球内集合之外，由调用方单独处理。

诊断字段：``candidate_count``（外接球候选数）、``inside_count``（椭球内
数）、``sector_counts``（各扇区经 ``max_per_sector`` 截断后进入合并池的
数量）、最终使用数 = ``len(indices)``、``rejection_reason``。
``NEIGHBORS_INSUFFICIENT`` 既是 ``rejection_reason`` 的取值，也是
``require_neighbors`` 硬失败路径的结构化错误码；取消语义与
``modeling.idw`` 一致（``RUN_CANCELED`` / http 409）。

设计依据：docs/superpowers/specs/2026-07-26-v0.6-professional-modeling-enhancements-design.md §8。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

# 旋转矩阵构造复用 anisotropy.py（同一包内复用模块级私有函数），保持
# +X→+Y / Rz(azimuth)·Ry(−dip)·Rx(roll) 约定的单一来源。
from geomodeling.modeling.anisotropy import _rotation_2d, _rotation_3d
from geomodeling.modeling.base import CancelFn
from geomodeling.modeling.professional_contracts import NeighborhoodSpec
from geomodeling.platform.errors import PlatformError

__all__ = [
    "NEIGHBORHOOD_INPUT_INVALID",
    "NEIGHBORS_INSUFFICIENT",
    "RUN_CANCELED",
    "NeighborSelection",
    "require_neighbors",
    "select_neighbors",
]

RUN_CANCELED = "RUN_CANCELED"
NEIGHBORS_INSUFFICIENT = "NEIGHBORS_INSUFFICIENT"
NEIGHBORHOOD_INPUT_INVALID = "NEIGHBORHOOD_INPUT_INVALID"

# 精确同点阈值（与 modeling.idw 的 EXACT_DISTANCE 一致）。
EXACT_DISTANCE = 1e-12

# 外接半径相对安全余量：只吸收浮点尾差，不改变几何语义。
_OUTER_RADIUS_SAFETY = 1e-12


@dataclass(frozen=True)
class NeighborSelection:
    """一次邻域选择的不可变结果。

    ``indices``/``source_rows``/``weight_distances`` 三者对齐并按
    ``(weight_distance, source_row)`` 升序；不足 ``min_neighbors`` 时三者
    为空且 ``rejection_reason`` 非 None，诊断计数仍反映真实流水线状态。
    """

    indices: np.ndarray
    source_rows: np.ndarray
    weight_distances: np.ndarray
    candidate_count: int
    inside_count: int
    sector_counts: tuple[int, ...]
    rejection_reason: str | None


def _never_canceled() -> bool:
    return False


def _raise_canceled() -> None:
    raise PlatformError(
        RUN_CANCELED, "任务已被取消", {"completed_queries": 0}, http_status=409
    )


def _empty_selection(
    candidate_count: int,
    inside_count: int,
    sector_counts: tuple[int, ...],
    rejection_reason: str,
) -> NeighborSelection:
    return NeighborSelection(
        indices=np.empty(0, dtype=np.int64),
        source_rows=np.empty(0, dtype=np.int64),
        weight_distances=np.empty(0, dtype=np.float64),
        candidate_count=candidate_count,
        inside_count=inside_count,
        sector_counts=sector_counts,
        rejection_reason=rejection_reason,
    )


def _validate_inputs(
    training: np.ndarray,
    query: np.ndarray,
    source_rows: np.ndarray,
    dimension: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """统一形状/有限性校验；返回 float64 坐标与 int64 标准行号。"""

    raw_rows = np.asarray(source_rows)
    training = np.asarray(training, dtype=np.float64)
    query = np.asarray(query, dtype=np.float64)
    if training.ndim != 2 or training.shape[1] != dimension:
        raise PlatformError(
            NEIGHBORHOOD_INPUT_INVALID,
            f"训练坐标必须为 (n, {dimension}) 二维数组",
            {"shape": list(training.shape), "dimension": dimension},
        )
    if query.shape != (dimension,):
        raise PlatformError(
            NEIGHBORHOOD_INPUT_INVALID,
            f"查询点必须为 ({dimension},) 一维数组",
            {"shape": list(query.shape), "dimension": dimension},
        )
    if raw_rows.shape != (training.shape[0],):
        raise PlatformError(
            NEIGHBORHOOD_INPUT_INVALID,
            "source_rows 必须与训练坐标逐行对齐",
            {"source_rows": list(raw_rows.shape), "training_rows": training.shape[0]},
        )
    if not np.issubdtype(raw_rows.dtype, np.integer):
        raise PlatformError(
            NEIGHBORHOOD_INPUT_INVALID, "source_rows 必须为整数类型"
        )
    if not np.isfinite(training).all() or not np.isfinite(query).all():
        raise PlatformError(
            NEIGHBORHOOD_INPUT_INVALID, "训练与查询坐标必须全部为有限值"
        )
    return training, query, raw_rows.astype(np.int64)


def _local_rotation(spec: NeighborhoodSpec, dimension: int) -> np.ndarray:
    """邻域自身旋转矩阵（列为主/次/垂向轴物理方向）；3D None 角按 0 处理。"""

    if dimension == 2:
        return _rotation_2d(float(spec.azimuth_deg))
    dip = 0.0 if spec.dip_deg is None else float(spec.dip_deg)
    roll = 0.0 if spec.roll_deg is None else float(spec.roll_deg)
    return _rotation_3d(float(spec.azimuth_deg), dip, roll)


def _sector_indices(local: np.ndarray, sector_count: int, dimension: int) -> np.ndarray:
    """绕主轴等分扇区：2D ``atan2(v, u)``，3D ``atan2(w, v)``（角度 0 → 扇区 0）。"""

    if dimension == 2:
        theta = np.arctan2(local[:, 1], local[:, 0])
    else:
        theta = np.arctan2(local[:, 2], local[:, 1])
    wedge = 2.0 * math.pi / sector_count
    sectors = np.floor(np.mod(theta, 2.0 * math.pi) / wedge).astype(np.int64)
    # np.mod 的浮点尾差理论上可给出恰好 2π（扇区号越界），钳回末扇区
    return np.minimum(sectors, sector_count - 1)


def _stable_order(weight_distances: np.ndarray, source_rows: np.ndarray) -> np.ndarray:
    """按 ``(weight_distance, source_row)`` 升序的稳定排列（lexsort 末键为主键）。"""

    return np.lexsort((source_rows, weight_distances))


def select_neighbors(
    training: np.ndarray,
    query: np.ndarray,
    source_rows: np.ndarray,
    spec: NeighborhoodSpec,
    *,
    allow_exact: bool = True,
    cancel: CancelFn | None = None,
) -> NeighborSelection:
    """单个查询点的有界旋转椭圆/椭球扇区邻域选择（流水线见模块 docstring）。

    不足 ``min_neighbors`` 时返回空选择（``rejection_reason=
    NEIGHBORS_INSUFFICIENT``），由调用方决定是否按 NoData 或硬失败处理；
    需要结构化硬失败的路径使用 :func:`require_neighbors`。
    """

    cancel_fn = cancel if cancel is not None else _never_canceled
    if cancel_fn():
        _raise_canceled()
    dimension = len(spec.radii)
    training, query, source_rows = _validate_inputs(training, query, source_rows, dimension)
    zero_counts = tuple(0 for _ in range(spec.sector_count))
    if training.shape[0] == 0:
        return _empty_selection(0, 0, zero_counts, NEIGHBORS_INSUFFICIENT)

    # 步骤 1：安全外接半径的有界候选查询（KD 树只用于这一步）
    tree = cKDTree(training)
    if cancel_fn():
        _raise_canceled()
    radii = np.asarray(spec.radii, dtype=np.float64)
    outer_radius = float(radii.max()) * (1.0 + _OUTER_RADIUS_SAFETY)
    candidates = np.asarray(tree.query_ball_point(query, r=outer_radius), dtype=np.int64)
    candidate_count = int(candidates.size)
    if candidate_count == 0:
        return _empty_selection(0, 0, zero_counts, NEIGHBORS_INSUFFICIENT)

    # 步骤 2：邻域自身旋转坐标中的精确椭圆/椭球判定（边界包含）
    offsets = training[candidates] - query
    local = offsets @ _local_rotation(spec, dimension)
    normalized = ((local / radii) ** 2).sum(axis=1)
    weight_distances = np.sqrt(normalized)
    inside = normalized <= 1.0
    if not allow_exact:
        euclidean = np.linalg.norm(offsets, axis=1)
        inside &= euclidean > EXACT_DISTANCE
    inside_positions = np.flatnonzero(inside)
    inside_count = int(inside_positions.size)
    if inside_count == 0:
        return _empty_selection(candidate_count, 0, zero_counts, NEIGHBORS_INSUFFICIENT)

    inside_distances = weight_distances[inside_positions]
    inside_rows = source_rows[candidates[inside_positions]]
    inside_sectors = _sector_indices(local[inside_positions], spec.sector_count, dimension)

    # 步骤 4：每扇区稳定排序并截断（全局序的子序列即扇区内稳定序）
    global_order = _stable_order(inside_distances, inside_rows)
    kept: list[np.ndarray] = []
    sector_counts_list: list[int] = []
    for sector_id in range(spec.sector_count):
        members = global_order[inside_sectors[global_order] == sector_id][: spec.max_per_sector]
        sector_counts_list.append(int(members.size))
        kept.append(members)
    merged = np.concatenate(kept) if kept else np.empty(0, dtype=np.int64)
    sector_counts = tuple(sector_counts_list)

    # 步骤 6：不足即空选择 + 原因；不扩大半径、不降低 min_neighbors
    if merged.size < spec.min_neighbors:
        return _empty_selection(
            candidate_count, inside_count, sector_counts, NEIGHBORS_INSUFFICIENT
        )

    # 步骤 5：合并后稳定排序，限制 max_neighbors
    final = merged[_stable_order(inside_distances[merged], inside_rows[merged])][
        : spec.max_neighbors
    ]
    return NeighborSelection(
        indices=candidates[inside_positions[final]].astype(np.int64),
        source_rows=inside_rows[final].astype(np.int64),
        weight_distances=inside_distances[final].astype(np.float64),
        candidate_count=candidate_count,
        inside_count=inside_count,
        sector_counts=sector_counts,
        rejection_reason=None,
    )


def require_neighbors(
    training: np.ndarray,
    query: np.ndarray,
    source_rows: np.ndarray,
    spec: NeighborhoodSpec,
    *,
    allow_exact: bool = True,
    cancel: CancelFn | None = None,
) -> NeighborSelection:
    """``select_neighbors`` 的硬失败形态：不足 ``min_neighbors`` 时抛出
    结构化 ``NEIGHBORS_INSUFFICIENT``（携带诊断计数），否则原样返回选择。"""

    selection = select_neighbors(
        training,
        query,
        source_rows,
        spec,
        allow_exact=allow_exact,
        cancel=cancel,
    )
    if selection.rejection_reason is not None:
        raise PlatformError(
            NEIGHBORS_INSUFFICIENT,
            f"搜索邻域内可用邻点不足：需要至少 {spec.min_neighbors} 个",
            {
                "min_neighbors": spec.min_neighbors,
                "candidate_count": selection.candidate_count,
                "inside_count": selection.inside_count,
                "sector_counts": list(selection.sector_counts),
            },
        )
    return selection
