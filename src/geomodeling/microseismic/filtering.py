from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from .schemas import DerivedVelocitySample, RejectedFilteredSample, ThreeSigmaResult

__all__ = ["filter_three_sigma"]

REASON_DEPTH = "深度"
REASON_VX = "速度"


def _sample_statistics(values: np.ndarray, ddof: int) -> tuple[float, float]:
    """Two-pass mean and standard deviation with naive sequential summation.

    Sequential float64 accumulation (not numpy's pairwise summation) is the
    golden table's exact arithmetic: only it reproduces the pinned rejected
    table's z-score bytes. The two-pass form squares deviations around the
    computed mean.
    """
    total = 0.0
    for value in values:
        total += value
    mean = total / len(values)
    squared = 0.0
    for value in values:
        squared += (value - mean) ** 2
    return mean, math.sqrt(squared / (len(values) - ddof))


def _zscores(values: np.ndarray, mean: float, std: float) -> np.ndarray:
    if std == 0.0:
        # A constant column has no deviation; every score is exactly zero.
        return np.zeros_like(values)
    return (values - mean) / std


def filter_three_sigma(
    rows: Sequence[DerivedVelocitySample],
    *,
    threshold: float,
    ddof: int,
) -> ThreeSigmaResult:
    """One-pass global 3σ split over depth and Vx sample statistics.

    Means and sample standard deviations (N-1 when ddof=1) are computed
    exactly once over the full finite input — no grouping by line, point, or
    depth, and no iterative recomputation after rejection. A row is rejected
    when either absolute z-score is strictly greater than the threshold; a
    score exactly equal to the threshold is retained. Rejected rows keep
    every derived source field plus both z-scores, and accepted/rejected each
    preserve source order. Source rows are never mutated, deleted,
    interpolated, or backfilled.
    """
    depth = np.asarray([row.depth_m for row in rows], dtype="float64")
    vx = np.asarray([row.vx_km_s for row in rows], dtype="float64")
    depth_mean, depth_std = _sample_statistics(depth, ddof)
    vx_mean, vx_std = _sample_statistics(vx, ddof)
    depth_z = _zscores(depth, depth_mean, depth_std)
    vx_z = _zscores(vx, vx_mean, vx_std)
    # Build accepted/rejected once from these arrays; never recompute.
    accepted: list[DerivedVelocitySample] = []
    rejected: list[RejectedFilteredSample] = []
    for index, row in enumerate(rows):
        depth_score = float(depth_z[index])
        vx_score = float(vx_z[index])
        reasons = [
            reason
            for reason, score in ((REASON_DEPTH, depth_score), (REASON_VX, vx_score))
            if abs(score) > threshold
        ]
        if not reasons:
            accepted.append(row)
            continue
        rejected.append(
            RejectedFilteredSample.from_derived(
                row,
                depth_zscore=depth_score,
                vx_zscore=vx_score,
                filter_reason=";".join(reasons),
            )
        )
    return ThreeSigmaResult(
        threshold=threshold,
        ddof=ddof,
        depth_mean=depth_mean,
        depth_std=depth_std,
        vx_mean=vx_mean,
        vx_std=vx_std,
        accepted=accepted,
        rejected=rejected,
    )
