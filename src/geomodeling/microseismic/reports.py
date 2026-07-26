from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from ..io import write_json
from .schemas import (
    COORD_TYPE_LOCAL,
    DEPTH_RULE,
    Z_RULE,
    AggregationResult,
    DerivedVelocitySample,
    InvalidDerivedSample,
    MicroseismicAuditResult,
    MicroseismicIssue,
    MicroseismicValidationReport,
    SourceFileManifestEntry,
    SurveyLine,
    SurveyPoint,
    VelocitySample,
)

if TYPE_CHECKING:
    from .service import MicroseismicDerivationResult

SEVERITY_ORDER = {"blocker": 0, "error": 1, "warning": 2, "info": 3}

AGGREGATED_NODE_COLUMNS = (
    "POINT_ID",
    "LINE_ID",
    "X_LOCAL_M",
    "Y_LOCAL_M",
    "Z_LOCAL_M",
    "VX_KM_S",
    "SOURCE_SAMPLE_IDS",
    "SAMPLE_COUNT",
    "VX_MIN_KM_S",
    "VX_MAX_KM_S",
    "VX_SAMPLE_STD_KM_S",
)

PROVENANCE_COLUMNS = (
    "source_row",
    "point_id",
    "line_id",
    "x_local_m",
    "y_local_m",
    "z_local_m",
    "vx_km_s",
    "source_sample_ids",
    "sample_count",
    "vx_min_km_s",
    "vx_max_km_s",
    "vx_sample_std_km_s",
)

SOURCE_ROW_RULE = (
    "source_row is the 1-based index of each aggregated modeling node in "
    "first-appearance order within the accepted golden table (the 3-sigma "
    "filter preserves accepted source order and exact-XYZ aggregation emits "
    "groups in first-appearance order). The platform standardized.parquet "
    "written by the v0.5 import reuses the same 1-based source_row for the "
    "same node, matching the platform ingest source_row convention."
)


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


def export_invalid_records(invalid: list[InvalidDerivedSample], path: Path) -> Path:
    _frame([row.model_dump() for row in invalid]).to_csv(path, index=False, encoding="utf-8")
    return path


def export_aggregated_nodes(aggregated: AggregationResult, path: Path) -> Path:
    rows = [
        {
            "POINT_ID": node.point_id,
            "LINE_ID": node.line_id,
            "X_LOCAL_M": node.x_local_m,
            "Y_LOCAL_M": node.y_local_m,
            "Z_LOCAL_M": node.z_local_m,
            "VX_KM_S": node.vx_km_s,
            "SOURCE_SAMPLE_IDS": ";".join(node.source_sample_ids),
            "SAMPLE_COUNT": node.sample_count,
            "VX_MIN_KM_S": node.vx_min_km_s,
            "VX_MAX_KM_S": node.vx_max_km_s,
            "VX_SAMPLE_STD_KM_S": node.vx_sample_std_km_s,
        }
        for node in aggregated.nodes
    ]
    _frame(rows).to_csv(path, index=False, encoding="utf-8")
    return path


def export_modeling_provenance(aggregated: AggregationResult, path: Path) -> Path:
    """Per-node provenance with the stable 1-based source_row (SOURCE_ROW_RULE)."""
    rows = [
        {
            "source_row": index,
            "point_id": node.point_id,
            "line_id": node.line_id,
            "x_local_m": node.x_local_m,
            "y_local_m": node.y_local_m,
            "z_local_m": node.z_local_m,
            "vx_km_s": node.vx_km_s,
            "source_sample_ids": ";".join(node.source_sample_ids),
            "sample_count": node.sample_count,
            "vx_min_km_s": node.vx_min_km_s,
            "vx_max_km_s": node.vx_max_km_s,
            "vx_sample_std_km_s": node.vx_sample_std_km_s,
        }
        for index, node in enumerate(aggregated.nodes, start=1)
    ]
    frame = pd.DataFrame(rows, columns=list(PROVENANCE_COLUMNS))
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path


def export_derivation_report(
    result: "MicroseismicDerivationResult",
    artifacts: dict[str, dict],
    path: Path,
) -> Path:
    filtered = result.filtered
    aggregated = result.aggregated
    payload = {
        "rule_version": result.rule_version,
        "adapter_version": result.adapter_version,
        "aggregation_method": result.aggregation_method,
        "layer_counts": {
            "source_records": len(result.audit.samples),
            "finite_records": len(result.finite),
            "invalid_records": len(result.invalid),
            "rejected_3sigma": len(filtered.rejected),
            "accepted_modeling": len(filtered.accepted),
            "aggregated_nodes": len(aggregated.nodes),
        },
        "three_sigma": {
            "threshold": filtered.threshold,
            "ddof": filtered.ddof,
            "depth_mean": filtered.depth_mean,
            "depth_std": filtered.depth_std,
            "vx_mean": filtered.vx_mean,
            "vx_std": filtered.vx_std,
        },
        "aggregation": {
            "conflict_group_count": aggregated.conflict_group_count,
            "conflict_row_count": aggregated.conflict_row_count,
            "collapsed_row_count": aggregated.collapsed_row_count,
            "max_value_range": aggregated.max_value_range,
        },
        "golden": {
            "passed": result.golden.passed,
            "checks": [check.model_dump(mode="json") for check in result.golden.checks],
        },
        "coordinates": {
            "coord_type": COORD_TYPE_LOCAL,
            "depth_rule": DEPTH_RULE,
            "z_rule": Z_RULE,
            "vx_unit": DerivedVelocitySample.vx_unit,
            "absolute_crs": "unavailable; blocks cross-case fusion only, not independent local modeling",
        },
        "source_row_rule": SOURCE_ROW_RULE,
        "downstream_gates": result.downstream_gates,
        "validation_passed": result.validation.passed,
        "artifacts": artifacts,
    }
    return write_json(path, payload)


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
        "# Microseismic v0.5 Issue List",
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
        "# Microseismic v0.5 Data Quality Report",
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
            "W8.dat line 2 keeps raw token `1.#QNAN0` with `is_numeric_valid=false`. It stays in `velocity_samples.csv` (2,006 rows) but is excluded from the 2,005 finite valid records. It is not set to 0, not silently deleted, and not overwritten by interpolation. In the v0.5 derivation it is routed to the `invalid_records` layer with its raw trace.",
            "",
            "## Source conflicts preserved",
            "",
            "- Paper table `823/818/364=2,005` conflicts with parsed file facts `823/819/364=2,006` source records and `822/819/364=2,005` finite values; registered as `LINE_COUNT_CONFLICT` without moving records between lines.",
            "- W28 and the 350 m interval are conflict-only registrations; formal L3 is W24—W27 (800/320/335 m).",
            "- Cleaning statements conflict: 80/2,005 ≈ 3.99% vs the stated 3.59%, and linear interpolation vs nearest-5-point IDW; the v0.5 formal cleaning rule is one-pass global 3σ rejection without imputation, and both paper statements stay registered as conflicts.",
            "",
            "## Semantic boundaries",
            "",
            "- `WL/2(km)` is preserved verbatim in the audit layer; the confirmed v0.5 derivation uses it directly as depth (`depth_m = WL/2(km) × 1000`, down-positive) with `z_local_m = -depth_m` (up-positive).",
            "- Audit-layer `derived_depth_m` / `derived_z_m` stay empty with `depth_derivation_status=unconfirmed` because the immutable audit table predates the confirmed rule; the confirmed values live in the v0.5 derived tables (`accepted_modeling`, `rejected_3sigma`).",
            "- Local engineering X/Y are confirmed (`local_engineering_m` from versioned config); absolute CRS/EPSG remains unavailable, which blocks cross-case fusion but not independent local modeling.",
            "",
            "## Capability statement",
            "",
            "v0.5 can: inventory and hash sources, parse traceable records, build the three standard tables, derive confirmed local X/Y/Z and Vx, run the one-pass global 3σ cleaning filter, aggregate exact-XYZ conflicts into unique modeling nodes, and verify every derived layer against the pinned golden contract. It cannot: assign absolute geographic coordinates or an EPSG, fuse with other cases without common control points, or tune interpolation parameters (that runs on the platform after import).",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


DATA_DICTIONARY = """# Microseismic v0.5 Data Dictionary

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
| geometry_status | audit-layer flag; the confirmed 2D local derivation is exported in the v0.5 derived tables |
| crs_type | `none`; no CRS claimed |
| origin_status / direction_status | `confirmed_local` for the local engineering frame |
| geometry_source | interval workbook, order source and local coordinate source |
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
| coordinate_status | `confirmed_local` with x_local_m/y_local_m for formal points; `unconfirmed` for conflict-only points |
| z_reference_status | `unconfirmed` in the audit layer; the confirmed Z rule is applied in the v0.5 derived tables |
| source_confidence | confidence statement |
| notes | extra notes |

## velocity_samples.csv
One row per real source record (2,006 total on real data). Key columns:
| column | meaning |
|---|---|
| sample_id | `{point_id}:{source_line_number}`, unique and traceable |
| point_id / line_id | owning point and line |
| source_file_id / source_file_name / source_line_number | exact source trace |
| wl_half_km_raw_token / vx_raw_token | verbatim source tokens |
| wl_half_km_value / vx_value | standardized finite values, empty when invalid |
| source_unit | audit-layer unit statement (WL/2(km) verbatim); the confirmed Vx unit km/s is declared by the v0.5 derivation rule |
| is_numeric_valid / invalid_reason | finite-validity flag and reason |
| quality_flags | e.g. SOURCE_SPECIAL_NAN_TOKEN |
| included_in_raw / included_in_valid_numeric / included_in_clean_candidate | membership flags; clean candidate stays false in the immutable audit layer — the v0.5 `accepted_modeling` table is the formal clean candidate set |
| outlier_reason / imputed / imputation_method / cleaning_version | cleaning fields; the audit layer performs no cleaning, v0.5 `derive` runs the formal 3σ filter |
| derived_depth_m / derived_z_m / depth_derivation_status | unconfirmed in the audit layer; confirmed values are exported in the v0.5 derived tables |
| notes | per-row notes |

## v0.5 derivation artifacts
Written by `microseismic derive` (and appended by `run-audit` when the confirmed contract validates). Layered CSV file names embed the actual row counts of the run (`source_records_2006.csv`, `invalid_records_1.csv`, `rejected_3sigma_80.csv`, `accepted_modeling_1925.csv`, `aggregated_nodes_1911.csv` on real data).

| artifact | meaning |
|---|---|
| source_records_N.csv | every source record including the invalid one; same columns as velocity_samples.csv |
| invalid_records_N.csv | non-finite records routed out of derivation with raw tokens and reasons |
| rejected_3sigma_N.csv | canonical golden bytes of the 3σ rejected table (adds DEPTH_ZSCORE, VX_ZSCORE, FILTER_STATUS, FILTER_REASON) |
| accepted_modeling_N.csv | canonical golden bytes of the accepted candidate table |
| aggregated_nodes_N.csv | unique modeling nodes: POINT_ID, LINE_ID, X/Y/Z_LOCAL_M, VX_KM_S (exact-XYZ arithmetic mean), SOURCE_SAMPLE_IDS, SAMPLE_COUNT, VX_MIN/MAX/SAMPLE_STD_KM_S |
| modeling_provenance.parquet | per-node point/line/original sample ids and aggregation statistics keyed by the stable 1-based source_row |
| derivation_report.json | rule/adapter versions, layered counts, 3σ statistics, golden checks, aggregation statistics, coordinate/unit declarations, the source_row rule, downstream gate status and per-artifact hashes |
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
        "# Microseismic v0.5 Audit Summary",
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
            "## Confirmed facts and boundaries",
            "",
            "- Local geometry: confirmed local engineering coordinates (`local_engineering_m` from versioned config, golden-verified through the derivation layer); no fabricated X/Y.",
            "- Depth/Z/Vx: confirmed rule `depth_m = WL/2(km) × 1000` (down-positive), `z_local_m = -depth_m` (up-positive), Vx in km/s.",
            "- Cleaning: `microseismic derive` runs the formal one-pass global 3σ filter; rejected rows keep both z-scores and reasons and are never imputed, overwritten, or deleted.",
            "- Aggregation: exact-XYZ conflict groups collapse to arithmetic-mean modeling nodes with full per-node provenance.",
            "- Absolute CRS/EPSG: still unavailable; blocks cross-case fusion only, not independent local modeling.",
            "- W28 conflict-only; excluded from formal L3.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
