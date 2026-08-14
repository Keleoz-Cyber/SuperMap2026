"""Task 10/15/23: version consistency across Python, API, web package, lockfile and home badge."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

EXPECTED = "0.9.3"


def test_pyproject_version():
    doc = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert doc["project"]["version"] == EXPECTED


def test_api_version_matches_distribution_metadata():
    from geomodeling.api.deps import PROJECT_VERSION

    assert PROJECT_VERSION == EXPECTED


def test_web_package_and_lockfile_versions():
    pkg = json.loads(Path("web/package.json").read_text(encoding="utf-8"))
    assert pkg["version"] == EXPECTED
    lock = json.loads(Path("web/package-lock.json").read_text(encoding="utf-8"))
    assert lock["version"] == EXPECTED
    assert lock["packages"][""]["version"] == EXPECTED


def test_home_badge_uses_shared_web_version_source():
    version_ts = Path("web/src/version.ts").read_text(encoding="utf-8")
    assert "WEB_VERSION" in version_ts
    # v0.9.0 起版本徽标在全局应用头（AppShell/AppHeader），首页不再单独放置
    header = Path("web/src/components/shell/AppHeader.vue").read_text(encoding="utf-8")
    assert "WEB_VERSION" in header
    assert not re.search(r"v0\.4\b[^.]", header), "版本徽标不得硬编码版本号"


def test_mock_health_reports_web_version():
    mock = Path("web/src/mocks/platformDemo.ts").read_text(encoding="utf-8")
    assert "WEB_VERSION" in mock


def test_web_version_source_stays_generated_not_hardcoded():
    version_ts = Path("web/src/version.ts").read_text(encoding="utf-8")
    assert "package.json" in version_ts
    assert EXPECTED not in version_ts, "web 运行时版本必须来自 package.json，不得二次硬编码"
