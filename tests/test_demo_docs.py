"""文档体系（单一事实归属 + 测试治理）的内容、链接与历史文档清理合同。

规范依据：docs/README.md（文档中心）；决策依据：docs/decisions/0005-documentation-system.md。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
DOCS = ROOT / "docs"
DOC_INDEX = DOCS / "README.md"
PRODUCT_GUIDE = DOCS / "product-guide.md"
ARCHITECTURE = DOCS / "architecture.md"
API_REFERENCE = DOCS / "api-reference.md"
OPERATIONS = DOCS / "operations.md"
CONTEST = DOCS / "contest.md"
CHANGELOG = ROOT / "CHANGELOG.md"


def _read(path: Path) -> str:
    assert path.exists(), f"{path} 不存在"
    return path.read_text(encoding="utf-8")


def _core_docs() -> list[Path]:
    return [
        README,
        CHANGELOG,
        DOC_INDEX,
        PRODUCT_GUIDE,
        ARCHITECTURE,
        API_REFERENCE,
        OPERATIONS,
        CONTEST,
    ]


def test_readme_points_to_documentation_index():
    text = _read(README)
    assert "docs/README.md" in text
    for name in (
        "product-guide.md",
        "architecture.md",
        "api-reference.md",
        "operations.md",
        "contest.md",
        "CHANGELOG.md",
        "evidence/",
    ):
        assert name in text, f"README 文档索引缺少 {name}"
    assert "1.0.0" in text


def test_doc_index_defines_standard_and_evidence_index():
    text = _read(DOC_INDEX)
    for token in (
        "单一事实归属",
        "文档受测试治理",
        "目录即合同",
        "过程与权威分离",
        "保留证据",
        "decisions/",
        "superpowers/",
        "evidence/",
    ):
        assert token in text, f"文档中心缺少 {token}"


def test_product_guide_covers_positioning_and_builtin_cases():
    text = _read(PRODUCT_GUIDE)
    for token in (
        "项目定位",
        "功能全景",
        "瓦斯含量_合格样品.csv",
        "地下电阻率节点_标准化.csv",
        "微震局部三维点_3Sigma_去重均值_1911.csv",
        "DEEPSEEK_API_KEY",
    ):
        assert token in text, f"产品指南缺少 {token}"


def test_product_guide_covers_microseismic_derivation_contract():
    text = _read(PRODUCT_GUIDE)
    for token in (
        "2,006",
        "2,005",
        "1,925",
        "1,911",
        "ddof=1",
        "算术平均",
        "1.#QNAN0",
    ):
        assert token in text, f"产品指南缺少微震合同 {token}"


def test_architecture_covers_layers_lifecycle_and_algorithms():
    text = _read(ARCHITECTURE)
    for token in (
        "技术架构",
        "模块边界",
        "数据生命周期",
        "建模算法",
        "空间验证",
        "VoxelGridLayer3D",
        "术语表",
        "decisions/",
    ):
        assert token in text, f"技术架构缺少 {token}"


def test_api_reference_covers_http_and_cli():
    text = _read(API_REFERENCE)
    for token in (
        "/api/health",
        "/api/results/{result_id}/materialize",
        "/api/render-assets/{asset_id}/volume.nc",
        "microseismic derive",
        "microseismic import-case",
        "GEOMODELING_DATA_DIR",
        "DEEPSEEK_API_KEY",
    ):
        assert token in text, f"API 参考缺少 {token}"


def test_operations_covers_runtime_packaging_and_ci():
    text = _read(OPERATIONS)
    for token in (
        "Windows 免安装包",
        "测试、CI 与验收",
        "build_portable.py",
        "install_supermap3d.py",
        "demo-check",
        "故障排查",
    ):
        assert token in text, f"运维手册缺少 {token}"


def test_contest_covers_defense_and_submission():
    text = _read(CONTEST)
    for token in (
        "答辩演示路线",
        "比赛提交",
        "已知边界",
        "前一天",
        "开机后",
        "上台前",
        "路线 A",
        "路线 B",
        "iServer 离线",
        "manual_required",
    ):
        assert token in text, f"比赛交付缺少 {token}"


def test_changelog_covers_version_history():
    text = _read(CHANGELOG)
    for token in (
        "v0.1.0",
        "v0.6.1",
        "v0.9.0",
        "v0.9.1",
        "v1.0.0",
        "未单独打 tag",
    ):
        assert token in text, f"更新日志缺少 {token}"


def test_core_docs_have_no_machine_paths_or_credentials():
    for path in _core_docs():
        text = _read(path)
        assert not re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", text), f"{path.name} 含本机路径"
        assert "ADMIN_PASSWORD" not in text
        assert "PRIVATE KEY" not in text


def test_superseded_project_docs_are_removed():
    old_paths = (
        "docs/acceptance.md",
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
        "docs/project-guide.md",
        "docs/项目特色与技术全景.md",
    )
    assert not [path for path in old_paths if (ROOT / path).exists()]


_MD_LINK_RE = re.compile(r"(?<!\!)\[([^\]]+)\]\(([^)]+)\)")
_SKIP_PREFIXES = ("http://", "https://", "mailto:", "#")


def test_all_tracked_markdown_relative_links_resolve():
    failures: list[str] = []
    markdown_files = [
        ROOT / "README.md",
        ROOT / "CHANGELOG.md",
        *sorted((ROOT / "docs").rglob("*.md")),
    ]
    for md in markdown_files:
        for _label, target in _MD_LINK_RE.findall(_read(md)):
            target = target.split("#")[0].strip()
            if not target or target.startswith(_SKIP_PREFIXES) or target.startswith("/"):
                continue
            if not (md.parent / target).resolve().exists():
                failures.append(f"{md.relative_to(ROOT)}: {target}")
    assert not failures, "\n".join(failures)
