from __future__ import annotations

from pathlib import Path

import typer

from ..audit import AuditLogger
from ..io import write_json
from .config import load_microseismic_config
from .reports import export_manifest, export_validation_json, export_velocity_samples
from .service import _derive_result, build_audit, derive_from_directory, export_all, export_derivation

microseismic_app = typer.Typer(add_completion=False, help="Microseismic v0.2a data audit and v0.5 derivation commands")


def _output_dir(config_path: Path, output_dir: Path | None) -> Path:
    config = load_microseismic_config(config_path)
    if output_dir is not None:
        base = output_dir.resolve()
    else:
        base = config.default_output_dir()
    base.mkdir(parents=True, exist_ok=True)
    return base


def _audit_log(base: Path, command: str, status: str, inputs: list, outputs: list, error: str | None = None) -> None:
    log_dir = base / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    AuditLogger(log_dir).log(command=command, status=status, inputs=inputs, outputs=outputs, error=error)


def _echo_counts(result) -> None:
    counts = result.counts
    typer.echo(
        f"dat_files={counts.get('dat_file_count')} nul_terminators={counts.get('nul_terminator_count')} "
        f"source_records={counts.get('source_record_total')} valid_numeric={counts.get('valid_numeric_total')} invalid_numeric={counts.get('invalid_numeric_total')}"
    )
    typer.echo(f"source_per_line={counts.get('source_record_counts')} valid_per_line={counts.get('valid_numeric_counts')}")


def _finish(command: str, result, base: Path, outputs: list) -> None:
    failed = [check for check in result.validation.checks if not check.passed]
    status = "failed" if not result.validation.passed else "succeeded"
    _audit_log(
        base,
        command,
        status,
        inputs=[entry.relative_path for entry in result.manifest],
        outputs=outputs,
        error=f"{len(failed)} contract checks failed" if failed else None,
    )
    typer.echo(f"validation_passed={result.validation.passed} failed_checks={len(failed)}")
    if not result.validation.passed:
        for check in failed:
            typer.echo(f"FAILED {check.name}: {check.evidence}")
        raise typer.Exit(code=1)


@microseismic_app.command("inventory")
def inventory(
    config: Path = typer.Option(Path("config/microseismic.yaml"), "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
) -> None:
    app_config = load_microseismic_config(config)
    base = _output_dir(config, output_dir)
    result = build_audit(app_config)
    path = export_manifest(result.manifest, base / "source_manifest.json")
    for entry in result.manifest:
        typer.echo(
            f"{entry.file_name}: point={entry.point_id} line={entry.line_id} records={entry.source_record_count} valid={entry.valid_numeric_count} nul={entry.nul_terminator} sha256={entry.sha256[:12]}..."
        )
    _echo_counts(result)
    _finish("microseismic inventory", result, base, [path])


@microseismic_app.command("parse")
def parse(
    config: Path = typer.Option(Path("config/microseismic.yaml"), "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
) -> None:
    app_config = load_microseismic_config(config)
    base = _output_dir(config, output_dir)
    result = build_audit(app_config)
    manifest_path = export_manifest(result.manifest, base / "source_manifest.json")
    samples_path = export_velocity_samples(result.samples, base / "velocity_samples.csv")
    typer.echo(f"velocity_samples_rows={len(result.samples)}")
    _echo_counts(result)
    _finish("microseismic parse", result, base, [manifest_path, samples_path])


@microseismic_app.command("validate")
def validate(
    config: Path = typer.Option(Path("config/microseismic.yaml"), "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
) -> None:
    app_config = load_microseismic_config(config)
    base = _output_dir(config, output_dir)
    result = build_audit(app_config)
    path = export_validation_json(result.validation, base / "microseismic_validation.json")
    for check in result.validation.checks:
        typer.echo(f"{'PASS' if check.passed else 'FAIL'} {check.name}: {check.evidence}")
    _echo_counts(result)
    _finish("microseismic validate", result, base, [path])


@microseismic_app.command("export-reports")
def export_reports(
    config: Path = typer.Option(Path("config/microseismic.yaml"), "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
) -> None:
    app_config = load_microseismic_config(config)
    base = _output_dir(config, output_dir)
    result = build_audit(app_config)
    result.output_dir = str(base)
    outputs = list(export_all(result, base).values())
    _echo_counts(result)
    typer.echo(f"reports_dir={base}")
    _finish("microseismic export-reports", result, base, outputs)


@microseismic_app.command("derive")
def derive(
    config: Path = typer.Option(Path("config/microseismic.yaml"), "--config", "-c"),
    source_dir: Path | None = typer.Option(None, "--source-dir", help="Directory holding the DAT files; defaults to the config data_dir."),
    output_dir: Path = typer.Option(..., "--output-dir", "-o", help="Output directory for the v0.5 derivation layers."),
) -> None:
    """Run the v0.5 derivation workflow: audit, local XYZ, 3σ filter, golden gate, aggregation."""
    app_config = load_microseismic_config(config)
    base = output_dir.resolve()
    base.mkdir(parents=True, exist_ok=True)
    source = source_dir.resolve() if source_dir is not None else app_config.data_dir
    result, output_map = derive_from_directory(app_config, source, base)
    typer.echo(
        f"source_records={len(result.audit.samples)} finite={len(result.finite)} invalid={len(result.invalid)} "
        f"rejected_3sigma={len(result.filtered.rejected)} accepted_modeling={len(result.filtered.accepted)} "
        f"modeling_nodes={len(result.aggregated.nodes)}"
    )
    typer.echo(f"golden_passed={result.golden.passed}")
    typer.echo(f"downstream_gates={result.downstream_gates}")
    typer.echo(f"output_dir={base}")
    failed = [check for check in result.validation.checks if not check.passed]
    _audit_log(
        base,
        "microseismic derive",
        "succeeded" if result.validation.passed else "failed",
        inputs=[entry.relative_path for entry in result.audit.manifest],
        outputs=list(output_map.values()),
        error=f"{len(failed)} checks failed" if failed else None,
    )
    typer.echo(f"validation_passed={result.validation.passed} failed_checks={len(failed)}")
    if not result.validation.passed:
        for check in failed:
            typer.echo(f"FAILED {check.name}: {check.evidence}")
        raise typer.Exit(code=1)


@microseismic_app.command("run-audit")
def run_audit(
    config: Path = typer.Option(Path("config/microseismic.yaml"), "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
) -> None:
    app_config = load_microseismic_config(config)
    base = _output_dir(config, output_dir)
    _audit_log(base, "microseismic run-audit", "started", [], [base])
    result = build_audit(app_config)
    result.output_dir = str(base)
    output_map = export_all(result, base)
    derivation = None
    # v0.5: when the confirmed derivation contract is present and the source
    # contract validates, append the derivation layers to the audit outputs.
    if result.validation.passed and getattr(app_config, "derivation", None) is not None:
        derivation = _derive_result(app_config, result)
        derivation.output_dir = str(base)
        output_map.update(export_derivation(derivation, base))
    write_json(base / "microseismic_run_outputs.json", {key: str(value) for key, value in output_map.items()})
    outputs = list(output_map.values())
    _echo_counts(result)
    if derivation is not None:
        typer.echo(
            f"derived: finite={len(derivation.finite)} invalid={len(derivation.invalid)} "
            f"rejected_3sigma={len(derivation.filtered.rejected)} accepted_modeling={len(derivation.filtered.accepted)} "
            f"modeling_nodes={len(derivation.aggregated.nodes)} golden_passed={derivation.golden.passed}"
        )
    typer.echo(f"output_dir={base}")
    _finish("microseismic run-audit", result, base, outputs)
    if derivation is not None and not derivation.golden.passed:
        for check in derivation.golden.checks:
            if not check.passed:
                typer.echo(f"FAILED golden_{check.name}: expected={check.expected} actual={check.actual}")
        raise typer.Exit(code=1)
