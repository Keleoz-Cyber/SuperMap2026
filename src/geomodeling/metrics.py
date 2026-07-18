from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .io import parse_point_xy, read_csv
from .schemas import MetricSummary
from .validation import column_id

DEPTH_EDGES = [-840.0, -630.0, -420.0, -210.0, 0.0]
DEPTH_LABELS = [
    "深部 [-840,-630) m",
    "中深部 [-630,-420) m",
    "中浅部 [-420,-210) m",
    "浅部 [-210,0] m",
]


def read_validation_truth(path: str | Path) -> pd.DataFrame:
    df = read_csv(path)[["X", "Y", "Z", "RHO"]].apply(pd.to_numeric, errors="coerce")
    result = pd.DataFrame(
        {
            "point_id": [str(index) for index in range(len(df))],
            "x": df["X"],
            "y": df["Y"],
            "z": df["Z"],
            "rho_true": df["RHO"],
        }
    )
    result["column_id"] = [column_id(row.x, row.y) for row in result.itertuples(index=False)]
    result["depth_band"] = pd.cut(result["z"], bins=DEPTH_EDGES, labels=DEPTH_LABELS, right=False, include_lowest=True)
    return result


def import_prediction_csv(
    path: str | Path,
    validation: pd.DataFrame,
    model_id: str,
    nodata_value: float = -9999,
    xy_tolerance: float = 1e-8,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw = read_csv(path)
    required = {"SmUserID", "Attribute", "Geometry"}
    missing = sorted(required - set(raw.columns))
    if missing:
        raise ValueError(f"prediction file missing required fields: {missing}")
    if len(raw) != len(validation):
        raise ValueError(f"prediction row count {len(raw)} does not match validation row count {len(validation)}")
    xy = raw["Geometry"].map(parse_point_xy)
    attribute = pd.to_numeric(raw["Attribute"], errors="coerce")
    pred_x = pd.Series([item[0] for item in xy], index=raw.index, dtype=float)
    pred_y = pd.Series([item[1] for item in xy], index=raw.index, dtype=float)
    mismatch = (pred_x - validation["x"]).abs().gt(xy_tolerance) | (pred_y - validation["y"]).abs().gt(xy_tolerance)
    is_nodata = attribute.eq(nodata_value) | ~np.isfinite(attribute)
    rho_pred = attribute.where(~is_nodata, np.nan)
    result = validation.copy()
    result["rho_pred"] = rho_pred
    result["is_nodata"] = is_nodata.to_numpy(dtype=bool)
    result["error"] = result["rho_pred"] - result["rho_true"]
    result["abs_error"] = result["error"].abs()
    result["relative_error"] = result["error"] / result["rho_true"]
    result["model_id"] = model_id
    quality = {
        "xy_mismatch_count": int(mismatch.sum()),
        "row_count": int(len(raw)),
        "nodata_count": int(is_nodata.sum()),
        "valid_count": int((~is_nodata).sum()),
    }
    return result, quality


def compute_metric_summary(
    truth: pd.Series,
    pred: pd.Series,
    model: str,
    valid_mask: pd.Series | None = None,
) -> MetricSummary:
    base_mask = np.isfinite(truth) & np.isfinite(pred)
    mask = base_mask if valid_mask is None else (valid_mask & base_mask)
    n_total = int(len(truth))
    n_valid = int(mask.sum())
    n_nodata = n_total - n_valid
    if n_valid == 0:
        values = {key: float("nan") for key in ["mae", "rmse", "r2", "median_abs_error", "mean_abs_relative_error", "median_abs_relative_error", "log10_rmse", "bias", "p90_abs_error"]}
    else:
        y = truth[mask].astype(float)
        p = pred[mask].astype(float)
        error = p - y
        abs_error = error.abs()
        sse = float((error**2).sum())
        sst = float(((y - y.mean()) ** 2).sum())
        positive = (y > 0) & (p > 0)
        if positive.any():
            log10_rmse = float(np.sqrt(np.mean((np.log10(p[positive]) - np.log10(y[positive])) ** 2)))
        else:
            log10_rmse = float("nan")
        values = {
            "mae": float(abs_error.mean()),
            "rmse": float(np.sqrt(np.mean(error**2))),
            "r2": float(1 - sse / sst) if sst else float("nan"),
            "median_abs_error": float(abs_error.median()),
            "mean_abs_relative_error": float((abs_error / y).mean()),
            "median_abs_relative_error": float((abs_error / y).median()),
            "log10_rmse": log10_rmse,
            "bias": float(error.mean()),
            "p90_abs_error": float(np.percentile(abs_error, 90)),
        }
    return MetricSummary(
        model=model,
        n_total=n_total,
        n_valid=n_valid,
        n_nodata=n_nodata,
        coverage_rate=float(n_valid / n_total) if n_total else float("nan"),
        **values,
    )


def common_valid_mask(predictions: dict[str, pd.DataFrame]) -> pd.Series:
    mask: pd.Series | None = None
    for df in predictions.values():
        valid = ~df["is_nodata"]
        mask = valid if mask is None else (mask & valid)
    if mask is None:
        raise ValueError("no prediction frames provided")
    return mask


def compute_common_metric_summaries(predictions: dict[str, pd.DataFrame]) -> dict[str, MetricSummary]:
    mask = common_valid_mask(predictions)
    return {
        model: compute_metric_summary(df["rho_true"], df["rho_pred"], model, valid_mask=mask)
        for model, df in predictions.items()
    }


def compare_metric_summaries(
    summaries: dict[str, MetricSummary],
    baseline_path: str | Path,
    tolerance: float,
) -> dict[str, Any]:
    baseline = read_csv(baseline_path)
    fields = [
        "n_total",
        "n_valid",
        "n_nodata",
        "coverage_rate",
        "mae",
        "rmse",
        "r2",
        "median_abs_error",
        "mean_abs_relative_error",
        "median_abs_relative_error",
        "log10_rmse",
        "bias",
        "p90_abs_error",
    ]
    differences = []
    for row in baseline.itertuples(index=False):
        model = getattr(row, "model")
        if model not in summaries:
            differences.append({"model": model, "field": "model", "expected": "present", "actual": "missing", "passed": False})
            continue
        actual = summaries[model].model_dump()
        for field in fields:
            expected = getattr(row, field)
            actual_value = actual[field]
            if isinstance(expected, (int, np.integer)):
                passed = int(actual_value) == int(expected)
            else:
                passed = math.isclose(float(actual_value), float(expected), rel_tol=0.0, abs_tol=tolerance)
            if not passed:
                differences.append(
                    {
                        "model": model,
                        "field": field,
                        "expected": float(expected),
                        "actual": float(actual_value),
                        "passed": False,
                    }
                )
    return {"passed": not differences, "differences": differences, "models_checked": int(len(baseline))}


def summarize_group_metrics(df: pd.DataFrame, group_column: str, mask: pd.Series) -> pd.DataFrame:
    rows = []
    for name, group in df.groupby(group_column, observed=True):
        group_mask = mask.loc[group.index]
        valid = group[group_mask]
        n_total = int(len(group))
        n_valid = int(len(valid))
        if n_valid:
            error = valid["rho_pred"] - valid["rho_true"]
            abs_error = error.abs()
            mae = float(abs_error.mean())
            rmse = float(np.sqrt(np.mean(error**2)))
            bias = float(error.mean())
        else:
            mae = rmse = bias = float("nan")
        rows.append(
            {
                group_column: name,
                "n_total": n_total,
                "n_valid": n_valid,
                "coverage_rate": float(n_valid / n_total) if n_total else float("nan"),
                "mae": mae,
                "rmse": rmse,
                "bias": bias,
            }
        )
    return pd.DataFrame(rows)
