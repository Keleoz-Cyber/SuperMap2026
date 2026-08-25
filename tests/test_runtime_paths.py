from __future__ import annotations

from pathlib import Path

from geomodeling import runtime_paths


def test_resource_root_prefers_explicit_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(runtime_paths.ENV_RESOURCE_ROOT, str(tmp_path))
    assert runtime_paths.resource_root() == tmp_path.resolve()


def test_resource_path_uses_resolved_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(runtime_paths.ENV_RESOURCE_ROOT, str(tmp_path))
    assert runtime_paths.resource_path("config", "default.yaml") == (
        tmp_path / "config" / "default.yaml"
    )


def test_frozen_macos_app_uses_writable_outer_package_root(
    monkeypatch, tmp_path: Path
) -> None:
    executable = (
        tmp_path
        / "GeoModelingPlatform.app"
        / "Contents"
        / "MacOS"
        / "GeoModelingPlatform"
    )
    monkeypatch.setattr(runtime_paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_paths.sys, "executable", str(executable))

    assert runtime_paths.executable_root() == tmp_path.resolve()
