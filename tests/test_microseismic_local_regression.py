from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

from geomodeling.microseismic.config import load_microseismic_config
from geomodeling.microseismic.derivation import derive_local_samples
from geomodeling.microseismic.filtering import filter_three_sigma
from geomodeling.microseismic.inventory import snapshot_sha256
from geomodeling.microseismic.service import build_audit, export_all

pytestmark = [
    pytest.mark.local_data,
    pytest.mark.skipif(
        not load_microseismic_config().data_dir.is_dir(),
        reason="microseismic read-only reference data is not available",
    ),
]


@pytest.fixture(scope="module")
def audit_result():
    config = load_microseismic_config()
    paths = [config.data_dir / point.source_file for _, point in config.formal_points()]
    before = snapshot_sha256(paths)
    result = build_audit(config)
    after = snapshot_sha256(paths)
    return result, before, after


def test_22_dat_files(audit_result):
    result, _, _ = audit_result
    assert len(result.manifest) == 22
    assert result.counts["dat_file_count"] == 22
    assert sum(entry.size_bytes for entry in result.manifest) == 66880


def test_22_nul_terminators(audit_result):
    result, _, _ = audit_result
    assert result.counts["nul_terminator_count"] == 22
    assert all(entry.nul_terminator for entry in result.manifest)


def test_record_count_layers(audit_result):
    result, _, _ = audit_result
    counts = result.counts
    assert counts["parsed_row_total_with_nul"] == 2028
    assert counts["source_record_total"] == 2006
    assert counts["invalid_numeric_total"] == 1
    assert counts["valid_numeric_total"] == 2005


def test_per_line_counts(audit_result):
    result, _, _ = audit_result
    assert result.counts["source_record_counts"] == {"L1": 823, "L2": 819, "L3": 364}
    assert result.counts["valid_numeric_counts"] == {"L1": 822, "L2": 819, "L3": 364}


def test_w8_special_value_traceable(audit_result):
    result, _, _ = audit_result
    special = [sample for sample in result.samples if "SOURCE_SPECIAL_NAN_TOKEN" in sample.quality_flags]
    assert len(special) == 1
    row = special[0]
    assert row.point_id == "W8"
    assert row.line_id == "L1"
    assert row.source_file_name == "W8.dat"
    assert row.source_line_number == 2
    assert row.wl_half_km_raw_token == "0.050000"
    assert row.vx_raw_token == "1.#QNAN0"
    assert row.vx_value is None
    assert row.is_numeric_valid is False
    assert row.included_in_raw is True
    assert row.included_in_valid_numeric is False


def test_w28_excluded_from_formal_set(audit_result):
    result, _, _ = audit_result
    formal_points = {point.point_id for point in result.points if point.included_in_formal_set}
    assert "W28" not in formal_points
    assert {sample.point_id for sample in result.samples}.isdisjoint({"W28"})
    w28 = [point for point in result.points if point.point_id == "W28"]
    assert len(w28) == 1
    assert w28[0].included_in_formal_set is False
    assert w28[0].sequence_on_line is None
    assert w28[0].cumulative_s_m is None
    assert w28[0].interval_from_previous_m == 350
    l3 = [point for point in result.points if point.line_id == "L3" and point.included_in_formal_set]
    assert [point.point_id for point in sorted(l3, key=lambda row: row.sequence_on_line)] == ["W24", "W25", "W26", "W27"]
    assert max(point.cumulative_s_m for point in l3) == 1455


def test_three_tables_export(audit_result, tmp_path):
    result, _, _ = audit_result
    export_all(result, tmp_path)
    samples = pd.read_csv(tmp_path / "velocity_samples.csv")
    assert len(samples) == 2006
    assert samples["is_numeric_valid"].sum() == 2005
    lines = pd.read_csv(tmp_path / "survey_lines.csv")
    assert len(lines) == 3
    points = pd.read_csv(tmp_path / "survey_points.csv")
    assert len(points) == 23
    assert points["included_in_formal_set"].sum() == 22


def test_source_sha256_unchanged(audit_result):
    result, before, after = audit_result
    assert before == after
    assert result.validation.sha256_protection["unchanged"] is True


def test_confirmed_local_coordinates(audit_result):
    result, _, _ = audit_result
    coordinates = load_microseismic_config().coordinate_lookup()
    formal = [point for point in result.points if point.included_in_formal_set]
    assert len(formal) == 22
    for point in formal:
        assert point.coordinate_status == "confirmed_local"
        assert (point.x_local_m, point.y_local_m) == coordinates[point.point_id]
    assert coordinates["W16"] == (0.0, 0.0)
    assert coordinates["W5"] == (0.0, 220.0)
    assert coordinates["W24"] == (960.0, 0.0)
    w28 = next(point for point in result.points if point.point_id == "W28")
    assert w28.x_local_m is None and w28.y_local_m is None
    assert w28.coordinate_status == "unconfirmed"
    assert all(sample.derived_depth_m is None and sample.derived_z_m is None for sample in result.samples)


def test_derive_local_samples_real_data(audit_result):
    result, _, _ = audit_result
    config = load_microseismic_config()
    finite, invalid = derive_local_samples(config, result)
    assert len(finite) == 2005
    assert len(invalid) == 1
    assert dict(Counter(item.line_id for item in finite)) == {"L1": 822, "L2": 819, "L3": 364}
    rejected = invalid[0]
    assert rejected.sample_id == "W8:2"
    assert rejected.source_file == "W8.dat"
    assert rejected.source_line == 2
    assert rejected.vx_raw_token == "1.#QNAN0"
    assert rejected.is_valid is False
    row = next(item for item in finite if item.sample_id == "W1:2")
    assert (row.x_local_m, row.y_local_m) == (400.0, 220.0)
    assert row.depth_m == pytest.approx(row.wl_half_km * 1000)
    assert row.z_local_m == pytest.approx(-row.depth_m)
    assert row.coord_type == "local_engineering_m"
    assert row.rule_version == "microseismic_local_3d_v0.2b_confirmed_2026-07-20"
    assert {item.point_id for item in finite}.isdisjoint({"W28"})


def test_filter_three_sigma_real_data_anchors(audit_result):
    result, _, _ = audit_result
    config = load_microseismic_config()
    finite, _ = derive_local_samples(config, result)
    filtered = filter_three_sigma(
        finite,
        threshold=config.derivation.sigma_threshold,
        ddof=config.derivation.sigma_ddof,
    )
    assert filtered.depth_mean == pytest.approx(676.620332169576)
    assert filtered.depth_std == pytest.approx(1138.5704399315825)
    assert filtered.vx_mean == pytest.approx(0.9019579860349127)
    assert filtered.vx_std == pytest.approx(0.7493428022868682)
    assert len(filtered.rejected) == 80
    assert Counter(row.filter_reason for row in filtered.rejected) == {"深度": 72, "速度": 8}
    assert len(filtered.accepted) == 1925
    # Accepted and rejected each preserve the derived source order.
    accepted_ids = {row.sample_id for row in filtered.accepted}
    assert [row.sample_id for row in filtered.accepted] == [
        row.sample_id for row in finite if row.sample_id in accepted_ids
    ]


def test_validation_passed(audit_result):
    result, _, _ = audit_result
    assert result.validation.passed is True


def test_manifest_relative_paths_not_absolute(audit_result):
    result, _, _ = audit_result
    for entry in result.manifest:
        assert not Path(entry.relative_path).is_absolute(), entry.relative_path
        assert "超图杯资料" in entry.relative_path
        assert entry.relative_path.endswith(entry.file_name)
