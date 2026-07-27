"""v0.6 professional analysis CLI（设计 §15）：与 API 共用同一平台服务层。

五个命令（diagnose/confirm/inspect-result/extract-anomalies/compare）只编排
服务调用，绝不复制数学实现；``PlatformRuntime`` 在 ``try/finally`` 中
initialize/close。诊断与异常提取在 CLI 进程内创建 ``JobWorker``、
``enqueue_analysis`` 后 ``wait_idle``——分派、取消旗标与 worker 兜底语义与
API 逐位一致。JSON 输出复用 ``platform.public_dto`` 白名单 DTO：只含逻辑身
份、相对工件名、SHA-256 与计数，绝不输出绝对路径（本任务不实现本机调试开
关）。结构化失败打印统一错误封套（``{"error": {"code", "message", ...}}``，
details 经 ``public_payload`` 脱敏）并以 exit 1 退出；意外异常不落 traceback
（栈帧含绝对路径），统一压缩为单行结构化错误。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import typer

from geomodeling.platform import PlatformRuntime, tables
from geomodeling.platform.analysis_jobs import (
    create_anomaly_extraction,
    create_professional_diagnosis,
    get_anomaly_extraction,
    get_professional_diagnosis,
)
from geomodeling.platform.errors import (
    PROFESSIONAL_ARTIFACTS_NOT_FOUND,
    PlatformError,
)
from geomodeling.platform.professional import (
    PROFESSIONAL_CONFIG_INVALID,
    compare_candidates,
    confirm_professional_diagnosis,
)
from geomodeling.platform.public_dto import (
    public_anomaly_extraction,
    public_comparison,
    public_confirmation,
    public_professional_diagnosis,
    public_professional_result,
)
from geomodeling.platform.results import CANDIDATE_NOT_SUCCEEDED, _load_candidate
from geomodeling.platform.settings import PlatformSettings
from geomodeling.platform.worker import JobWorker

professional_app = typer.Typer(
    add_completion=False,
    help="v0.6 专业建模分析命令（与 API 共用同一平台服务层）",
)

PROFESSIONAL_CLI_UNEXPECTED_ERROR = "PROFESSIONAL_CLI_UNEXPECTED_ERROR"


@contextmanager
def _runtime(data_dir: Path) -> Iterator[PlatformRuntime]:
    runtime = PlatformRuntime(settings=PlatformSettings(data_dir=data_dir))
    runtime.initialize()
    try:
        yield runtime
    finally:
        runtime.close()


@contextmanager
def _structured_errors() -> Iterator[None]:
    """统一失败通道：结构化错误打印脱敏封套 exit 1；意外异常不落 traceback。"""

    try:
        yield
    except PlatformError as exc:
        _emit(exc.public_payload())
        raise typer.Exit(code=1) from exc
    except Exception as exc:  # noqa: BLE001
        _emit(
            {
                "error": {
                    "code": PROFESSIONAL_CLI_UNEXPECTED_ERROR,
                    "message": f"{type(exc).__name__}: {str(exc)[:200]}",
                }
            }
        )
        raise typer.Exit(code=1) from exc


def _emit(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def _load_config_json(config_json: str) -> dict[str, Any]:
    try:
        payload = json.loads(config_json)
    except json.JSONDecodeError as exc:
        raise PlatformError(
            PROFESSIONAL_CONFIG_INVALID,
            "--config-json 不是合法 JSON",
            {"reason": str(exc)[:200]},
        ) from exc
    if not isinstance(payload, dict):
        raise PlatformError(PROFESSIONAL_CONFIG_INVALID, "--config-json 必须是 JSON 对象")
    return payload


def _execute_analysis(runtime: PlatformRuntime, job_id: str) -> None:
    """进程内 worker 执行分析任务并等待终态（与 API 同一分派/兜底语义）。"""

    worker = JobWorker(runtime)
    try:
        worker.enqueue_analysis(job_id)
        worker.wait_idle()
    finally:
        worker.shutdown()


def _professional_result_dto(runtime: PlatformRuntime, result_id: str) -> dict[str, Any]:
    """成果专业证据 DTO：与 ``GET /api/results/{id}/professional`` 同一装配。

    归属链 + succeeded 门禁走平台服务；capabilities/参数出处/manifest 摘要复
    用同一白名单构造函数；legacy 候选明示 ``LEGACY_RESULT_NOT_COMPUTED``，绝
    不伪造零值指标或能力。
    """

    candidate, _run, experiment = _load_candidate(runtime, result_id)
    if candidate.status != "succeeded":
        raise PlatformError(
            CANDIDATE_NOT_SUCCEEDED,
            "只有成功候选才能公开专业证据",
            {"result_id": result_id, "status": candidate.status},
            http_status=409,
        )
    params = tables.loads_canonical(experiment.params_json)
    algorithm = params["algorithm"]
    with runtime.session() as session:
        artifacts_row = (
            session.query(tables.ProfessionalResultArtifacts)
            .filter(tables.ProfessionalResultArtifacts.candidate_result_id == result_id)
            .one_or_none()
        )
    if artifacts_row is None:
        if params.get("professional") is None:
            return public_professional_result(
                result_id,
                algorithm=algorithm,
                confirmation_id=None,
                capabilities=None,
                parameter_provenance=None,
                manifest=None,
            )
        raise PlatformError(
            PROFESSIONAL_ARTIFACTS_NOT_FOUND,
            "专业候选缺少工件集合，证据不完整",
            {"result_id": result_id},
            http_status=404,
        )
    manifest = (
        tables.loads_canonical(artifacts_row.manifest_json) if artifacts_row.manifest_json else {}
    )
    # 参数出处住在物化期 metadata.json（已登记工件）；未物化时为 None
    provenance = None
    metadata_path = runtime.settings.professional_result_dir(result_id) / "metadata.json"
    if metadata_path.is_file():
        provenance = json.loads(metadata_path.read_text(encoding="utf-8")).get(
            "parameter_provenance"
        )
    return public_professional_result(
        result_id,
        algorithm=algorithm,
        confirmation_id=artifacts_row.confirmation_id,
        capabilities=(
            tables.loads_canonical(artifacts_row.capabilities_json)
            if artifacts_row.capabilities_json
            else {}
        ),
        parameter_provenance=provenance,
        manifest=manifest or None,
    )


_DATA_DIR_OPTION = typer.Option(..., "--data-dir", help="平台数据目录（GEOMODELING_DATA_DIR 布局）")


@professional_app.command("diagnose")
def diagnose_command(
    data_dir: Path = _DATA_DIR_OPTION,
    dataset_id: str = typer.Option(..., "--dataset-id", help="数据版本 id"),
    config_json: str = typer.Option("{}", "--config-json", help="VariogramDiagnosticSpec JSON"),
) -> None:
    """创建专业诊断并同步执行到终态，输出诊断 id/状态/指纹/manifest 摘要。"""

    with _structured_errors(), _runtime(data_dir) as runtime:
        config = _load_config_json(config_json)
        request = create_professional_diagnosis(runtime, dataset_id, config)
        if request.job_id is not None:
            _execute_analysis(runtime, request.job_id)
        record = get_professional_diagnosis(runtime, request.id)
        dto = {
            **public_professional_diagnosis(record),
            "job_id": request.job_id,
            "reused": request.reused,
        }
    _emit(dto)
    # 结构化执行失败（如有效 bin 不足）：诊断 DTO 已含统一错误码，exit 1
    if dto["status"] != "succeeded":
        raise typer.Exit(code=1)


@professional_app.command("confirm")
def confirm_command(
    data_dir: Path = _DATA_DIR_OPTION,
    diagnosis_id: str = typer.Option(..., "--diagnosis-id", help="成功诊断 id"),
    note: str = typer.Option(..., "--note", help="确认说明（写入不可变快照）"),
    config_json: str = typer.Option("{}", "--config-json", help="确认配置 JSON"),
) -> None:
    """为成功诊断创建不可变确认快照，输出快照 id/指纹。"""

    with _structured_errors(), _runtime(data_dir) as runtime:
        config = _load_config_json(config_json)
        record = confirm_professional_diagnosis(runtime, diagnosis_id, config, note)
        dto = public_confirmation(record)
    _emit(dto)


@professional_app.command("inspect-result")
def inspect_result_command(
    data_dir: Path = _DATA_DIR_OPTION,
    result_id: str = typer.Option(..., "--result-id", help="候选成果 id"),
) -> None:
    """输出成果专业证据：capabilities/parameter_provenance/manifest 摘要。"""

    with _structured_errors(), _runtime(data_dir) as runtime:
        dto = _professional_result_dto(runtime, result_id)
    _emit(dto)


@professional_app.command("extract-anomalies")
def extract_anomalies_command(
    data_dir: Path = _DATA_DIR_OPTION,
    result_id: str = typer.Option(..., "--result-id", help="已物化候选成果 id"),
    config_json: str = typer.Option(..., "--config-json", help="AnomalyExtractionSpec JSON"),
) -> None:
    """创建异常提取并同步执行到终态，输出提取 id/状态/component 数。"""

    with _structured_errors(), _runtime(data_dir) as runtime:
        config = _load_config_json(config_json)
        request = create_anomaly_extraction(runtime, result_id, config)
        if request.job_id is not None:
            _execute_analysis(runtime, request.job_id)
        record = get_anomaly_extraction(runtime, request.id)
        dto = {
            **public_anomaly_extraction(record),
            "job_id": request.job_id,
            "reused": request.reused,
        }
    _emit(dto)
    if dto["status"] != "succeeded":
        raise typer.Exit(code=1)


@professional_app.command("compare")
def compare_command(
    data_dir: Path = _DATA_DIR_OPTION,
    first: str = typer.Option(..., "--first", help="第一个候选成果 id"),
    second: str = typer.Option(..., "--second", help="第二个候选成果 id"),
) -> None:
    """比较两个成功候选，输出 compatible/mismatches/metric_deltas/比较指纹。"""

    with _structured_errors(), _runtime(data_dir) as runtime:
        comparison = compare_candidates(runtime, first, second)
        dto = public_comparison(comparison)
    _emit(dto)
