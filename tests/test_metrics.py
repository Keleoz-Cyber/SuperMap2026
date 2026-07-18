import pytest

from geomodeling.config import load_config
from geomodeling.metrics import (
    common_valid_mask,
    compare_metric_summaries,
    compute_common_metric_summaries,
    import_prediction_csv,
    read_validation_truth,
)

pytestmark = pytest.mark.local_data


def _predictions(config):
    validation = read_validation_truth(config.resolve_path(config.paths["validation"]))
    files = config.prediction_files()
    predictions = {}
    qualities = {}
    for model in config.models:
        name = model["display_name"]
        frame, quality = import_prediction_csv(files[name], validation, model["model_id"], nodata_value=config.nodata_value)
        predictions[name] = frame
        qualities[name] = quality
    return predictions, qualities


def test_prediction_import_nodata_and_alignment():
    config = load_config()
    predictions, qualities = _predictions(config)
    assert len(predictions) == 5
    for quality in qualities.values():
        assert quality["row_count"] == 1722
        assert quality["xy_mismatch_count"] == 0
        assert quality["valid_count"] == 1481
        assert quality["nodata_count"] == 241
    mask = common_valid_mask(predictions)
    assert int(mask.sum()) == config.expected["common_valid"]
    assert int((~mask).sum()) == config.expected["common_nodata"]


def test_recomputed_metrics_match_baseline():
    config = load_config()
    predictions, _ = _predictions(config)
    summaries = compute_common_metric_summaries(predictions)
    assert summaries["Kriging 20m/40点"].mae == pytest.approx(3.222594, abs=1e-5)
    assert summaries["IDW 20m/25点"].rmse == pytest.approx(5.787635, abs=1e-5)
    comparison = compare_metric_summaries(summaries, config.resolve_path(config.paths["metrics_baseline"]), config.metric_tolerance)
    assert comparison["passed"] is True
    assert comparison["differences"] == []


def test_selection_conclusion_is_not_single_winner():
    config = load_config()
    predictions, _ = _predictions(config)
    summaries = compute_common_metric_summaries(predictions)
    best_mae = min(summaries.values(), key=lambda item: item.mae).model
    best_rmse = min(summaries.values(), key=lambda item: item.rmse).model
    assert best_mae == "Kriging 20m/40点"
    assert best_rmse == "IDW 20m/25点"
    assert best_mae != best_rmse
