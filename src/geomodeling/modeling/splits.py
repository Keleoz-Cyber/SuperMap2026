"""Spatial validation splits: 2D grid-cell groups, 3D whole XY columns.

Groups are assigned to folds by a seeded shuffle followed by greedy
balancing on row count, so every row lands in exactly one validation fold
and neighboring Z samples of one XY column never straddle train/validate.
Random point-wise splitting is deliberately not offered.
"""

from __future__ import annotations

import numpy as np

from geomodeling.modeling.contracts import Fold
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import Dimension, SpatialValidationSpec

SPLIT_INSUFFICIENT_GROUPS = "SPLIT_INSUFFICIENT_GROUPS"


def _dimension_of(dimension: str | Dimension) -> str:
    return Dimension(dimension).value


def _groups_2d(points: np.ndarray, folds: int) -> np.ndarray:
    """Uniform XY grid-cell group ids, one per row."""

    nx = max(2, int(np.ceil(np.sqrt(folds * 3))))
    lows = points[:, :2].min(axis=0)
    highs = points[:, :2].max(axis=0)
    spans = np.where(highs - lows > 0, highs - lows, 1.0)
    cell = spans / nx
    idx = np.floor((points[:, :2] - lows) / cell).astype(int)
    idx = np.clip(idx, 0, nx - 1)
    return idx[:, 0] * nx + idx[:, 1]


def _groups_3d(points: np.ndarray) -> np.ndarray:
    """Whole-XY-column group ids; quantization tolerance follows the plan."""

    xy = points[:, :2]
    span = max(xy[:, 0].max() - xy[:, 0].min(), xy[:, 1].max() - xy[:, 1].min())
    tol = max(span * 1e-9, 1e-8)
    keys = np.floor((xy - xy.min(axis=0)) / tol).astype(np.int64)
    _, groups = np.unique(keys, axis=0, return_inverse=True)
    return groups


def _assign(groups: np.ndarray, count: int, seed: int) -> list[list[int]]:
    """Seeded shuffle of groups then greedy balance into ``count`` bins."""

    rng = np.random.default_rng(seed)
    unique = np.unique(groups)
    sizes = np.array([(groups == g).sum() for g in unique])
    order = rng.permutation(len(unique))
    bins: list[list[int]] = [[] for _ in range(count)]
    loads = np.zeros(count, dtype="int64")
    for position in order:
        group = unique[position]
        target = int(np.argmin(loads))
        bins[target].append(int(group))
        loads[target] += sizes[position]
    return bins


def _to_folds(groups: np.ndarray, bins: list[list[int]], n_rows: int) -> list[Fold]:
    folds = []
    for index, members in enumerate(bins):
        validation_mask = np.isin(groups, np.array(members, dtype="int64"))
        validation = np.nonzero(validation_mask)[0]
        training = np.nonzero(~validation_mask)[0]
        folds.append(
            Fold(
                index=index,
                training_indices=training.astype("int64"),
                validation_indices=validation.astype("int64"),
            )
        )
    return folds


def build_spatial_splits(
    points: np.ndarray,
    dimension: str | Dimension,
    spec: SpatialValidationSpec,
) -> list[Fold]:
    """Build deterministic spatial folds for a modeling point set."""

    dim = _dimension_of(dimension)
    points = np.asarray(points, dtype="float64")
    n_rows = len(points)
    if n_rows == 0:
        raise PlatformError(SPLIT_INSUFFICIENT_GROUPS, "空数据集无法折分")

    if spec.method == "spatial_holdout":
        groups = _groups_3d(points) if dim == Dimension.THREE_D.value else _groups_2d(points, 3)
        unique_count = len(np.unique(groups))
        if unique_count < 2:
            raise PlatformError(
                SPLIT_INSUFFICIENT_GROUPS,
                f"空间分组数 {unique_count} 不足以做留出验证",
                {"groups": unique_count},
            )
        # 贪心装满留出比例为止：从打乱的分组中依次取组直到达到目标行数
        rng = np.random.default_rng(spec.seed)
        unique = np.unique(groups)
        order = rng.permutation(len(unique))
        target_rows = max(1, int(round(n_rows * spec.holdout_fraction)))
        members: list[int] = []
        held = 0
        for position in order:
            group = int(unique[position])
            members.append(group)
            held += int((groups == group).sum())
            if held >= target_rows:
                break
        rest = [int(g) for g in unique if g not in members]
        validation_mask = np.isin(groups, np.array(members, dtype="int64"))
        training_mask = np.isin(groups, np.array(rest, dtype="int64"))
        return [
            Fold(
                index=0,
                training_indices=np.nonzero(training_mask)[0].astype("int64"),
                validation_indices=np.nonzero(validation_mask)[0].astype("int64"),
            )
        ]

    fold_count = spec.folds
    groups = _groups_3d(points) if dim == Dimension.THREE_D.value else _groups_2d(points, fold_count)
    unique_count = len(np.unique(groups))
    if unique_count < fold_count:
        raise PlatformError(
            SPLIT_INSUFFICIENT_GROUPS,
            f"空间分组数 {unique_count} 少于折数 {fold_count}",
            {"groups": unique_count, "folds": fold_count},
        )
    bins = _assign(groups, fold_count, spec.seed)
    return _to_folds(groups, bins, n_rows)
