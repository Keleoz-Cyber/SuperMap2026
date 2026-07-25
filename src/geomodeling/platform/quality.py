"""Deterministic dataset quality evaluation.

Blockers stop experiments outright; warnings require an exact client-side
confirmation before experiments may start. Evaluation never silently
deletes, interpolates, clamps, or replaces a value — every statistic is
derived from the immutable standardized Parquet.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import Dimension, FieldMapping

GEOGRAPHIC_NOT_PROJECTED = "GEOGRAPHIC_NOT_PROJECTED"

# blocker codes
MISSING_NUMERIC = "MISSING_NUMERIC"
NON_FINITE = "NON_FINITE"
NODATA_VALUE = "NODATA_VALUE"
CONFLICTING_COORDINATE = "CONFLICTING_COORDINATE"
INSUFFICIENT_VALID_POINTS = "INSUFFICIENT_VALID_POINTS"
DEGENERATE_EXTENT = "DEGENERATE_EXTENT"

# warning codes
DUPLICATE_ROWS = "DUPLICATE_ROWS"
EXTREME_VALUES = "EXTREME_VALUES"
SPARSE_DISTRIBUTION = "SPARSE_DISTRIBUTION"
SUSPICIOUS_MAGNITUDE = "SUSPICIOUS_MAGNITUDE"
HIGH_INVALID_RATIO = "HIGH_INVALID_RATIO"

BLOCKER_CODES = (
    MISSING_NUMERIC,
    NON_FINITE,
    NODATA_VALUE,
    CONFLICTING_COORDINATE,
    INSUFFICIENT_VALID_POINTS,
    DEGENERATE_EXTENT,
)
WARNING_CODES = (
    DUPLICATE_ROWS,
    EXTREME_VALUES,
    SPARSE_DISTRIBUTION,
    SUSPICIOUS_MAGNITUDE,
    HIGH_INVALID_RATIO,
)

NODATA_SENTINEL = -9999
MIN_VALID_2D = 10
MIN_VALID_3D = 20
INVALID_RATIO_THRESHOLD = 0.05
MAD_OUTLIER_K = 6.0
SPARSE_UNIQUE_THRESHOLD = 3
MAGNITUDE_COORD_LIMIT = 1e7
MAGNITUDE_VALUE_LIMIT = 1e9


def _issue(code: str, kind: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "kind": kind, "message": message, "details": details or {}}


def evaluate_quality(
    *,
    frame: pd.DataFrame | None,
    mapping: FieldMapping,
    source_sha256: str,
    standardized_sha256: str,
) -> dict[str, Any]:
    """Evaluate a standardized dataset against the quality contract.

    ``frame`` is the standardized table (``source_row, x, y, z, value,
    is_numeric_valid``). Blockers raise no exceptions; they mark the report
    ``blocked``. Geographic mapping without projection is a hard
    PlatformError because no standardized artifact may exist in that state.
    """

    if mapping.coordinate_kind == "geographic":
        raise PlatformError(
            GEOGRAPHIC_NOT_PROJECTED,
            "经纬度坐标必须先完成投影转换才能建模；v0.4 暂不支持直接以角度插值",
            {"coordinate_kind": mapping.coordinate_kind},
        )
    assert frame is not None, "frame is required for non-geographic mappings"

    issues: list[dict[str, Any]] = []
    required_numeric = ["x", "y", "value"] + (["z"] if mapping.z else [])
    numeric_block = frame[required_numeric].to_numpy(dtype="float64", na_value=np.nan)
    finite_rows = np.isfinite(numeric_block).all(axis=1)
    valid = frame.loc[finite_rows]
    row_count = len(frame)
    valid_count = len(valid)
    invalid_count = row_count - valid_count

    coord_cols = ["x", "y"] + (["z"] if mapping.z else [])
    group_keys = [valid[col] for col in coord_cols]
    if valid_count:
        grouped = valid.groupby(coord_cols, sort=False)["value"]
        conflict_count = int((grouped.nunique() > 1).sum())
    else:
        conflict_count = 0
    duplicate_count = int(frame.duplicated(subset=coord_cols + ["value"]).sum())
    unique_coordinate_count = int(valid[coord_cols].drop_duplicates().shape[0]) if valid_count else 0

    ranges: dict[str, list[float] | None] = {}
    for col in required_numeric:
        if valid_count:
            ranges[col] = [float(valid[col].min()), float(valid[col].max())]
        else:
            ranges[col] = None

    # ---------------------------------------------------------------- blockers
    if valid_count == 0:
        issues.append(_issue(MISSING_NUMERIC, "blocker", "必填坐标/属性全部无法解析为有限数值"))

    if row_count and not finite_rows.all():
        has_inf = np.isinf(numeric_block).any()
        if has_inf:
            issues.append(_issue(NON_FINITE, "blocker", "必填字段含 Infinity"))

    if valid_count and bool((valid["value"] == NODATA_SENTINEL).any()):
        count = int((valid["value"] == NODATA_SENTINEL).sum())
        issues.append(
            _issue(NODATA_VALUE, "blocker", "属性值含 -9999 NoData 哨兵", {"count": count})
        )

    if conflict_count:
        issues.append(
            _issue(
                CONFLICTING_COORDINATE,
                "blocker",
                "同一坐标存在冲突属性值且未选择处理方式",
                {"conflict_count": conflict_count},
            )
        )

    min_valid = MIN_VALID_3D if mapping.dimension == Dimension.THREE_D else MIN_VALID_2D
    if 0 < valid_count < min_valid:
        issues.append(
            _issue(
                INSUFFICIENT_VALID_POINTS,
                "blocker",
                f"有效样本 {valid_count} 少于算法前置要求 {min_valid}",
                {"valid_row_count": valid_count, "min_required": min_valid},
            )
        )

    if valid_count:
        for col in coord_cols:
            lo, hi = ranges[col]  # type: ignore[index]
            if hi == lo:
                issues.append(
                    _issue(DEGENERATE_EXTENT, "blocker", f"坐标轴 {col} 范围退化为 0", {"axis": col})
                )

    # ---------------------------------------------------------------- warnings
    if duplicate_count:
        issues.append(
            _issue(DUPLICATE_ROWS, "warning", "存在精确重复的坐标/属性记录", {"duplicate_count": duplicate_count})
        )

    if valid_count >= 4:
        median = float(valid["value"].median())
        mad = float((valid["value"] - median).abs().median())
        if mad > 0:
            outliers = valid.loc[(valid["value"] - median).abs() > MAD_OUTLIER_K * mad, "value"]
            if len(outliers):
                issues.append(
                    _issue(
                        EXTREME_VALUES,
                        "warning",
                        "存在统计离群候选值（MAD 规则，仅报告不删除）",
                        {"outlier_count": int(len(outliers)), "median": median, "mad": mad},
                    )
                )

    if valid_count:
        sparse_axes = [col for col in ("x", "y") if valid[col].nunique() < SPARSE_UNIQUE_THRESHOLD]
        if sparse_axes:
            issues.append(
                _issue(SPARSE_DISTRIBUTION, "warning", "坐标轴分布稀疏", {"axes": sparse_axes})
            )

    if valid_count:
        coord_max = max(abs(float(valid[c].abs().max())) for c in ("x", "y"))
        value_max = abs(float(valid["value"].abs().max()))
        if coord_max > MAGNITUDE_COORD_LIMIT or value_max > MAGNITUDE_VALUE_LIMIT:
            issues.append(
                _issue(
                    SUSPICIOUS_MAGNITUDE,
                    "warning",
                    "坐标或属性量级可疑（请确认单位）",
                    {"coord_abs_max": coord_max, "value_abs_max": value_max},
                )
            )

    if row_count and invalid_count / row_count > INVALID_RATIO_THRESHOLD:
        issues.append(
            _issue(
                HIGH_INVALID_RATIO,
                "warning",
                f"无效源行占比 {invalid_count / row_count:.1%} 超过 5%",
                {"invalid_row_count": invalid_count, "row_count": row_count},
            )
        )

    blockers = [i for i in issues if i["kind"] == "blocker"]
    warnings = [i for i in issues if i["kind"] == "warning"]
    status = "blocked" if blockers else ("warnings" if warnings else "passed")

    all_checks = [
        {"code": code, "kind": "blocker", "passed": not any(i["code"] == code for i in blockers)}
        for code in BLOCKER_CODES
    ] + [
        {"code": code, "kind": "warning", "passed": not any(i["code"] == code for i in warnings)}
        for code in WARNING_CODES
    ]

    return {
        "status": status,
        "checks": all_checks,
        "issues": issues,
        "statistics": {
            "ranges": ranges,
            "unique_coordinate_count": unique_coordinate_count,
            "duplicate_count": duplicate_count,
            "conflict_count": conflict_count,
        },
        "valid_row_count": valid_count,
        "invalid_row_count": invalid_count,
        "row_count": row_count,
        "source_sha256": source_sha256,
        "standardized_sha256": standardized_sha256,
        "confirmed": not warnings,
        "confirmed_issue_codes": [],
    }


def open_warning_codes(report: dict[str, Any]) -> set[str]:
    """Warning codes currently requiring client confirmation."""

    if report.get("status") != "warnings":
        return set()
    return {i["code"] for i in report["issues"] if i["kind"] == "warning"}
