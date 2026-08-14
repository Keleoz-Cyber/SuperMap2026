"""统一项目说明的内容、链接与历史文档清理合同。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
GUIDE = ROOT / "docs" / "project-guide.md"


def _read(path: Path) -> str:
    assert path.exists(), f"{path} 不存在"
    return path.read_text(encoding="utf-8")


def test_readme_points_to_single_canonical_guide():
    text = _read(README)
    assert "docs/project-guide.md" in text
    assert "唯一权威" in text
    assert "0.9.3" in text


def test_guide_covers_product_architecture_runtime_and_submission():
    text = _read(GUIDE)
    for token in (
        "项目定位",
        "技术架构",
        "数据生命周期",
        "算法、参数和验证",
        "三维渲染、切片与 SuperMap",
        "Windows 免安装包",
        "测试、CI 与验收",
        "答辩演示路线",
        "比赛提交",
        "已知边界",
        "保留证据",
    ):
        assert token in text, f"统一说明缺少 {token}"


def test_guide_covers_demo_and_microseismic_contracts():
    text = _read(GUIDE)
    for token in (
        "前一天",
        "开机后",
        "上台前",
        "路线 A",
        "路线 B",
        "iServer 离线",
        "microseismic derive",
        "microseismic import-case",
        "2,006",
        "2,005",
        "1,925",
        "1,911",
        "ddof=1",
        "算术平均",
    ):
        assert token in text, f"统一说明缺少 {token}"


def test_guide_has_no_machine_paths_or_credentials():
    text = _read(GUIDE)
    assert not re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", text)
    assert "ADMIN_PASSWORD" not in text
    assert "PRIVATE KEY" not in text


def test_superseded_project_docs_are_removed():
    old_paths = (
        "docs/acceptance.md",
        "docs/architecture.md",
        "docs/contest-submission.md",
        "docs/data/contracts.md",
        "docs/data/gas.md",
        "docs/data/microseismic.md",
        "docs/data/resistivity.md",
        "docs/portable-delivery.md",
        "docs/product-blueprint.md",
        "docs/status/current-status.md",
        "docs/supermap-integration.md",
        "docs/v0.3-iserver-loop.md",
        "docs/v0.4-generic-modeling-loop.md",
        "docs/v0.4.1-demo-runbook.md",
        "docs/v0.5-microseismic-loop.md",
        "docs/v0.6-professional-modeling-loop.md",
        "docs/v0.6.1-netcdf-native-rendering-runbook.md",
    )
    assert not [path for path in old_paths if (ROOT / path).exists()]


_MD_LINK_RE = re.compile(r"(?<!\!)\[([^\]]+)\]\(([^)]+)\)")
_SKIP_PREFIXES = ("http://", "https://", "mailto:", "#")


def test_all_tracked_markdown_relative_links_resolve():
    failures: list[str] = []
    for md in (ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))):
        for _label, target in _MD_LINK_RE.findall(_read(md)):
            target = target.split("#")[0].strip()
            if not target or target.startswith(_SKIP_PREFIXES) or target.startswith("/"):
                continue
            if not (md.parent / target).resolve().exists():
                failures.append(f"{md.relative_to(ROOT)}: {target}")
    assert not failures, "\n".join(failures)
