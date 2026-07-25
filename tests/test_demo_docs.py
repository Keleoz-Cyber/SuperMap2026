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
