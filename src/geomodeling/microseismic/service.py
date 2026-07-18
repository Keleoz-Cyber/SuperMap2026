from __future__ import annotations

from pathlib import Path

from .config import MicroseismicConfig
from .contracts import issues_from_failed_checks, run_contract_checks
from .geometry import build_survey_geometry
from .inventory import build_inventory, discover_dat_files, snapshot_sha256
from .issues import build_standard_issues
from .reports import (
    export_audit_summary_markdown,
    export_data_dictionary,
    export_data_quality_markdown,
    export_issues_json,
    export_issues_markdown,
    export_manifest,
    export_survey_lines,
    export_survey_points,
    export_validation_json,
    export_velocity_samples,
)
from .schemas import MicroseismicAuditResult


def build_audit(config: MicroseismicConfig) -> MicroseismicAuditResult:
    found, _ = discover_dat_files(config)
    ordered_paths = [found[point.point_id] for _, point in config.formal_points() if point.point_id in found]
    sha_before = snapshot_sha256(ordered_paths)

    manifest, samples, problems = build_inventory(config)
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
