from __future__ import annotations

import numpy as np
import pytest

from geomodeling.microseismic.aggregation import aggregate_exact_xyz
from geomodeling.microseismic.schemas import AggregationContractError, DerivedVelocitySample


def derived(sample_id: str, *, x: float, y: float, z: float, vx: float, point_id: str = "W1", line_id: str = "L1") -> DerivedVelocitySample:
    """Synthetic derived rows; portable tests never touch real-data counts."""
    return DerivedVelocitySample(
        sample_id=sample_id,
        point_id=point_id,
        line_id=line_id,
        x_local_m=float(x),
        y_local_m=float(y),
        depth_m=-float(z),
        z_local_m=float(z),
        vx_km_s=float(vx),
        wl_half_km=-float(z) / 1000.0,
        source_file=f"{point_id}.dat",
        source_line=1,
        vx_raw_token=f"{vx:.6f}",
        depth_rule="DEPTH_M=WL_HALF_KM*1000;down_positive",
        z_rule="Z_LOCAL_M=-DEPTH_M;up_positive",
        rule_version="test",
    )


def test_exact_xyz_conflicts_are_arithmetic_meaned_with_provenance():
    rows = [
        derived("a", x=0, y=0, z=-10, vx=0.3),
        derived("b", x=0, y=0, z=-10, vx=0.9),
        derived("c", x=0, y=0, z=-10.000001, vx=0.4),
    ]
    result = aggregate_exact_xyz(rows)
    assert len(result.nodes) == 2
    node = next(n for n in result.nodes if n.z_local_m == -10)
    assert node.vx_km_s == pytest.approx(0.6)
    assert node.source_sample_ids == ["a", "b"]
    assert node.sample_count == 2
    assert node.vx_sample_std_km_s == pytest.approx(np.std([0.3, 0.9], ddof=1))
    assert node.vx_min_km_s == pytest.approx(0.3)
    assert node.vx_max_km_s == pytest.approx(0.9)
    assert any(n.z_local_m == -10.000001 for n in result.nodes)


def test_singleton_node_keeps_source_value_and_null_std():
    rows = [derived("only", x=5, y=6, z=-70.5, vx=0.4321)]
    result = aggregate_exact_xyz(rows)
    assert len(result.nodes) == 1
    node = result.nodes[0]
    assert node.vx_km_s == 0.4321
    assert node.sample_count == 1
    assert node.source_sample_ids == ["only"]
    assert node.vx_sample_std_km_s is None
    assert node.vx_min_km_s == pytest.approx(0.4321)
    assert node.vx_max_km_s == pytest.approx(0.4321)
    assert result.conflict_group_count == 0
    assert result.conflict_row_count == 0
    assert result.collapsed_row_count == 0
    assert result.max_value_range == 0.0


def test_node_order_follows_first_coordinate_occurrence():
    rows = [
        derived("a", x=0, y=0, z=-10, vx=0.3),
        derived("b", x=1, y=0, z=-20, vx=0.5),
        derived("c", x=0, y=0, z=-10, vx=0.9),
        derived("d", x=2, y=0, z=-30, vx=0.7),
        derived("e", x=1, y=0, z=-20, vx=0.1),
    ]
    result = aggregate_exact_xyz(rows)
    assert [(n.x_local_m, n.z_local_m) for n in result.nodes] == [
        (0.0, -10.0),
        (1.0, -20.0),
        (2.0, -30.0),
    ]
    assert [n.source_sample_ids for n in result.nodes] == [["a", "c"], ["b", "e"], ["d"]]


def test_provenance_covers_every_input_row_exactly_once():
    rows = [
        derived("a", x=0, y=0, z=-10, vx=0.3),
        derived("b", x=0, y=0, z=-10, vx=0.9),
        derived("c", x=0, y=0, z=-10, vx=0.5),
        derived("d", x=1, y=1, z=-20, vx=0.4),
    ]
    result = aggregate_exact_xyz(rows)
    provenance = [sample_id for node in result.nodes for sample_id in node.source_sample_ids]
    assert provenance == ["a", "b", "c", "d"]
    assert sum(node.sample_count for node in result.nodes) == len(rows)
    assert result.conflict_group_count == 1
    assert result.conflict_row_count == 3
    assert result.collapsed_row_count == 2
    assert result.max_value_range == pytest.approx(0.9 - 0.3)


def test_max_value_range_tracks_largest_conflict_group_spread():
    rows = [
        derived("a", x=0, y=0, z=-10, vx=0.3),
        derived("b", x=0, y=0, z=-10, vx=0.9),
        derived("c", x=1, y=1, z=-20, vx=1.0),
        derived("d", x=1, y=1, z=-20, vx=1.2),
    ]
    result = aggregate_exact_xyz(rows)
    assert result.conflict_group_count == 2
    assert result.max_value_range == pytest.approx(0.6)


def test_conflicting_point_or_line_identity_is_a_contract_error():
    rows = [
        derived("a", x=0, y=0, z=-10, vx=0.3, point_id="W1", line_id="L1"),
        derived("b", x=0, y=0, z=-10, vx=0.9, point_id="W2", line_id="L1"),
    ]
    with pytest.raises(AggregationContractError):
        aggregate_exact_xyz(rows)
    rows = [
        derived("a", x=0, y=0, z=-10, vx=0.3, point_id="W1", line_id="L1"),
        derived("b", x=0, y=0, z=-10, vx=0.9, point_id="W1", line_id="L2"),
    ]
    with pytest.raises(AggregationContractError):
        aggregate_exact_xyz(rows)


def test_empty_input_yields_zero_nodes_and_zeroed_statistics():
    result = aggregate_exact_xyz([])
    assert result.nodes == []
    assert result.conflict_group_count == 0
    assert result.conflict_row_count == 0
    assert result.collapsed_row_count == 0
    assert result.max_value_range == 0.0
