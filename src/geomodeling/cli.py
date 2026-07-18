from __future__ import annotations

from pathlib import Path

import typer

from .config import AppConfig, load_config
from .io import sha256_file, write_json
from .metrics import (
    common_valid_mask,
    compare_metric_summaries,
    compute_common_metric_summaries,
    import_prediction_csv,
    read_validation_truth,
    summarize_group_metrics,
)
from .registry import DatasetRegistry
from .reports import (
    export_inventory_json,
    export_inventory_markdown,
    export_metrics_json,
    export_metrics_markdown,
    export_model_metadata,
    model_metadata_from_config,
)
from .schemas import DatasetType, QualityStatus
from .supermap import SuperMapRegistry, formal_results, registrations_from_config, result_inventory, select_supermap_result_for_model
from .validation import registration_from_report, validate_train_validation_split, validate_xyzrho_contract

app = typer.Typer(add_completion=False)


def _dirs(config: AppConfig, output_dir: Path | None) -> dict[str, Path]:
    if output_dir is None:
        return {
            "registry": config.output_dir("registry_dir"),
            "reports": config.output_dir("reports_dir"),
            "metrics": config.output_dir("metrics_dir"),
        }
    base = output_dir.resolve()
    base.mkdir(parents=True, exist_ok=True)
    dirs = {"registry": base / "registry", "reports": base / "reports", "metrics": base / "metrics"}
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def _register_validated_dataset(config: AppConfig, registry: DatasetRegistry, key: str, dataset_id: str, dataset_type: DatasetType):
    path = config.resolve_path(config.paths[key])
    expected = config.expected.get(f"{key}_rows")
    report = validate_xyzrho_contract(path, dataset_id=dataset_id, dataset_type=dataset_type, expected_row_count=expected)
    registration = registration_from_report(report, path, created_by="geomodeling-cli", source_reference=str(path))
    registry.save_validation_report(report)
    result = registry.register(registration)
    return report, registration, result


@app.command("validate-data")
def validate_data(
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
) -> None:
    app_config = load_config(config)
    dirs = _dirs(app_config, output_dir)
    registry = DatasetRegistry(dirs["registry"] / "datasets")
    reports = []
    for key, dataset_id, dataset_type in [
        ("standardized", "rho_standardized_v1", DatasetType.STANDARDIZED_OBSERVATION),
        ("training", "rho_training_v1", DatasetType.TRAIN_VALIDATION_SPLIT),
        ("validation", "rho_validation_v1", DatasetType.TRAIN_VALIDATION_SPLIT),
    ]:
        report, registration, result = _register_validated_dataset(app_config, registry, key, dataset_id, dataset_type)
        reports.append(report)
        typer.echo(f"{dataset_id}: {report.quality_status} rows={report.row_count} duplicate_sha256={result['duplicate_sha256']}")
    split = validate_train_validation_split(app_config.resolve_path(app_config.paths["training"]), app_config.resolve_path(app_config.paths["validation"]))
    write_json(dirs["reports"] / "train_validation_split.json", split)
    typer.echo(f"spatial_column_overlap={split['spatial_column_overlap']}")
    failed = any(report.quality_status == QualityStatus.FAILED for report in reports) or not split["passed"]
    if failed:
        raise typer.Exit(code=1)


def _import_predictions(app_config: AppConfig, metrics_dir: Path):
    validation_path = app_config.resolve_path(app_config.paths["validation"])
    validation = read_validation_truth(validation_path)
    predictions = {}
    qualities = {}
    prediction_files = app_config.prediction_files()
    for model in app_config.models:
        name = model["display_name"]
        path = prediction_files[name]
        frame, quality = import_prediction_csv(path, validation, model["model_id"], nodata_value=app_config.nodata_value)
        predictions[name] = frame
        qualities[name] = quality
        frame.to_csv(metrics_dir / f"prediction_{model['model_id']}.csv", index=False, encoding="utf-8")
    write_json(metrics_dir / "prediction_import_quality.json", qualities)
    return validation, predictions, qualities


@app.command("import-predictions")
def import_predictions(
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
) -> None:
    app_config = load_config(config)
    dirs = _dirs(app_config, output_dir)
    _, _, qualities = _import_predictions(app_config, dirs["metrics"])
    for name, quality in qualities.items():
        typer.echo(f"{name}: rows={quality['row_count']} valid={quality['valid_count']} nodata={quality['nodata_count']} xy_mismatch={quality['xy_mismatch_count']}")
    if any(quality["xy_mismatch_count"] != 0 for quality in qualities.values()):
        raise typer.Exit(code=1)


@app.command("compute-metrics")
def compute_metrics(
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
) -> None:
    app_config = load_config(config)
    dirs = _dirs(app_config, output_dir)
    _, predictions, _ = _import_predictions(app_config, dirs["metrics"])
    summaries = compute_common_metric_summaries(predictions)
    comparison = compare_metric_summaries(summaries, app_config.resolve_path(app_config.paths["metrics_baseline"]), app_config.metric_tolerance)
    export_metrics_json(summaries, comparison, dirs["metrics"] / "metric_summaries.json")
    export_metrics_markdown(summaries, comparison, dirs["reports"] / "metric_summaries.md")
    mask = common_valid_mask(predictions)
    for name, frame in predictions.items():
        summarize_group_metrics(frame, "depth_band", mask).to_csv(dirs["metrics"] / f"depth_summary_{frame['model_id'].iloc[0]}.csv", index=False, encoding="utf-8")
        summarize_group_metrics(frame, "column_id", mask).to_csv(dirs["metrics"] / f"column_summary_{frame['model_id'].iloc[0]}.csv", index=False, encoding="utf-8")
    for name, summary in summaries.items():
        typer.echo(f"{name}: n_valid={summary.n_valid} n_nodata={summary.n_nodata} MAE={summary.mae:.6f} RMSE={summary.rmse:.6f}")
    typer.echo(f"baseline_passed={comparison['passed']}")
    if not comparison["passed"]:
        raise typer.Exit(code=1)


@app.command("register-supermap-results")
def register_supermap_results(
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
    udbx_path: str | None = typer.Option(None, "--udbx-path"),
) -> None:
    app_config = load_config(config)
    dirs = _dirs(app_config, output_dir)
    registry = SuperMapRegistry(dirs["registry"] / "supermap")
    records = registrations_from_config(app_config, udbx_path=udbx_path)
    for record in records:
        registry.register(record)
    items = result_inventory(records)
    export_inventory_json(items, dirs["reports"] / "supermap_result_inventory.json")
    export_inventory_markdown(items, dirs["reports"] / "supermap_result_inventory.md")
    typer.echo(f"registered={len(records)} formal={len(formal_results(records))}")


@app.command("export-reports")
def export_reports(
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
    udbx_path: str | None = typer.Option(None, "--udbx-path"),
) -> None:
    app_config = load_config(config)
    dirs = _dirs(app_config, output_dir)
    _, predictions, _ = _import_predictions(app_config, dirs["metrics"])
    summaries = compute_common_metric_summaries(predictions)
    comparison = compare_metric_summaries(summaries, app_config.resolve_path(app_config.paths["metrics_baseline"]), app_config.metric_tolerance)
    export_metrics_json(summaries, comparison, dirs["reports"] / "metric_summaries.json")
    export_metrics_markdown(summaries, comparison, dirs["reports"] / "metric_summaries.md")
    records = registrations_from_config(app_config, udbx_path=udbx_path)
    items = result_inventory(records)
    export_inventory_json(items, dirs["reports"] / "supermap_result_inventory.json")
    export_inventory_markdown(items, dirs["reports"] / "supermap_result_inventory.md")
    training_path = app_config.resolve_path(app_config.paths["training"])
    input_sha256 = sha256_file(training_path)
    model_dir = dirs["reports"] / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    for model in app_config.models:
        metadata = model_metadata_from_config(
            model,
            "rho_training_v1",
            input_sha256,
            select_supermap_result_for_model(records, model["model_id"]),
        )
        export_model_metadata(metadata, model_dir / f"{model['model_id']}.json")
    typer.echo(f"reports_dir={dirs['reports']}")
    if not comparison["passed"]:
        raise typer.Exit(code=1)


@app.command("run-all")
def run_all(
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
    udbx_path: str | None = typer.Option(None, "--udbx-path"),
) -> None:
    validate_data(config=config, output_dir=output_dir)
    import_predictions(config=config, output_dir=output_dir)
    compute_metrics(config=config, output_dir=output_dir)
    register_supermap_results(config=config, output_dir=output_dir, udbx_path=udbx_path)
    export_reports(config=config, output_dir=output_dir, udbx_path=udbx_path)


if __name__ == "__main__":
    app()
