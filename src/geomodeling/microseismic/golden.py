from __future__ import annotations

from collections import Counter
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict

from .canonical import accepted_csv_bytes, rejected_csv_bytes
from .config import MicroseismicConfig
from .schemas import AggregationResult, ThreeSigmaResult

__all__ = ["GoldenCheck", "GoldenGateResult", "verify_golden"]


class GoldenCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    expected: Any
    actual: Any


class GoldenGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    checks: list[GoldenCheck]


def verify_golden(
    config: MicroseismicConfig,
    filtered: ThreeSigmaResult,
    aggregated: AggregationResult,
) -> GoldenGateResult:
    """Compare one derivation run against the pinned golden contract.

    Every check returns a structured GoldenCheck; nothing is raised here, so
    the caller decides whether to persist diagnostics or block the run.
    """
    spec = config.derivation
    accepted = filtered.accepted
    rejected = filtered.rejected
    checks: list[GoldenCheck] = []

    def check(name: str, expected: Any, actual: Any) -> None:
        checks.append(GoldenCheck(name=name, passed=expected == actual, expected=expected, actual=actual))

    check("accepted_count", spec.expected_accepted, len(accepted))
    check("rejected_count", spec.expected_rejected, len(rejected))

    valid_counts = config.expected.get("valid_numeric_counts")
    if valid_counts is not None:
        rejected_per_line = Counter(row.line_id for row in rejected)
        expected_per_line = {
            line_id: count - rejected_per_line.get(line_id, 0)
            for line_id, count in valid_counts.items()
        }
        actual_per_line = dict(Counter(row.line_id for row in accepted))
        check("per_line_accepted_counts", expected_per_line, actual_per_line)

    reason_counts = Counter(row.filter_reason for row in rejected)
    checks.append(
        GoldenCheck(
            name="rejection_reason_counts",
            passed=sum(reason_counts.values()) == spec.expected_rejected
            and all(reason_counts.keys()),
            expected={"rejected_total": spec.expected_rejected},
            actual=dict(reason_counts),
        )
    )

    check(
        "accepted_sha256",
        spec.golden.accepted_sha256,
        sha256(accepted_csv_bytes(accepted)).hexdigest(),
    )
    check(
        "rejected_sha256",
        spec.golden.rejected_sha256,
        sha256(rejected_csv_bytes(rejected)).hexdigest(),
    )
    check("conflict_group_count", spec.expected_conflict_groups, aggregated.conflict_group_count)
    check("conflict_row_count", spec.expected_conflict_rows, aggregated.conflict_row_count)
    check("modeling_node_count", spec.expected_modeling_nodes, len(aggregated.nodes))
    return GoldenGateResult(passed=all(item.passed for item in checks), checks=checks)
