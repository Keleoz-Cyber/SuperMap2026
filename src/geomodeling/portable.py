"""Windows one-directory launcher for the contest evaluation package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import uvicorn

from geomodeling import __version__
from geomodeling.runtime_paths import executable_root, resource_path


APP_NAME = "GeoModelingPlatform"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
STATE_FILE = "portable-state.json"
MANIFEST_FILE = "portable-manifest.json"
ORIGIN_FILE = "portable-origin.txt"
TEMPLATE_ROOT_MARKER = "__GEOMODELING_PORTABLE_RUNTIME__"


class PortableError(RuntimeError):
    pass


@dataclass(frozen=True)
class PortableLayout:
    package_root: Path
    runtime_dir: Path
    logs_dir: Path
    state_path: Path
    manifest_path: Path
    template_dir: Path
    frontend_dist: Path

    @classmethod
    def resolve(cls, package_root: Path | None = None) -> "PortableLayout":
        root = (package_root or executable_root()).resolve()
        runtime_dir = root / "runtime"
        return cls(
            package_root=root,
            runtime_dir=runtime_dir,
            logs_dir=runtime_dir / "logs",
            state_path=runtime_dir / STATE_FILE,
            manifest_path=root / MANIFEST_FILE,
            template_dir=resource_path("runtime-template"),
            frontend_dist=resource_path("web", "dist"),
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_manifest(layout: PortableLayout) -> dict:
    if not layout.manifest_path.is_file():
        raise PortableError("便携包完整性清单缺失，请重新解压官方交付包。")
    payload = json.loads(layout.manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("files")
    if not isinstance(entries, list) or not entries:
        raise PortableError("便携包完整性清单格式无效。")
    for entry in entries:
        relative = entry.get("path") if isinstance(entry, dict) else None
        expected = entry.get("sha256") if isinstance(entry, dict) else None
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise PortableError("便携包完整性清单包含无效条目。")
        candidate = (layout.package_root / relative).resolve()
        if layout.package_root not in candidate.parents:
            raise PortableError("便携包完整性清单包含越界路径。")
        if not candidate.is_file() or _sha256(candidate) != expected:
            raise PortableError(f"便携包文件缺失或损坏：{relative}")
    return payload


def initialize_runtime(layout: PortableLayout) -> None:
    """Create the writable runtime once, using a release-built seed template."""

    layout.runtime_dir.mkdir(parents=True, exist_ok=True)
    layout.logs_dir.mkdir(parents=True, exist_ok=True)
    marker = layout.runtime_dir / ".initialized"
    if marker.exists():
        return
    template_db = layout.template_dir / "platform.sqlite3"
    if not template_db.is_file():
        raise PortableError("内置案例运行库模板缺失，无法首次初始化。")
    for child in layout.template_dir.iterdir():
        target = layout.runtime_dir / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            shutil.copy2(child, target)
    origin_path = layout.runtime_dir / ORIGIN_FILE
    if not origin_path.is_file():
        raise PortableError("运行库模板缺少路径重定位信息。")
    origin = origin_path.read_text(encoding="utf-8").strip()
    if not origin:
        raise PortableError("运行库模板路径重定位信息为空。")
    relocate_runtime(layout.runtime_dir, origin, str(layout.runtime_dir))
    origin_path.unlink(missing_ok=True)
    marker.write_text("initialized\n", encoding="utf-8")


def relocate_runtime(runtime_dir: Path, old_root: str, new_root: str) -> None:
    """Rewrite internal absolute paths after the template is copied.

    The modeling database stores server-only paths in TEXT and JSON columns.
    Replacing the template root is safe because result/data hashes are content
    hashes and are not derived from these path strings.
    """

    db_path = runtime_dir / "platform.sqlite3"
    if not db_path.is_file():
        raise PortableError("运行库数据库缺失，无法完成路径重定位。")
    replacements = (
        (old_root.replace("\\", "\\\\"), new_root.replace("\\", "\\\\")),
        (old_root, new_root),
    )
    connection = sqlite3.connect(db_path)
    try:
        table_rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (table,) in table_rows:
            columns = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            for column in columns:
                name = column[1]
                declared_type = str(column[2]).upper()
                if "TEXT" not in declared_type and "CHAR" not in declared_type:
                    continue
                for source, target in replacements:
                    connection.execute(
                        f'UPDATE "{table}" SET "{name}" = replace("{name}", ?, ?) '
                        f'WHERE instr("{name}", ?) > 0',
                        (source, target, source),
                    )
        connection.commit()
        # SQLite may retain replaced absolute paths in free pages. Compact the
        # database so delivery scans cannot recover build-machine paths.
        connection.execute("VACUUM")
    finally:
        connection.close()

    for pattern in ("*.json", "*.jsonl", "*.txt", "*.yaml", "*.yml"):
        for path in runtime_dir.rglob(pattern):
            if path.name == ORIGIN_FILE:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            updated = text
            for source, target in replacements:
                updated = updated.replace(source, target)
            if updated != text:
                path.write_text(updated, encoding="utf-8")


def _health_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/api/health"


def probe_health(host: str, port: int, timeout: float = 1.5) -> dict | None:
    try:
        with urllib.request.urlopen(_health_url(host, port), timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("status") == "ok":
            return payload
    except (OSError, ValueError, urllib.error.URLError):
        return None
    return None


def _is_this_platform(payload: dict | None) -> bool:
    return bool(
        payload
        and payload.get("status") == "ok"
        and payload.get("version") == __version__
    )


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def _runtime_environment(layout: PortableLayout) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "GEOMODELING_DATA_DIR": str(layout.runtime_dir),
            "GEOMODELING_FRONTEND_DIST": str(layout.frontend_dist),
            "GEOMODELING_CONFIG": str(resource_path("config", "default.yaml")),
            "GEOMODELING_EVIDENCE_DIR": str(layout.runtime_dir / "evidence"),
            "PYTHONUTF8": "1",
        }
    )
    return env


def _write_state(layout: PortableLayout, host: str, port: int) -> None:
    layout.state_path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "host": host,
                "port": port,
                "started_at": time.time(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def serve(layout: PortableLayout, host: str, port: int) -> int:
    os.environ.update(_runtime_environment(layout))
    from geomodeling.api.deps import get_settings

    get_settings.cache_clear()
    _write_state(layout, host, port)
    try:
        uvicorn.run(
            "geomodeling.api.app:create_app",
            factory=True,
            host=host,
            port=port,
            workers=1,
            log_config=None,
        )
    finally:
        layout.state_path.unlink(missing_ok=True)
    return 0


def _spawn_server(layout: PortableLayout, host: str, port: int) -> subprocess.Popen:
    log_path = layout.logs_dir / "server.log"
    log_handle = log_path.open("a", encoding="utf-8")
    if getattr(sys, "frozen", False):
        command = [sys.executable, "serve", "--host", host, "--port", str(port)]
    else:
        command = [
            sys.executable,
            "-m",
            "geomodeling.portable",
            "serve",
            "--host",
            host,
            "--port",
            str(port),
        ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return subprocess.Popen(
            command,
            cwd=layout.package_root,
            env=_runtime_environment(layout),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=flags,
            close_fds=True,
        )
    finally:
        log_handle.close()


def start(layout: PortableLayout, host: str, port: int, *, open_browser: bool) -> int:
    verify_manifest(layout)
    initialize_runtime(layout)
    health = probe_health(host, port)
    if _is_this_platform(health):
        if open_browser:
            webbrowser.open(f"http://{host}:{port}/")
        print(f"平台已在运行：http://{host}:{port}/")
        return 0
    if health is not None:
        raise PortableError(
            f"端口 {port} 上运行的不是 GeoModelingPlatform {__version__}，请先关闭占用程序。"
        )
    if not _port_available(host, port):
        raise PortableError(f"端口 {port} 已被其他程序占用，请关闭占用程序后重试。")
    process = _spawn_server(layout, host, port)
    for _ in range(60):
        if process.poll() is not None:
            raise PortableError(f"平台启动失败，请查看 {layout.logs_dir / 'server.log'}")
        if _is_this_platform(probe_health(host, port)):
            if open_browser:
                webbrowser.open(f"http://{host}:{port}/")
            print(f"平台启动成功：http://{host}:{port}/")
            return 0
        time.sleep(0.5)
    process.terminate()
    raise PortableError("平台在 30 秒内未完成启动，请查看 runtime/logs/server.log。")


def _read_state(layout: PortableLayout) -> dict | None:
    try:
        payload = json.loads(layout.state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("pid"), int):
        return None
    return payload


def stop(layout: PortableLayout) -> int:
    state = _read_state(layout)
    if state is None:
        print("平台未运行，或运行状态文件已不存在。")
        return 0
    pid = int(state["pid"])
    host = str(state.get("host", DEFAULT_HOST))
    port = int(state.get("port", DEFAULT_PORT))
    health = probe_health(host, port)
    if not _is_this_platform(health):
        layout.state_path.unlink(missing_ok=True)
        print("状态文件已过期；未停止任何进程。")
        return 0
    if os.name == "nt":
        completed = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode not in (0, 128):
            raise PortableError(f"无法停止平台进程 PID {pid}。")
    else:
        os.kill(pid, 15)
    layout.state_path.unlink(missing_ok=True)
    print("平台已停止。")
    return 0


def doctor(layout: PortableLayout) -> int:
    manifest = verify_manifest(layout)
    initialize_runtime(layout)
    report = {
        "ok": True,
        "version": manifest.get("version"),
        "package_root": str(layout.package_root),
        "runtime_writable": os.access(layout.runtime_dir, os.W_OK),
        "frontend_ready": (layout.frontend_dist / "index.html").is_file(),
        "template_ready": (layout.template_dir / "platform.sqlite3").is_file(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=APP_NAME)
    sub = parser.add_subparsers(dest="command")
    for command in ("start", "serve"):
        item = sub.add_parser(command)
        item.add_argument("--host", default=DEFAULT_HOST)
        item.add_argument("--port", type=int, default=DEFAULT_PORT)
        if command == "start":
            item.add_argument("--no-browser", action="store_true")
    sub.add_parser("stop")
    sub.add_parser("doctor")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    command = args.command or "start"
    layout = PortableLayout.resolve()
    try:
        if command == "start":
            return start(layout, args.host, args.port, open_browser=not args.no_browser)
        if command == "serve":
            return serve(layout, args.host, args.port)
        if command == "stop":
            return stop(layout)
        if command == "doctor":
            return doctor(layout)
    except PortableError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1
    raise PortableError(f"未知命令：{command}")


if __name__ == "__main__":
    raise SystemExit(main())
