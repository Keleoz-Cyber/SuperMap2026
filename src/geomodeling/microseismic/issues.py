from __future__ import annotations

from .config import MicroseismicConfig
from .schemas import MicroseismicIssue, MicroseismicSeverity


def build_standard_issues(config: MicroseismicConfig, counts: dict) -> list[MicroseismicIssue]:
    expected = config.expected
    paper = expected.get("paper_counts", {})
    source_counts = counts.get("source_record_counts", {})
    cleaning = config.cleaning_conflicts
    excluded = config.excluded_points[0] if config.excluded_points else None
    return [
        MicroseismicIssue(
            severity=MicroseismicSeverity.INFO,
            code="SOURCE_NUL_TERMINATOR",
            message="each DAT file ends with a NUL byte pseudo-line that must not be counted as a sample",
            affected_scope="all 22 DAT source files",
            evidence=f"nul_terminator_files={counts.get('nul_terminator_count')}; parsed_rows_excluded={counts.get('nul_terminator_count')}",
            source_a="binary inspection of DAT files",
            source_b="generic pandas first-pass row count of 2,028",
            current_handling="detect trailing NUL bytes, register one pseudo-line per file, exclude from samples, and record in the manifest",
            blocks_geometry=False,
            blocks_cleaning=False,
            blocks_interpolation=False,
        ),
        MicroseismicIssue(
            severity=MicroseismicSeverity.WARNING,
            code="SOURCE_SPECIAL_NAN_TOKEN",
            message="W8.dat line 2 contains the legacy MSVC NaN token 1.#QNAN0 which is not a finite value",
            affected_scope="W8 / L1 valid numeric statistics",
            evidence="W8.dat line 2: '0.050000        1.#QNAN0'",
            source_a="W8.dat raw bytes",
            source_b="finite numeric contract",
            current_handling="keep the raw token and line trace, mark is_numeric_valid=false, exclude from the 2,005 finite records, never replace with 0 or silent interpolation",
            blocks_geometry=False,
            blocks_cleaning=False,
            blocks_interpolation=False,
        ),
        MicroseismicIssue(
            severity=MicroseismicSeverity.WARNING,
            code="LINE_COUNT_CONFLICT",
            message="paper per-line record counts differ from parsed file facts",
            affected_scope="L1/L2/L3 record statistics",
            evidence=(
                f"files source records L1/L2/L3={source_counts.get('L1')}/{source_counts.get('L2')}/{source_counts.get('L3')} "
                f"(total {counts.get('source_record_total')}); paper table={paper.get('L1')}/{paper.get('L2')}/{paper.get('L3')}={paper.get('total')}"
            ),
            source_a="22 parsed DAT files (2,006 source records; 2,005 finite values)",
            source_b="paper table 823/818/364=2,005",
            current_handling="register both statements as a source conflict; do not move records between lines to match the paper",
            blocks_geometry=False,
            blocks_cleaning=False,
            blocks_interpolation=False,
        ),
        MicroseismicIssue(
            severity=MicroseismicSeverity.WARNING,
            code="L3_W28_SOURCE_CONFLICT",
            message="W28 appears in paper figures and interval material but has no formal DAT and is not part of formal L3",
            affected_scope="L3 point set",
            evidence=excluded.reason if excluded else "W28 conflict registered in configuration",
            source_a="paper figures / 点间距.xlsx W28 row",
            source_b="formal DAT set W24—W27",
            current_handling="register W28 as conflict-only; exclude from formal L3, cumulative distance, cleaning set, and models",
            blocks_geometry=False,
            blocks_cleaning=False,
            blocks_interpolation=False,
        ),
        MicroseismicIssue(
            severity=MicroseismicSeverity.WARNING,
            code="L3_W28_INTERVAL_EXCLUDED",
            message="the 350 m interval associated with W28 is conflict information only",
            affected_scope="L3 cumulative distance",
            evidence=f"conflict_interval_m={excluded.conflict_interval_m if excluded else 350}",
            source_a="点间距.xlsx W28 row (350 m)",
            source_b="formal L3 intervals 800/320/335 m",
            current_handling="keep the 350 m value in the conflict record only; formal L3 cumulative distance ends at W27",
            blocks_geometry=False,
            blocks_cleaning=False,
            blocks_interpolation=False,
        ),
        MicroseismicIssue(
            severity=MicroseismicSeverity.INFO,
            code="LOCAL_GEOMETRY_CONFIRMED",
            message="survey point local X/Y and line origin/direction are confirmed for the local engineering frame",
            affected_scope="survey_points / survey_lines geometry",
            evidence="config local_coordinates pin every formal point; origin W16 and line-parallel axes confirmed by the 2026-07-20 source decision",
            source_a="config/microseismic.yaml local_coordinates",
            source_b="confirmed golden derived table microseismic_local_3d_v0.2b_confirmed_2026-07-20",
            current_handling="export x_local_m/y_local_m with coordinate_status=confirmed_local; conflict-only points keep no coordinates; no EPSG is claimed",
            blocks_geometry=False,
            blocks_cleaning=False,
            blocks_interpolation=False,
        ),
        MicroseismicIssue(
            severity=MicroseismicSeverity.INFO,
            code="DEPTH_Z_VX_RULE_CONFIRMED",
            message="WL/2(km) is used directly as depth, Z is the up-positive display axis, and Vx is km/s",
            affected_scope="v0.5 derived tables accepted_modeling / rejected_3sigma",
            evidence="depth_m=WL/2(km)*1000 (down-positive); z_local_m=-depth_m (up-positive); Vx unit km/s, all pinned by the golden derived table",
            source_a="confirmed golden derived table microseismic_local_3d_v0.2b_confirmed_2026-07-20",
            source_b="DAT header WL/2(km) preserved verbatim",
            current_handling="apply the confirmed rule in the v0.5 derived tables; keep the audit-layer header and unit strings verbatim and never rename or rescale them",
            blocks_geometry=False,
            blocks_cleaning=False,
            blocks_interpolation=False,
        ),
        MicroseismicIssue(
            severity=MicroseismicSeverity.WARNING,
            code="ABSOLUTE_COORDINATES_UNAVAILABLE",
            message="no trusted absolute geographic coordinates or EPSG exist for the survey points",
            affected_scope="cross-case spatial fusion only",
            evidence="no CRS/EPSG/absolute-origin evidence in available materials; local engineering coordinates are confirmed",
            source_a="config local_coordinates (local_engineering_m)",
            source_b="absolute coordinate requirement for cross-case fusion",
            current_handling="model the case independently in the confirmed local frame; keep absolute registration blocked until common control points and a trusted transform exist",
            blocks_geometry=False,
            blocks_cleaning=False,
            blocks_interpolation=False,
        ),
        MicroseismicIssue(
            severity=MicroseismicSeverity.WARNING,
            code="CLEANING_RATE_CONFLICT",
            message="paper cleaning rate statement conflicts with the computed ratio",
            affected_scope="cleaning rule definition",
            evidence=(
                f"paper claims {cleaning.get('outlier_count_claim')} outliers removed at {cleaning.get('rate_claim_percent')}%; "
                f"{cleaning.get('outlier_count_claim')}/2005 = {cleaning.get('computed_rate_percent')}%"
            ),
            source_a="paper text: 80 outliers, 3.59%",
            source_b="file facts: 80/2005 ≈ 3.99%",
            current_handling="register both values as a conflict; the v0.5 formal rule is one-pass global 3σ rejection without imputation and reports the actual count",
            blocks_geometry=False,
            blocks_cleaning=False,
            blocks_interpolation=False,
        ),
        MicroseismicIssue(
            severity=MicroseismicSeverity.WARNING,
            code="CLEANING_METHOD_CONFLICT",
            message="paper materials describe two different outlier handling methods",
            affected_scope="cleaning rule definition",
            evidence=f"method_a={cleaning.get('method_a')}; method_b={cleaning.get('method_b')}",
            source_a="paper text: linear interpolation",
            source_b="paper text: nearest 5 point IDW",
            current_handling="neither paper method is adopted; the v0.5 formal rule rejects by 3σ and preserves the rejected rows with z-scores and reasons, never deleting or backfilling source records",
            blocks_geometry=False,
            blocks_cleaning=False,
            blocks_interpolation=False,
        ),
    ]
