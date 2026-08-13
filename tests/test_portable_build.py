from __future__ import annotations

import os
import tomllib
from pathlib import Path

from scripts import build_portable


def test_windows_batch_entrypoint_is_resolved_for_subprocess() -> None:
    resolved = build_portable.resolve_command(["npm", "--version"])
    expected = "npm.cmd" if os.name == "nt" else "npm"
    assert resolved[0] == expected
    assert resolved[1:] == ["--version"]


def test_package_extra_pins_setuptools_before_pkg_resources_removal() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    requirements = project["optional-dependencies"]["package"]
    assert "setuptools>=70,<81" in requirements


def test_pyinstaller_command_avoids_collect_all_from_global_environment(tmp_path) -> None:
    command = build_portable.pyinstaller_command(tmp_path, tmp_path, tmp_path)
    joined = " ".join(command)
    assert "--collect-all" not in joined
    assert "--collect-submodules geomodeling" not in joined
    assert "--hidden-import geomodeling.api.app" in joined
    assert "--collect-submodules uvicorn" in joined


def test_isolated_builder_uses_build_directory_virtualenv() -> None:
    python = build_portable.isolated_python_path()
    assert python == build_portable.BUILD_ROOT / "venv" / "Scripts" / "python.exe"
