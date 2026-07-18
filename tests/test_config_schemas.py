from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from geomodeling.config import load_config
from geomodeling.schemas import ModelMetadata, ModelStatus, ResultCategory, SuperMapResultRegistration


def test_default_config_loads():
    config = load_config()
    assert config.expected["standardized_rows"] == 17549
    assert config.expected["validation_rows"] == 1722
    assert len(config.models) == 5
    assert config.prediction_files()["Kriging 20m/40点"].name == "RHO_KRIG_CV_VALID_40.csv"


def test_model_status_is_fixed():
    assert {status.value for status in ModelStatus} == {"created", "running", "succeeded", "failed", "invalidated"}


def test_model_metadata_rejects_dsi_method():
    with pytest.raises(ValidationError):
        ModelMetadata(
            model_id="bad",
            method="DSI",
            input_dataset_id="rho_training_v1",
            input_sha256="0" * 64,
            crs={"type": "local_engineering", "epsg": None},
            axis={"horizontal_unit": "m", "vertical_unit": "m", "z_positive": "up"},
            grid={},
            generated_at=datetime.now(timezone.utc),
        )


def test_supermap_registration_prevents_false_success():
    with pytest.raises(ValidationError):
        SuperMapResultRegistration(
            dataset="EMPTY_BUT_SUCCESS",
            model_id="rho_kriging_20m_n40_v1",
            dataset_type="isosurface",
            method="KRIGING_ORDINARY",
            datasource_alias="expore1",
            status="succeeded",
            result_category=ResultCategory.FORMAL,
            object_count=0,
            openable=True,
        )
