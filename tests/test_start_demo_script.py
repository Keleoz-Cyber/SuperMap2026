"""Task 5: start_demo.ps1 safety contract (static + check-only behavior)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

SCRIPT = Path("scripts/start_demo.ps1")


def _read() -> str:
    assert SCRIPT.exists(), "scripts/start_demo.ps1 不存在"
    return SCRIPT.read_text(encoding="utf-8")


def test_launcher_contains_no_dangerous_operations():
    text = _read()
    for forbidden in ("pip install", "npm install", "Remove-Item", "Stop-Process", "taskkill", "Password", "token"):
        assert forbidden not in text, f"启动脚本不得包含 {forbidden!r}"
    assert "Start-Process" not in text, "Uvicorn 必须前台运行，不得 Start-Process"


def test_launcher_required_shape():
    text = _read()
    assert "var/demo_v041" in text
    assert "geomodeling demo-check --json" in text
    assert "--workers 1" in text
    assert "geomodeling.api.app:app" in text
    assert "-NoBrowser" in text
    assert "-CheckOnly" in text
    assert "GEOMODELING_DATA_DIR" in text


def test_launcher_check_only_leaves_no_listener(tmp_path):
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    env = {"GEOMODELING_FRONTEND_DIST": str(dist), **__import__("os").environ}
    result = subprocess.run(
        [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
         "-CheckOnly", "-NoBrowser", "-Port", "58995",
         "-DataDir", str(tmp_path / "data")],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert result.returncode in (0, 1), result.stderr[:400]
    assert "demo" in result.stdout.lower() or "PASSED" in result.stdout or "BLOCKED" in result.stdout or "WARNING" in result.stdout
    # check-only 不得留下监听进程
    import socket
    sock = socket.socket()
    sock.settimeout(1.0)
    assert sock.connect_ex(("127.0.0.1", 58995)) != 0
    sock.close()
