"""Optional modeling provenance sidecar and per-line/point diagnostics.

A dataset profile may declare a provenance artifact (the v0.5 microseismic
import writes ``derived/modeling_provenance.parquet`` and records the
relative key ``modeling_provenance`` in the profile). Once declared, the
sidecar must exist, carry the full declared schema, key every row by a
unique ``source_row`` and cover every standardized row — anything less
fails closed with a structured error and the run cannot succeed. When the
profile does not declare it, loading returns ``None`` and generic runs stay
byte-identical: no ``group_diagnostics`` key is ever added.

Diagnostics join candidate predictions to the sidecar by stable
``source_row`` and recompute RMSE/MAE/R²/Bias/count per survey line and
survey point on the *public common-valid mask* only. They are evidence for
the leaderboard and the export contract; they never feed ``best``
selection, coverage, or the public ranking.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from geomodeling.platform.errors import PlatformError
from geomodeling.platform.settings import PlatformSettings

PROVENANCE_ARTIFACT_MISSING = "PROVENANCE_ARTIFACT_MISSING"
PROVENANCE_ARTIFACT_INVALID = "PROVENANCE_ARTIFACT_INVALID"
PROVENANCE_SCHEMA_MISMATCH = "PROVENANCE_SCHEMA_MISMATCH"
PROVENANCE_DUPLICATE_SOURCE_ROW = "PROVENANCE_DUPLICATE_SOURCE_ROW"
PROVENANCE_SOURCE_ROW_UNMATCHED = "PROVENANCE_SOURCE_ROW_UNMATCHED"

# profile 中的显式声明键（微震导入写入相对路径 "derived/modeling_provenance.parquet"）。
PROFILE_DECLARATION_KEY = "modeling_provenance"

# 与微震派生产物 modeling_provenance.parquet 的实际 12 列一致（Task 5 契约）：
# 声明即承诺完整模式，缺列即 fail closed。
REQUIRED_PROVENANCE_COLUMNS = (
    "source_row",
    "point_id",
    "line_id",
    "x_local_m",
    "y_local_m",
    "z_local_m",
    "vx_km_s",
    "source_sample_ids",
    "sample_count",
    "vx_min_km_s",
    "vx_max_km_s",
    "vx_sample_std_km_s",
)

# group_diagnostics 的两类分组：测线 line_id、测点 point_id。
GROUP_COLUMNS = {"line": "line_id", "point": "point_id"}


def load_optional_provenance(
    settings: PlatformSettings,
    case_id: str,
    dataset_id: str,
    profile: dict[str, Any],
) -> pd.DataFrame | None:
    """Load the declared provenance sidecar, or ``None`` when undeclared.

    未声明（profile 无显式 ``modeling_provenance`` 键）一律返回 ``None``，
    通用数据集行为逐位不变。声明之后文件缺失、无法解析、列不齐或
    ``source_row`` 为空/不唯一，均抛出结构化 :class:`PlatformError`。
    """

    declaration = profile.get(PROFILE_DECLARATION_KEY)
    if not declaration:
        return None
    path = settings.modeling_provenance(case_id, dataset_id)
    if not path.exists():
        raise PlatformError(
            PROVENANCE_ARTIFACT_MISSING,
            "数据集声明了建模来源工件，但 modeling_provenance.parquet 不存在",
            {"dataset_id": dataset_id, "declaration": declaration},
            http_status=422,
        )
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        raise PlatformError(
            PROVENANCE_ARTIFACT_INVALID,
            "建模来源工件无法解析",
            {"dataset_id": dataset_id, "error": str(exc)[:200]},
            http_status=422,
        ) from exc
    missing = [column for column in REQUIRED_PROVENANCE_COLUMNS if column not in frame.columns]
    if missing:
        raise PlatformError(
            PROVENANCE_SCHEMA_MISMATCH,
            "建模来源工件缺少声明列",
            {"dataset_id": dataset_id, "missing_columns": missing},
            http_status=422,
        )
    if frame["source_row"].isna().any() or frame["source_row"].duplicated().any():
        raise PlatformError(
            PROVENANCE_DUPLICATE_SOURCE_ROW,
            "建模来源工件的 source_row 必须非空且唯一",
            {"dataset_id": dataset_id, "row_count": int(len(frame))},
            http_status=422,
        )
    return frame


def ensure_provenance_coverage(provenance: pd.DataFrame, source_rows: pd.Series) -> None:
    """Every standardized row must be attributable to one provenance row."""

    known = set(provenance["source_row"].tolist())
    unmatched = sorted({int(row) for row in source_rows.tolist() if row not in known})
    if unmatched:
        raise PlatformError(
            PROVENANCE_SOURCE_ROW_UNMATCHED,
            "建模来源工件未覆盖全部标准化数据行",
            {"unmatched_count": len(unmatched), "unmatched_source_rows": unmatched[:20]},
            http_status=422,
        )


def compute_group_diagnostics(
    predictions: pd.DataFrame,
    provenance: pd.DataFrame,
    common_mask: np.ndarray,
) -> dict[str, dict[str, dict[str, Any]]]:
    """RMSE/MAE/R²/Bias/count per survey line and point on the common mask.

    ``predictions`` carries one row per validation point keyed by stable
    ``source_row``; ``common_mask`` is the public common-valid mask shared
    by every succeeded candidate. A group with no common-valid point keeps
    ``count`` 0 and null metrics instead of borrowing the candidate's own
    valid set.
    """

    joined = predictions[["source_row"]].merge(
        provenance[["source_row", "line_id", "point_id"]],
        on="source_row",
        how="left",
        validate="one_to_one",
    )
    truth = predictions["truth"].to_numpy(dtype="float64")
    prediction = predictions["prediction"].to_numpy(dtype="float64")
    mask = np.asarray(common_mask, dtype=bool)
    return {
        kind: _group_metrics(truth, prediction, mask, joined[column].to_numpy())
        for kind, column in GROUP_COLUMNS.items()
    }


def _group_metrics(
    truth: np.ndarray,
    prediction: np.ndarray,
    mask: np.ndarray,
    groups: np.ndarray,
) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for key in pd.unique(groups):
        selector = mask & (groups == key)
        count = int(selector.sum())
        if count == 0:
            summary[str(key)] = {"rmse": None, "mae": None, "r2": None, "bias": None, "count": 0}
            continue
        errors = prediction[selector] - truth[selector]
        ss_res = float((errors**2).sum())
        centered = truth[selector] - truth[selector].mean()
        ss_tot = float((centered**2).sum())
        if ss_tot == 0.0:
            r2 = 1.0 if ss_res == 0.0 else 0.0
        else:
            r2 = 1.0 - ss_res / ss_tot
        summary[str(key)] = {
            "rmse": float(np.sqrt((errors**2).mean())),
            "mae": float(np.abs(errors).mean()),
            "r2": float(r2),
            "bias": float(errors.mean()),
            "count": count,
        }
    return summary
