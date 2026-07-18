from pathlib import Path

from geomodeling.schemas import QualityStatus
from geomodeling.validation import validate_xyzrho_contract


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


def test_non_finite_value_is_blocked(tmp_path: Path):
    path = tmp_path / "nonfinite.csv"
    path.write_text("X,Y,Z,RHO\n1,2,3,NaN\n", encoding="utf-8")
    report = validate_xyzrho_contract(path, dataset_id="bad_nonfinite")
    assert report.quality_status == QualityStatus.FAILED
    assert any(issue.code == "NON_FINITE_VALUES" for issue in report.issues)


def test_duplicate_xyz_is_warning_not_silent(tmp_path: Path):
    path = tmp_path / "duplicate.csv"
    path.write_text("X,Y,Z,RHO\n1,2,3,10\n1,2,3,11\n", encoding="utf-8")
    report = validate_xyzrho_contract(path, dataset_id="duplicate")
    assert report.quality_status == QualityStatus.WARNING
    assert report.checks["duplicate_xyz_count"] == 1
    assert any(issue.code == "DUPLICATE_XYZ" and not issue.blocking for issue in report.issues)
