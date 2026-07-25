"""Task 4: demo-check preflight contract tests."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from geomodeling.demo_check import (
    DemoCheckItem,
    PortProbeResult,
    run_demo_checks,
)

BLOCKER_IDS = {
    "python_imports",
    "config_load",
    "frontend_build",
    "demo_dataset",
    "runtime_directory",
    "sqlite_initialize",
    "api_port",
}
OPTIONAL_IDS = {"iserver_optional", "s3m_optional", "iserver_credentials_optional"}


def make_frontend(tmp_path: Path) -> Path:
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    return dist


def run_checks(tmp_path: Path, **overrides):
    dist = make_frontend(tmp_path)
    kwargs = {
        "host": "127.0.0.1",
        "port": 58999,  # 高位空闲端口，避免与本机服务冲突
        "data_dir": tmp_path / "data",
        "config_path": Path("config/default.yaml"),
        "frontend_dist": dist,
    }
    kwargs.update(overrides)
    return run_demo_checks(**kwargs)


def warning_probe():
    return [
        DemoCheckItem("iserver_optional", "warning", "iServer 未启动", "可选：内置案例需要 iServer"),
        DemoCheckItem("s3m_optional", "warning", "S3M 缓存服务不可访问", "可选"),
        DemoCheckItem("iserver_credentials_optional", "warning", "未配置 iServer 凭据", "可选"),
    ]


def test_all_blockers_pass_with_optional_warnings_aggregates_warning(tmp_path):
    report = run_checks(tmp_path, optional_probe=warning_probe)
    assert report.status == "warning"
    assert report.exit_code == 0
    ids = {item.id for item in report.checks}
    assert ids == BLOCKER_IDS | OPTIONAL_IDS
    assert {item.id for item in report.checks if item.status == "blocked"} == set()
    payload = json.dumps(report.to_dict(), ensure_ascii=False)
    assert ":\\" not in payload  # 消息与修复建议不含盘符路径


def test_one_blocker_failure_aggregates_blocked(tmp_path):
    report = run_checks(tmp_path, frontend_dist=tmp_path / "no-dist", optional_probe=list)
    assert report.status == "blocked"
    assert report.exit_code == 1
    frontend = next(item for item in report.checks if item.id == "frontend_build")
    assert frontend.status == "blocked"
    assert frontend.remediation
    assert ":\\" not in frontend.message + (frontend.remediation or "")


def test_all_pass_aggregates_passed(tmp_path):
    report = run_checks(tmp_path, optional_probe=list)
    assert report.status == "passed"
    assert report.exit_code == 0
    assert all(item.status == "passed" for item in report.checks)


def test_missing_demo_dataset_blocks(tmp_path):
    report = run_checks(tmp_path, asset_path=tmp_path / "missing.csv", optional_probe=list)
    assert report.status == "blocked"
    item = next(i for i in report.checks if i.id == "demo_dataset")
    assert item.status == "blocked"
    assert str(tmp_path) not in item.message


def test_unwritable_data_dir_blocks(tmp_path):
    marker = tmp_path / "blocker-file"
    marker.write_text("not a dir", encoding="utf-8")
    report = run_checks(tmp_path, data_dir=marker / "sub", optional_probe=list)
    item = next(i for i in report.checks if i.id == "runtime_directory")
    assert item.status == "blocked"


def test_unknown_port_listener_blocks(tmp_path):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        report = run_checks(tmp_path, port=port, optional_probe=list)
    finally:
        listener.close()
    item = next(i for i in report.checks if i.id == "api_port")
    assert item.status == "blocked"
    assert report.status == "blocked"


def test_current_platform_instance_is_reusable(tmp_path):
    from fastapi.testclient import TestClient
    from geomodeling.api.app import create_app
    import threading
    import uvicorn

    # 起一个真实平台实例，验证“已是本平台健康实例则复用”
    config = uvicorn.Config(
        create_app(), host="127.0.0.1", port=0, log_level="error", workers=1
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        import time

        deadline = time.time() + 15
        port = None
        while time.time() < deadline:
            if server.started:
                port = server.servers[0].sockets[0].getsockname()[1]
                break
            time.sleep(0.1)
        assert port is not None
        report = run_checks(tmp_path, port=port, optional_probe=list)
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    item = next(i for i in report.checks if i.id == "api_port")
    assert item.status == "passed"
    assert report.reuse_existing is True


def test_optional_absence_never_blocks(tmp_path):
    report = run_checks(tmp_path, optional_probe=warning_probe)
    assert report.exit_code == 0
    for item in report.checks:
        if item.id in OPTIONAL_IDS:
            assert item.status == "warning"


class _FakeSocket:
    """模拟端口已被占用（connect_ex 返回 0）的假 socket。"""

    def __init__(self, *args, **kwargs):
        pass

    def settimeout(self, _t):
        pass

    def connect_ex(self, _addr):
        return 0

    def close(self):
        pass


def _patch_open_port(monkeypatch, dc):
    monkeypatch.setattr(dc.socket, "socket", lambda *a, **k: _FakeSocket())


def test_reusable_probe_rejects_mismatched_version(monkeypatch):
    """相同标题 + status=ok 但 version 落后（如 v0.4.0）必须判为未知占用。"""

    import json as _json
    from geomodeling import demo_check as dc
    from geomodeling.api.deps import PROJECT_VERSION

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return _json.dumps(self._payload).encode("utf-8")

    def fake_urlopen(url, timeout=0):
        if url.endswith("/api/health"):
            return _Resp({"status": "ok", "version": "0.4.0", "time": "2026-07-25T00:00:00Z"})
        if url.endswith("/openapi.json"):
            return _Resp({"info": {"title": "GeoModelingPlatform API"}})
        raise AssertionError(url)

    monkeypatch.setattr(dc.urllib.request, "urlopen", fake_urlopen)
    _patch_open_port(monkeypatch, dc)
    assert PROJECT_VERSION != "0.4.0"  # 当前代码已高于 0.4.0
    assert dc.probe_api_port("127.0.0.1", 8000) is dc.PortProbeResult.OCCUPIED_UNKNOWN


def test_reusable_probe_accepts_exact_current_version(monkeypatch):
    import json as _json
    from geomodeling import demo_check as dc
    from geomodeling.api.deps import PROJECT_VERSION

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return _json.dumps(self._payload).encode("utf-8")

    def fake_urlopen(url, timeout=0):
        if url.endswith("/api/health"):
            return _Resp({"status": "ok", "version": PROJECT_VERSION, "time": "2026-07-25T00:00:00Z"})
        if url.endswith("/openapi.json"):
            return _Resp({"info": {"title": "GeoModelingPlatform API"}})
        raise AssertionError(url)

    monkeypatch.setattr(dc.urllib.request, "urlopen", fake_urlopen)
    _patch_open_port(monkeypatch, dc)
    assert dc.probe_api_port("127.0.0.1", 8000) is dc.PortProbeResult.REUSABLE
