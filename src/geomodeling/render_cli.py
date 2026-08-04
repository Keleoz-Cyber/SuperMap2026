"""v0.6.1 legacy 渲染网格登记 CLI（设计：内置电阻率案例的唯一权威网格入口）。

``import-csv`` 只编排 ``platform.legacy_render_sources.import_legacy_grid`` 服务
调用，绝不复制网格校验/登记逻辑；``PlatformRuntime`` 在 ``try/finally`` 中
initialize/close。JSON 输出只含逻辑身份、相对工件目录与 SHA-256，绝不输出绝
对路径；结构化失败打印统一错误封套（``{"error": {"code", "message", ...}}``，
details 经 ``public_payload`` 脱敏）并以 exit 1 退出。

独立入口：``python -m geomodeling.render_cli import-csv ...``；同一命令组也
以 ``render-grid`` 挂在主 CLI（``python -m geomodeling.cli render-grid``）。
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import typer

from geomodeling.platform import PlatformRuntime
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.legacy_render_sources import import_legacy_grid
from geomodeling.platform.settings import DEFAULT_DATA_DIR, ENV_DATA_DIR, PlatformSettings

render_app = typer.Typer(
    add_completion=False,
    help="v0.6.1 渲染源登记命令（legacy 权威规则网格导入）",
)

RENDER_CLI_UNEXPECTED_ERROR = "RENDER_CLI_UNEXPECTED_ERROR"


@render_app.callback()
def _render_app_callback() -> None:
    """v0.6.1 渲染源登记命令组（单命令也保持 group 形态，子命令名稳定）。"""


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
                    "code": RENDER_CLI_UNEXPECTED_ERROR,
                    "message": f"{type(exc).__name__}: {str(exc)[:200]}",
                }
            }
        )
        raise typer.Exit(code=1) from exc


def _emit(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@render_app.command("import-csv")
def import_csv_command(
    source_id: str = typer.Option(..., "--source-id", help="legacy 渲染源 id（如 resistivity）"),
    csv: Path = typer.Option(..., "--csv", help="权威规则网格 CSV"),
    x: str = typer.Option(..., "--x", help="X 坐标列名"),
    y: str = typer.Option(..., "--y", help="Y 坐标列名"),
    z: str = typer.Option(..., "--z", help="Z 坐标列名"),
    value: str = typer.Option(..., "--value", help="属性值列名"),
    property_name: str = typer.Option(..., "--property-name", help="属性名（如 RHO）"),
    units: str = typer.Option(..., "--units", help="单位（缺失时字面 unknown）"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="平台数据目录（默认 GEOMODELING_DATA_DIR 或 var/geomodeling）"),
) -> None:
    """把权威 CSV 原子登记为内置 legacy 规则网格渲染源，输出登记记录 JSON。"""

    resolved_data_dir = data_dir or Path(os.environ.get(ENV_DATA_DIR, DEFAULT_DATA_DIR))
    with _structured_errors(), _runtime(resolved_data_dir) as runtime:
        record = import_legacy_grid(
            runtime,
            source_id=source_id,
            csv_path=csv,
            x_column=x,
            y_column=y,
            z_column=z,
            value_column=value,
            property_name=property_name,
            units=units,
        )
        payload = {
            "source_kind": record.source_kind,
            "source_id": record.source_id,
            "grid_sha256": record.grid_sha256,
            "property_name": record.property_name,
            "units": record.units,
            "shape": record.shape,
            "artifact_dir": record.artifact_dir,
            "import_source_sha256": record.import_source_sha256,
        }
    _emit(payload)


if __name__ == "__main__":
    render_app()
