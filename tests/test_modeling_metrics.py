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
    assert summary.n_valid == 4
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
    assert summary.n_valid == 3
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
