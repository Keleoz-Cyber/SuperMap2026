"""v0.7.0 微震预置维护 CLI（显式维护命令；任何 HTTP GET 都不触发这些动作）。

``analyze-microseismic``：在受控 CSV 上执行固定 27 成员普通克里金候选矩阵，
输出只读候选报告（canonical JSON + 指纹）。报告经评审后其指纹冻结进
``config/presets/microseismic-official-baseline.json``；``seed-microseismic``
（Task 3）是唯一调用 seed 服务的生产命令。

独立入口：``python -m geomodeling.preset_cli analyze-microseismic ...``。
JSON 输出只含逻辑身份与 SHA-256，绝不输出绝对路径。
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from geomodeling.platform.errors import PlatformError
from geomodeling.platform.microseismic_preset import (
    DEFAULT_PRESET_CSV,
    analyze_preset_candidates,
    load_microseismic_preset,
    report_to_json,
    seed_microseismic_preset,
)
from geomodeling.platform.tables import dumps_canonical

preset_app = typer.Typer(
    add_completion=False,
    help="v0.7.0 微震预置维护命令（候选分析 / 官方基线 seed）",
)

PRESET_CLI_UNEXPECTED_ERROR = "PRESET_CLI_UNEXPECTED_ERROR"


@preset_app.callback()
def _preset_app_callback() -> None:
    """v0.7.0 微震预置维护命令组（子命令名稳定）。"""


@preset_app.command("analyze-microseismic")
def analyze_microseismic(
    output: Path = typer.Option(..., "--output", help="候选报告输出路径（canonical JSON）"),
    csv: Path = typer.Option(DEFAULT_PRESET_CSV, "--csv", help="受控预置 CSV（默认入库文件）"),
) -> None:
    """执行固定候选矩阵分析并写出只读候选报告（纯计算，不触碰运行时）。"""

    try:
        source = load_microseismic_preset(csv)
        report = analyze_preset_candidates(source)
        payload = report_to_json(report)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(dumps_canonical(payload) + "\n", encoding="utf-8")
        typer.echo(
            json.dumps(
                {
                    "source_sha256": report.source_sha256,
                    "candidate_report_sha256": report.sha256,
                    "candidate_count": len(report.candidates),
                    "common_valid_count": report.common_valid_count,
                },
                ensure_ascii=False,
            )
        )
    except PlatformError as exc:
        typer.echo(json.dumps(exc.public_payload(), ensure_ascii=False))
        raise typer.Exit(code=1) from exc
    except Exception as exc:  # noqa: BLE001 - 统一错误封套
        payload = {"error": {"code": PRESET_CLI_UNEXPECTED_ERROR, "message": str(exc), "details": {}}}
        typer.echo(json.dumps(payload, ensure_ascii=False))
        raise typer.Exit(code=1) from exc


def main() -> None:
    preset_app()


@preset_app.command("seed-microseismic")
def seed_microseismic(
    data_dir: Path = typer.Option(
        None,
        "--data-dir",
        help="平台运行时数据目录（默认 GEOMODELING_DATA_DIR 或 var/geomodeling）",
    ),
) -> None:
    """经正常生命周期 seed 官方微震成果（幂等；唯一生产 seed 入口）。

    首建走完整 Case→DatasetVersion→Experiment→Run→CandidateResult→
    materialize→FormalSelection 链；同身份同指纹已存在时只查询复用，
    绝不重算或改写。NetCDF 资产只能经既有显式渲染资产服务另行创建。
    """

    from geomodeling.platform import PlatformRuntime
    from geomodeling.platform.settings import PlatformSettings

    try:
        settings = (
            PlatformSettings(data_dir=data_dir) if data_dir else PlatformSettings.resolve()
        )
        runtime = PlatformRuntime(settings=settings)
        runtime.initialize()
        try:
            record = seed_microseismic_preset(runtime)
        finally:
            runtime.close()
        typer.echo(
            json.dumps(
                {
                    "case_id": record.case_id,
                    "workspace_kind": record.workspace_kind,
                    "dataset_version_id": record.dataset_version_id,
                    "experiment_id": record.experiment_id,
                    "run_id": record.run_id,
                    "official_result": record.official_result.model_dump(mode="json"),
                    "source_sha256": record.source_sha256,
                    "baseline_sha256": record.baseline_sha256,
                },
                ensure_ascii=False,
            )
        )
    except PlatformError as exc:
        typer.echo(json.dumps(exc.public_payload(), ensure_ascii=False))
        raise typer.Exit(code=1) from exc
    except Exception as exc:  # noqa: BLE001 - 统一错误封套
        payload = {"error": {"code": PRESET_CLI_UNEXPECTED_ERROR, "message": str(exc), "details": {}}}
        typer.echo(json.dumps(payload, ensure_ascii=False))
        raise typer.Exit(code=1) from exc


def main() -> None:
    preset_app()


if __name__ == "__main__":
    main()
