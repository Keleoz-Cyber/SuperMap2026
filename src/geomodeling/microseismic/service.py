from __future__ import annotations

from pathlib import Path

from ..io import sha256_file
from .aggregation import aggregate_exact_xyz
from .canonical import accepted_csv_bytes, rejected_csv_bytes, write_canonical_bytes
from .config import MicroseismicConfig
from .contracts import issues_from_failed_checks, run_contract_checks
from .derivation import derive_local_samples
from .filtering import filter_three_sigma
from .geometry import build_survey_geometry
from .golden import GoldenGateResult, verify_golden
from .inventory import build_inventory, discover_dat_files, snapshot_sha256
from .issues import build_standard_issues
from .reports import (
    export_aggregated_nodes,
    export_audit_summary_markdown,
    export_data_dictionary,
    export_data_quality_markdown,
    export_derivation_report,
    export_invalid_records,
    export_issues_json,
    export_issues_markdown,
    export_manifest,
    export_modeling_provenance,
    export_survey_lines,
    export_survey_points,
    export_validation_json,
    export_velocity_samples,
)
from .schemas import (
    AggregationResult,
    DerivedVelocitySample,
    InvalidDerivedSample,
    MicroseismicAuditResult,
    MicroseismicCheck,
    MicroseismicModel,
    MicroseismicSeverity,
    MicroseismicValidationReport,
    ThreeSigmaResult,
)


class MicroseismicDerivationResult(MicroseismicModel):
    """Composite v0.5 derivation outcome: audit + local XYZ + 3σ + golden + aggregation.

    validation merges the audit contract checks with the golden gate checks;
    validation.passed is True only when the audit contract passed AND the
    golden gate passed. downstream_gates stay blocked unless everything
    passed.
    """

    output_dir: str
    rule_version: str
    adapter_version: str
    aggregation_method: str
    audit: MicroseismicAuditResult
    finite: list[DerivedVelocitySample]
    invalid: list[InvalidDerivedSample]
    filtered: ThreeSigmaResult
    aggregated: AggregationResult
    golden: GoldenGateResult
    validation: MicroseismicValidationReport
    downstream_gates: dict[str, bool]


def build_audit(config: MicroseismicConfig, data_dir: str | Path | None = None) -> MicroseismicAuditResult:
    found, _ = discover_dat_files(config, data_dir=data_dir)
    ordered_paths = [found[point.point_id] for _, point in config.formal_points() if point.point_id in found]
    sha_before = snapshot_sha256(ordered_paths)

    manifest, samples, problems = build_inventory(config, data_dir=data_dir)
    lines, points = build_survey_geometry(config, manifest)

    sha_after = snapshot_sha256(ordered_paths)
    validation = run_contract_checks(config, manifest, samples, points, problems, sha_before, sha_after)

    counts = dict(validation.counts)
    issues = build_standard_issues(config, counts)
    issues.extend(issues_from_failed_checks(validation))

    return MicroseismicAuditResult(
        output_dir="",
        manifest=manifest,
        lines=lines,
        points=points,
        samples=samples,
        issues=issues,
        validation=validation,
        counts=counts,
    )


def _derive_result(config: MicroseismicConfig, audit: MicroseismicAuditResult) -> MicroseismicDerivationResult:
    """Compose the v0.5 derivation layers for one audit result (no file IO)."""
    finite, invalid = derive_local_samples(config, audit)
    filtered = filter_three_sigma(
        finite,
        threshold=config.derivation.sigma_threshold,
        ddof=config.derivation.sigma_ddof,
    )
    aggregated = aggregate_exact_xyz(filtered.accepted)
    golden = verify_golden(config, filtered, aggregated)

    golden_checks = [
        MicroseismicCheck(
            name=f"golden_{check.name}",
            passed=check.passed,
            severity=MicroseismicSeverity.BLOCKER,
            evidence=f"expected={check.expected} actual={check.actual}",
        )
        for check in golden.checks
    ]
    counts = dict(audit.validation.counts)
    counts.update(
        {
            "finite_total": len(finite),
            "invalid_total": len(invalid),
            "rejected_3sigma_total": len(filtered.rejected),
            "accepted_modeling_total": len(filtered.accepted),
            "aggregated_node_total": len(aggregated.nodes),
            "conflict_group_count": aggregated.conflict_group_count,
            "conflict_row_count": aggregated.conflict_row_count,
            "collapsed_row_count": aggregated.collapsed_row_count,
        }
    )
    validation = MicroseismicValidationReport(
        passed=audit.validation.passed and golden.passed,
        checks=[*audit.validation.checks, *golden_checks],
        counts=counts,
        sha256_protection=audit.validation.sha256_protection,
    )
    blocked = not validation.passed
    return MicroseismicDerivationResult(
        output_dir="",
        rule_version=config.derivation.rule_version,
        adapter_version=config.derivation.adapter_version,
        aggregation_method=config.derivation.aggregation_method,
        audit=audit,
        finite=finite,
        invalid=invalid,
        filtered=filtered,
        aggregated=aggregated,
        golden=golden,
        validation=validation,
        downstream_gates={
            "geometry_blocked": blocked,
            "cleaning_blocked": blocked,
            "interpolation_blocked": blocked,
        },
    )


def export_derivation(result: MicroseismicDerivationResult, output_dir: str | Path) -> dict[str, Path]:
    """Write every v0.5 derivation layer, including diagnostics for blocked runs.

    Layered CSV names embed the actual row counts of this run, so real data
    naturally lands on source_records_2006 / accepted_modeling_1925 /
    rejected_3sigma_80 / aggregated_nodes_1911 while portable fixtures get
    their own counts.
    """
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    samples = result.audit.samples
    rejected = result.filtered.rejected
    accepted = result.filtered.accepted
    nodes = result.aggregated.nodes
    outputs = {
        "source_records": export_velocity_samples(samples, base / f"source_records_{len(samples)}.csv"),
        "invalid_records": export_invalid_records(result.invalid, base / f"invalid_records_{len(result.invalid)}.csv"),
        "rejected_3sigma": write_canonical_bytes(base / f"rejected_3sigma_{len(rejected)}.csv", rejected_csv_bytes(rejected)),
        "accepted_modeling": write_canonical_bytes(base / f"accepted_modeling_{len(accepted)}.csv", accepted_csv_bytes(accepted)),
        "aggregated_nodes": export_aggregated_nodes(result.aggregated, base / f"aggregated_nodes_{len(nodes)}.csv"),
        "modeling_provenance": export_modeling_provenance(result.aggregated, base / "modeling_provenance.parquet"),
    }
    row_counts = {
        "source_records": len(samples),
        "invalid_records": len(result.invalid),
        "rejected_3sigma": len(rejected),
        "accepted_modeling": len(accepted),
        "aggregated_nodes": len(nodes),
        "modeling_provenance": len(nodes),
    }
    artifacts = {
        key: {"file": path.name, "rows": row_counts[key], "sha256": sha256_file(path)}
        for key, path in outputs.items()
    }
    outputs["derivation_report"] = export_derivation_report(result, artifacts, base / "derivation_report.json")
    return outputs


def derive_from_directory(
    config: MicroseismicConfig,
    source_dir: str | Path,
    output_dir: str | Path,
) -> tuple[MicroseismicDerivationResult, dict[str, Path]]:
    """Run the full v0.5 workflow for one DAT directory and export all layers.

    Diagnostics are exported even when the audit contract or the golden gate
    fails; the result is then marked blocked (downstream_gates all True) and
    callers decide the exit code.
    """
    audit = build_audit(config, data_dir=source_dir)
    result = _derive_result(config, audit)
    result.output_dir = str(Path(output_dir).resolve())
    outputs = export_derivation(result, output_dir)
    return result, outputs


def export_all(result: MicroseismicAuditResult, output_dir: str | Path) -> dict[str, Path]:
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    outputs = {
        "source_manifest": export_manifest(result.manifest, base / "source_manifest.json"),
        "survey_lines": export_survey_lines(result.lines, base / "survey_lines.csv"),
        "survey_points": export_survey_points(result.points, base / "survey_points.csv"),
        "velocity_samples": export_velocity_samples(result.samples, base / "velocity_samples.csv"),
        "validation": export_validation_json(result.validation, base / "microseismic_validation.json"),
        "issues_json": export_issues_json(result.issues, base / "microseismic_issue_list.json"),
        "issues_markdown": export_issues_markdown(result.issues, base / "microseismic_issue_list.md"),
        "data_quality": export_data_quality_markdown(result, base / "microseismic_data_quality.md"),
        "data_dictionary": export_data_dictionary(base / "microseismic_data_dictionary.md"),
        "audit_summary": export_audit_summary_markdown(result, base / "microseismic_audit_summary.md"),
    }
    return outputs


def run_full_audit(config: MicroseismicConfig, output_dir: str | Path) -> tuple[MicroseismicAuditResult, dict[str, Path]]:
    result = build_audit(config)
    result.output_dir = str(Path(output_dir).resolve())
    outputs = export_all(result, output_dir)
    return result, outputs
