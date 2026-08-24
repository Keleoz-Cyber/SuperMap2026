from __future__ import annotations

import os
import tomllib
import zipfile
from pathlib import Path

import pytest

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


def test_portable_guide_uses_in_product_ai_settings_as_primary_path() -> None:
    source = Path("scripts/build_portable.py").read_text(encoding="utf-8")
    assert "AI 设置" in source
    assert "Windows 用户的凭据管理器" in source
    assert "不要将团队 API Key" in source
    assert "DEEPSEEK_API_KEY" in source
    assert "sk-" not in source


def test_create_zip_rejects_initialized_runtime_even_when_manifested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "release"
    output = dist / "GeoModelingPlatform-1.0.0-win-x64"
    runtime = output / "runtime"
    runtime.mkdir(parents=True)
    (output / "GeoModelingPlatform.exe").write_bytes(b"exe")
    (runtime / ".initialized").write_text("initialized\n", encoding="utf-8")
    monkeypatch.setattr(build_portable, "DIST_ROOT", dist)
    build_portable.write_manifest(output)

    with pytest.raises(RuntimeError, match="runtime"):
        build_portable.create_zip(output)


def test_create_zip_rejects_files_added_after_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "release"
    output = dist / "GeoModelingPlatform-1.0.0-win-x64"
    output.mkdir(parents=True)
    (output / "GeoModelingPlatform.exe").write_bytes(b"exe")
    monkeypatch.setattr(build_portable, "DIST_ROOT", dist)
    build_portable.write_manifest(output)
    (output / "server.log").write_text("late mutation", encoding="utf-8")

    with pytest.raises(RuntimeError, match="清单外文件"):
        build_portable.create_zip(output)


def test_create_zip_rejects_file_mutated_after_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "release"
    output = dist / "GeoModelingPlatform-1.0.0-win-x64"
    output.mkdir(parents=True)
    executable = output / "GeoModelingPlatform.exe"
    executable.write_bytes(b"clean")
    monkeypatch.setattr(build_portable, "DIST_ROOT", dist)
    build_portable.write_manifest(output)
    executable.write_bytes(b"mutated")

    with pytest.raises(RuntimeError, match="清单校验失败"):
        build_portable.create_zip(output)


def test_create_zip_accepts_clean_manifested_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "release"
    output = dist / "GeoModelingPlatform-1.0.0-win-x64"
    output.mkdir(parents=True)
    (output / "GeoModelingPlatform.exe").write_bytes(b"clean")
    monkeypatch.setattr(build_portable, "DIST_ROOT", dist)
    build_portable.write_manifest(output)

    archive = build_portable.create_zip(output)

    assert archive.is_file()
    assert archive.with_suffix(archive.suffix + ".sha256").is_file()
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
    assert f"{output.name}/GeoModelingPlatform.exe" in names
    assert f"{output.name}/portable-manifest.json" in names
