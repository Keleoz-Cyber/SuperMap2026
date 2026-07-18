from pathlib import Path

import pytest

from geomodeling.metrics import compute_metric_summary, import_prediction_csv, read_validation_truth

FIXTURES = Path(__file__).parent / "fixtures"


def test_tiny_prediction_import_handles_nodata_and_alignment():
    validation = read_validation_truth(FIXTURES / "rho_tiny_validation.csv")
    frame, quality = import_prediction_csv(FIXTURES / "rho_tiny_predictions.csv", validation, "tiny_model")
    assert quality["row_count"] == 3
    assert quality["valid_count"] == 2
    assert quality["nodata_count"] == 1
    assert quality["xy_mismatch_count"] == 0
    assert bool(frame.loc[1, "is_nodata"]) is True
    assert frame.loc[1, "rho_pred"] != frame.loc[1, "rho_pred"]


def test_tiny_prediction_xy_mismatch_is_counted():
    validation = read_validation_truth(FIXTURES / "rho_tiny_validation.csv")
    _, quality = import_prediction_csv(FIXTURES / "rho_tiny_predictions_xy_mismatch.csv", validation, "tiny_model")
    assert quality["xy_mismatch_count"] == 1


def test_tiny_metric_summary_values():
    validation = read_validation_truth(FIXTURES / "rho_tiny_validation.csv")
    frame, _ = import_prediction_csv(FIXTURES / "rho_tiny_predictions.csv", validation, "tiny_model")
    summary = compute_metric_summary(frame["rho_true"], frame["rho_pred"], "tiny_model")
    assert summary.n_total == 3
    assert summary.n_valid == 2
    assert summary.n_nodata == 1
    assert summary.mae == pytest.approx(3.0)
    assert summary.rmse == pytest.approx(13.0**0.5)
    assert summary.bias == pytest.approx(-2.0)
