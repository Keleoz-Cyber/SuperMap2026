from __future__ import annotations

from collections import Counter

from .config import MicroseismicConfig
from .schemas import (
    MicroseismicCheck,
    MicroseismicIssue,
    MicroseismicSeverity,
    MicroseismicValidationReport,
    SourceFileManifestEntry,
    SurveyPoint,
    VelocitySample,
)


def _check(name: str, passed: bool, evidence: str, severity: MicroseismicSeverity = MicroseismicSeverity.BLOCKER) -> MicroseismicCheck:
    return MicroseismicCheck(name=name, passed=passed, severity=severity, evidence=evidence)


def run_contract_checks(
    config: MicroseismicConfig,
    manifest: list[SourceFileManifestEntry],
    samples: list[VelocitySample],
    points: list[SurveyPoint],
    problems: dict[str, list[str]],
    sha_before: dict[str, str],
    sha_after: dict[str, str],
) -> MicroseismicValidationReport:
    expected = config.expected
    checks: list[MicroseismicCheck] = []

    checks.append(
        _check(
            "formal_dat_file_count",
            len(manifest) == expected["dat_file_count"] and not problems["missing_files"],
            f"manifest={len(manifest)} expected={expected['dat_file_count']} missing={problems['missing_files']}",
        )
    )
    checks.append(
        _check(
            "no_unexpected_dat_files",
            not problems["unexpected_files"],
            f"unexpected={problems['unexpected_files']}",
            severity=MicroseismicSeverity.ERROR,
        )
    )

    line_points = {line.line_id: len(line.points) for line in config.lines}
    checks.append(
        _check(
            "line_point_counts",
            line_points == expected["line_point_counts"],
            f"actual={line_points} expected={expected['line_point_counts']}",
        )
    )

    per_file: dict[str, int] = {entry.point_id: entry.source_record_count for entry in manifest}
    point_line = {point.point_id: line.line_id for line in config.lines for point in line.points}
    source_by_line = Counter()
    valid_by_line = Counter()
    invalid_by_line = Counter()
    for entry in manifest:
        line_id = point_line[entry.point_id]
        source_by_line[line_id] += entry.source_record_count
        valid_by_line[line_id] += entry.valid_numeric_count
        invalid_by_line[line_id] += entry.invalid_numeric_count
    source_counts = dict(source_by_line)
    valid_counts = dict(valid_by_line)
    source_total = sum(source_counts.values())
    valid_total = sum(valid_counts.values())
    invalid_total = sum(invalid_by_line.values())

    checks.append(
        _check(
            "source_record_counts_per_line",
            source_counts == expected["source_record_counts"] and source_total == expected["source_record_total"],
            f"actual={source_counts} total={source_total} expected={expected['source_record_counts']} total={expected['source_record_total']}",
        )
    )
    checks.append(
        _check(
            "valid_numeric_counts_per_line",
            valid_counts == expected["valid_numeric_counts"] and valid_total == expected["valid_numeric_total"],
            f"actual={valid_counts} total={valid_total} expected={expected['valid_numeric_counts']} total={expected['valid_numeric_total']}",
        )
    )
    checks.append(
        _check(
            "invalid_numeric_total",
            invalid_total == expected["invalid_numeric_total"],
            f"actual={invalid_total} expected={expected['invalid_numeric_total']}",
        )
    )

    special_point = expected.get("special_nan_point")
    special_token = expected.get("special_nan_token")
    special_rows = [sample for sample in samples if "SOURCE_SPECIAL_NAN_TOKEN" in sample.quality_flags]
    checks.append(
        _check(
            "special_nan_traceable",
            len(special_rows) == 1
            and special_rows[0].point_id == special_point
            and special_rows[0].vx_raw_token == special_token
            and not special_rows[0].is_numeric_valid
            and special_rows[0].vx_value is None,
            f"rows={[(row.point_id, row.source_line_number, row.vx_raw_token) for row in special_rows]}",
        )
    )

    nul_count = sum(entry.nul_pseudo_line_count for entry in manifest)
    nul_in_samples = sum(1 for sample in samples if sample.wl_half_km_raw_token is None and sample.vx_raw_token is None)
    checks.append(
        _check(
            "nul_terminators_excluded",
            nul_count == expected["nul_terminator_count"] and nul_in_samples == 0,
            f"nul_pseudo_lines={nul_count} expected={expected['nul_terminator_count']} leaked_into_samples={nul_in_samples}",
        )
    )

    file_per_point = Counter(entry.point_id for entry in manifest)
    unique_file = all(count == 1 for count in file_per_point.values()) and len(file_per_point) == expected["dat_file_count"]
    checks.append(
        _check(
            "one_dat_per_formal_point",
            unique_file,
            f"points_with_files={len(file_per_point)} duplicates={[key for key, value in file_per_point.items() if value != 1]}",
        )
    )

    file_line_keys = [(sample.source_file_id, sample.source_line_number) for sample in samples]
    unique_file_line = len(file_line_keys) == len(set(file_line_keys))
    sample_ids = [sample.sample_id for sample in samples]
    unique_sample_ids = len(sample_ids) == len(set(sample_ids))
    checks.append(
        _check(
            "source_file_line_unique",
            unique_file_line,
            f"rows={len(file_line_keys)} unique={len(set(file_line_keys))}",
        )
    )
    checks.append(
        _check(
            "sample_id_unique",
            unique_sample_ids,
            f"rows={len(sample_ids)} unique={len(set(sample_ids))}",
        )
    )

    formal_ids = set(config.formal_point_ids())
    excluded_ids = {point.point_id for point in config.excluded_points}
    formal_sample_points = {sample.point_id for sample in samples}
    formal_table_points = {point.point_id for point in points if point.included_in_formal_set}
    checks.append(
        _check(
            "excluded_points_not_in_formal_set",
            not (excluded_ids & formal_sample_points) and not (excluded_ids & formal_table_points) and not (excluded_ids & formal_ids),
            f"excluded={sorted(excluded_ids)} formal_table={sorted(formal_table_points)}",
        )
    )

    monotonic = True
    traceable = True
    for line in config.lines:
        line_points_rows = sorted(
            [point for point in points if point.line_id == line.line_id and point.included_in_formal_set],
            key=lambda row: row.sequence_on_line,
        )
        cumulative = 0.0
        for index, row in enumerate(line_points_rows):
            if index == 0:
                if row.cumulative_s_m != 0 or row.interval_from_previous_m is not None:
                    traceable = False
            else:
                cumulative += row.interval_from_previous_m or 0.0
                if abs(row.cumulative_s_m - cumulative) > 1e-9 or row.cumulative_s_m <= line_points_rows[index - 1].cumulative_s_m:
                    monotonic = False
    checks.append(
        _check(
            "cumulative_distance_monotonic_traceable",
            monotonic and traceable,
            f"monotonic={monotonic} traceable={traceable}",
        )
    )

    no_fake_xy = all(point.x_local_m is None and point.y_local_m is None for point in points)
    no_fake_z = all(sample.derived_depth_m is None and sample.derived_z_m is None and sample.depth_derivation_status == "unconfirmed" for sample in samples)
    checks.append(
        _check(
            "no_fabricated_coordinates_or_z",
            no_fake_xy and no_fake_z,
            f"points_with_xy={sum(1 for point in points if point.x_local_m is not None or point.y_local_m is not None)} samples_with_z={sum(1 for sample in samples if sample.derived_z_m is not None or sample.derived_depth_m is not None)}",
        )
    )

    unchanged = sha_before == sha_after
    changed = [path for path in sha_before if sha_before.get(path) != sha_after.get(path)]
    checks.append(
        _check(
            "source_sha256_unchanged",
            unchanged and len(sha_before) == len(manifest),
            f"files={len(sha_before)} changed={changed}",
        )
    )

    passed = all(check.passed for check in checks if check.severity in {MicroseismicSeverity.BLOCKER, MicroseismicSeverity.ERROR})
    counts = {
        "dat_file_count": len(manifest),
        "nul_terminator_count": nul_count,
        "source_record_counts": source_counts,
        "source_record_total": source_total,
        "valid_numeric_counts": valid_counts,
        "valid_numeric_total": valid_total,
        "invalid_numeric_total": invalid_total,
        "parsed_row_total_with_nul": source_total + nul_count,
        "per_file_source_records": per_file,
    }
    return MicroseismicValidationReport(
        passed=passed,
        checks=checks,
        counts=counts,
        sha256_protection={
            "files_checked": len(sha_before),
            "unchanged": unchanged,
            "changed_files": changed,
        },
    )


def issues_from_failed_checks(report: MicroseismicValidationReport) -> list[MicroseismicIssue]:
    issues: list[MicroseismicIssue] = []
    for check in report.checks:
        if check.passed:
            continue
        issues.append(
            MicroseismicIssue(
                severity=check.severity,
                code=f"CONTRACT_{check.name.upper()}",
                message=f"contract check failed: {check.name}",
                affected_scope="microseismic v0.2a audit",
                evidence=check.evidence,
                source_a="parsed DAT files and configuration",
                source_b="expected contract values in config/microseismic.yaml",
                current_handling="block formal outputs until the underlying data or expectation is resolved with evidence",
                blocks_geometry=True,
                blocks_cleaning=True,
                blocks_interpolation=True,
            )
        )
    return issues
