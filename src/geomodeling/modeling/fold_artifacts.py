"""Stable fold assignments and out-of-fold (OOF) residual records.

折分证据是 run 级事实：每个有效数据行恰好在一个折中担任验证样本，空间组
（2D 网格单元 / 3D 完整 XY 柱）在同一折内不得同时出现在训练与验证两侧。
泄漏检查不是警告——任何行级或组级重叠都以 ``FOLD_LEAKAGE_DETECTED``
结构化失败；验证覆盖不是"每行恰好一次"则以 ``FOLD_ASSIGNMENT_INCOMPLETE``
失败。折外残差只来自该点未参与训练的折外预测：候选预测的 ``source_row``
集合、折归属与折分计划不一致时以 ``OOF_PREDICTION_MISMATCH`` fail-closed。

``validation_fingerprint`` 规范化（数据集 standardized SHA-256 + 验证规格 +
逐行折分分配 + 有序验证 source_row 列表）后取 SHA-256，同输入必稳定。

Parquet 持久化沿用平台原子写约定：同级临时文件写入、回读校验、
``os.replace`` 原子替换，返回文件 SHA-256。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from geomodeling.modeling import splits
from geomodeling.modeling.contracts import Fold
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import Dimension, SpatialValidationSpec

FOLD_LEAKAGE_DETECTED = "FOLD_LEAKAGE_DETECTED"
FOLD_ASSIGNMENT_INCOMPLETE = "FOLD_ASSIGNMENT_INCOMPLETE"
OOF_PREDICTION_MISMATCH = "OOF_PREDICTION_MISMATCH"
FOLD_ARTIFACT_WRITE_FAILED = "FOLD_ARTIFACT_WRITE_FAILED"

OOF_COLUMNS = [
    "source_row",
    "fold_index",
    "x",
    "y",
    "z",
    "observed",
    "predicted",
    "residual",
    "absolute_error",
    "squared_error",
    "is_nodata",
]

ASSIGNMENT_COLUMNS = ["fold_index", "source_row", "group_key", "role", "leakage_detected"]

ROLE_TRAINING = "training"
ROLE_VALIDATION = "validation"


@dataclass(frozen=True)
class FoldArtifacts:
    """一次验证计划的不可变证据：逐行折分分配、折外残差记录与稳定指纹。"""

    fold_assignments: pd.DataFrame
    oof: pd.DataFrame
    validation_fingerprint: str

    @property
    def assignments(self) -> pd.DataFrame:
        return self.fold_assignments


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dimension_of(dimension: str | Dimension) -> str:
    return Dimension(dimension).value


def _spatial_groups(points: np.ndarray, dimension: str, spec: SpatialValidationSpec) -> np.ndarray:
    """空间组身份必须与 ``build_spatial_splits`` 的分组语义逐位一致。

    直接复用 splits 内部的分组助手（同包私有复用），避免在两处维护同一套
    2D 网格 / 3D 整 XY 柱规则而悄悄分叉。
    """

    if _dimension_of(dimension) == Dimension.THREE_D.value:
        return splits._groups_3d(points)
    if spec.method == "spatial_holdout":
        return splits._groups_2d(points, 3)
    return splits._groups_2d(points, spec.folds)


def _coord_columns(dimension: str) -> list[str]:
    return ["x", "y"] + (["z"] if _dimension_of(dimension) == Dimension.THREE_D.value else [])


def build_fold_assignments(
    frame: pd.DataFrame,
    folds: list[Fold],
    *,
    dimension: str,
    validation: SpatialValidationSpec,
    data_sha256: str,
) -> tuple[pd.DataFrame, str]:
    """构建 run 级逐行折分分配表并返回 ``(assignments, fingerprint)``。

    ``frame`` 为有效行帧（位置索引与 ``Fold`` 的 0 基行号对应）。泄漏或
    覆盖不完整时不返回部分证据，直接抛出结构化 ``PlatformError``。
    """

    n_rows = len(frame)
    source_rows = frame["source_row"].to_numpy(dtype="int64")
    if len(np.unique(source_rows)) != n_rows:
        raise PlatformError(
            FOLD_ASSIGNMENT_INCOMPLETE,
            "标准化帧 source_row 不唯一，无法建立稳定折分分配",
            {"row_count": n_rows},
        )
    fold_indices = [fold.index for fold in folds]
    if len(set(fold_indices)) != len(fold_indices):
        raise PlatformError(
            FOLD_ASSIGNMENT_INCOMPLETE,
            "折索引重复，折分计划不完整",
            {"fold_indices": fold_indices},
        )
    points = frame[_coord_columns(dimension)].to_numpy(dtype="float64")
    groups = _spatial_groups(points, dimension, validation)

    coverage = np.zeros(n_rows, dtype="int64")
    leakage_rows: list[np.ndarray] = []
    frames: list[pd.DataFrame] = []
    unassigned_any = False
    for fold in folds:
        train = np.asarray(fold.training_indices, dtype="int64")
        val = np.asarray(fold.validation_indices, dtype="int64")
        for label, indices in (("training", train), ("validation", val)):
            if indices.size and (indices.min() < 0 or indices.max() >= n_rows):
                raise PlatformError(
                    FOLD_ASSIGNMENT_INCOMPLETE,
                    f"折 {fold.index} 的{label}索引超出数据行范围",
                    {"fold": fold.index, "role": label, "row_count": n_rows},
                )
        train_mask = np.zeros(n_rows, dtype=bool)
        train_mask[train] = True
        val_mask = np.zeros(n_rows, dtype=bool)
        val_mask[val] = True
        coverage += np.bincount(val, minlength=n_rows) if val.size else np.zeros(n_rows, dtype="int64")

        unassigned_any = unassigned_any or bool((~(train_mask | val_mask)).any())
        # 行级泄漏：同一行既是训练又是验证；组级泄漏：同一空间组横跨两侧
        leaked_groups = set(groups[val_mask].tolist()) & set(groups[train_mask].tolist())
        row_leakage = (train_mask & val_mask) | np.isin(groups, list(leaked_groups))
        leakage_rows.append(row_leakage)
        frames.append(
            pd.DataFrame(
                {
                    "fold_index": np.full(n_rows, fold.index, dtype="int64"),
                    "source_row": source_rows,
                    "group_key": groups.astype("int64"),
                    "role": np.where(val_mask, ROLE_VALIDATION, ROLE_TRAINING),
                    "leakage_detected": row_leakage,
                }
            )
        )

    assignments = pd.concat(frames, ignore_index=True)[ASSIGNMENT_COLUMNS]
    if any(mask.any() for mask in leakage_rows):
        raise PlatformError(
            FOLD_LEAKAGE_DETECTED,
            "折分泄漏：同一空间组同时出现在同一折的训练与验证中",
            {"leaked_row_count": int(sum(int(mask.sum()) for mask in leakage_rows))},
        )
    # k-fold 中每个数据行必须恰好担任一次验证；holdout 只有留出子集有折外
    # 预测，仅要求验证归属不重复且非空（训练行本就无折外记录）。
    if validation.method == "spatial_kfold":
        incomplete = bool((coverage != 1).any())
    else:
        incomplete = bool((coverage > 1).any()) or not bool((coverage > 0).any())
    if unassigned_any or incomplete:
        raise PlatformError(
            FOLD_ASSIGNMENT_INCOMPLETE,
            "验证覆盖不完整：k-fold 要求每行恰好验证一次，holdout 要求留出集非空且不重复",
            {
                "never_validated_count": int((coverage == 0).sum()),
                "over_validated_count": int((coverage > 1).sum()),
            },
        )

    validation_source_rows = sorted(int(row) for row in source_rows[coverage > 0])
    payload = {
        "dataset_sha256": data_sha256,
        "validation": validation.model_dump(mode="json"),
        "fold_assignments": assignments[ASSIGNMENT_COLUMNS[:-1]].values.tolist(),
        "validation_source_rows": validation_source_rows,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return assignments, fingerprint


def build_oof_predictions(
    frame: pd.DataFrame,
    folds: list[Fold],
    candidate_predictions: pd.DataFrame,
    *,
    dimension: str,
) -> pd.DataFrame:
    """把候选的折外预测规范化为 OOF 残差记录（列精确为 ``OOF_COLUMNS``）。

    ``candidate_predictions`` 须含 ``source_row/fold/prediction/is_nodata``
    （runner 的原生产出，``truth`` 列可选）。任何与折分计划不一致的
    source_row 集合或折归属都以 ``OOF_PREDICTION_MISMATCH`` 失败。
    """

    n_rows = len(frame)
    source_rows = frame["source_row"].to_numpy(dtype="int64")
    validation_fold = np.full(n_rows, -1, dtype="int64")
    for fold in folds:
        val = np.asarray(fold.validation_indices, dtype="int64")
        validation_fold[val] = fold.index
    covered = validation_fold >= 0
    expected_source_rows = source_rows[covered]
    if expected_source_rows.size == 0:
        raise PlatformError(
            FOLD_ASSIGNMENT_INCOMPLETE,
            "折分计划没有任何验证样本，无法建立折外记录",
        )

    required = {"source_row", "fold", "prediction", "is_nodata"}
    missing_columns = sorted(required - set(candidate_predictions.columns))
    if missing_columns:
        raise PlatformError(
            OOF_PREDICTION_MISMATCH,
            "候选预测缺少必需列",
            {"missing_columns": missing_columns},
        )
    predictions = candidate_predictions
    pred_rows = predictions["source_row"].to_numpy(dtype="int64")
    if len(np.unique(pred_rows)) != len(pred_rows) or set(pred_rows.tolist()) != set(
        expected_source_rows.tolist()
    ):
        raise PlatformError(
            OOF_PREDICTION_MISMATCH,
            "候选预测 source_row 集合与折分计划的验证样本不一致",
            {
                "prediction_rows": int(len(pred_rows)),
                "expected_rows": int(expected_source_rows.size),
                "prediction_unique_rows": int(len(np.unique(pred_rows))),
            },
        )

    position_of = {int(row): position for position, row in enumerate(source_rows)}
    positions = np.array([position_of[int(row)] for row in pred_rows], dtype="int64")
    pred_fold = predictions["fold"].to_numpy(dtype="int64")
    expected_fold = validation_fold[positions]
    if not np.array_equal(pred_fold, expected_fold):
        raise PlatformError(
            OOF_PREDICTION_MISMATCH,
            "候选预测的折归属与折分计划不一致",
            {"mismatched_rows": int((pred_fold != expected_fold).sum())},
        )

    is_nodata = predictions["is_nodata"].to_numpy(dtype=bool)
    observed = frame["value"].to_numpy(dtype="float64")[positions]
    predicted = predictions["prediction"].to_numpy(dtype="float64")
    predicted = np.where(is_nodata, np.nan, predicted)
    residual = predicted - observed
    if _dimension_of(dimension) == Dimension.THREE_D.value:
        z_values = frame["z"].to_numpy(dtype="float64")[positions]
    else:
        z_values = np.full(len(pred_rows), np.nan)

    order = np.lexsort((pred_rows, pred_fold))
    oof = pd.DataFrame(
        {
            "source_row": pred_rows[order],
            "fold_index": pred_fold[order],
            "x": frame["x"].to_numpy(dtype="float64")[positions][order],
            "y": frame["y"].to_numpy(dtype="float64")[positions][order],
            "z": z_values[order],
            "observed": observed[order],
            "predicted": predicted[order],
            "residual": residual[order],
            "absolute_error": np.abs(residual)[order],
            "squared_error": (residual**2)[order],
            "is_nodata": is_nodata[order],
        }
    )
    return oof.reset_index(drop=True)[OOF_COLUMNS]


def build_fold_artifacts(
    frame: pd.DataFrame,
    folds: list[Fold],
    candidate_predictions: pd.DataFrame,
    *,
    dimension: str,
    data_sha256: str,
    validation: SpatialValidationSpec,
) -> FoldArtifacts:
    """组合折分分配与候选 OOF 记录为一份完整折证据。"""

    assignments, fingerprint = build_fold_assignments(
        frame, folds, dimension=dimension, validation=validation, data_sha256=data_sha256
    )
    oof = build_oof_predictions(frame, folds, candidate_predictions, dimension=dimension)
    return FoldArtifacts(
        fold_assignments=assignments, oof=oof, validation_fingerprint=fingerprint
    )


def write_artifact_parquet(target: Path, frame: pd.DataFrame) -> str:
    """原子写 Parquet 工件：同级临时文件 + 回读校验 + ``os.replace``。

    成功返回最终文件的 SHA-256；失败清理临时文件且不触碰原目标。
    """

    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{target.stem}-", suffix=".parquet", dir=target.parent
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        frame.to_parquet(tmp_path, index=False)
        reread = pd.read_parquet(tmp_path)
        if list(reread.columns) != list(frame.columns):
            raise PlatformError(
                FOLD_ARTIFACT_WRITE_FAILED,
                "折证据工件回读 schema 校验失败",
                {"columns": [str(c) for c in reread.columns]},
            )
        if len(reread) != len(frame):
            raise PlatformError(FOLD_ARTIFACT_WRITE_FAILED, "折证据工件回读行数校验失败")
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return sha256_file(target)
