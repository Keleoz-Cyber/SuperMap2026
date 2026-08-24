"""版本一致性与 NetCDF/SuperMap 渲染、SDK 预检与恢复的文档合同。

渲染合同记载于 docs/architecture.md；SDK 预检与中断恢复记载于 docs/operations.md。
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

EXPECTED = "1.0.1"
ARCHITECTURE = Path("docs/architecture.md")
OPERATIONS = Path("docs/operations.md")


def test_all_version_surfaces_are_current():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads(Path("web/package.json").read_text(encoding="utf-8"))
    lock = json.loads(Path("web/package-lock.json").read_text(encoding="utf-8"))
    assert project["project"]["version"] == EXPECTED
    assert package["version"] == EXPECTED
    assert lock["version"] == EXPECTED
    assert lock["packages"][""]["version"] == EXPECTED


def test_python_and_web_runtime_version_sources_are_current():
    from geomodeling import __version__

    assert __version__ == EXPECTED
    web_version = Path("web/src/version.ts").read_text(encoding="utf-8")
    assert "package.json" in web_version
    assert EXPECTED not in web_version


def test_architecture_covers_render_asset_and_supermap_boundaries():
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for token in (
        "NetCDF classic/v3",
        "VoxelGridLayer3D",
        "display_anchor_only",
        "auxiliary points",
        "no silent fallback",
        "32^3/64^3",
        "render_contracts",
        "render_coordinates",
        "render_assets",
        "netcdf_volume",
        "legacy_render_sources",
        "rendering",
    ):
        assert token in text, f"技术架构缺少渲染合同 {token}"


def test_operations_covers_sdk_preflight_and_recovery():
    text = OPERATIONS.read_text(encoding="utf-8")
    for token in (
        "scripts/install_supermap3d.py",
        "--expected-sha256",
        "--verify-only",
        "source_contract",
        "netcdf_export",
        "asset_identity",
        "sdk_runtime",
        "camera_or_bounds",
        "browser_or_gpu",
        "message_protocol",
        "interrupted",
        "retry_failed",
    ):
        assert token in text, f"运维手册缺少预检/恢复合同 {token}"
