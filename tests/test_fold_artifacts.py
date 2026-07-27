"""Task 9: stable fold assignments and out-of-fold residual artifacts.

Fold evidence is run-level: every row of the valid dataset appears in
exactly one validation fold, spatial groups (2D grid cells / 3D whole XY
columns) never straddle train/validation inside one fold, and any leakage
fails closed instead of producing a warning. Out-of-fold records carry
only held-out predictions — one row per validation sample with stable
``source_row`` identity — and NoData predictions keep null residual
columns. The validation fingerprint canonicalizes the dataset hash,
validation spec, fold assignment and ordered validation source rows.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from geomodeling.modeling.contracts import Fold
from geomodeling.modeling.fold_artifacts import (
    ASSIGNMENT_COLUMNS,
    FOLD_ASSIGNMENT_INCOMPLETE,
    FOLD_LEAKAGE_DETECTED,
    OOF_COLUMNS,
    OOF_PREDICTION_MISMATCH,
    FoldArtifacts,
    build_fold_artifacts,
    build_fold_assignments,
    build_oof_predictions,
    write_artifact_parquet,
)
from geomodeling.modeling.splits import build_spatial_splits
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import SpatialValidationSpec

DATA_SHA256 = "c" * 64
SPEC_KFOLD = SpatialValidationSpec(method="spatial_kfold", folds=3, seed=11, holdout_fraction=0.2)


def make_frame_2d(n: int = 18) -> pd.DataFrame:
    rng = np.random.default_rng(20260726)
    x = rng.uniform(0.0, 100.0, n)
    y = rng.uniform(0.0, 100.0, n)
    return pd.DataFrame(
        {
            "source_row": np.arange(1, n + 1, dtype="int64"),
            "x": x,
            "y": y,
            "z": np.full(n, np.nan),
            "value": np.sin(x / 20.0) + np.cos(y / 25.0) + 5.0,
            "is_numeric_valid": True,
        }
    )


def make_frame_3d_columns() -> pd.DataFrame:
    """4 根完整 XY 柱 × 3 个 Z 采样：空间组身份必须按整柱划分。"""

    rows = []
    source_row = 1
    for x, y in [(0.0, 0.0), (10.0, 0.0), (0.0, 10.0), (10.0, 10.0)]:
        for z in (-100.0, -50.0, -10.0):
            rows.append((source_row, x, y, z, x + y + z / 100.0))
            source_row += 1
    return pd.DataFrame(
        rows, columns=["source_row", "x", "y", "z", "value"]
    ).assign(is_numeric_valid=True)


def make_folds(frame: pd.DataFrame, dimension: str, spec: SpatialValidationSpec = SPEC_KFOLD) -> list[Fold]:
    coord_cols = ["x", "y"] + (["z"] if dimension == "3d" else [])
    points = frame[coord_cols].to_numpy(dtype="float64")
    return build_spatial_splits(points, dimension, spec)


def make_predictions(
    frame: pd.DataFrame, folds: list[Fold], nodata_rows: tuple[int, ...] = ()
) -> pd.DataFrame:
    """模拟 runner 产出的候选预测（source_row/fold/truth/prediction/is_nodata）。"""

    parts = []
    for fold in folds:
        rows = frame.iloc[fold.validation_indices]
        is_nodata = np.isin(rows["source_row"].to_numpy(), list(nodata_rows))
        prediction = np.where(is_nodata, np.nan, rows["value"].to_numpy() + 0.5)
        parts.append(
            pd.DataFrame(
                {
                    "source_row": rows["source_row"].to_numpy(),
                    "fold": fold.index,
                    "truth": rows["value"].to_numpy(),
                    "prediction": prediction,
                    "is_nodata": is_nodata,
                }
            )
        )
    return pd.concat(parts, ignore_index=True)


def build_default(frame, folds, predictions, dimension="2d") -> FoldArtifacts:
    return build_fold_artifacts(
        frame,
        folds,
        predictions,
        dimension=dimension,
        data_sha256=DATA_SHA256,
        validation=SPEC_KFOLD,
    )


def test_oof_records_are_complete_unique_and_leakage_free():
    frame = make_frame_2d()
    folds = make_folds(frame, "2d")
    artifacts = build_default(frame, folds, make_predictions(frame, folds))
    assert artifacts.oof["source_row"].is_unique
    assert set(artifacts.oof["source_row"]) == set(frame["source_row"])
    assert not artifacts.fold_assignments["leakage_detected"].any()
    assert {"observed", "predicted", "residual", "absolute_error", "squared_error"} <= set(artifacts.oof)


def test_oof_columns_are_exact_and_residuals_match_hand_calculation():
    frame = make_frame_2d()
    folds = make_folds(frame, "2d")
    artifacts = build_default(frame, folds, make_predictions(frame, folds))
    assert list(artifacts.oof.columns) == [
        "source_row", "fold_index", "x", "y", "z",
        "observed", "predicted", "residual",
        "absolute_error", "squared_error", "is_nodata",
    ]
    assert list(artifacts.oof.columns) == OOF_COLUMNS
    merged = artifacts.oof.merge(frame[["source_row", "value"]], on="source_row")
    assert (merged["predicted"] - merged["value"]).to_numpy() == pytest.approx(0.5)
    assert merged["residual"].to_numpy() == pytest.approx(0.5)
    assert merged["absolute_error"].to_numpy() == pytest.approx(0.5)
    assert merged["squared_error"].to_numpy() == pytest.approx(0.25)
    assert not artifacts.oof["is_nodata"].any()


def test_nodata_predictions_keep_null_residual_columns():
    frame = make_frame_2d()
    folds = make_folds(frame, "2d")
    nodata_rows = tuple(int(frame["source_row"].iloc[i]) for i in (0, 5, 11))
    artifacts = build_default(frame, folds, make_predictions(frame, folds, nodata_rows))
    oof = artifacts.oof.set_index("source_row")
    for row in nodata_rows:
        record = oof.loc[row]
        assert bool(record["is_nodata"]) is True
        for column in ("predicted", "residual", "absolute_error", "squared_error"):
            assert pd.isna(record[column]), column
        assert not pd.isna(record["observed"])
    valid = oof.drop(index=list(nodata_rows))
    assert not valid["is_nodata"].any()
    assert valid["residual"].notna().all()


def test_2d_z_column_is_null_and_3d_keeps_real_z():
    frame = make_frame_2d()
    folds = make_folds(frame, "2d")
    artifacts = build_default(frame, folds, make_predictions(frame, folds), dimension="2d")
    assert artifacts.oof["z"].isna().all()

    frame3d = make_frame_3d_columns()
    folds3d = make_folds(frame3d, "3d")
    artifacts3d = build_fold_artifacts(
        frame3d, folds3d, make_predictions(frame3d, folds3d),
        dimension="3d", data_sha256=DATA_SHA256, validation=SPEC_KFOLD,
    )
    merged = artifacts3d.oof.merge(
        frame3d[["source_row", "z"]], on="source_row", suffixes=("", "_truth")
    )
    np.testing.assert_allclose(merged["z"], merged["z_truth"])


def test_3d_grouping_uses_whole_xy_columns():
    frame = make_frame_3d_columns()
    folds = make_folds(frame, "3d")
    artifacts = build_fold_artifacts(
        frame, folds, make_predictions(frame, folds),
        dimension="3d", data_sha256=DATA_SHA256, validation=SPEC_KFOLD,
    )
    assignments = artifacts.fold_assignments
    for (_x, _y), column in frame.groupby(["x", "y"]):
        rows = assignments[assignments["source_row"].isin(column["source_row"])]
        # 同一 XY 柱：空间组身份唯一，且只在同一折做验证
        assert rows["group_key"].nunique() == 1
        validation = rows[rows["role"] == "validation"]
        assert validation["fold_index"].nunique() == 1
        assert len(validation) == len(column)


def test_assignments_cover_every_row_per_fold_with_unique_validation():
    frame = make_frame_2d()
    folds = make_folds(frame, "2d")
    artifacts = build_default(frame, folds, make_predictions(frame, folds))
    assignments = artifacts.fold_assignments
    assert {"fold_index", "source_row", "group_key", "role", "leakage_detected"} <= set(
        assignments.columns
    )
    assert set(assignments["role"]) == {"training", "validation"}
    # 每一折内每个样本恰好一个角色
    assert not assignments.duplicated(subset=["fold_index", "source_row"]).any()
    assert set(assignments["fold_index"]) == {fold.index for fold in folds}
    per_fold = assignments.groupby("fold_index")["source_row"].nunique()
    assert (per_fold == len(frame)).all()
    # 每个样本恰好在一个折中担任验证
    validation = assignments[assignments["role"] == "validation"]
    counts = validation.groupby("source_row").size()
    assert (counts == 1).all()
    assert set(validation["source_row"]) == set(frame["source_row"])


def test_spatial_holdout_produces_single_fold_assignments():
    frame = make_frame_2d()
    spec = SpatialValidationSpec(
        method="spatial_holdout", folds=3, seed=11, holdout_fraction=0.25
    )
    folds = make_folds(frame, "2d", spec)
    assert len(folds) == 1
    artifacts = build_fold_artifacts(
        frame, folds, make_predictions(frame, folds),
        dimension="2d", data_sha256=DATA_SHA256, validation=spec,
    )
    assignments = artifacts.fold_assignments
    assert set(assignments["fold_index"]) == {0}
    validation = assignments[assignments["role"] == "validation"]
    assert 0 < len(validation) < len(frame)
    assert set(artifacts.oof["source_row"]) == set(validation["source_row"])


def test_fingerprint_is_stable_and_sensitive_to_inputs():
    frame = make_frame_2d()
    folds = make_folds(frame, "2d")
    predictions = make_predictions(frame, folds)
    first = build_default(frame, folds, predictions)
    second = build_default(frame, folds, predictions)
    assert first.validation_fingerprint == second.validation_fingerprint
    assert len(first.validation_fingerprint) == 64

    # 预测行顺序不影响指纹与 OOF 内容（规范化）
    shuffled = predictions.sample(frac=1.0, random_state=7).reset_index(drop=True)
    reordered = build_default(frame, folds, shuffled)
    assert reordered.validation_fingerprint == first.validation_fingerprint
    pd.testing.assert_frame_equal(reordered.oof, first.oof)

    # 数据集哈希、验证规格、折分变化都会改变指纹
    other_hash = build_fold_artifacts(
        frame, folds, predictions,
        dimension="2d", data_sha256="d" * 64, validation=SPEC_KFOLD,
    )
    assert other_hash.validation_fingerprint != first.validation_fingerprint
    other_spec = SpatialValidationSpec(method="spatial_kfold", folds=3, seed=12, holdout_fraction=0.2)
    other_folds = make_folds(frame, "2d", other_spec)
    other_seed = build_fold_artifacts(
        frame, other_folds, make_predictions(frame, other_folds),
        dimension="2d", data_sha256=DATA_SHA256, validation=other_spec,
    )
    assert other_seed.validation_fingerprint != first.validation_fingerprint


def test_row_overlap_between_training_and_validation_fails_closed():
    frame = make_frame_2d(12)
    # fold 0 的训练与验证共享行 3/4/5；验证覆盖仍保持每行一次
    folds = [
        Fold(
            index=0,
            training_indices=np.array([0, 1, 2, 3, 4, 5]),
            validation_indices=np.array([3, 4, 5, 6, 7, 8]),
        ),
        Fold(
            index=1,
            training_indices=np.array([6, 7, 8, 9, 10, 11]),
            validation_indices=np.array([0, 1, 2, 9, 10, 11]),
        ),
    ]
    with pytest.raises(PlatformError) as exc:
        build_default(frame, folds, make_predictions(frame, folds))
    assert exc.value.code == FOLD_LEAKAGE_DETECTED


def test_xy_column_split_across_train_and_validation_fails_closed():
    frame = make_frame_3d_columns()  # 行 0-5 属柱 A/B？按构造顺序：0-2 柱1，3-5 柱2
    # fold 0：柱 1 的前两行做训练、最后一行做验证（行级不重叠，组级泄漏）
    folds = [
        Fold(
            index=0,
            training_indices=np.array([0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11]),
            validation_indices=np.array([2]),
        ),
        Fold(
            index=1,
            training_indices=np.array([2, 3, 4, 5, 6, 7, 8, 9, 10, 11]),
            validation_indices=np.array([0, 1]),
        ),
        Fold(
            index=2,
            training_indices=np.array([0, 1, 2, 6, 7, 8, 9, 10, 11]),
            validation_indices=np.array([3, 4, 5]),
        ),
        Fold(
            index=3,
            training_indices=np.array([0, 1, 2, 3, 4, 5]),
            validation_indices=np.array([6, 7, 8, 9, 10, 11]),
        ),
    ]
    with pytest.raises(PlatformError) as exc:
        build_fold_artifacts(
            frame, folds, make_predictions(frame, folds),
            dimension="3d", data_sha256=DATA_SHA256, validation=SPEC_KFOLD,
        )
    assert exc.value.code == FOLD_LEAKAGE_DETECTED


def test_validation_coverage_not_exactly_once_fails_closed():
    frame = make_frame_2d()
    folds = make_folds(frame, "2d")
    # 把 fold 0 验证集中的一整个空间组挪入训练（保持组完整，不引入泄漏），
    # 使这些行从未担任验证样本
    from geomodeling.modeling import splits

    points = frame[["x", "y"]].to_numpy(dtype="float64")
    groups = splits._groups_2d(points, SPEC_KFOLD.folds)
    fold0 = folds[0]
    val = np.asarray(fold0.validation_indices, dtype="int64")
    group = groups[val[0]]
    members = val[groups[val] == group]
    folds[0] = Fold(
        index=fold0.index,
        training_indices=np.sort(np.concatenate([fold0.training_indices, members])),
        validation_indices=np.setdiff1d(val, members),
    )
    with pytest.raises(PlatformError) as exc:
        build_default(frame, folds, make_predictions(frame, folds))
    assert exc.value.code == FOLD_ASSIGNMENT_INCOMPLETE


def test_mismatched_prediction_source_rows_fail_closed():
    frame = make_frame_2d(12)
    folds = make_folds(frame, "2d")
    predictions = make_predictions(frame, folds)

    missing = predictions.iloc[1:].reset_index(drop=True)
    with pytest.raises(PlatformError) as exc:
        build_default(frame, folds, missing)
    assert exc.value.code == OOF_PREDICTION_MISMATCH

    duplicated = pd.concat([predictions, predictions.iloc[[0]]], ignore_index=True)
    with pytest.raises(PlatformError) as exc:
        build_default(frame, folds, duplicated)
    assert exc.value.code == OOF_PREDICTION_MISMATCH

    wrong_fold = predictions.copy()
    first = wrong_fold.index[0]
    wrong_fold.loc[first, "fold"] = (int(wrong_fold.loc[first, "fold"]) + 1) % len(folds)
    with pytest.raises(PlatformError) as exc:
        build_default(frame, folds, wrong_fold)
    assert exc.value.code == OOF_PREDICTION_MISMATCH


def test_write_artifact_parquet_is_atomic_and_verified(tmp_path):
    frame = make_frame_2d(6)
    folds = make_folds(frame, "2d")
    artifacts = build_default(frame, folds, make_predictions(frame, folds))

    target = tmp_path / "nested" / "oof.parquet"
    sha256 = write_artifact_parquet(target, artifacts.oof)
    assert target.exists()
    assert sha256 == hashlib.sha256(target.read_bytes()).hexdigest()
    # 无临时文件残留，回读内容逐位一致
    leftovers = [p for p in target.parent.iterdir() if p.name != target.name]
    assert leftovers == []
    pd.testing.assert_frame_equal(pd.read_parquet(target), artifacts.oof)

    # 覆盖写：内容替换且哈希更新，仍无临时残留
    updated = artifacts.oof.assign(predicted=artifacts.oof["predicted"] + 1.0)
    sha256_v2 = write_artifact_parquet(target, updated)
    assert sha256_v2 != sha256
    assert sha256_v2 == hashlib.sha256(target.read_bytes()).hexdigest()
    pd.testing.assert_frame_equal(pd.read_parquet(target), updated)


def test_build_fold_assignments_returns_assignments_and_fingerprint():
    frame = make_frame_2d()
    folds = make_folds(frame, "2d")
    assignments, fingerprint = build_fold_assignments(
        frame, folds, dimension="2d", validation=SPEC_KFOLD, data_sha256=DATA_SHA256
    )
    assert list(assignments.columns) == ASSIGNMENT_COLUMNS
    assert len(fingerprint) == 64
    artifacts = build_default(frame, folds, make_predictions(frame, folds))
    assert artifacts.validation_fingerprint == fingerprint
    pd.testing.assert_frame_equal(artifacts.fold_assignments, assignments)


def test_build_oof_predictions_matches_composed_artifacts():
    frame = make_frame_2d()
    folds = make_folds(frame, "2d")
    predictions = make_predictions(frame, folds, nodata_rows=(3,))
    oof = build_oof_predictions(frame, folds, predictions, dimension="2d")
    artifacts = build_default(frame, folds, predictions)
    pd.testing.assert_frame_equal(oof, artifacts.oof)
