from __future__ import annotations

import json
from pathlib import Path

import typer
from pydantic import ValidationError

from .audit import AuditLogger
from .config import AppConfig, load_config
from .io import sha256_file, write_json
from .issues import current_issues
from .metrics import (
    common_valid_mask,
    compare_metric_summaries,
    compute_common_metric_summaries,
    import_prediction_csv,
    read_validation_truth,
    summarize_group_metrics,
)
from .microseismic.cli import microseismic_app
from .model_tasks import ModelTaskRegistry, build_model_task, ensure_config_model_tasks, select_models
from .professional_cli import professional_app
from .registry import DatasetRegistry
from .render_cli import render_app
from .reports import (
    export_acceptance_summary,
    export_dataset_markdown,
    export_inventory_json,
    export_inventory_markdown,
    export_issues_json,
    export_issues_markdown,
    export_metrics_json,
    export_metrics_markdown,
    export_model_list_markdown,
    export_model_markdown,
    export_model_metadata,
    export_view_configurations_json,
    export_view_configurations_markdown,
    model_metadata_from_config,
)
from .schemas import DatasetType, QualityStatus
from .supermap import (
    SuperMapRegistry,
    formal_results,
    result_inventory,
    select_supermap_result_for_model,
    verification_report,
    verify_supermap_results,
)
from .validation import registration_from_report, validate_train_validation_split, validate_xyzrho_contract
from .views import view_configurations_from_config

app = typer.Typer(add_completion=False)
app.add_typer(microseismic_app, name="microseismic")
app.add_typer(professional_app, name="professional")
app.add_typer(render_app, name="render-grid")


def _dirs(config: AppConfig, output_dir: Path | None) -> dict[str, Path]:
    if output_dir is None:
        return {
            "registry": config.output_dir("registry_dir"),
            "reports": config.output_dir("reports_dir"),
            "metrics": config.output_dir("metrics_dir"),
            "logs": config.output_dir("logs_dir"),
        }
    base = output_dir.resolve()
    base.mkdir(parents=True, exist_ok=True)
    dirs = {"registry": base / "registry", "reports": base / "reports", "metrics": base / "metrics", "logs": base / "logs"}
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def _audit(
    config: AppConfig,
    dirs: dict[str, Path],
    command: str,
    status: str,
    inputs: list[str | Path] | None = None,
    parameters: dict | None = None,
    outputs: list[str | Path] | None = None,
    error: str | None = None,
) -> None:
    AuditLogger(dirs["logs"]).log(
        command=command,
        status=status,
        inputs=inputs,
        parameters=parameters,
        supermap_version=config.supermap.get("version"),
        outputs=outputs,
        error=error,
    )


def _register_validated_dataset(config: AppConfig, registry: DatasetRegistry, key: str, dataset_id: str, dataset_type: DatasetType):
    path = config.resolve_path(config.paths[key])
    expected = config.expected.get(f"{key}_rows")
    report = validate_xyzrho_contract(path, dataset_id=dataset_id, dataset_type=dataset_type, expected_row_count=expected)
    registration = registration_from_report(report, path, created_by="geomodeling-cli", source_reference=str(path))
    registry.save_validation_report(report)
    result = registry.register(registration)
    return report, registration, result


def _training_sha256(config: AppConfig) -> str:
    return sha256_file(config.resolve_path(config.paths["training"]))


@app.command("validate-data")
def validate_data(
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
) -> None:
    app_config = load_config(config)
    dirs = _dirs(app_config, output_dir)
    inputs = [app_config.resolve_path(app_config.paths[key]) for key in ["standardized", "training", "validation"]]
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
    _audit(
        app_config,
        dirs,
        "validate-data",
        "failed" if failed else "succeeded",
        inputs=inputs,
        parameters={"expected": app_config.expected},
        outputs=[dirs["registry"] / "datasets", dirs["reports"] / "train_validation_split.json"],
        error="validation failed" if failed else None,
    )
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
    failed = any(quality["xy_mismatch_count"] != 0 for quality in qualities.values())
    _audit(
        app_config,
        dirs,
        "import-predictions",
        "failed" if failed else "succeeded",
        inputs=[app_config.resolve_path(app_config.paths["validation"]), *app_config.prediction_files().values()],
        parameters={"nodata_value": app_config.nodata_value},
        outputs=[dirs["metrics"]],
        error="xy mismatch detected" if failed else None,
    )
    if failed:
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
    _audit(
        app_config,
        dirs,
        "compute-metrics",
        "failed" if not comparison["passed"] else "succeeded",
        inputs=[app_config.resolve_path(app_config.paths["validation"]), *app_config.prediction_files().values(), app_config.resolve_path(app_config.paths["metrics_baseline"])],
        parameters={"metric_tolerance": app_config.metric_tolerance},
        outputs=[dirs["metrics"] / "metric_summaries.json", dirs["reports"] / "metric_summaries.md"],
        error="baseline comparison failed" if not comparison["passed"] else None,
    )
    if not comparison["passed"]:
        raise typer.Exit(code=1)


def _write_supermap_outputs(app_config: AppConfig, dirs: dict[str, Path], records, udbx_path: str | None):
    registry = SuperMapRegistry(dirs["registry"] / "supermap")
    for record in records:
        registry.register(record)
    items = result_inventory(records)
    export_inventory_json(items, dirs["reports"] / "supermap_result_inventory.json")
    export_inventory_markdown(items, dirs["reports"] / "supermap_result_inventory.md")
    report = verification_report(app_config, records, udbx_path=udbx_path)
    write_json(dirs["reports"] / "supermap_verification.json", report)
    return items, report


@app.command("register-supermap-results")
def register_supermap_results(
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
    udbx_path: str | None = typer.Option(None, "--udbx-path"),
) -> None:
    app_config = load_config(config)
    dirs = _dirs(app_config, output_dir)
    records = verify_supermap_results(app_config, udbx_path=udbx_path)
    items, report = _write_supermap_outputs(app_config, dirs, records, udbx_path)
    for record in records:
        typer.echo(
            f"{record.dataset}: evidence_level={record.evidence_level} file_verified={record.file_verified} dataset_verified={record.dataset_verified} status={record.status}"
        )
    typer.echo(
        f"registered_config_results={len(records)} formal_config_results={len(formal_results(records))} file_verified_results={sum(record.file_verified for record in records)} dataset_verified_results={sum(record.dataset_verified for record in records)}"
    )
    _audit(
        app_config,
        dirs,
        "register-supermap-results",
        "succeeded",
        inputs=[report.udbx_path] if report.udbx_path else [],
        parameters={"dataset_api": app_config.supermap.get("dataset_api", "none")},
        outputs=[dirs["registry"] / "supermap", dirs["reports"] / "supermap_result_inventory.json", dirs["reports"] / "supermap_verification.json"],
    )


@app.command("verify-supermap")
def verify_supermap(
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
    udbx_path: str | None = typer.Option(None, "--udbx-path"),
    compute_hash: bool = typer.Option(True, "--compute-hash/--no-compute-hash"),
) -> None:
    app_config = load_config(config)
    dirs = _dirs(app_config, output_dir)
    records = verify_supermap_results(app_config, udbx_path=udbx_path, compute_hash=compute_hash)
    items, report = _write_supermap_outputs(app_config, dirs, records, udbx_path)
    for record in records:
        typer.echo(
            f"{record.dataset}: evidence_level={record.evidence_level} file_verified={record.file_verified} dataset_verified={record.dataset_verified} object_count={record.object_count} status={record.status}"
        )
    typer.echo(f"udbx_exists={report.file_exists} udbx_file_verified={report.file_verified} dataset_verified={report.dataset_verified}")
    _audit(
        app_config,
        dirs,
        "verify-supermap",
        "succeeded",
        inputs=[report.udbx_path] if report.udbx_path else [],
        parameters={"compute_hash": compute_hash, "dataset_api": app_config.supermap.get("dataset_api", "none")},
        outputs=[dirs["reports"] / "supermap_verification.json", dirs["reports"] / "supermap_result_inventory.json"],
    )


@app.command("create-model")
def create_model(
    model_id: str = typer.Option(..., "--model-id"),
    display_name: str = typer.Option(..., "--display-name"),
    method: str = typer.Option(..., "--method"),
    input_dataset_id: str = typer.Option("rho_training_v1", "--input-dataset-id"),
    input_sha256: str | None = typer.Option(None, "--input-sha256"),
    parameters_json: str = typer.Option("{}", "--parameters-json"),
    role: str = typer.Option("candidate", "--role"),
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
) -> None:
    app_config = load_config(config)
    dirs = _dirs(app_config, output_dir)
    parameters = json.loads(parameters_json)
    snapshot = {
        "model_id": model_id,
        "display_name": display_name,
        "method": method,
        "input_dataset_id": input_dataset_id,
        "parameters": parameters,
        "role": role,
    }
    registry = ModelTaskRegistry(dirs["registry"] / "models")
    try:
        task = build_model_task(
            model_id=model_id,
            display_name=display_name,
            method=method,
            input_dataset_id=input_dataset_id,
            input_sha256=input_sha256 or _training_sha256(app_config),
            parameters=parameters,
            config_snapshot=snapshot,
            role=role,
        )
        registry.create(task)
    except (ValueError, ValidationError) as exc:
        _audit(app_config, dirs, "create-model", "failed", inputs=[app_config.resolve_path(app_config.paths["training"])], parameters=snapshot, error=str(exc))
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    typer.echo(f"created_model={task.model_id} status={task.status} fingerprint={task.fingerprint}")
    _audit(app_config, dirs, "create-model", "succeeded", inputs=[app_config.resolve_path(app_config.paths["training"])], parameters=snapshot, outputs=[registry.path_for(task.model_id)])


@app.command("list-models")
def list_models(
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
) -> None:
    app_config = load_config(config)
    dirs = _dirs(app_config, output_dir)
    registry = ModelTaskRegistry(dirs["registry"] / "models")
    tasks = registry.list()
    if not tasks:
        typer.echo("no_model_tasks")
    for task in tasks:
        typer.echo(f"{task.model_id}: method={task.method} role={task.role} status={task.status} input={task.input_dataset_id}")
    _audit(app_config, dirs, "list-models", "succeeded", parameters={"task_count": len(tasks)}, outputs=[dirs["registry"] / "models"])


@app.command("select-models")
def select_models_command(
    default_model_id: str | None = typer.Option(None, "--default-model-id"),
    comparison_model_id: str | None = typer.Option(None, "--comparison-model-id"),
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
    udbx_path: str | None = typer.Option(None, "--udbx-path"),
) -> None:
    app_config = load_config(config)
    dirs = _dirs(app_config, output_dir)
    records = verify_supermap_results(app_config, udbx_path=udbx_path)
    registry = ModelTaskRegistry(dirs["registry"] / "models")
    tasks = ensure_config_model_tasks(app_config, registry, "rho_training_v1", _training_sha256(app_config), records)
    _, predictions, _ = _import_predictions(app_config, dirs["metrics"])
    summaries = compute_common_metric_summaries(predictions)
    try:
        selection = select_models(
            tasks,
            summaries,
            default_model_id=default_model_id,
            comparison_model_id=comparison_model_id,
        )
    except ValueError as exc:
        _audit(
            app_config,
            dirs,
            "select-models",
            "failed",
            parameters={"default_model_id": default_model_id, "comparison_model_id": comparison_model_id},
            error=str(exc),
        )
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    registry.save_selection(selection)
    typer.echo(f"default_model={selection.default_model_id} comparison_model={selection.comparison_model_id}")
    typer.echo(selection.rationale)
    _audit(
        app_config,
        dirs,
        "select-models",
        "succeeded",
        inputs=[app_config.resolve_path(app_config.paths["training"]), app_config.resolve_path(app_config.paths["validation"]), *app_config.prediction_files().values()],
        parameters={"default_model_id": selection.default_model_id, "comparison_model_id": selection.comparison_model_id},
        outputs=[dirs["registry"] / "models" / "_selection.json"],
    )


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
    records = verify_supermap_results(app_config, udbx_path=udbx_path)
    items, _ = _write_supermap_outputs(app_config, dirs, records, udbx_path)
    views = view_configurations_from_config(app_config, udbx_path=udbx_path)
    export_view_configurations_json(views, dirs["reports"] / "view_configurations.json")
    export_view_configurations_markdown(views, dirs["reports"] / "view_configurations.md")
    issues = current_issues(app_config)
    export_issues_json(issues, dirs["reports"] / "issue_list.json")
    export_issues_markdown(issues, dirs["reports"] / "issue_list.md")
    input_sha256 = _training_sha256(app_config)
    model_registry = ModelTaskRegistry(dirs["registry"] / "models")
    tasks = ensure_config_model_tasks(app_config, model_registry, "rho_training_v1", input_sha256, records)
    selection = select_models(tasks, summaries)
    model_registry.save_selection(selection)
    dataset_registrations = DatasetRegistry(dirs["registry"] / "datasets").list()
    export_dataset_markdown(dataset_registrations, dirs["reports"] / "dataset_inventory.md")
    export_model_list_markdown(tasks, selection, dirs["reports"] / "model_inventory.md")
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
        export_model_markdown(metadata, model_dir / f"{model['model_id']}.md")
    export_acceptance_summary(
        dirs["reports"] / "acceptance_summary.md",
        dataset_registrations,
        tasks,
        selection,
        summaries,
        comparison,
        records,
        views,
        issues,
    )
    typer.echo(f"reports_dir={dirs['reports']}")
    _audit(
        app_config,
        dirs,
        "export-reports",
        "failed" if not comparison["passed"] else "succeeded",
        inputs=[app_config.resolve_path(app_config.paths["training"]), app_config.resolve_path(app_config.paths["validation"]), *app_config.prediction_files().values(), app_config.resolve_path(app_config.paths["metrics_baseline"])],
        parameters={"metric_tolerance": app_config.metric_tolerance},
        outputs=[dirs["reports"]],
        error="baseline comparison failed" if not comparison["passed"] else None,
    )
    if not comparison["passed"]:
        raise typer.Exit(code=1)


@app.command("run-all")
def run_all(
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c"),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o"),
    udbx_path: str | None = typer.Option(None, "--udbx-path"),
) -> None:
    app_config = load_config(config)
    dirs = _dirs(app_config, output_dir)
    _audit(app_config, dirs, "run-all", "started", parameters={"output_dir": str(dirs["reports"].parent)})
    validate_data(config=config, output_dir=output_dir)
    import_predictions(config=config, output_dir=output_dir)
    compute_metrics(config=config, output_dir=output_dir)
    register_supermap_results(config=config, output_dir=output_dir, udbx_path=udbx_path)
    export_reports(config=config, output_dir=output_dir, udbx_path=udbx_path)
    _audit(app_config, dirs, "run-all", "succeeded", outputs=[dirs["reports"]])


@app.command("demo-check")
def demo_check(
    json_output: bool = typer.Option(False, "--json", help="输出固定 JSON 契约"),
    host: str = typer.Option("127.0.0.1", "--host", help="API 监听地址"),
    port: int = typer.Option(8000, "--port", help="API 端口"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="运行时数据目录"),
    config: Path = typer.Option(Path("config/default.yaml"), "--config", help="平台配置文件"),
    frontend_dist: Path | None = typer.Option(None, "--frontend-dist", help="前端构建产物目录"),
) -> None:
    """演示启动前只读检查：阻断项失败退出码 1，可选项仅警告。"""
    import os

    from .demo_check import run_demo_checks

    resolved_data_dir = data_dir or Path(os.environ.get("GEOMODELING_DATA_DIR", "var/geomodeling"))
    resolved_dist = frontend_dist or Path(os.environ.get("GEOMODELING_FRONTEND_DIST", "web/dist"))
    report = run_demo_checks(
        host=host,
        port=port,
        data_dir=resolved_data_dir,
        config_path=config,
        frontend_dist=resolved_dist,
    )
    if json_output:
        typer.echo(json.dumps(report.to_dict(), ensure_ascii=False))
    else:
        tags = {"passed": "[PASSED]", "warning": "[WARNING]", "blocked": "[BLOCKED]"}
        for item in report.checks:
            line = f"{tags[item.status]} {item.id}: {item.message}"
            if item.remediation:
                line += f"（{item.remediation}）"
            typer.echo(line)
        typer.echo(f"status={report.status} exit_code={report.exit_code}")
    # 打印完完整报告后再按聚合结果退出；不启动任何服务
    raise typer.Exit(code=report.exit_code)


if __name__ == "__main__":
    app()
