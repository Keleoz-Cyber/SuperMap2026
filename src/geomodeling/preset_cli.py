"""预置维护 CLI（显式维护命令；任何 HTTP GET 都不触发这些动作）。

``analyze-microseismic``：在受控 CSV 上执行固定 27 成员普通克里金候选矩阵，
输出只读候选报告（canonical JSON + 指纹）。报告经评审后其指纹冻结进
``config/presets/microseismic-official-baseline.json``；``seed-microseismic``
是唯一调用微震 seed 服务的生产命令。

``analyze-resistivity``（v0.8.0 Task 5）：在外部电阻率源上执行最小官方
候选矩阵（1 IDW + 4 普通克里金 + 2 DSI-like），并把遗留训练/验证分区
与源逐行匹配后的溯源事实（仅计数 + 验证柱指纹）冻结进只读候选报告；
报告指纹经评审后写入 ``config/presets/resistivity-official-baseline.json``。

``analyze-gas``（v0.8.0 第三批 Task 5）：在内置瓦斯源上执行 13 候选官方
矩阵（IDW 9 + 普通克里金 4）并条件评估 DSI-like 默认参数对照候选（全部
门通过才 evaluated，任一不过 excluded 带原因）；报告指纹经评审后写入
``config/presets/gas-official-baseline.json``。

``seed-resistivity``（v0.8.0 Task 2）：把电阻率标准化散点 CSV seed 为
只读 ``builtin_preset`` 案例链；``--source`` 缺省为项目内
``example_data/地下电阻率节点_标准化.csv`` 内置源（v0.8.0 第三批起，
字节冻结合同；仅测试/审计显式覆盖），官方基线 JSON 默认读受控路径
``config/presets/resistivity-official-baseline.json``（Task 5 冻结）。

``seed-gas``（v0.8.0 第三批 Task 4）：把瓦斯含量合格样品 CSV seed 为只读
``builtin_preset`` 案例链；``--source`` 缺省为项目内
``example_data/瓦斯含量_合格样品.csv`` 内置源，官方基线 JSON 默认读受控路径
``config/presets/gas-official-baseline.json``（Task 5 冻结，缺失 fail-closed）。

独立入口：``python -m geomodeling.preset_cli <command> ...``。
JSON 输出只含逻辑身份与 SHA-256，绝不输出绝对路径。
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from geomodeling.platform.errors import PlatformError
from geomodeling.platform.gas_preset import (
    DEFAULT_BASELINE_PATH as GAS_DEFAULT_BASELINE_PATH,
)
from geomodeling.platform.gas_preset import (
    DEFAULT_PRESET_CSV as GAS_DEFAULT_PRESET_CSV,
)
from geomodeling.platform.gas_preset import (
    analyze_gas_candidates,
    load_gas_preset,
    rank_gas_candidates,
    seed_gas_preset,
)
from geomodeling.platform.gas_preset import (
    report_to_json as gas_report_to_json,
)
from geomodeling.platform.microseismic_preset import (
    DEFAULT_PRESET_CSV,
    analyze_preset_candidates,
    load_microseismic_preset,
    report_to_json,
    seed_microseismic_preset,
)
from geomodeling.platform.resistivity_preset import (
    DEFAULT_BASELINE_PATH as RESISTIVITY_DEFAULT_BASELINE_PATH,
)
from geomodeling.platform.resistivity_preset import (
    LEGACY_TRAINING_FILENAME,
    LEGACY_VALIDATION_FILENAME,
    analyze_resistivity_candidates,
    load_resistivity_preset,
    match_legacy_partition,
    rank_resistivity_candidates,
)
from geomodeling.platform.resistivity_preset import (
    report_to_json as resistivity_report_to_json,
)
from geomodeling.platform.resistivity_preset import (
    seed_resistivity_preset,
    verify_partition_facts,
)
from geomodeling.platform.tables import dumps_canonical

preset_app = typer.Typer(
    add_completion=False,
    help="预置维护命令（微震候选分析/seed；电阻率散点 seed）",
)

PRESET_CLI_UNEXPECTED_ERROR = "PRESET_CLI_UNEXPECTED_ERROR"


@preset_app.callback()
def _preset_app_callback() -> None:
    """预置维护命令组（子命令名稳定）。"""


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


@preset_app.command("analyze-resistivity")
def analyze_resistivity(
    source: Path = typer.Option(
        ...,
        "--source",
        help="电阻率标准化散点 CSV（外部私有源；必填，无仓库默认，如 $env:GEOMODELING_RHO_SOURCE）",
    ),
    output: Path = typer.Option(
        ..., "--output", help="候选报告输出路径（canonical JSON；仅本地运行产物，绝不提交）"
    ),
    legacy_training: Path = typer.Option(
        None,
        "--legacy-training",
        help="遗留训练集 CSV（默认从 --source 同目录按标准文件名解析；仅本地使用）",
    ),
    legacy_validation: Path = typer.Option(
        None,
        "--legacy-validation",
        help="遗留验证集 CSV（默认从 --source 同目录按标准文件名解析；仅本地使用）",
    ),
) -> None:
    """执行 7 候选最小官方矩阵分析并写出只读候选报告（纯计算，不触碰运行时）。

    遗留训练/验证分区与受控源逐行精确匹配后，只把分区溯源事实（计数 +
    验证柱身份指纹）写进报告；坐标清单绝不输出。报告指纹经评审后冻结进
    ``config/presets/resistivity-official-baseline.json``。
    JSON 输出只含逻辑身份与 SHA-256，绝不输出绝对路径。
    """

    try:
        training = (
            Path(legacy_training) if legacy_training else source.parent / LEGACY_TRAINING_FILENAME
        )
        validation = (
            Path(legacy_validation)
            if legacy_validation
            else source.parent / LEGACY_VALIDATION_FILENAME
        )
        preset_source = load_resistivity_preset(source)
        facts = match_legacy_partition(preset_source, training, validation)
        verify_partition_facts(facts)
        report = analyze_resistivity_candidates(preset_source, partition=facts)
        payload = resistivity_report_to_json(report)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(dumps_canonical(payload) + "\n", encoding="utf-8")
        kriging_ranked = rank_resistivity_candidates(
            report.candidates, algorithm="ordinary_kriging"
        )
        succeeded: dict[str, int] = {}
        for entry in report.candidates:
            if entry["metrics"] is not None:
                succeeded[entry["algorithm"]] = succeeded.get(entry["algorithm"], 0) + 1
        typer.echo(
            json.dumps(
                {
                    "source_sha256": report.source_sha256,
                    "candidate_report_sha256": report.sha256,
                    "candidate_count": len(report.candidates),
                    "succeeded_by_algorithm": succeeded,
                    "common_valid_count": report.common_valid_count,
                    "partition": report.partition,
                    "kriging_winner": (
                        {
                            "parameters": kriging_ranked[0]["params"],
                            "metrics": kriging_ranked[0]["metrics"],
                        }
                        if kriging_ranked
                        else None
                    ),
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


@preset_app.command("analyze-gas")
def analyze_gas(
    output: Path = typer.Option(
        ..., "--output", help="候选报告输出路径（canonical JSON；仅本地运行产物，绝不提交）"
    ),
    source: Path = typer.Option(
        GAS_DEFAULT_PRESET_CSV,
        "--source",
        help="瓦斯含量合格样品 CSV（默认项目内 example_data/ 内置源；仅测试/审计显式覆盖）",
    ),
) -> None:
    """执行 13 候选官方矩阵分析并写出只读候选报告（纯计算，不触碰运行时）。

    IDW 9 组合 + 普通克里金 4 组合在空间 5 折（整 XY 柱分组）公共有效集上
    复算指标；DSI-like 默认参数对照候选经条件评估（交叉验证/公共有效集/
    指标有限/全数据 fit+网格物化全部门通过才 evaluated，否则 excluded 带
    原因）。报告指纹经评审后冻结进 ``config/presets/gas-official-baseline.json``。
    JSON 输出只含逻辑身份与 SHA-256，绝不输出绝对路径。
    """

    try:
        preset_source = load_gas_preset(source)
        report = analyze_gas_candidates(preset_source)
        payload = gas_report_to_json(report)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(dumps_canonical(payload) + "\n", encoding="utf-8")
        ranked = rank_gas_candidates(report.candidates)
        succeeded: dict[str, int] = {}
        for entry in report.candidates:
            if entry["metrics"] is not None:
                succeeded[entry["algorithm"]] = succeeded.get(entry["algorithm"], 0) + 1
        typer.echo(
            json.dumps(
                {
                    "source_sha256": report.source_sha256,
                    "candidate_report_sha256": report.sha256,
                    "candidate_count": len(report.candidates),
                    "succeeded_by_algorithm": succeeded,
                    "common_valid_count": report.common_valid_count,
                    "fold_validation_rows": list(report.fold_validation_rows),
                    "winner": (
                        {
                            "algorithm": ranked[0]["algorithm"],
                            "parameters": ranked[0]["params"],
                            "metrics": ranked[0]["metrics"],
                        }
                        if ranked
                        else None
                    ),
                    "dsi_like": {
                        "status": report.dsi_like["status"],
                        "reason": report.dsi_like["reason"],
                    },
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


@preset_app.command("seed-resistivity")
def seed_resistivity(
    source: Path = typer.Option(
        None,
        "--source",
        help="电阻率标准化散点 CSV（默认项目内 example_data/ 内置源；仅测试/审计显式覆盖）",
    ),
    data_dir: Path = typer.Option(
        None,
        "--data-dir",
        help="平台运行时数据目录（默认 GEOMODELING_DATA_DIR 或 var/geomodeling）",
    ),
    baseline: Path = typer.Option(
        RESISTIVITY_DEFAULT_BASELINE_PATH,
        "--baseline",
        help="评审冻结的官方基线 JSON（默认受控路径；Task 5 前不存在即 fail-closed）",
    ),
) -> None:
    """经正常生命周期 seed 电阻率散点只读预置成果（幂等；唯一生产 seed 入口）。

    首建走完整 Case→DatasetVersion→Experiment→Run→CandidateResult→
    materialize→FormalSelection 链；同身份同指纹已存在时只查询复用，
    绝不重算或改写。缺源/源合同不符/基线缺失或不符全部 fail-closed。
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
            record = seed_resistivity_preset(
                runtime, source_path=source, baseline_path=baseline
            )
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


@preset_app.command("seed-gas")
def seed_gas(
    source: Path = typer.Option(
        None,
        "--source",
        help="瓦斯含量合格样品 CSV（默认项目内 example_data/ 内置源；仅测试/审计显式覆盖）",
    ),
    data_dir: Path = typer.Option(
        None,
        "--data-dir",
        help="平台运行时数据目录（默认 GEOMODELING_DATA_DIR 或 var/geomodeling）",
    ),
    baseline: Path = typer.Option(
        GAS_DEFAULT_BASELINE_PATH,
        "--baseline",
        help="评审冻结的官方基线 JSON（默认受控路径；Task 5 前不存在即 fail-closed）",
    ),
) -> None:
    """经正常生命周期 seed 瓦斯含量只读预置成果（幂等；唯一生产 seed 入口）。

    首建走完整 Case→DatasetVersion→Experiment→Run→CandidateResult→
    materialize→FormalSelection 链；同身份同指纹已存在时只查询复用，
    绝不重算或改写。缺源/源合同不符/基线缺失或不符全部 fail-closed。
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
            record = seed_gas_preset(runtime, source_path=source, baseline_path=baseline)
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
