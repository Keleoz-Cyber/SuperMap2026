"""Task 5 metric tests: common-valid mask, metric computation, honest ranking."""

from __future__ import annotations

import numpy as np
import pytest


def test_compute_metrics_known_values():
    from geomodeling.modeling.metrics import compute_metrics

    truth = np.array([10.0, 20.0, 30.0, 40.0])
    prediction = np.array([11.0, 19.0, 33.0, 37.0])
    mask = np.array([True, True, True, True])
    summary = compute_metrics(truth, prediction, mask)
    assert summary.common_valid_count == 4
    assert summary.candidate_valid_count == 4
    assert summary.candidate_nodata_count == 0
    assert summary.total_count == 4
    assert summary.coverage == 1.0
    errors = prediction - truth
    assert summary.mae == pytest.approx(np.abs(errors).mean())
    assert summary.rmse == pytest.approx(np.sqrt((errors**2).mean()))
    assert summary.bias == pytest.approx(errors.mean())
    ss_res = (errors**2).sum()
    ss_tot = ((truth - truth.mean()) ** 2).sum()
    assert summary.r2 == pytest.approx(1 - ss_res / ss_tot)


def test_compute_metrics_respects_mask_and_nodata():
    from geomodeling.modeling.metrics import compute_metrics

    truth = np.array([10.0, 20.0, 30.0, 40.0])
    prediction = np.array([11.0, 19.0, 33.0, 37.0])
    mask = np.array([True, False, True, True])
    summary = compute_metrics(truth, prediction, mask)
    assert summary.common_valid_count == 3
    assert summary.total_count == 4
    # 未提供候选自身 is_nodata 时，候选口径退化为公共口径
    assert summary.candidate_valid_count == 3
    assert summary.candidate_nodata_count == 1
    assert summary.coverage == pytest.approx(0.75)
    assert summary.mae == pytest.approx((1.0 + 3.0 + 3.0) / 3)


def test_common_valid_mask_is_intersection():
    from geomodeling.modeling.metrics import common_valid_mask

    predictions = {
        "a": (np.array([1.0, 2.0, 3.0, 4.0]), np.array([False, False, False, False])),
        "b": (np.array([1.1, 2.1, 3.1, 4.1]), np.array([False, True, False, False])),
        "c": (np.array([0.9, 1.9, 2.9, 3.9]), np.array([False, False, True, False])),
    }
    mask = common_valid_mask(predictions)
    assert mask.tolist() == [True, False, False, True]


def test_extra_nodata_does_not_improve_ranking():
    """公共掩膜上，把困难点报成 NoData 的候选不得获得虚假精度优势。"""

    from geomodeling.modeling.metrics import common_valid_mask, compute_metrics

    truth = np.array([1.0, 2.0, 3.0, 100.0])
    pred_honest = np.array([1.1, 2.1, 2.9, 90.0])
    pred_lazy = np.array([1.1, 2.1, 2.9, 50.0])

    predictions = {
        "honest": (pred_honest, np.array([False, False, False, False])),
        "lazy": (pred_lazy, np.array([False, False, False, True])),
    }
    mask = common_valid_mask(predictions)
    assert mask.tolist() == [True, True, True, False]

    honest = compute_metrics(truth, pred_honest, mask, is_nodata=predictions["honest"][1])
    lazy = compute_metrics(truth, pred_lazy, mask, is_nodata=predictions["lazy"][1])
    # 公共集合上 lazy 只少了最难点，RMSE 仍应大于等于 honest 的公共 RMSE
    assert lazy.rmse <= honest.rmse + 1e-12
    # 覆盖率独立展示：lazy 覆盖率低于 honest，虚假优势在覆盖率上被拆穿
    assert lazy.coverage < honest.coverage


def test_zero_common_valid_is_safe():
    from geomodeling.modeling.metrics import common_valid_mask, compute_metrics

    predictions = {
        "a": (np.array([1.0, 2.0]), np.array([True, False])),
        "b": (np.array([1.0, 2.0]), np.array([False, True])),
    }
    mask = common_valid_mask(predictions)
    assert not mask.any()
    with pytest.raises(Exception):
        compute_metrics(np.array([1.0, 2.0]), np.array([1.0, 2.0]), mask)


def test_all_finite_input_reports_zero_exclusions():
    """全有限输入与既有行为逐位一致，且排除计数为零。"""

    from geomodeling.modeling.metrics import compute_metrics

    truth = np.array([10.0, 20.0, 30.0, 40.0])
    prediction = np.array([11.0, 19.0, 33.0, 37.0])
    mask = np.array([True, True, True, True])
    summary = compute_metrics(truth, prediction, mask)
    assert summary.truth_excluded_count == 0
    assert summary.prediction_excluded_count == 0
    errors = prediction - truth
    assert summary.rmse == float(np.sqrt((errors**2).mean()))
    assert summary.mae == float(np.abs(errors).mean())
    assert summary.bias == float(errors.mean())


def test_nonfinite_truth_is_excluded_and_counted():
    """掩膜内的非有限 truth 不得毒化指标：排除、计数披露、指标有限。"""

    from geomodeling.modeling.metrics import compute_metrics

    truth = np.array([10.0, np.nan, 30.0, 40.0])
    prediction = np.array([11.0, 19.0, 33.0, 37.0])
    mask = np.array([True, True, True, True])
    summary = compute_metrics(truth, prediction, mask)
    assert summary.truth_excluded_count == 1
    assert summary.prediction_excluded_count == 0
    assert summary.common_valid_count == 3
    assert summary.total_count == 4
    kept = np.array([0, 2, 3])
    errors = prediction[kept] - truth[kept]
    assert summary.mae == pytest.approx(np.abs(errors).mean())
    assert summary.rmse == pytest.approx(np.sqrt((errors**2).mean()))
    assert summary.bias == pytest.approx(errors.mean())
    for value in (summary.mae, summary.rmse, summary.r2, summary.bias):
        assert np.isfinite(value)


def test_nonfinite_prediction_is_excluded_and_counted():
    """掩膜内的非有限 prediction 同样排除并披露（不只看 NoData 标记）。"""

    from geomodeling.modeling.metrics import compute_metrics

    truth = np.array([10.0, 20.0, 30.0, 40.0])
    prediction = np.array([11.0, np.nan, 33.0, 37.0])
    mask = np.array([True, True, True, True])
    summary = compute_metrics(truth, prediction, mask)
    assert summary.truth_excluded_count == 0
    assert summary.prediction_excluded_count == 1
    assert summary.common_valid_count == 3
    kept = np.array([0, 2, 3])
    errors = prediction[kept] - truth[kept]
    assert summary.rmse == pytest.approx(np.sqrt((errors**2).mean()))
    assert np.isfinite(summary.bias)


def test_all_nonfinite_truth_still_fails_closed():
    """排除后公共集合为空 → 仍以 METRICS_EMPTY_COMMON_VALID fail-closed。"""

    from geomodeling.modeling.metrics import METRICS_EMPTY_COMMON_VALID, compute_metrics
    from geomodeling.platform.errors import PlatformError

    truth = np.array([np.nan, np.nan])
    prediction = np.array([1.0, 2.0])
    mask = np.array([True, True])
    with pytest.raises(PlatformError) as exc:
        compute_metrics(truth, prediction, mask)
    assert exc.value.code == METRICS_EMPTY_COMMON_VALID
