from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from geomodeling.microseismic.config import load_microseismic_config
from geomodeling.microseismic.derivation import derive_local_samples
from geomodeling.microseismic.filtering import filter_three_sigma
from geomodeling.microseismic.schemas import DerivedVelocitySample
from geomodeling.microseismic.service import build_audit

from microseismic_fixtures import write_fixture_config, write_fixture_tree


def derived_rows(depth: list[float], vx: list[float]) -> list[DerivedVelocitySample]:
    """Synthetic derived rows; portable tests never touch real-data counts."""
    assert len(depth) == len(vx)
    rows: list[DerivedVelocitySample] = []
    for index, (depth_value, vx_value) in enumerate(zip(depth, vx, strict=True)):
        rows.append(
            DerivedVelocitySample(
                sample_id=f"W{index + 1}:1",
                point_id=f"W{index + 1}",
                line_id="L1",
                x_local_m=float(index * 100),
                y_local_m=0.0,
                depth_m=float(depth_value),
                z_local_m=-float(depth_value),
                vx_km_s=float(vx_value),
                wl_half_km=float(depth_value) / 1000.0,
                source_file=f"W{index + 1}.dat",
                source_line=1,
                vx_raw_token=f"{vx_value:.6f}",
                depth_rule="DEPTH_M=WL_HALF_KM*1000;down_positive",
                z_rule="Z_LOCAL_M=-DEPTH_M;up_positive",
                rule_version="test",
            )
        )
    return rows


def test_three_sigma_uses_sample_std_once_globally():
    rows = derived_rows(depth=[0, 1, 2, 3, 100], vx=[1, 1, 1, 1, 1])
    result = filter_three_sigma(rows, threshold=1.5, ddof=1)
    expected = np.std([0, 1, 2, 3, 100], ddof=1)
    assert result.depth_std == pytest.approx(expected)
    assert result.rejected[0].sample_id == rows[-1].sample_id
    assert result.rejected[0].filter_reason == "深度"


def test_statistics_are_not_recomputed_after_rejection():
    rows = derived_rows(depth=[0, 1, 2, 3, 100], vx=[1, 1, 1, 1, 1])
    result = filter_three_sigma(rows, threshold=1.5, ddof=1)
    # One global pass over every input row: an iterative implementation would
    # drop the 100 m outlier and recompute std([0, 1, 2, 3]) instead.
    assert result.depth_mean == pytest.approx(np.mean([0, 1, 2, 3, 100]))
    assert result.depth_std == pytest.approx(np.std([0, 1, 2, 3, 100], ddof=1))
    assert result.depth_std != pytest.approx(np.std([0, 1, 2, 3], ddof=1))
    assert result.vx_mean == pytest.approx(np.mean([1, 1, 1, 1, 1]))
    assert result.vx_std == pytest.approx(np.std([1, 1, 1, 1, 1], ddof=1))


def test_abs_zscore_equal_to_threshold_is_retained():
    # depth [0, 1, 2] has mean 1 and sample std 1, so the boundary rows sit at
    # exactly |z| == 1.0 with no floating-point ambiguity.
    rows = derived_rows(depth=[0, 1, 2], vx=[5, 5, 5])
    result = filter_three_sigma(rows, threshold=1.0, ddof=1)
    assert result.rejected == []
    assert [row.sample_id for row in result.accepted] == [row.sample_id for row in rows]


def test_abs_zscore_strictly_above_threshold_is_rejected():
    rows = derived_rows(depth=[0, 1, 2], vx=[5, 5, 5])
    result = filter_three_sigma(rows, threshold=0.999, ddof=1)
    assert [row.sample_id for row in result.rejected] == [rows[0].sample_id, rows[2].sample_id]
    assert all(row.filter_reason == "深度" for row in result.rejected)
    assert [row.sample_id for row in result.accepted] == [rows[1].sample_id]


def test_velocity_outlier_reports_velocity_reason():
    rows = derived_rows(depth=[1, 1, 1, 1, 1], vx=[0.5, 0.5, 0.5, 0.5, 9.5])
    result = filter_three_sigma(rows, threshold=1.5, ddof=1)
    assert len(result.rejected) == 1
    assert result.rejected[0].sample_id == rows[-1].sample_id
    assert result.rejected[0].filter_reason == "速度"


def test_both_reasons_serialize_as_joined_string():
    rows = derived_rows(depth=[0, 1, 2, 3, 100], vx=[1, 1, 1, 1, 9])
    result = filter_three_sigma(rows, threshold=1.5, ddof=1)
    assert len(result.rejected) == 1
    rejected = result.rejected[0]
    assert rejected.filter_reason == "深度;速度"
    dumped = rejected.model_dump(by_alias=True)
    assert dumped["FILTER_REASON"] == "深度;速度"
    assert dumped["FILTER_STATUS"] == "rejected"
    assert "DEPTH_ZSCORE" in dumped
    assert "VX_ZSCORE" in dumped


def test_output_order_follows_source_order():
    rows = derived_rows(depth=[0, 1, 2, 3, 100], vx=[1, 1, 1, 1, 1])
    # |z| values: 0.481, 0.458, 0.436, 0.413, 1.788 — threshold 0.46 rejects
    # the first and last rows while keeping the middle three in source order.
    result = filter_three_sigma(rows, threshold=0.46, ddof=1)
    assert [row.sample_id for row in result.rejected] == [rows[0].sample_id, rows[-1].sample_id]
    assert [row.sample_id for row in result.accepted] == [
        rows[1].sample_id,
        rows[2].sample_id,
        rows[3].sample_id,
    ]


def test_rejected_rows_keep_both_zscores_and_source_fields():
    rows = derived_rows(depth=[0, 1, 2, 3, 100], vx=[1, 1, 1, 1, 1])
    result = filter_three_sigma(rows, threshold=1.5, ddof=1)
    rejected = result.rejected[0]
    source = rows[-1]
    assert rejected.sample_id == source.sample_id
    assert rejected.point_id == source.point_id
    assert rejected.line_id == source.line_id
    assert rejected.source_file == source.source_file
    assert rejected.source_line == source.source_line
    assert (rejected.x_local_m, rejected.y_local_m) == (source.x_local_m, source.y_local_m)
    assert rejected.depth_m == source.depth_m
    assert rejected.z_local_m == source.z_local_m
    assert rejected.vx_km_s == source.vx_km_s
    assert rejected.vx_raw_token == source.vx_raw_token
    expected_depth_z = (100 - np.mean([0, 1, 2, 3, 100])) / np.std([0, 1, 2, 3, 100], ddof=1)
    assert rejected.depth_zscore == pytest.approx(expected_depth_z)
    # Constant vx has zero deviation, so its z-score is exactly zero.
    assert rejected.vx_zscore == 0.0
    assert rejected.filter_status == "rejected"
    assert rejected.filter_reason == "深度"


def test_source_rows_are_never_mutated():
    rows = derived_rows(depth=[0, 1, 2, 3, 100], vx=[1, 1, 1, 1, 1])
    before = [row.model_dump() for row in rows]
    filter_three_sigma(rows, threshold=1.5, ddof=1)
    assert [row.model_dump() for row in rows] == before


def test_fixture_finite_rows_all_accepted_at_configured_threshold(tmp_path: Path):
    data_dir = write_fixture_tree(tmp_path)
    config = load_microseismic_config(write_fixture_config(tmp_path, data_dir))
    finite, _ = derive_local_samples(config, build_audit(config))
    result = filter_three_sigma(
        finite,
        threshold=config.derivation.sigma_threshold,
        ddof=config.derivation.sigma_ddof,
    )
    assert len(result.accepted) == config.derivation.expected_accepted
    assert len(result.rejected) == config.derivation.expected_rejected
    assert [row.sample_id for row in result.accepted] == [row.sample_id for row in finite]
