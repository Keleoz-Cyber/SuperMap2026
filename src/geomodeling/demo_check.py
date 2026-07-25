"""`geomodeling demo-check` 的预检编排（纯逻辑、可注入探针）。

阻断项失败聚合为 ``blocked`` + 退出码 1；iServer/S3M/凭据缺失只产生
``warning``，整体仍返回 0。公开消息与修复建议只使用逻辑名，不含本机
绝对路径。
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Literal, Sequence

CheckStatus = Literal["passed", "warning", "blocked"]

BLOCKER = "blocked"
WARNING = "warning"
PASSED = "passed"


@dataclass(frozen=True)
class DemoCheckItem:
    id: str
    status: CheckStatus
    message: str
    remediation: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "message": self.message,
            "remediation": self.remediation,
        }


@dataclass(frozen=True)
class DemoCheckReport:
    status: CheckStatus
    exit_code: int
    reuse_existing: bool
    checks: tuple[DemoCheckItem, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "exit_code": self.exit_code,
            "reuse_existing": self.reuse_existing,
            "checks": [item.to_dict() for item in self.checks],
        }


class PortProbeResult(Enum):
    FREE = "free"
    REUSABLE = "reusable"
    OCCUPIED_UNKNOWN = "occupied_unknown"


def probe_api_port(host: str, port: int) -> PortProbeResult:
    """短超时探测：空闲 / 已是本平台健康实例（可复用）/ 未知占用。"""

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.5)
    try:
        if sock.connect_ex((host, port)) != 0:
            return PortProbeResult.FREE
    finally:
        sock.close()

    def _get_json(path: str) -> dict | None:
        try:
            with urllib.request.urlopen(f"http://{host}:{port}{path}", timeout=2.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    health = _get_json("/api/health")
    if not health or health.get("status") != "ok":
        return PortProbeResult.OCCUPIED_UNKNOWN
    openapi = _get_json("/openapi.json")
    title = (openapi or {}).get("info", {}).get("title")
    # 必须精确匹配本平台身份；前缀匹配不算
    if title != "GeoModelingPlatform API":
        return PortProbeResult.OCCUPIED_UNKNOWN
    return PortProbeResult.REUSABLE


def probe_optional_services() -> Sequence[DemoCheckItem]:
    """iServer / S3M 缓存 / 凭据：全部只产生 warning，任何异常都转 warning。"""

    items: list[DemoCheckItem] = []
    base_url = os.environ.get("GEOMODELING_ISERVER_URL", "http://localhost:8090/iserver").rstrip("/")
    try:
        with urllib.request.urlopen(f"{base_url}/services.rjson", timeout=2.0) as resp:
            resp.read(1)
        items.append(DemoCheckItem("iserver_optional", PASSED, "iServer 在线"))
    except Exception:
        items.append(
            DemoCheckItem(
                "iserver_optional",
                WARNING,
                "iServer 未启动或不可访问（仅影响内置电阻率路线）",
                "通用建模演示无需 iServer；如需路线 B 请先启动 iServer",
            )
        )

    try:
        with urllib.request.urlopen(
            f"{base_url}/services/3D-local3DCache-RHO_KRIG_FINAL_20M_40_VOL_S3M2/rest/realspace/datas/RHO_KRIG_FINAL_20M_40_VOL_S3M2/config",
            timeout=2.0,
        ) as resp:
            resp.read(1)
        items.append(DemoCheckItem("s3m_optional", PASSED, "S3M 体元缓存服务可访问"))
    except Exception:
        items.append(
            DemoCheckItem(
                "s3m_optional",
                WARNING,
                "S3M 体元缓存服务不可访问（仅影响体元展示）",
                "可选：在 iServer 发布体元缓存服务后恢复",
            )
        )

    if os.environ.get("GEOMODELING_ISERVER_ADMIN_USER") and os.environ.get(
        "GEOMODELING_ISERVER_ADMIN_PASSWORD"
    ):
        items.append(DemoCheckItem("iserver_credentials_optional", PASSED, "已配置 iServer 凭据"))
    else:
        items.append(
            DemoCheckItem(
                "iserver_credentials_optional",
                WARNING,
                "未配置 iServer 管理凭据（只读探测不受影响）",
                "可选：经环境变量提供凭据以启用管理面探测",
            )
        )
    return items


def _check_python_imports() -> DemoCheckItem:
    try:
        from geomodeling.api.app import create_app  # noqa: F401
        from geomodeling.modeling.idw import IDWInterpolator  # noqa: F401
        from geomodeling.modeling.kriging import OrdinaryKrigingInterpolator  # noqa: F401
        from geomodeling.platform import PlatformRuntime  # noqa: F401

        return DemoCheckItem("python_imports", PASSED, "Python 包与关键模块可导入")
    except Exception as exc:
        return DemoCheckItem(
            "python_imports",
            BLOCKER,
            f"Python 包或关键模块导入失败（{type(exc).__name__}）",
            "执行 python -m pip install -e \".[api,test]\"",
        )


def _check_config(config_path: Path) -> DemoCheckItem:
    try:
        from geomodeling.config import load_config

        load_config(config_path)
        return DemoCheckItem("config_load", PASSED, "配置文件可加载")
    except Exception as exc:
        return DemoCheckItem(
            "config_load",
            BLOCKER,
            f"配置加载失败（{type(exc).__name__}）",
            "核对 GEOMODELING_CONFIG 指向的配置文件",
        )


def _check_frontend(frontend_dist: Path) -> DemoCheckItem:
    if (frontend_dist / "index.html").exists():
        return DemoCheckItem("frontend_build", PASSED, "前端构建产物存在")
    return DemoCheckItem(
        "frontend_build",
        BLOCKER,
        "前端构建产物缺失（web/dist/index.html 不存在）",
        "执行 npm --prefix web ci; npm --prefix web run build",
    )


def _check_demo_dataset(asset_path: Path | None) -> DemoCheckItem:
    from geomodeling.demo_assets import get_demo_dataset

    try:
        asset = get_demo_dataset(asset_path)
        return DemoCheckItem(
            "demo_dataset", PASSED, f"演示数据完整（{asset.row_count} 行，SHA-256 固定）"
        )
    except Exception as exc:
        return DemoCheckItem(
            "demo_dataset",
            BLOCKER,
            f"演示数据不可用（{type(exc).__name__}）",
            "恢复仓库内 demo/platform_demo_3d.csv",
        )


def _check_runtime_directory(data_dir: Path) -> DemoCheckItem:
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=data_dir) as handle:
            handle.write(b"probe")
        return DemoCheckItem("runtime_directory", PASSED, "数据目录可创建、可写")
    except Exception as exc:
        return DemoCheckItem(
            "runtime_directory",
            BLOCKER,
            f"数据目录不可创建或不可写（{type(exc).__name__}）",
            "检查 GEOMODELING_DATA_DIR 权限或更换目录",
        )


def _check_sqlite(data_dir: Path) -> DemoCheckItem:
    runtime = None
    try:
        from geomodeling.platform import PlatformRuntime

        runtime = PlatformRuntime(data_dir)
        runtime.initialize()
        return DemoCheckItem("sqlite_initialize", PASSED, "SQLite 可初始化并关闭")
    except Exception as exc:
        return DemoCheckItem(
            "sqlite_initialize",
            BLOCKER,
            f"SQLite 初始化失败（{type(exc).__name__}）",
            "检查数据目录与数据库文件状态",
        )
    finally:
        if runtime is not None:
            runtime.close()


def _check_api_port(host: str, port: int, port_probe) -> tuple[DemoCheckItem, bool]:
    result = port_probe(host, port)
    if result is PortProbeResult.FREE:
        return DemoCheckItem("api_port", PASSED, "API 端口空闲"), False
    if result is PortProbeResult.REUSABLE:
        return (
            DemoCheckItem("api_port", PASSED, "端口上已是本平台健康实例，可直接复用"),
            True,
        )
    return (
        DemoCheckItem(
            "api_port",
            BLOCKER,
            "API 端口被未知进程占用",
            "更换端口（--port）或人工确认占用者；不要结束未知进程",
        ),
        False,
    )


def run_demo_checks(
    *,
    host: str,
    port: int,
    data_dir: Path,
    config_path: Path,
    frontend_dist: Path,
    asset_path: Path | None = None,
    port_probe: Callable[[str, int], PortProbeResult] = probe_api_port,
    optional_probe: Callable[[], Sequence[DemoCheckItem]] = probe_optional_services,
) -> DemoCheckReport:
    """执行全部预检并聚合结果（只读，不启动服务）。"""

    checks: list[DemoCheckItem] = [
        _check_python_imports(),
        _check_config(config_path),
        _check_frontend(frontend_dist),
        _check_demo_dataset(asset_path),
        _check_runtime_directory(data_dir),
        _check_sqlite(data_dir),
    ]
    port_item, reuse_existing = _check_api_port(host, port, port_probe)
    checks.append(port_item)

    for item in optional_probe():
        # 可选项任何状态都不得升级为阻断
        status = item.status if item.status != BLOCKER else WARNING
        checks.append(
            DemoCheckItem(item.id, status, item.message, item.remediation)
        )

    blocked = any(item.status == BLOCKER for item in checks)
    warning = any(item.status == WARNING for item in checks)
    if blocked:
        status: CheckStatus = BLOCKER
        exit_code = 1
    elif warning:
        status = WARNING
        exit_code = 0
    else:
        status = PASSED
        exit_code = 0
    return DemoCheckReport(
        status=status,
        exit_code=exit_code,
        reuse_existing=reuse_existing,
        checks=tuple(checks),
    )
