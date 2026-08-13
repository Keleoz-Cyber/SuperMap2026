"""v0.6.1 Task 15: 版本面、运行手册命令合同与状态文档措辞防护。

锁定三类事实：

1. 全部版本面（pyproject / ``geomodeling.__version__`` / API 分发元数据 /
   web package.json 与 lockfile）一致等于 ``0.6.1``；``web/src/version.ts``
   保持「由 package.json 生成、不二次硬编码」的既有机制。
2. v0.6.1 运行手册包含全部必需精确命令（安装、SDK 安装/预检、启动、显式
   物化与资产 POST、legacy 网格导入、资产状态/哈希检查、聚焦/全量测试、
   隔离运行时 live 32^3/64^3 门、七类诊断、creating→interrupted 恢复与显式
   重试），且不含本机绝对路径、凭据或占位符。
3. 状态文档包含 v0.6.1 关键事实词；不得把 PR #10 描述为 pending，不得把
   ``/volume-demo`` 描述为产品路由。
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

EXPECTED = "0.9.1"

PYPROJECT = Path("pyproject.toml")
PKG_INIT = Path("src/geomodeling/__init__.py")
WEB_PKG = Path("web/package.json")
WEB_LOCK = Path("web/package-lock.json")
WEB_VERSION_TS = Path("web/src/version.ts")
STATUS_DOC = Path("docs/status/current-status.md")
ARCH_DOC = Path("docs/architecture.md")
ACCEPTANCE_DOC = Path("docs/acceptance.md")
SUPERMAP_DOC = Path("docs/supermap-integration.md")
RUNBOOK = Path("docs/v0.6.1-netcdf-native-rendering-runbook.md")

STATUS_REQUIRED_TERMS = (
    "VoxelGridLayer3D",
    "NetCDF classic/v3",
    "display_anchor_only",
    "auxiliary points",
    "no silent fallback",
    "32^3",
    "64^3",
)

RUNBOOK_REQUIRED_COMMANDS = (
    # 1. Python/npm 安装
    'python -m pip install -e ".[api,test]"',
    "npm --prefix web ci",
    # 2. SuperMap3D SDK 安装与预检
    "scripts/install_supermap3d.py",
    "--expected-sha256",
    "--verify-only",
    "web/public/SuperMap3D-2026",
    # 3. 启动 FastAPI 与 Vite
    "python -m uvicorn geomodeling.api.app:app",
    "npm --prefix web run dev",
    # 4. 显式物化与渲染资产 POST
    "/materialize",
    "/render-assets/netcdf",
    # 5. legacy 权威规则网格导入
    "python -m geomodeling.render_cli import-csv",
    # 6. 资产状态与哈希检查
    "/manifest",
    "/volume.nc",
    # 7. 聚焦/全量后端与前端测试
    'python -m pytest -q -m "not local_data"',
    "npm --prefix web run test:unit",
    "npm --prefix web run type-check",
    "npm --prefix web run build",
    "npm --prefix web run test:e2e",
    # 8. 隔离运行时 live 32^3/64^3 门
    "test:e2e:live",
    "e2e-live/supermap-native-volume-live.spec.ts",
    "GEOMODELING_DATA_DIR",
    # 10. creating -> interrupted 恢复与显式重试
    "interrupted",
    "retry_failed",
)

RUNBOOK_DIAGNOSIS_CATEGORIES = (
    "source_contract",
    "netcdf_export",
    "asset_identity",
    "sdk_runtime",
    "camera_or_bounds",
    "browser_or_gpu",
    "message_protocol",
)

# 读者面文本不得出现的本机绝对路径/凭据/占位符模式
_FORBIDDEN_DOC_PATTERNS = (
    re.compile(r"[A-Za-z]:\\\\"),
    re.compile(r"[A-Za-z]:/(Users|study|supermap)"),
    re.compile(r"\bTBD\b|\bTODO\b|占位|fill in", re.IGNORECASE),
)


def _read(path: Path) -> str:
    assert path.exists(), f"{path} 不存在"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------- 版本面


def test_pyproject_version_is_061():
    doc = tomllib.loads(_read(PYPROJECT))
    assert doc["project"]["version"] == EXPECTED


def test_package_init_version_is_061():
    from geomodeling import __version__

    assert __version__ == EXPECTED


def test_web_package_and_lockfile_versions_are_061():
    pkg = json.loads(_read(WEB_PKG))
    assert pkg["version"] == EXPECTED
    lock = json.loads(_read(WEB_LOCK))
    assert lock["version"] == EXPECTED
    assert lock["packages"][""]["version"] == EXPECTED


def test_web_version_source_stays_generated():
    text = _read(WEB_VERSION_TS)
    assert "package.json" in text, "web 运行时版本必须来自 package.json"
    assert EXPECTED not in text, "web/src/version.ts 不得硬编码版本号"


# ---------------------------------------------------------- 运行手册


def test_runbook_exists_with_all_required_commands():
    text = _read(RUNBOOK)
    missing = [cmd for cmd in RUNBOOK_REQUIRED_COMMANDS if cmd not in text]
    assert not missing, "运行手册缺少必需命令/事实: " + "; ".join(missing)


def test_runbook_covers_all_diagnosis_categories():
    text = _read(RUNBOOK)
    missing = [cat for cat in RUNBOOK_DIAGNOSIS_CATEGORIES if cat not in text]
    assert not missing, "运行手册缺少诊断类别: " + "; ".join(missing)


def test_runbook_has_no_absolute_paths_credentials_or_placeholders():
    text = _read(RUNBOOK)
    offenders = [
        pattern.pattern
        for pattern in _FORBIDDEN_DOC_PATTERNS
        if pattern.search(text)
    ]
    assert not offenders, "运行手册含绝对路径/占位符模式: " + "; ".join(offenders)


# ---------------------------------------------------------- 状态文档


def test_status_doc_contains_v061_required_terms():
    text = _read(STATUS_DOC)
    assert "v0.6.1" in text, "状态文档缺少 v0.6.1 条目"
    missing = [term for term in STATUS_REQUIRED_TERMS if term not in text]
    assert not missing, "状态文档缺少 v0.6.1 事实词: " + "; ".join(missing)


def test_status_doc_does_not_describe_pr10_as_pending():
    text = _read(STATUS_DOC)
    assert "PR #10" in text, "状态文档必须记录 PR #10 事实"
    pr10_lines = [line for line in text.splitlines() if "PR #10" in line]
    for line in pr10_lines:
        assert not re.search(r"pending|待合并|未合并|待批准", line), (
            f"状态文档不得把 PR #10 描述为 pending: {line}"
        )
    assert any("已合并" in line for line in pr10_lines), (
        "状态文档必须明确 PR #10 已合并入 main"
    )


def test_status_doc_does_not_describe_volume_demo_as_product_route():
    text = _read(STATUS_DOC)
    demo_lines = [line for line in text.splitlines() if "/volume-demo" in line]
    assert demo_lines, "状态文档必须记录 /volume-demo 的取代关系"
    for line in demo_lines:
        assert any(marker in line for marker in ("取代", "POC", "非产品")), (
            f"/volume-demo 必须被描述为被取代的 POC/非产品路由: {line}"
        )


# ---------------------------------------------------------- 其余文档


def test_architecture_doc_covers_render_layer_boundaries():
    text = _read(ARCH_DOC)
    for term in (
        "render_contracts",
        "render_coordinates",
        "render_assets",
        "netcdf_volume",
        "legacy_render_sources",
        "rendering",
        "render_assets 表",
    ):
        assert term in text, f"architecture.md 缺少渲染层模块边界: {term}"


def test_acceptance_doc_has_v061_commands():
    text = _read(ACCEPTANCE_DOC)
    assert "v0.6.1" in text, "acceptance.md 缺少 v0.6.1 验收节"
    assert "tests/test_v061_docs.py" in text
    assert "test:e2e:live" in text, "live SDK 门必须列入验收命令"


def test_supermap_integration_doc_covers_supermap3d_native_volume():
    text = _read(SUPERMAP_DOC)
    assert "SuperMap3D" in text
    assert "VoxelGridLayer3D" in text
