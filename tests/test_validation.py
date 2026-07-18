from pathlib import Path

import pytest

from geomodeling.config import load_config
from geomodeling.registry import DatasetRegistry
from geomodeling.schemas import DatasetType, QualityStatus
from geomodeling.validation import registration_from_report, validate_train_validation_split, validate_xyzrho_contract

pytestmark = pytest.mark.local_data


def test_real_xyzrho_contracts_pass():
    config = load_config()
    cases = [
        ("standardized", "rho_standardized_v1", DatasetType.STANDARDIZED_OBSERVATION),
        ("training", "rho_training_v1", DatasetType.TRAIN_VALIDATION_SPLIT),
        ("validation", "rho_validation_v1", DatasetType.TRAIN_VALIDATION_SPLIT),
    ]
    for key, dataset_id, dataset_type in cases:
        report = validate_xyzrho_contract(
            config.resolve_path(config.paths[key]),
            dataset_id=dataset_id,
            dataset_type=dataset_type,
            expected_row_count=config.expected[f"{key}_rows"],
        )
        assert report.quality_status == QualityStatus.PASSED
        assert report.row_count == config.expected[f"{key}_rows"]
        assert report.checks["required_fields_present"] is True
        assert report.checks["finite_values"] is True
        assert report.checks["rho_positive"] is True


def test_train_validation_spatial_columns_do_not_overlap():
    config = load_config()
    split = validate_train_validation_split(config.resolve_path(config.paths["training"]), config.resolve_path(config.paths["validation"]))
    assert split["training_column_count"] == config.expected["training_columns"]
    assert split["validation_column_count"] == config.expected["validation_columns"]
    assert split["spatial_column_overlap"] == config.expected["spatial_column_overlap"]
    assert split["passed"] is True


def test_missing_required_field_is_blocked(tmp_path: Path):
    path = tmp_path / "missing.csv"
    path.write_text("X,Y,Z\n1,2,3\n", encoding="utf-8")
    report = validate_xyzrho_contract(path, dataset_id="bad_missing")
    assert report.quality_status == QualityStatus.FAILED
    assert any(issue.code == "MISSING_FIELDS" for issue in report.issues)


def test_nodata_observed_rho_is_blocked(tmp_path: Path):
    path = tmp_path / "nodata.csv"
    path.write_text("X,Y,Z,RHO\n1,2,3,-9999\n", encoding="utf-8")
    report = validate_xyzrho_contract(path, dataset_id="bad_nodata")
    assert report.quality_status == QualityStatus.FAILED
    assert any(issue.code == "INVALID_RHO" for issue in report.issues)


def test_dataset_registry_detects_duplicate_sha256(tmp_path: Path):
    config = load_config()
    path = config.resolve_path(config.paths["validation"])
    report = validate_xyzrho_contract(path, dataset_id="rho_validation_v1", dataset_type=DatasetType.TRAIN_VALIDATION_SPLIT, expected_row_count=1722)
    registration = registration_from_report(report, path, created_by="pytest", source_reference=str(path))
    registry = DatasetRegistry(tmp_path / "registry")
    first = registry.register(registration)
    second = registry.register(registration)
    assert first["duplicate_sha256"] is False
    assert second["duplicate_sha256"] is True
