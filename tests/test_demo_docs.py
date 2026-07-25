"""Task 8/9: demo runbook content contract and stale-state guards."""

from __future__ import annotations

import re
from pathlib import Path

RUNBOOK = Path("docs/v0.4.1-demo-runbook.md")


def _runbook() -> str:
    assert RUNBOOK.exists(), "docs/v0.4.1-demo-runbook.md 不存在"
    return RUNBOOK.read_text(encoding="utf-8")


def test_runbook_has_three_level_checklist():
    text = _runbook()
    for phrase in ("前一天", "开机后", "上台前"):
        assert phrase in text, f"运行手册缺少 {phrase} 检查清单"


def test_runbook_references_launcher_and_preflight():
    text = _runbook()
    assert "scripts/start_demo.ps1" in text
    assert "geomodeling demo-check" in text


def test_runbook_covers_dual_routes_and_slices():
    text = _runbook()
    assert "路线 A" in text and "路线 B" in text
    assert "X/Y/Z" in text or "Z/X/Y" in text
    assert "电阻率" in text


def test_runbook_iserver_online_offline_and_evidence_distinction():
    text = _runbook()
    assert "iServer 在线" in text and "iServer 离线" in text
    assert "实时" in text and "备用" in text


def test_runbook_recovery_table_scenarios():
    text = _runbook()
    for phrase in ("端口", "任务", "刷新", "CSV"):
        assert phrase in text, f"故障恢复缺少 {phrase} 场景"


def test_runbook_forbidden_claims_section():
    text = _runbook()
    assert "多源融合" in text
    assert "未知" in text and "CRS" in text
    assert "瓦斯" in text
    assert "微震" in text


def test_runbook_has_no_drive_letter_paths_or_credential_literals():
    text = _runbook()
    assert not re.search(r"[A-Za-z]:\\\\", text), "运行手册不得含盘符路径"
    assert "ADMIN_PASSWORD" not in text
    assert "BEGIN" not in text or "PRIVATE KEY" not in text


# ---------------------------------------------------------- Task 9: stale-state guards
STATUS_DOC = Path("docs/status/current-status.md")
BLUEPRINT = Path("docs/product-blueprint.md")


def test_status_has_no_stale_current_claims():
    text = STATUS_DOC.read_text(encoding="utf-8")
    assert "feat/v0.4-generic-platform` 分支，开发中" not in text
    assert "feat/v0.4-generic-platform` 分支，v0.4.0 候选" not in text
    assert "0.4.0-dev" not in text
    for stale in ("仍无通用上传", "插值执行、调参任务", "通用上传、插值执行、调参任务、微震三维接入"):
        assert stale not in text, f"状态文档仍把 v0.4 能力描述为未实现：{stale}"


def test_status_records_v040_release_facts():
    text = STATUS_DOC.read_text(encoding="utf-8")
    assert "b95f12b" in text
    assert "已发布" in text


def test_blueprint_separates_current_from_future():
    text = BLUEPRINT.read_text(encoding="utf-8")
    assert "已实现" in text
    assert "未来" in text


_MD_LINK_RE = re.compile(r"(?<!\!)\[([^\]]+)\]\(([^)]+)\)")
_SKIP_PREFIXES = ("http://", "https://", "mailto:", "#")


def _markdown_files() -> list[Path]:
    roots = [Path("README.md"), Path("docs/v0.4.1-demo-runbook.md"), STATUS_DOC, BLUEPRINT,
             Path("docs/v0.4-generic-modeling-loop.md"), Path("docs/acceptance.md")]
    return [p for p in roots if p.exists()]


def test_internal_markdown_links_resolve():
    failures: list[str] = []
    for md in _markdown_files():
        for _label, target in _MD_LINK_RE.findall(md.read_text(encoding="utf-8")):
            target = target.split("#")[0].strip()
            if not target or target.startswith(_SKIP_PREFIXES):
                continue
            if target.startswith("/"):
                continue  # 运行时 API 链接，不是文件链接
            resolved = (md.parent / target).resolve()
            if not resolved.exists():
                failures.append(f"{md}: 无法解析的链接 {target}")
    assert not failures, "\n".join(failures)
