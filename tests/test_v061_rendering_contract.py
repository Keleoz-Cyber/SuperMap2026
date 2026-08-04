"""v0.6.1 NetCDF 原生体渲染回归防护契约（Task 13）。

v0.6.1 起，浏览器内三维渲染收敛为「SuperMap3D iframe 原生体渲染」：
旧的 index.html 全局 Cesium 脚本、Field3D/RhoScene3D 组件与自定义
体渲染演示（/volume-demo 系 main 分支 PR #10 内容，集成分支由 Task 16
删除）一律退出产品代码。本契约扫描 Git 跟踪的产品文件，防止旧渲染
路径复活。

口径说明：

- 禁用路径按 ``git ls-files`` 精确判定（含目录前缀）。
- 禁用术语只扫描产品源码（web/src、web/index.html、web/package.json）。
  web/e2e/supermap-native-volume.spec.ts 以 ``a[href*="volume-demo"]``
  做「无此入口」的行为级反向断言，属于防护本身而非产品代码，故不纳入
  字面量扫描。
- 后端 src/geomodeling/publishing/schemas.py 的 FALLBACK_POINTS 是 v0.3
  发布证据链的拒绝判据（伪造点云证据一律判负），不是渲染路径，不在
  禁用语义内。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 旧自定义体渲染演示（main 分支 PR #10）与旧 Cesium 组件：不得被 Git 跟踪
FORBIDDEN_PATHS = {
    "web/src/views/VolumeDemoView.vue",
    "web/src/components/volume",
    "web/e2e/volume-demo.spec.ts",
    "web/src/components/results/Field3D.vue",
    "web/src/components/RhoScene3D.vue",
}

# 旧自定义渲染器词汇：不得出现在前端产品源码
FORBIDDEN_PRODUCT_TERMS = (
    "/volume-demo",
    "VolumeRenderer",
    "volumeShaders",
    "fallback_points",
)

TERM_SCAN_PREFIXES = ("web/src/",)
TERM_SCAN_FILES = ("web/index.html", "web/package.json")

VOLUME_IFRAME = PROJECT_ROOT / "web" / "public" / "supermap-volume-frame" / "index.html"


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def test_forbidden_paths_absent_from_tracked_files():
    tracked = _tracked_files()
    offenders = [
        path
        for path in tracked
        if any(
            path == forbidden or path.startswith(forbidden + "/")
            for forbidden in FORBIDDEN_PATHS
        )
    ]
    assert not offenders, "禁用渲染路径仍被 Git 跟踪: " + ", ".join(offenders)


def test_forbidden_terms_absent_from_product_source():
    tracked = _tracked_files()
    scanned = [
        rel
        for rel in tracked
        if rel.startswith(TERM_SCAN_PREFIXES) or rel in TERM_SCAN_FILES
    ]
    assert scanned, "术语扫描未覆盖任何产品源码文件"
    hits: list[str] = []
    for rel in scanned:
        try:
            text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for term in FORBIDDEN_PRODUCT_TERMS:
            if term in text:
                hits.append(f"{rel}: {term}")
    assert not hits, "禁用渲染术语仍出现在产品源码: " + "; ".join(hits)


def test_index_html_loads_no_legacy_browser_globals():
    html = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "./Cesium/Cesium.js" not in html, "index.html 仍加载旧全局 Cesium.js"
    assert "./Cesium/Widgets/widgets.css" not in html, "index.html 仍加载旧 Cesium 样式"
    assert "SuperMap3D.js" not in html, "SuperMap3D 只允许由体渲染 iframe 加载"


def test_supermap3d_loaded_by_volume_iframe():
    text = VOLUME_IFRAME.read_text(encoding="utf-8")
    assert "SuperMap3D.js" in text, "体渲染 iframe 未加载 SuperMap3D.js"


def test_package_json_has_no_three_or_cesium_dependency():
    pkg = json.loads((PROJECT_ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    for section in ("dependencies", "devDependencies"):
        names = {name.lower() for name in pkg.get(section, {})}
        banned = sorted(
            name
            for name in names
            if name == "three" or name.startswith("three/") or "cesium" in name
        )
        assert not banned, f"web/package.json {section} 含 three/cesium 依赖: {banned}"
