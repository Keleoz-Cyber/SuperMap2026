from __future__ import annotations

from typing import Sequence

import numpy as np

from .schemas import (
    AggregationContractError,
    AggregationResult,
    AggregatedModelingNode,
    DerivedVelocitySample,
)

__all__ = ["aggregate_exact_xyz"]


def aggregate_exact_xyz(rows: Sequence[DerivedVelocitySample]) -> AggregationResult:
    """Collapse exactly collocated candidate rows into unique modeling nodes.

    Grouping keys on the three Python float values directly — no rounding and
    no distance tolerance. Every group must share one point and line identity,
    the modeling value is the group's arithmetic-mean Vx, and source sample
    ids are preserved in source order. The accepted candidate set itself is
    never modified; aggregation only produces the modeling-node collection.
    """
    groups: dict[tuple[float, float, float], list[DerivedVelocitySample]] = {}
    for row in rows:
        key = (row.x_local_m, row.y_local_m, row.z_local_m)
        groups.setdefault(key, []).append(row)
    nodes: list[AggregatedModelingNode] = []
    conflict_group_count = 0
    conflict_row_count = 0
    max_value_range = 0.0
    for (x, y, z), members in groups.items():
        point_ids = {member.point_id for member in members}
        line_ids = {member.line_id for member in members}
        if len(point_ids) != 1 or len(line_ids) != 1:
            raise AggregationContractError(
                f"exact-xyz group at ({x}, {y}, {z}) mixes identities: "
                f"points={sorted(point_ids)}, lines={sorted(line_ids)}"
            )
        vx = np.asarray([member.vx_km_s for member in members], dtype="float64")
        sample_count = len(members)
        vx_min = float(vx.min())
        vx_max = float(vx.max())
        nodes.append(
            AggregatedModelingNode(
                x_local_m=x,
                y_local_m=y,
                z_local_m=z,
                vx_km_s=float(vx.mean()),
                point_id=members[0].point_id,
                line_id=members[0].line_id,
                source_sample_ids=[member.sample_id for member in members],
                sample_count=sample_count,
                vx_min_km_s=vx_min,
                vx_max_km_s=vx_max,
                vx_sample_std_km_s=float(vx.std(ddof=1)) if sample_count > 1 else None,
            )
        )
        if sample_count > 1:
            conflict_group_count += 1
            conflict_row_count += sample_count
            max_value_range = max(max_value_range, vx_max - vx_min)
    return AggregationResult(
        nodes=nodes,
        conflict_group_count=conflict_group_count,
        conflict_row_count=conflict_row_count,
        collapsed_row_count=conflict_row_count - conflict_group_count,
        max_value_range=max_value_range,
    )
