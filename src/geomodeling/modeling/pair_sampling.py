"""Deterministic bounded pair sampling for variogram diagnostics (design §6.2).

总点对数 ``n*(n-1)/2`` 不超过 ``max_pairs`` 时使用全部 ``i<j`` 点对
（字典序）；超限时执行确定性分层抽样：先确定性超采样点对 rank（不放回，
内存只与超采样量相关），按有界批次计算距离并在每批前检查取消，再按
分位数距离层把上限比例分摊到非空层，最终 ``(i, j)`` 字典序排列。
随机种子只来自数据 SHA-256 与诊断配置（``seed_from_contract``），不依赖
进程时间；同一输入与配置产生相同的点对身份与字节。全程不分配 ``n×n``
距离矩阵，也不调用 ``scipy.spatial.distance.pdist``。

设计依据：docs/superpowers/specs/2026-07-26-v0.6-professional-modeling-enhancements-design.md §6.2。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from geomodeling.modeling.base import CancelFn
from geomodeling.platform.errors import PlatformError

__all__ = [
    "DISTANCE_BATCH_SIZE",
    "DISTANCE_STRATUM_COUNT",
    "OVERSAMPLE_FACTOR",
    "PAIR_SAMPLE_INPUT_INVALID",
    "RUN_CANCELED",
    "PairSample",
    "sample_pairs",
    "seed_from_contract",
]

RUN_CANCELED = "RUN_CANCELED"
PAIR_SAMPLE_INPUT_INVALID = "PAIR_SAMPLE_INPUT_INVALID"

OVERSAMPLE_FACTOR = 4
DISTANCE_STRATUM_COUNT = 8
DISTANCE_BATCH_SIZE = 100_000


@dataclass(frozen=True)
class PairSample:
    """一次点对抽样的不可变结果（DTO 披露字段：total/used/rate/seed）。

    ``indices`` 为 ``(used_pair_count, 2)`` 的 int64 数组，每行 ``i < j``
    且按字典序排列；``distance_strata`` 与 ``indices`` 对齐，记录每个点对
    所属的分位数距离层。``sampling_rate = used_pair_count / total_pair_count``
    （total 为 0 时定义为 1.0）。
    """

    indices: np.ndarray
    total_pair_count: int
    used_pair_count: int
    sampled: bool
    sampling_rate: float
    seed: int
    distance_strata: np.ndarray


def seed_from_contract(data_sha256: str, canonical_config: bytes) -> int:
    """从数据 SHA-256 与规范化诊断配置派生确定性种子（不依赖进程时间）。"""

    digest = hashlib.sha256(data_sha256.encode("ascii") + b"\0" + canonical_config).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def _never_canceled() -> bool:
    return False


def _raise_canceled(completed_pairs: int) -> None:
    raise PlatformError(
        RUN_CANCELED, "任务已被取消", {"completed_pairs": completed_pairs}, http_status=409
    )


def _draw_unique_ranks(rng: np.random.Generator, total: int, count: int) -> np.ndarray:
    """确定性不放回抽取 ``count`` 个 pair rank（内存只与 ``count`` 相关）。

    直接 ``rng.choice(total, replace=False)`` 会分配 ``total`` 大小的置换
    数组，不可接受；改为带放回抽取后去重并补足，超采样量远小于
    ``sqrt(total)`` 时碰撞极少，补足循环通常零次或一次。

    ``count >= total`` 时抽取目标即全集，去重补足会退化为 coupon-collector
    收集（欠额越小新 rank 越难抽中，尾部近乎停滞，实测挂起）；此时直接返回
    ``0..total-1`` 全量 ranks，与全量路径语义一致且不消耗随机序列。
    """

    if count >= total:
        return np.arange(total, dtype=np.int64)
    draws = rng.integers(0, total, size=count, dtype=np.int64)
    unique = np.unique(draws)
    while unique.size < count:
        top_up = rng.integers(0, total, size=count - unique.size, dtype=np.int64)
        unique = np.unique(np.concatenate((unique, top_up)))
    return unique


def _pair_ranks_to_indices(ranks: np.ndarray, n: int) -> np.ndarray:
    """字典序 pair rank → ``(i, j)``（``i < j``），不物化全部点对。

    rank ``r`` 的第 ``i`` 行起点为 ``C(i) = i*(2n-1-i)/2``；先闭式浮点
    估计再用整数不等式校正到 ``C(i) <= r < C(i+1)``，避免分配 ``total``
    大小的数组，也不受浮点舍入影响。
    """

    estimate = np.floor(
        ((2 * n - 1) - np.sqrt((2 * n - 1) ** 2 - 8.0 * ranks.astype(np.float64))) / 2.0
    ).astype(np.int64)
    i = np.clip(estimate, 0, n - 2)
    while True:
        starts = i * (2 * n - 1 - i) // 2
        too_high = starts > ranks
        if not too_high.any():
            break
        i = np.where(too_high, i - 1, i)
    while True:
        next_starts = (i + 1) * (2 * n - 2 - i) // 2
        too_low = next_starts <= ranks
        if not too_low.any():
            break
        i = np.where(too_low, i + 1, i)
    j = i + 1 + (ranks - i * (2 * n - 1 - i) // 2)
    return np.stack((i, j), axis=1).astype(np.int64)


def _batched_distances(
    points: np.ndarray, pairs: np.ndarray, cancel: CancelFn
) -> np.ndarray:
    """按有界批次计算点对欧氏距离，每批前检查协作式取消。"""

    distances = np.empty(pairs.shape[0], dtype=np.float64)
    for start in range(0, pairs.shape[0], DISTANCE_BATCH_SIZE):
        if cancel():
            _raise_canceled(start)
        batch = pairs[start : start + DISTANCE_BATCH_SIZE]
        distances[start : start + batch.shape[0]] = np.linalg.norm(
            points[batch[:, 0]] - points[batch[:, 1]], axis=1
        )
    return distances


def _distance_strata(distances: np.ndarray) -> np.ndarray:
    """固定数量的分位数距离层；重复分位边导致的空层由分摊逻辑跳过。"""

    if distances.size == 0:
        return np.empty(0, dtype=np.int64)
    inner = np.linspace(0.0, 1.0, DISTANCE_STRATUM_COUNT + 1)[1:-1]
    edges = np.quantile(distances, inner)
    return np.digitize(distances, edges).astype(np.int64)


def _allocate_cap(strata: np.ndarray, cap: int) -> np.ndarray:
    """把 ``cap`` 按层规模比例分摊到非空层（最大余数法，同余数给低层号）。

    ``cap < strata.size`` 时每层配额不超过层规模（余数进位也不越界），
    因此配额之和恒等于 ``cap``。
    """

    counts = np.bincount(strata, minlength=DISTANCE_STRATUM_COUNT).astype(np.int64)
    oversample_count = int(counts.sum())
    base = counts * cap // oversample_count
    remainder = cap - int(base.sum())
    if remainder:
        fractions = counts * cap - base * oversample_count  # 空层恒为 0，不会被进位
        order = np.argsort(-fractions, kind="stable")
        base[order[:remainder]] += 1
    return base


def _select_by_strata(strata: np.ndarray, allocation: np.ndarray) -> np.ndarray:
    """按各层配额取超采样序列中该层的前 ``allocation[s]`` 个，保持确定性。"""

    order = np.argsort(strata, kind="stable")
    sorted_strata = strata[order]
    group_start = np.searchsorted(sorted_strata, sorted_strata, side="left")
    within = np.arange(strata.size) - group_start
    keep_sorted = within < allocation[sorted_strata]
    return np.sort(order[keep_sorted])


def sample_pairs(
    points: np.ndarray,
    *,
    max_pairs: int,
    seed: int,
    cancel: CancelFn | None = None,
) -> PairSample:
    """确定性有界点对抽样；取消语义与 ``modeling.idw`` 一致（RUN_CANCELED/409）。"""

    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] == 0:
        raise PlatformError(
            PAIR_SAMPLE_INPUT_INVALID,
            "坐标必须为 (n, d) 二维数组",
            {"shape": list(points.shape)},
        )
    max_pairs = int(max_pairs)
    if max_pairs < 1:
        raise PlatformError(
            PAIR_SAMPLE_INPUT_INVALID, "max_pairs 必须 ≥ 1", {"max_pairs": max_pairs}
        )
    seed = int(seed)
    if seed < 0:
        raise PlatformError(PAIR_SAMPLE_INPUT_INVALID, "seed 必须 ≥ 0", {"seed": seed})
    cancel_fn = cancel if cancel is not None else _never_canceled

    n = points.shape[0]
    total = n * (n - 1) // 2
    if cancel_fn():
        _raise_canceled(0)

    if total <= max_pairs:
        rows, cols = np.triu_indices(n, k=1)
        indices = np.stack((rows, cols), axis=1).astype(np.int64)
        strata = _distance_strata(_batched_distances(points, indices, cancel_fn))
        return PairSample(
            indices=indices,
            total_pair_count=total,
            used_pair_count=int(indices.shape[0]),
            sampled=False,
            sampling_rate=1.0,
            seed=seed,
            distance_strata=strata,
        )

    oversample_count = min(total, max_pairs * OVERSAMPLE_FACTOR)
    rng = np.random.default_rng(seed)
    ranks = _draw_unique_ranks(rng, total, oversample_count)
    pairs = _pair_ranks_to_indices(ranks, n)
    strata = _distance_strata(_batched_distances(points, pairs, cancel_fn))
    keep = _select_by_strata(strata, _allocate_cap(strata, max_pairs))
    selected = pairs[keep]
    order = np.lexsort((selected[:, 1], selected[:, 0]))
    indices = np.ascontiguousarray(selected[order])
    used = int(indices.shape[0])
    return PairSample(
        indices=indices,
        total_pair_count=total,
        used_pair_count=used,
        sampled=True,
        sampling_rate=used / total,
        seed=seed,
        distance_strata=strata[keep][order],
    )
