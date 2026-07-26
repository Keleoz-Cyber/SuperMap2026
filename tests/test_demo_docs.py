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
             Path("docs/v0.4-generic-modeling-loop.md"), Path("docs/acceptance.md"),
             Path("docs/v0.5-microseismic-loop.md")]
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


# ---------------------------------------------------------- Task 15: v0.5 microseismic loop docs
V05_RUNBOOK = Path("docs/v0.5-microseismic-loop.md")
MICRO_DATA_DOC = Path("docs/data/microseismic.md")
CONTRACTS_DOC = Path("docs/data/contracts.md")
README_DOC = Path("README.md")


def _v05_runbook() -> str:
    assert V05_RUNBOOK.exists(), "docs/v0.5-microseismic-loop.md 不存在"
    return V05_RUNBOOK.read_text(encoding="utf-8")


def test_v05_runbook_records_expected_counts():
    text = _v05_runbook()
    for token in ("2,006", "2,005", "80", "1,925", "1,911"):
        assert token in text, f"v0.5 运行手册缺少预期计数 {token}"


def test_v05_runbook_distinguishes_local_coords_candidates_and_nodes():
    text = _v05_runbook()
    assert "局部工程坐标" in text, "运行手册必须说明局部工程坐标"
    assert "源记录" in text, "运行手册必须区分源记录层"
    assert "候选" in text and "聚合" in text, "运行手册必须区分 1,925 候选与 1,911 聚合节点"


def test_v05_runbook_covers_browser_and_cli_entries():
    text = _v05_runbook()
    assert "microseismic derive" in text, "运行手册缺少 CLI derive 入口"
    assert "microseismic import-case" in text, "运行手册缺少 CLI import-case 入口"
    assert "导入微震 DAT" in text, "运行手册缺少浏览器 DAT 导入步骤"


def test_v05_runbook_covers_modeling_recovery_export_and_demo():
    text = _v05_runbook()
    for phrase in ("IDW", "克里金", "50 m", "z_scale", "重启", "导出", "演示"):
        assert phrase in text, f"v0.5 运行手册缺少 {phrase} 内容"
    assert "预检" in text, "运行手册缺少预检清单"
    assert "失败" in text or "诊断" in text, "运行手册缺少失败诊断"


def test_v05_runbook_has_no_absolute_paths_or_private_tracking():
    text = _v05_runbook()
    assert not re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", text), "运行手册不得含盘符绝对路径"
    assert "超图杯资料" not in text or "../超图杯资料" in text, "原始资料只允许相对引用"


def test_readme_documents_microseismic_browser_and_cli_entries():
    text = README_DOC.read_text(encoding="utf-8")
    assert "导入微震 DAT" in text or "浏览器" in text, "README 缺少浏览器 DAT 导入入口说明"
    assert "microseismic derive" in text, "README CLI 清单缺少 derive"
    assert "microseismic import-case" in text, "README CLI 清单缺少 import-case"


def test_no_stale_claim_that_browser_cannot_read_dat():
    for doc in (MICRO_DATA_DOC, README_DOC, STATUS_DOC):
        text = doc.read_text(encoding="utf-8")
        assert "不读取 DAT" not in text, f"{doc} 仍声称浏览器不读取 DAT"


def test_no_stale_microseismic_not_implemented_claims():
    micro = MICRO_DATA_DOC.read_text(encoding="utf-8")
    status = STATUS_DOC.read_text(encoding="utf-8")
    assert "仍是v0.2a实现" not in micro, "微震文档 §1 仍停留在 v0.2a 口径"
    assert "仍无微震三维派生表代码化" not in status, "状态文档仍称微震派生未代码化"
    assert "微震局部三维和3σ规则的仓库内可复现实现、微震三维场景接入" not in status


def test_contracts_document_v05_aggregation_and_three_sigma():
    text = CONTRACTS_DOC.read_text(encoding="utf-8")
    assert "1,911" in text, "数据契约缺少 1,911 聚合节点口径"
    assert "算术平均" in text, "数据契约缺少算术平均聚合规则"
    assert "ddof=1" in text, "数据契约缺少 3σ 样本标准差 ddof=1 口径"
