"""Compatible two-candidate comparison on registered evidence (设计 §4.3/§13.3).

两个候选只有同时满足全部兼容条件才允许显示指标差值：同一
``dataset_version_id``、同一验证折分指纹、同一验证目标行身份（OOF
``source_row`` 集合）、同一公共有效掩膜定义（在所选候选的交集上重算）、
值单位一致（value_name/value_unit 来自数据集 profile）。不兼容仍可分别
打开，但 ``metric_deltas`` 必须为 None 且 ``mismatches`` 列出具体不符字
段名——绝不显示 RMSE/R²/覆盖率差值。

跨实验比较只读两候选已登记的 OOF 工件，构造所选候选的公共有效交集
（``(~a.is_nodata) & (~b.is_nodata)``），在交集上重算双方
MAE/RMSE/R²/Bias 与差值（first − second）；绝不复用各自实验内不同的公
共掩膜。场差只在相同网格轴与两者共同有效网格节点上给出有界摘要
（mean/max_abs）；轴不一致或共同有效节点为空 → 不生成差值。

验证折分指纹从已登记的 fold_assignments 工件重算：规范化载荷与
``fold_artifacts.build_fold_assignments`` 逐位一致（数据集 standardized
SHA-256 + 验证规格 + 逐行折分分配 + 有序验证 source_row 列表），同输入
必稳定。comparison fingerprint = 两候选指纹 + 公共行身份的规范化哈希
（确定性；first/second 有序，交换顺序指纹不同）。
"""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from geomodeling.modeling.fold_artifacts import ASSIGNMENT_COLUMNS, ROLE_VALIDATION
from geomodeling.modeling.metrics import compute_metrics
from geomodeling.platform.schemas import ContractModel, SpatialValidationSpec

__all__ = [
    "METRIC_DELTA_KEYS",
    "CandidateComparison",
    "GridDifferenceSummary",
    "align_oof_pair",
    "comparison_fingerprint",
    "grid_axes_identical",
    "grid_difference_summary",
    "pair_common_valid_mask",
    "pair_metric_deltas",
    "validation_fingerprint_from_assignments",
]

#: 交集上重算并做差（first − second）的指标键
METRIC_DELTA_KEYS = ("mae", "rmse", "r2", "bias")


class GridDifferenceSummary(ContractModel):
    """场差有界摘要（first − second）：只在共同有效网格节点上计算。"""

    common_valid_count: int
    mean: float
    max_abs: float


class CandidateComparison(ContractModel):
    """双候选比较结论：兼容判定、不符字段、交集指标差与有界场差摘要。"""

    first_result_id: str
    second_result_id: str
    compatible: bool
    mismatches: list[str]
    common_valid_count: int | None
    metric_deltas: dict[str, float] | None
    grid_difference_available: bool
    grid_difference: GridDifferenceSummary | None = None
    comparison_fingerprint: str = ""


def validation_fingerprint_from_assignments(
    assignments: pd.DataFrame, *, validation: SpatialValidationSpec, data_sha256: str
) -> str:
    """从已登记的 fold_assignments 工件重算验证折分指纹。

    规范化载荷与 ``build_fold_assignments`` 逐位一致；验证目标行身份即分
    配表中担任过验证角色的有序 source_row 列表。
    """

    validation_source_rows = sorted(
        int(row)
        for row in assignments.loc[assignments["role"] == ROLE_VALIDATION, "source_row"].unique()
    )
    payload = {
        "dataset_sha256": data_sha256,
        "validation": validation.model_dump(mode="json"),
        "fold_assignments": assignments[ASSIGNMENT_COLUMNS[:-1]].values.tolist(),
        "validation_source_rows": validation_source_rows,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def comparison_fingerprint(
    first_fingerprint: str, second_fingerprint: str, common_source_rows
) -> str:
    """comparison fingerprint = 两候选指纹 + 公共行身份的规范化哈希（确定性）。"""

    payload = {
        "first_fingerprint": first_fingerprint,
        "second_fingerprint": second_fingerprint,
        "common_source_rows": sorted(int(row) for row in common_source_rows),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def align_oof_pair(
    first_oof: pd.DataFrame, second_oof: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """按 source_row 对齐两份 OOF 记录（兼容对集合一致，对齐后逐行对应）。"""

    first = first_oof.sort_values("source_row").reset_index(drop=True)
    second = second_oof.sort_values("source_row").reset_index(drop=True)
    return first, second


def pair_common_valid_mask(first_oof: pd.DataFrame, second_oof: pd.DataFrame) -> np.ndarray:
    """所选候选的公共有效交集（§4.3：绝不复用各 run 预存的公共掩膜）。"""

    return (~first_oof["is_nodata"].to_numpy(dtype=bool)) & (
        ~second_oof["is_nodata"].to_numpy(dtype=bool)
    )


def pair_metric_deltas(
    first_oof: pd.DataFrame, second_oof: pd.DataFrame, mask: np.ndarray
) -> tuple[int, dict[str, float]]:
    """在公共有效交集上重算双方指标，返回 ``(common_valid_count, 差值)``。

    差值方向为 first − second；观测值取自同一数据版本的 OOF 记录（兼容
    门禁已保证两候选 source_row 与数据集一致）。
    """

    truth = first_oof["observed"].to_numpy(dtype="float64")
    first_summary = compute_metrics(
        truth,
        first_oof["predicted"].to_numpy(dtype="float64"),
        mask,
        is_nodata=first_oof["is_nodata"].to_numpy(dtype=bool),
    )
    second_summary = compute_metrics(
        truth,
        second_oof["predicted"].to_numpy(dtype="float64"),
        mask,
        is_nodata=second_oof["is_nodata"].to_numpy(dtype=bool),
    )
    deltas = {
        key: float(getattr(first_summary, key) - getattr(second_summary, key))
        for key in METRIC_DELTA_KEYS
    }
    return int(mask.sum()), deltas


def grid_axes_identical(first_axes: tuple, second_axes: tuple) -> bool:
    """网格身份：逐轴完全一致（轴一致即 shape/bounds 一致，分辨率由轴回算）。"""

    if len(first_axes) != len(second_axes):
        return False
    return all(
        np.array_equal(np.asarray(first, dtype="float64"), np.asarray(second, dtype="float64"))
        for first, second in zip(first_axes, second_axes)
    )


def grid_difference_summary(
    first_values: np.ndarray,
    first_is_nodata: np.ndarray,
    second_values: np.ndarray,
    second_is_nodata: np.ndarray,
) -> GridDifferenceSummary | None:
    """场差有界摘要（first − second）：只在共同有效网格节点上计算。

    共同有效节点为空时不生成差值（返回 None），绝不对空集取均值冒充 0。
    """

    common = (~np.asarray(first_is_nodata, dtype=bool)) & (
        ~np.asarray(second_is_nodata, dtype=bool)
    )
    count = int(common.sum())
    if count == 0:
        return None
    difference = (
        np.asarray(first_values, dtype="float64")[common]
        - np.asarray(second_values, dtype="float64")[common]
    )
    return GridDifferenceSummary(
        common_valid_count=count,
        mean=float(difference.mean()),
        max_abs=float(np.abs(difference).max()),
    )
