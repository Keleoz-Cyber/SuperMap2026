"""Common-valid metrics for honest cross-candidate comparison.

All candidates in one experiment share one common-valid mask: the
intersection of their non-NoData prediction points. Public metrics are
recomputed only on that mask, so a candidate cannot gain rank by marking
difficult points as NoData; per-candidate coverage is reported separately
to keep that trade-off visible.
"""

from __future__ import annotations

import numpy as np

from geomodeling.modeling.contracts import MetricSummary
from geomodeling.platform.errors import PlatformError

METRICS_EMPTY_COMMON_VALID = "METRICS_EMPTY_COMMON_VALID"


def common_valid_mask(predictions: dict[str, tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    """Intersection of non-NoData masks across candidates."""

    mask: np.ndarray | None = None
    for _values, is_nodata in predictions.values():
        valid = ~np.asarray(is_nodata, dtype=bool)
        mask = valid if mask is None else (mask & valid)
    if mask is None:
        raise PlatformError(METRICS_EMPTY_COMMON_VALID, "没有候选可计算公共有效集合")
    return mask


def compute_metrics(
    truth: np.ndarray,
    prediction: np.ndarray,
    mask: np.ndarray,
    *,
    is_nodata: np.ndarray | None = None,
) -> MetricSummary:
    """Recompute MAE/RMSE/R²/Bias/coverage on the shared mask.

    指标一律在公共 ``mask`` 上复算；``coverage`` 默认按公共掩膜计，若提供
    候选自身的 ``is_nodata``，则按候选自身有效点口径单独呈现（公共集合
    比较与覆盖率展示分离，报 NoData 不能换取排名优势）。
    """

    truth = np.asarray(truth, dtype="float64")
    prediction = np.asarray(prediction, dtype="float64")
    mask = np.asarray(mask, dtype=bool)
    total_count = int(mask.size)
    common_valid_count = int(mask.sum())
    if common_valid_count == 0:
        raise PlatformError(METRICS_EMPTY_COMMON_VALID, "公共有效集合为空，无法复算指标")

    errors = prediction[mask] - truth[mask]
    mae = float(np.abs(errors).mean())
    rmse = float(np.sqrt((errors**2).mean()))
    bias = float(errors.mean())
    ss_res = float((errors**2).sum())
    centered = truth[mask] - truth[mask].mean()
    ss_tot = float((centered**2).sum())
    if ss_tot == 0.0:
        r2 = 1.0 if ss_res == 0.0 else 0.0
    else:
        r2 = 1.0 - ss_res / ss_tot
    if is_nodata is not None:
        candidate_valid_count = int((~np.asarray(is_nodata, dtype=bool)).sum())
    else:
        candidate_valid_count = common_valid_count
    candidate_nodata_count = total_count - candidate_valid_count
    coverage = candidate_valid_count / total_count
    return MetricSummary(
        common_valid_count=common_valid_count,
        candidate_valid_count=candidate_valid_count,
        candidate_nodata_count=candidate_nodata_count,
        total_count=total_count,
        coverage=coverage,
        mae=mae,
        rmse=rmse,
        r2=r2,
        bias=bias,
    )
