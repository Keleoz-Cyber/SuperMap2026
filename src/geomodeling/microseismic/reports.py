from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..io import write_json
from .schemas import (
    MicroseismicAuditResult,
    MicroseismicIssue,
    MicroseismicValidationReport,
    SourceFileManifestEntry,
    SurveyLine,
    SurveyPoint,
    VelocitySample,
)

SEVERITY_ORDER = {"blocker": 0, "error": 1, "warning": 2, "info": 3}


def _frame(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    for column in frame.columns:
        frame[column] = frame[column].apply(lambda value: ";".join(value) if isinstance(value, list) else value)
    return frame


def export_survey_lines(lines: list[SurveyLine], path: Path) -> Path:
    _frame([line.model_dump() for line in lines]).to_csv(path, index=False, encoding="utf-8")
    return path


def export_survey_points(points: list[SurveyPoint], path: Path) -> Path:
    _frame([point.model_dump() for point in points]).to_csv(path, index=False, encoding="utf-8")
    return path


def export_velocity_samples(samples: list[VelocitySample], path: Path) -> Path:
    _frame([sample.model_dump() for sample in samples]).to_csv(path, index=False, encoding="utf-8")
    return path


def export_manifest(manifest: list[SourceFileManifestEntry], path: Path) -> Path:
    return write_json(path, [entry.model_dump(mode="json") for entry in manifest])


def export_validation_json(report: MicroseismicValidationReport, path: Path) -> Path:
    return write_json(path, report)


def export_issues_json(issues: list[MicroseismicIssue], path: Path) -> Path:
    ordered = sorted(issues, key=lambda issue: (SEVERITY_ORDER.get(issue.severity, 9), issue.code))
    return write_json(path, [issue.model_dump(mode="json") for issue in ordered])


def export_issues_markdown(issues: list[MicroseismicIssue], path: Path) -> Path:
    ordered = sorted(issues, key=lambda issue: (SEVERITY_ORDER.get(issue.severity, 9), issue.code))
    lines = [
        "# Microseismic v0.2a Issue List",
        "",
        f"Total issues: {len(ordered)}",
        "",
        "| severity | code | affected_scope | blocks_geometry | blocks_cleaning | blocks_interpolation |",
        "|---|---|---|---|---|---|",
    ]
    for issue in ordered:
        lines.append(
            f"| {issue.severity} | {issue.code} | {issue.affected_scope} | {issue.blocks_geometry} | {issue.blocks_cleaning} | {issue.blocks_interpolation} |"
        )
    lines.append("")
    for issue in ordered:
        lines.extend(
            [
                f"## {issue.code} ({issue.severity})",
                "",
                f"- message: {issue.message}",
                f"- affected_scope: {issue.affected_scope}",
                f"- evidence: {issue.evidence}",
                f"- source_a: {issue.source_a}",
                f"- source_b: {issue.source_b}",
                f"- current_handling: {issue.current_handling}",
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def export_data_quality_markdown(result: MicroseismicAuditResult, path: Path) -> Path:
    counts = result.counts
    lines = [
        "# Microseismic v0.2a Data Quality Report",
        "",
        "## Row-count chain",
        "",
        f"- generic first-pass parsed rows (including NUL pseudo-lines): {counts.get('parsed_row_total_with_nul')}",
        f"- NUL terminator pseudo-lines (one per DAT, excluded from samples): {counts.get('nul_terminator_count')}",
        f"- real source records: {counts.get('source_record_total')}",
        f"- invalid numeric records (W8 1.#QNAN0): {counts.get('invalid_numeric_total')}",
        f"- finite valid numeric records: {counts.get('valid_numeric_total')}",
        "",
        "## Per-line statistics",
        "",
        "| line | source records | valid numeric | points |",
        "|---|---:|---:|---:|",
    ]
    source_counts = counts.get("source_record_counts", {})
    valid_counts = counts.get("valid_numeric_counts", {})
    point_counts = {line.line_id: line.formal_point_count for line in result.lines}
    for line_id in sorted(source_counts):
        lines.append(f"| {line_id} | {source_counts[line_id]} | {valid_counts.get(line_id)} | {point_counts.get(line_id)} |")
    lines.extend(
        [
            "",
            "## W8 special NaN record",
            "",
            "W8.dat line 2 keeps raw token `1.#QNAN0` with `is_numeric_valid=false`. It stays in `velocity_samples.csv` (2,006 rows) but is excluded from the 2,005 finite valid records. It is not set to 0, not silently deleted, and not overwritten by interpolation.",
            "",
            "## Source conflicts preserved",
            "",
            "- Paper table `823/818/364=2,005` conflicts with parsed file facts `823/819/364=2,006` source records and `822/819/364=2,005` finite values; registered as `LINE_COUNT_CONFLICT` without moving records between lines.",
            "- W28 and the 350 m interval are conflict-only registrations; formal L3 is W24—W27 (800/320/335 m).",
            "- Cleaning statements conflict: 80/2,005 ≈ 3.99% vs the stated 3.59%, and linear interpolation vs nearest-5-point IDW; no formal cleaning is produced in v0.2a.",
            "",
            "## Semantic boundaries",
            "",
            "- `WL/2(km)` is preserved verbatim; its physical meaning is unconfirmed (`WL_HALF_MEANING_UNCONFIRMED`).",
            "- `derived_depth_m` / `derived_z_m` are empty with `depth_derivation_status=unconfirmed`.",
            "- No absolute coordinates, EPSG, origin, or azimuth are available; `x_local_m`/`y_local_m` remain empty. v0.2a provides only 1D `cumulative_s_m` from registered point intervals.",
            "",
            "## Capability statement",
            "",
            "v0.2a can: inventory and hash sources, parse 2,006 traceable records, build the three standard tables, compute 1D cumulative distances, and register conflicts/issues. It cannot: reconstruct 2D/3D coordinates, confirm depth/Z, perform formal cleaning, or run interpolation.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


DATA_DICTIONARY = """# Microseismic v0.2a Data Dictionary

## source_manifest.json
One entry per formal DAT file: `source_file_id`, `relative_path`, `file_name`, `size_bytes`, `sha256`, `mtime`, `encoding`, `header_text`, `nul_terminator`, `nul_pseudo_line_count`, `point_id`, `line_id`, `source_record_count`, `valid_numeric_count`, `invalid_numeric_count`, `parse_status`, `quality_issues`.

## survey_lines.csv
| column | meaning |
|---|---|
| line_id | formal line identifier L1/L2/L3 |
| point_start / point_end | first and last formal point |
| formal_point_count | number of formal points on the line |
| source_record_count | parsed source records (NUL pseudo-lines excluded) |
| valid_numeric_count | finite numeric records |
| geometry_status | `cumulative_1d_only` in v0.2a |
| crs_type | `none`; no CRS claimed |
| origin_status / direction_status | `unconfirmed` |
| geometry_source | interval workbook and order source |
| source_confidence | which parts are source-confirmed |
| notes | scope notes |

## survey_points.csv
| column | meaning |
|---|---|
| point_id / original_point_label | formal point id and source label |
| source_file_id | owning DAT manifest id |
| line_id | owning line |
| sequence_on_line | 1-based order on the line |
| previous_point_id | previous formal point |
| interval_from_previous_m | registered interval from 点间距.xlsx |
| cumulative_s_m | 1D along-line cumulative distance |
| interval_source / order_source | provenance of interval and order |
| included_in_formal_set / exclusion_reason | formal membership; W28 is conflict-only |
| source_record_count / valid_numeric_count | per-point record statistics |
| coordinate_status | `unconfirmed`; x_local_m/y_local_m stay empty |
| z_reference_status | `unconfirmed` |
| source_confidence | confidence statement |
| notes | extra notes |

## velocity_samples.csv
One row per real source record (2,006 total). Key columns:
| column | meaning |
|---|---|
| sample_id | `{point_id}:{source_line_number}`, unique and traceable |
| point_id / line_id | owning point and line |
| source_file_id / source_file_name / source_line_number | exact source trace |
| wl_half_km_raw_token / vx_raw_token | verbatim source tokens |
| wl_half_km_value / vx_value | standardized finite values, empty when invalid |
| source_unit | unit statement (WL/2(km) verbatim; Vx unit pending) |
| is_numeric_valid / invalid_reason | finite-validity flag and reason |
| quality_flags | e.g. SOURCE_SPECIAL_NAN_TOKEN |
| included_in_raw / included_in_valid_numeric / included_in_clean_candidate | membership flags; clean candidate stays false in v0.2a |
| outlier_reason / imputed / imputation_method / cleaning_version | cleaning fields; no formal cleaning in v0.2a |
| derived_depth_m / derived_z_m / depth_derivation_status | unconfirmed derivations stay empty |
| notes | per-row notes |
"""


def export_data_dictionary(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DATA_DICTIONARY, encoding="utf-8")
    return path


def export_audit_summary_markdown(result: MicroseismicAuditResult, path: Path) -> Path:
    counts = result.counts
    failed = [check for check in result.validation.checks if not check.passed]
    validation_blockers = [
        check for check in failed if check.severity in {"blocker", "error"}
    ]
    geometry_gates = [issue for issue in result.issues if issue.blocks_geometry]
    cleaning_gates = [issue for issue in result.issues if issue.blocks_cleaning]
    interpolation_gates = [issue for issue in result.issues if issue.blocks_interpolation]
    lines = [
        "# Microseismic v0.2a Audit Summary",
        "",
        f"- validation_passed: {result.validation.passed}",
        f"- dat_files: {counts.get('dat_file_count')} (total bytes {sum(entry.size_bytes for entry in result.manifest)})",
        f"- nul_terminators: {counts.get('nul_terminator_count')}",
        f"- source_records: {counts.get('source_record_total')} per-line {counts.get('source_record_counts')}",
        f"- valid_numeric: {counts.get('valid_numeric_total')} per-line {counts.get('valid_numeric_counts')}",
        f"- invalid_numeric: {counts.get('invalid_numeric_total')} (W8 1.#QNAN0)",
        f"- survey_lines rows: {len(result.lines)}",
        f"- survey_points rows: {len(result.points)} (formal {sum(1 for point in result.points if point.included_in_formal_set)})",
        f"- velocity_samples rows: {len(result.samples)}",
        f"- sha256_protection_unchanged: {result.validation.sha256_protection.get('unchanged')}",
        f"- issues: {len(result.issues)} (validation blockers {len(validation_blockers)})",
        "",
        "## Downstream gates",
        "",
        "These gates are separate from validation blockers: validation passing means the audit facts are consistent, not that 3D interpolation is ready.",
        "",
        f"- geometry_blocked: {bool(geometry_gates)} ({', '.join(sorted(issue.code for issue in geometry_gates)) or 'none'})",
        f"- cleaning_blocked: {bool(cleaning_gates)} ({', '.join(sorted(issue.code for issue in cleaning_gates)) or 'none'})",
        f"- interpolation_blocked: {bool(interpolation_gates)} ({', '.join(sorted(issue.code for issue in interpolation_gates)) or 'none'})",
        "",
        "## Validation blockers",
        "",
    ]
    if failed:
        for check in failed:
            lines.append(f"- {check.name} ({check.severity}): {check.evidence}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Boundaries",
            "",
            "- 1D cumulative distance only; no X/Y/Z fabricated.",
            "- WL/2(km) meaning, depth/Z derivation, origin, azimuth, CRS: unconfirmed.",
            "- Cleaning conflicts registered; no formal cleaning output.",
            "- W28 conflict-only; excluded from formal L3.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
