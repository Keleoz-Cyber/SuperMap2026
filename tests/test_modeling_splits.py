"""Task 5 spatial split tests: 2D grid groups, 3D XY columns, determinism."""

from __future__ import annotations

import numpy as np
import pytest


def points_2d():
    rng = np.random.default_rng(7)
    x = rng.uniform(-160.0, -40.0, 200)
    y = rng.uniform(220.0, 660.0, 200)
    return np.column_stack([x, y])


def points_3d_columns():
    # 12 个 XY 柱，每柱 5 个 Z 样本
    rng = np.random.default_rng(11)
    xs = rng.uniform(-160.0, -40.0, 12)
    ys = rng.uniform(220.0, 660.0, 12)
    rows = []
    for cx, cy in zip(xs, ys):
        for k in range(5):
            rows.append([cx, cy, -800.0 + 20.0 * k])
    return np.array(rows)


def test_2d_kfold_covers_all_rows_without_overlap():
    from geomodeling.modeling.splits import build_spatial_splits
    from geomodeling.platform.schemas import SpatialValidationSpec

    points = points_2d()
    folds = build_spatial_splits(points, "2d", SpatialValidationSpec(folds=5, seed=42))
    assert len(folds) == 5
    assigned = np.concatenate([f.validation_indices for f in folds])
    assert len(assigned) == len(points)
    assert len(np.unique(assigned)) == len(points)
    # 折叠间索引不重叠
    seen: set[int] = set()
    for fold in folds:
        current = set(fold.validation_indices.tolist())
        assert not seen & current
        seen |= current
    # 每个 fold 有训练与验证
    for fold in folds:
        assert len(fold.training_indices) > 0
        assert len(fold.validation_indices) > 0


def test_splits_are_deterministic_with_seed():
    from geomodeling.modeling.splits import build_spatial_splits
    from geomodeling.platform.schemas import SpatialValidationSpec

    points = points_2d()
    a = build_spatial_splits(points, "2d", SpatialValidationSpec(folds=5, seed=42))
    b = build_spatial_splits(points, "2d", SpatialValidationSpec(folds=5, seed=42))
    c = build_spatial_splits(points, "2d", SpatialValidationSpec(folds=5, seed=43))
    for fa, fb in zip(a, b):
        np.testing.assert_array_equal(fa.validation_indices, fb.validation_indices)
    different = any(
        not np.array_equal(fa.validation_indices, fc.validation_indices)
        for fa, fc in zip(a, c)
    )
    assert different


def test_3d_xy_column_stays_in_one_fold():
    from geomodeling.modeling.splits import build_spatial_splits
    from geomodeling.platform.schemas import SpatialValidationSpec

    points = points_3d_columns()
    folds = build_spatial_splits(points, "3d", SpatialValidationSpec(folds=4, seed=5))
    xy = points[:, :2]
    columns: dict[tuple[float, float], set[int]] = {}
    for idx, (x, y) in enumerate(xy):
        columns.setdefault((round(float(x), 6), round(float(y), 6)), set()).add(idx)
    # 每个 XY 柱的所有 Z 样本必须整体落在同一个 fold 的验证集或整体不在
    for key, members in columns.items():
        hits = [
            fi for fi, fold in enumerate(folds)
            if members & set(fold.validation_indices.tolist())
        ]
        assert len(hits) <= 1, f"XY 柱 {key} 跨折泄漏: {hits}"
        if hits:
            assert members <= set(folds[hits[0]].validation_indices.tolist()), \
                f"XY 柱 {key} 的部分 Z 样本被单独划入验证集"


def test_insufficient_groups_rejected():
    from geomodeling.modeling.splits import build_spatial_splits
    from geomodeling.platform.schemas import SpatialValidationSpec
    from geomodeling.platform.errors import PlatformError

    points = np.array([[0.0, 0.0], [0.0, 0.0], [1.0, 1.0], [1.0, 1.0]])
    with pytest.raises(PlatformError) as exc:
        build_spatial_splits(points, "2d", SpatialValidationSpec(folds=5, seed=1))
    assert exc.value.code == "SPLIT_INSUFFICIENT_GROUPS"


def test_holdout_mode_respects_fraction_and_separation():
    from geomodeling.modeling.splits import build_spatial_splits
    from geomodeling.platform.schemas import SpatialValidationSpec

    points = points_3d_columns()
    folds = build_spatial_splits(
        points, "3d", SpatialValidationSpec(method="spatial_holdout", holdout_fraction=0.25, seed=3)
    )
    assert len(folds) == 1
    fold = folds[0]
    total = len(points)
    assert abs(len(fold.validation_indices) / total - 0.25) < 0.1
    assert not set(fold.training_indices.tolist()) & set(fold.validation_indices.tolist())
    xy = points[:, :2]
    holdout_cols = {tuple(np.round(xy[i], 6)) for i in fold.validation_indices}
    train_cols = {tuple(np.round(xy[i], 6)) for i in fold.training_indices}
    assert not holdout_cols & train_cols
