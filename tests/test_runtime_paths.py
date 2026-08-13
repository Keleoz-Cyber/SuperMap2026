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
