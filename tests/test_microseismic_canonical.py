from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from geomodeling.microseismic.aggregation import aggregate_exact_xyz
from geomodeling.microseismic.canonical import (
    accepted_csv_bytes,
    rejected_csv_bytes,
    write_canonical_bytes,
)
from geomodeling.microseismic.config import load_microseismic_config
from geomodeling.microseismic.derivation import derive_local_samples
from geomodeling.microseismic.filtering import filter_three_sigma
from geomodeling.microseismic.golden import verify_golden
from geomodeling.microseismic.schemas import (
    DEPTH_RULE,
    Z_RULE,
    DerivedVelocitySample,
    RejectedFilteredSample,
)
from geomodeling.microseismic.service import build_audit

from microseismic_fixtures import write_fixture_config, write_fixture_tree

RULE_VERSION = "microseismic_local_3d_v0.2b_confirmed_2026-07-20"
ACCEPTED_HEADER = (
    "SAMPLE_ID,POINT_ID,LINE_ID,X_LOCAL_M,Y_LOCAL_M,DEPTH_M,Z_LOCAL_M,VX_KM_S,"
    "WL_HALF_KM,SOURCE_FILE,SOURCE_LINE,VX_RAW_TOKEN,IS_VALID,COORD_TYPE,"
    "DEPTH_RULE,Z_RULE,RULE_VERSION"
)
REJECTED_HEADER = ACCEPTED_HEADER + ",DEPTH_ZSCORE,VX_ZSCORE,FILTER_STATUS,FILTER_REASON"


def canonical_rows() -> list[DerivedVelocitySample]:
    """Two synthetic rows mirroring the golden value formats."""
    base = {
        "point_id": "W1",
        "line_id": "L1",
        "x_local_m": 400.0,
        "y_local_m": 220.0,
        "source_file": "W1.dat",
        "depth_rule": DEPTH_RULE,
        "z_rule": Z_RULE,
        "rule_version": RULE_VERSION,
    }
    return [
        DerivedVelocitySample(
            sample_id="W1:2",
            depth_m=50.0,
            z_local_m=-50.0,
            vx_km_s=0.2,
            wl_half_km=0.05,
            source_line=2,
            vx_raw_token="0.200000",
            **base,
        ),
        DerivedVelocitySample(
            sample_id="W1:3",
            depth_m=50.505,
            z_local_m=-50.505,
            vx_km_s=0.2,
            wl_half_km=0.050505,
            source_line=3,
            vx_raw_token="0.200000",
            **base,
        ),
    ]


def test_accepted_bytes_use_bom_crlf_and_golden_value_formats():
    payload = accepted_csv_bytes(canonical_rows())
    assert payload.startswith(b"\xef\xbb\xbf")
    assert payload.count(b"\r\n") == 3
    assert b",true," in payload
    assert b",400,220,50,-50,0.2," in payload


def test_accepted_header_is_exact_and_record_order_is_source_order():
    payload = accepted_csv_bytes(canonical_rows())
    lines = payload.decode("utf-8-sig").split("\r\n")
    assert lines[0] == ACCEPTED_HEADER
    assert lines[1].startswith("W1:2,")
    assert lines[2].startswith("W1:3,")
    assert lines[3] == ""
    # Non-integral floats keep the full shortest repr; nothing is rounded.
    assert ",50.505,-50.505,0.2,0.050505," in lines[2]


def test_whole_number_float_columns_serialize_without_decimal_point():
    rows = canonical_rows()
    rows[0] = rows[0].model_copy(update={"wl_half_km": 3.0, "depth_m": 3000.0, "z_local_m": -3000.0})
    payload = accepted_csv_bytes(rows)
    assert b",3000,-3000,0.2,3," in payload
    assert b"3000.0" not in payload
    assert b",3.0," not in payload


def test_rejected_bytes_append_filter_columns_with_golden_tokens():
    source = canonical_rows()[0]
    rejected = RejectedFilteredSample.from_derived(
        source,
        depth_zscore=3.3979756826138052,
        vx_zscore=2.0252106370191294,
        filter_reason="深度",
    )
    payload = rejected_csv_bytes([rejected])
    lines = payload.decode("utf-8-sig").split("\r\n")
    assert lines[0] == REJECTED_HEADER
    assert rejected.filter_status == "剔除"
    assert lines[1].endswith(",3.3979756826138052,2.0252106370191294,剔除,深度")
    assert payload.count(b"\r\n") == 2


def test_empty_rejected_set_is_header_only():
    payload = rejected_csv_bytes([])
    assert payload.count(b"\r\n") == 1
    assert payload.decode("utf-8-sig").split("\r\n")[0] == REJECTED_HEADER


def test_write_canonical_bytes_replaces_atomically(tmp_path: Path):
    target = tmp_path / "out" / "accepted.csv"
    first = accepted_csv_bytes(canonical_rows())
    write_canonical_bytes(target, first)
    assert target.read_bytes() == first
    second = rejected_csv_bytes([])
    write_canonical_bytes(target, second)
    assert target.read_bytes() == second
    leftovers = [path for path in target.parent.iterdir() if path.name != target.name]
    assert leftovers == []


def _fixture_pipeline(tmp_path: Path):
    data_dir = write_fixture_tree(tmp_path)
    config = load_microseismic_config(write_fixture_config(tmp_path, data_dir))
    audit = build_audit(config)
    finite, _ = derive_local_samples(config, audit)
    filtered = filter_three_sigma(
        finite,
        threshold=config.derivation.sigma_threshold,
        ddof=config.derivation.sigma_ddof,
    )
    aggregated = aggregate_exact_xyz(filtered.accepted)
    return config, filtered, aggregated


def test_verify_golden_passes_for_repinned_fixture(tmp_path: Path):
    config, filtered, aggregated = _fixture_pipeline(tmp_path)
    result = verify_golden(config, filtered, aggregated)
    assert [check.name for check in result.checks] == [
        "accepted_count",
        "rejected_count",
        "per_line_accepted_counts",
        "rejection_reason_counts",
        "accepted_sha256",
        "rejected_sha256",
        "conflict_group_count",
        "conflict_row_count",
        "modeling_node_count",
    ]
    assert all(check.passed for check in result.checks)
    assert result.passed is True
    per_line = next(check for check in result.checks if check.name == "per_line_accepted_counts")
    assert per_line.actual == {"L1": 4, "L2": 2}
    assert per_line.expected == {"L1": 4, "L2": 2}
    pinned = next(check for check in result.checks if check.name == "accepted_sha256")
    assert pinned.actual == config.derivation.golden.accepted_sha256
    assert pinned.actual == sha256(accepted_csv_bytes(filtered.accepted)).hexdigest()


def test_verify_golden_reports_failures_without_raising(tmp_path: Path):
    config, filtered, aggregated = _fixture_pipeline(tmp_path)
    tampered_golden = config.derivation.golden.model_copy(update={"accepted_sha256": "0" * 64})
    tampered = config.model_copy(
        update={"derivation": config.derivation.model_copy(update={"golden": tampered_golden})}
    )
    result = verify_golden(tampered, filtered, aggregated)
    assert result.passed is False
    failed = [check for check in result.checks if not check.passed]
    assert [check.name for check in failed] == ["accepted_sha256"]
    assert failed[0].expected == "0" * 64
    assert failed[0].actual == sha256(accepted_csv_bytes(filtered.accepted)).hexdigest()
