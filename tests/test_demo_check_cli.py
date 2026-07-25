"""Task 5: demo-check CLI contract (portable, no local data needed)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from geomodeling.cli import app

runner = CliRunner()

# ---------------------------------------------------------- demo-check
def _frontend(tmp_path):
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    return dist


def test_demo_check_json_contract(tmp_path):
    result = runner.invoke(app, [
        "demo-check", "--json",
        "--port", "58998",
        "--data-dir", str(tmp_path / "data"),
        "--frontend-dist", str(_frontend(tmp_path)),
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert set(payload) == {"status", "exit_code", "reuse_existing", "checks"}
    assert payload["status"] in ("passed", "warning")
    assert payload["exit_code"] == 0
    assert isinstance(payload["checks"], list) and payload["checks"]
    assert ":\\" not in result.output


def test_demo_check_human_output_levels(tmp_path):
    result = runner.invoke(app, [
        "demo-check",
        "--port", "58997",
        "--data-dir", str(tmp_path / "data"),
        "--frontend-dist", str(_frontend(tmp_path)),
    ])
    assert result.exit_code == 0
    assert "[PASSED]" in result.output
    # iServer 离线环境下可选项为警告
    if "[WARNING]" in result.output:
        assert result.exit_code == 0


def test_demo_check_blocker_exits_one_with_full_json(tmp_path):
    result = runner.invoke(app, [
        "demo-check", "--json",
        "--port", "58996",
        "--data-dir", str(tmp_path / "data"),
        "--frontend-dist", str(tmp_path / "no-dist"),
    ])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "blocked"
    assert payload["exit_code"] == 1
    blocked = [c for c in payload["checks"] if c["status"] == "blocked"]
    assert any(c["id"] == "frontend_build" for c in blocked)
    assert ":\\" not in result.output
