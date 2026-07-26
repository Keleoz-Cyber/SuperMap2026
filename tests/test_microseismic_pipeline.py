import json
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from geomodeling.cli import app
from geomodeling.microseismic.config import load_microseismic_config
from geomodeling.microseismic.service import build_audit, export_all

from microseismic_fixtures import write_fixture_config, write_fixture_tree

runner = CliRunner()

EXPECTED_ISSUE_CODES = {
    "SOURCE_NUL_TERMINATOR",
    "SOURCE_SPECIAL_NAN_TOKEN",
    "LINE_COUNT_CONFLICT",
    "L3_W28_SOURCE_CONFLICT",
    "L3_W28_INTERVAL_EXCLUDED",
    "LOCAL_GEOMETRY_CONFIRMED",
    "DEPTH_Z_VX_RULE_CONFIRMED",
    "ABSOLUTE_COORDINATES_UNAVAILABLE",
    "CLEANING_RATE_CONFLICT",
    "CLEANING_METHOD_CONFLICT",
}


@pytest.fixture()
def fixture_setup(tmp_path: Path):
    data_dir = write_fixture_tree(tmp_path)
    config_path = write_fixture_config(tmp_path, data_dir)
    config = load_microseismic_config(config_path)
    return config, config_path, tmp_path / "out"


def test_build_audit_counts(fixture_setup):
    config, _, _ = fixture_setup
    result = build_audit(config)
    assert result.validation.passed is True
    counts = result.counts
    assert counts["dat_file_count"] == 3
    assert counts["nul_terminator_count"] == 2
    assert counts["source_record_total"] == 7
    assert counts["valid_numeric_total"] == 6
    assert counts["invalid_numeric_total"] == 1
    assert counts["parsed_row_total_with_nul"] == 9


def test_special_nan_row_traceable(fixture_setup):
    config, _, _ = fixture_setup
    result = build_audit(config)
    special = [sample for sample in result.samples if "SOURCE_SPECIAL_NAN_TOKEN" in sample.quality_flags]
    assert len(special) == 1
    row = special[0]
    assert row.point_id == "W2"
    assert row.source_line_number == 2
    assert row.vx_raw_token == "1.#QNAN0"
    assert row.vx_value is None
    assert row.is_numeric_valid is False
    assert row.included_in_valid_numeric is False


def test_nul_pseudo_lines_never_become_samples(fixture_setup):
    config, _, _ = fixture_setup
    result = build_audit(config)
    leaked = [sample for sample in result.samples if sample.wl_half_km_raw_token is None and sample.vx_raw_token is None]
    assert leaked == []


def test_excluded_point_not_in_formal_set(fixture_setup):
    config, _, _ = fixture_setup
    result = build_audit(config)
    formal_points = {point.point_id for point in result.points if point.included_in_formal_set}
    assert "W99" not in formal_points
    excluded = [point for point in result.points if point.point_id == "W99"]
    assert len(excluded) == 1
    assert excluded[0].included_in_formal_set is False
    assert excluded[0].exclusion_reason
    sample_points = {sample.point_id for sample in result.samples}
    assert "W99" not in sample_points


def test_excluded_point_has_null_sequence_and_cumulative(fixture_setup):
    config, _, _ = fixture_setup
    result = build_audit(config)
    excluded = next(point for point in result.points if point.point_id == "W99")
    assert excluded.sequence_on_line is None
    assert excluded.cumulative_s_m is None
    assert excluded.interval_from_previous_m == 350
    formal = [point for point in result.points if point.included_in_formal_set]
    assert all(point.sequence_on_line is not None and point.sequence_on_line >= 1 for point in formal)
    assert all(point.cumulative_s_m is not None for point in formal)
    assert next(point for point in formal if point.point_id == "W1").cumulative_s_m == 0


def test_manifest_relative_path_is_stable_and_resolvable(fixture_setup):
    config, _, _ = fixture_setup
    result = build_audit(config)
    from geomodeling.microseismic.config import PROJECT_ROOT

    for entry in result.manifest:
        assert not Path(entry.relative_path).is_absolute(), entry.relative_path
        assert not entry.relative_path.startswith(("D:", "d:", "C:", "c:", "/"))
        resolved = (PROJECT_ROOT / entry.relative_path).resolve()
        if not resolved.is_file():
            resolved = (config.data_dir / entry.relative_path).resolve()
        assert resolved.is_file(), entry.relative_path
        assert resolved.name == entry.file_name


def test_cumulative_distance(fixture_setup):
    config, _, _ = fixture_setup
    result = build_audit(config)
    points = {point.point_id: point for point in result.points if point.included_in_formal_set}
    assert points["W1"].cumulative_s_m == 0
    assert points["W1"].interval_from_previous_m is None
    assert points["W2"].interval_from_previous_m == 100
    assert points["W2"].cumulative_s_m == 100
    assert points["W2"].previous_point_id == "W1"
    assert points["W2"].interval_source


def test_confirmed_local_coordinates(fixture_setup):
    config, _, _ = fixture_setup
    result = build_audit(config)
    coordinates = config.coordinate_lookup()
    formal = [point for point in result.points if point.included_in_formal_set]
    assert all(point.coordinate_status == "confirmed_local" for point in formal)
    assert all((point.x_local_m, point.y_local_m) == coordinates[point.point_id] for point in formal)
    excluded = [point for point in result.points if not point.included_in_formal_set]
    assert all(point.x_local_m is None and point.y_local_m is None for point in excluded)
    assert all(point.coordinate_status == "unconfirmed" for point in excluded)
    assert all(sample.derived_depth_m is None and sample.derived_z_m is None for sample in result.samples)
    assert all(sample.depth_derivation_status == "unconfirmed" for sample in result.samples)


def test_no_formal_cleaning_output(fixture_setup):
    config, _, _ = fixture_setup
    result = build_audit(config)
    assert all(sample.included_in_clean_candidate is False for sample in result.samples)
    assert all(sample.imputed is False for sample in result.samples)
    assert all(sample.cleaning_version == "none_v0.2a" for sample in result.samples)


def test_standard_issue_list(fixture_setup):
    config, _, _ = fixture_setup
    result = build_audit(config)
    codes = {issue.code for issue in result.issues}
    assert EXPECTED_ISSUE_CODES <= codes
    for issue in result.issues:
        assert issue.severity in {"info", "warning", "error", "blocker"}
        assert issue.affected_scope
        assert issue.current_handling


def test_export_all_outputs(fixture_setup):
    config, _, out_dir = fixture_setup
    result = build_audit(config)
    outputs = export_all(result, out_dir)
    expected_files = {
        "source_manifest.json",
        "survey_lines.csv",
        "survey_points.csv",
        "velocity_samples.csv",
        "microseismic_validation.json",
        "microseismic_issue_list.json",
        "microseismic_issue_list.md",
        "microseismic_data_quality.md",
        "microseismic_data_dictionary.md",
        "microseismic_audit_summary.md",
    }
    assert {path.name for path in outputs.values()} == expected_files
    samples = pd.read_csv(out_dir / "velocity_samples.csv")
    assert len(samples) == 7
    assert samples["is_numeric_valid"].sum() == 6
    lines = pd.read_csv(out_dir / "survey_lines.csv")
    assert len(lines) == 2
    points = pd.read_csv(out_dir / "survey_points.csv")
    assert len(points) == 4
    validation = json.loads((out_dir / "microseismic_validation.json").read_text(encoding="utf-8"))
    assert validation["passed"] is True
    issues = json.loads((out_dir / "microseismic_issue_list.json").read_text(encoding="utf-8"))
    assert EXPECTED_ISSUE_CODES <= {issue["code"] for issue in issues}
    summary = (out_dir / "microseismic_audit_summary.md").read_text(encoding="utf-8")
    assert "validation_passed: True" in summary


def test_audit_summary_separates_blockers_and_gates(fixture_setup):
    config, _, out_dir = fixture_setup
    result = build_audit(config)
    export_all(result, out_dir)
    summary = (out_dir / "microseismic_audit_summary.md").read_text(encoding="utf-8")
    assert "## Downstream gates" in summary
    assert "## Validation blockers" in summary
    # v0.5: local geometry, depth/Z, Vx and the 3-sigma cleaning rule are
    # confirmed, so a passing audit no longer blocks the downstream gates.
    assert "geometry_blocked: False" in summary
    assert "cleaning_blocked: False" in summary
    assert "interpolation_blocked: False" in summary
    issues = json.loads((out_dir / "microseismic_issue_list.json").read_text(encoding="utf-8"))
    absolute = next(issue for issue in issues if issue["code"] == "ABSOLUTE_COORDINATES_UNAVAILABLE")
    # Absolute CRS is still unavailable but blocks only cross-case fusion,
    # never the independent local modeling gates.
    assert absolute["blocks_geometry"] is False
    assert absolute["blocks_cleaning"] is False
    assert absolute["blocks_interpolation"] is False


def test_sha256_protection_check(fixture_setup):
    config, _, _ = fixture_setup
    result = build_audit(config)
    assert result.validation.sha256_protection["unchanged"] is True
    assert result.validation.sha256_protection["files_checked"] == 3


def test_cli_run_audit_success(fixture_setup):
    _, config_path, out_dir = fixture_setup
    completed = runner.invoke(app, ["microseismic", "run-audit", "--config", str(config_path), "-o", str(out_dir)])
    assert completed.exit_code == 0, completed.output
    assert "source_records=7" in completed.output
    assert "validation_passed=True" in completed.output
    assert (out_dir / "velocity_samples.csv").is_file()
    assert (out_dir / "logs" / "audit.jsonl").is_file()


def test_cli_blocker_returns_nonzero(tmp_path: Path):
    data_dir = write_fixture_tree(tmp_path)
    config_path = write_fixture_config(tmp_path, data_dir, expected={"source_record_total": 999})
    out_dir = tmp_path / "out"
    completed = runner.invoke(app, ["microseismic", "run-audit", "--config", str(config_path), "-o", str(out_dir)])
    assert completed.exit_code == 1
    assert "validation_passed=False" in completed.output
    assert (out_dir / "microseismic_validation.json").is_file()
    validation = json.loads((out_dir / "microseismic_validation.json").read_text(encoding="utf-8"))
    assert validation["passed"] is False


def test_cli_missing_file_blocker(tmp_path: Path):
    data_dir = write_fixture_tree(tmp_path)
    (data_dir / "WA.dat").unlink()
    config_path = write_fixture_config(tmp_path, data_dir)
    completed = runner.invoke(app, ["microseismic", "run-audit", "--config", str(config_path), "-o", str(tmp_path / "out")])
    assert completed.exit_code == 1


def test_cli_validate_lists_checks(fixture_setup):
    _, config_path, out_dir = fixture_setup
    completed = runner.invoke(app, ["microseismic", "validate", "--config", str(config_path), "-o", str(out_dir)])
    assert completed.exit_code == 0
    assert "PASS formal_dat_file_count" in completed.output
    assert "PASS confirmed_local_coordinates" in completed.output
