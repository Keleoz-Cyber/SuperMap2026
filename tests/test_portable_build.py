from __future__ import annotations

import json
import os
import plistlib
import tomllib
import zipfile
from pathlib import Path

import pytest

from scripts import build_portable


MACOS_WORKFLOW = Path(".github/workflows/build-macos-portable.yml")


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


def test_macos_arm64_target_uses_posix_runtime_and_launchers() -> None:
    target = build_portable.detect_build_target(system="Darwin", machine="arm64")

    assert target.tag == "macos-arm64"
    assert target.executable_name == "GeoModelingPlatform"
    assert target.app_bundle_name == "GeoModelingPlatform.app"
    assert target.executable_relative == Path(
        "GeoModelingPlatform.app/Contents/MacOS/GeoModelingPlatform"
    )
    assert target.start_label == "GeoModelingPlatform.app"
    assert target.python_relative == Path("venv/bin/python")
    assert target.launchers == ("启动平台.command", "停止平台.command")
    assert build_portable.isolated_python_path(target) == (
        build_portable.BUILD_ROOT / "venv" / "bin" / "python"
    )


@pytest.mark.parametrize(
    ("system", "machine"),
    [("Darwin", "x86_64"), ("Linux", "x86_64"), ("Windows", "ARM64")],
)
def test_unsupported_portable_build_target_is_rejected(system: str, machine: str) -> None:
    with pytest.raises(RuntimeError, match="不支持的便携包构建平台"):
        build_portable.detect_build_target(system=system, machine=machine)


def test_macos_pyinstaller_command_collects_keychain_backend(tmp_path: Path) -> None:
    target = build_portable.detect_build_target(system="Darwin", machine="arm64")

    command = build_portable.pyinstaller_command(tmp_path, tmp_path, tmp_path, target)

    joined = " ".join(command)
    assert "--hidden-import keyring.backends.macOS" in joined
    assert "--copy-metadata keyring" in joined


def test_macos_launchers_are_present_and_use_local_executable() -> None:
    portable = Path("portable")

    start = (portable / "启动平台.command").read_text(encoding="utf-8")
    stop = (portable / "停止平台.command").read_text(encoding="utf-8")

    assert './GeoModelingPlatform.app/Contents/MacOS/GeoModelingPlatform start' in start
    assert './GeoModelingPlatform.app/Contents/MacOS/GeoModelingPlatform stop' in stop


def test_macos_app_bundle_wraps_pyinstaller_onedir_output(tmp_path: Path) -> None:
    target = build_portable.detect_build_target(system="Darwin", machine="arm64")
    pyinstaller_output = tmp_path / "GeoModelingPlatform"
    pyinstaller_output.mkdir()
    (pyinstaller_output / "GeoModelingPlatform").write_bytes(b"mach-o")
    (pyinstaller_output / "_internal").mkdir()
    (pyinstaller_output / "_internal" / "resource.bin").write_bytes(b"resource")
    output = tmp_path / "GeoModelingPlatform-1.0.1-macos-arm64"

    app = build_portable.wrap_macos_app(pyinstaller_output, output, target)

    assert app == output / "GeoModelingPlatform.app"
    assert (app / "Contents/MacOS/GeoModelingPlatform").read_bytes() == b"mach-o"
    assert (app / "Contents/MacOS/_internal/resource.bin").read_bytes() == b"resource"
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    assert info["CFBundleExecutable"] == "GeoModelingPlatform"
    assert info["CFBundleIdentifier"] == "com.keleoz.geomodelingplatform"
    assert info["CFBundleShortVersionString"] == "1.0.1"
    assert info["LSUIElement"] is True


def test_macos_app_is_ad_hoc_signed_before_manifest() -> None:
    target = build_portable.detect_build_target(system="Darwin", machine="arm64")
    app = Path("release/GeoModelingPlatform.app")

    assert build_portable.macos_sign_commands(app, target) == [
        ["codesign", "--force", "--deep", "--sign", "-", str(app)],
        ["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)],
    ]


def test_macos_delivery_uses_command_launchers_and_keychain_guide(tmp_path: Path) -> None:
    target = build_portable.detect_build_target(system="Darwin", machine="arm64")
    output = tmp_path / f"GeoModelingPlatform-1.0.0-{target.tag}"
    output.mkdir()

    build_portable.add_delivery_files(output, {"resistivity": "result-1"}, target)

    assert (output / "启动平台.command").is_file()
    assert (output / "停止平台.command").is_file()
    assert not (output / "启动平台.cmd").exists()
    guide = (output / "使用说明.txt").read_text(encoding="utf-8-sig")
    assert "macOS 用户的钥匙串" in guide
    assert "GeoModelingPlatform doctor" in guide
    assert ".exe" not in guide


def test_macos_archive_command_preserves_finder_metadata(tmp_path: Path) -> None:
    output = tmp_path / "GeoModelingPlatform-1.0.0-macos-arm64"
    archive = tmp_path / f"{output.name}.zip"

    assert build_portable.macos_archive_command(output, archive) == [
        "ditto",
        "-c",
        "-k",
        "--sequesterRsrc",
        "--keepParent",
        str(output),
        str(archive),
    ]


def test_macos_manifest_records_native_platform(tmp_path: Path) -> None:
    target = build_portable.detect_build_target(system="Darwin", machine="arm64")
    output = tmp_path / "GeoModelingPlatform-1.0.0-macos-arm64"
    output.mkdir()
    (output / "GeoModelingPlatform").write_bytes(b"binary")

    manifest = build_portable.write_manifest(output, target)

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["platform"] == "macos-arm64"


def test_macos_portable_workflow_is_manual_native_and_uploads_release_assets() -> None:
    source = MACOS_WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in source
    assert "runs-on: macos-15" in source
    assert "architecture: arm64" in source
    assert "GeoModelingPlatform-1.0.0-win-x64.zip" in source
    assert "zipfile.ZipFile" in source
    assert "scripts/install_supermap3d.py" in source
    assert "python scripts/build_portable.py" in source
    assert "GeoModelingPlatform-1.0.1-macos-arm64.zip" in source
    assert "GeoModelingPlatform.app" in source
    assert "codesign --verify --deep --strict" in source
    assert "actions/upload-artifact@v4" in source


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
