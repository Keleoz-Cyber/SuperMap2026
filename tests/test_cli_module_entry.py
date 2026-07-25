"""Merge-blocker: module entry point must come after all command definitions."""

from __future__ import annotations

import subprocess
import sys


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "geomodeling.cli", *args],
        capture_output=True,
        text=False,
        timeout=60,
    )


def test_module_help_lists_demo_check():
    result = _run("--help")
    stdout = result.stdout.decode("utf-8", errors="replace")
    assert result.returncode == 0, stdout
    assert "demo-check" in stdout


def test_module_demo_check_help_works():
    result = _run("demo-check", "--help")
    stdout = result.stdout.decode("utf-8", errors="replace")
    assert result.returncode == 0, stdout
    assert "--json" in stdout
    assert "--port" in stdout
