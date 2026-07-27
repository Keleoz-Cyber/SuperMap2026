"""Task 23: v0.6 documentation contract, banned-claim scan and release-state guards.

禁止表述只允许出现在显式「禁止表述」引述 fixture 区（由
``banned-claims-fixture:start/end`` 标记包裹），不得出现在读者面能力陈述中。
设计来源：docs/superpowers/specs/2026-07-26-v0.6-professional-modeling-enhancements-design.md §21。
"""

from __future__ import annotations

import re
from pathlib import Path

README_DOC = Path("README.md")
STATUS_DOC = Path("docs/status/current-status.md")
ARCH_DOC = Path("docs/architecture.md")
ACCEPTANCE_DOC = Path("docs/acceptance.md")
CONTRACTS_DOC = Path("docs/data/contracts.md")
BLUEPRINT_DOC = Path("docs/product-blueprint.md")
V06_RUNBOOK = Path("docs/v0.6-professional-modeling-loop.md")

SCAN_DOCS = (
    README_DOC,
    STATUS_DOC,
    ARCH_DOC,
    ACCEPTANCE_DOC,
    CONTRACTS_DOC,
    BLUEPRINT_DOC,
    V06_RUNBOOK,
)

BANNED_CLAIMS = (
    "自动发现真实地质主方向",
    "置信区间",
    "预测未来灾害",
    "异常区等于危险区",
    "局部坐标已完成多源融合",
)

FIXTURE_START = "<!-- banned-claims-fixture:start -->"
FIXTURE_END = "<!-- banned-claims-fixture:end -->"


def _read(doc: Path) -> str:
    assert doc.exists(), f"{doc} 不存在"
    return doc.read_text(encoding="utf-8")


def _strip_fixture_zones(text: str, doc: Path) -> tuple[str, str]:
    """拆分读者面文本与 fixture 引述文本；标记必须配对。"""
    assert text.count(FIXTURE_START) == text.count(FIXTURE_END), \
        f"{doc} 禁止表述 fixture 标记不配对"
    reader_parts: list[str] = []
    fixture_parts: list[str] = []
    rest = text
    while FIXTURE_START in rest:
        head, rest = rest.split(FIXTURE_START, 1)
        zone, rest = rest.split(FIXTURE_END, 1)
        reader_parts.append(head)
        fixture_parts.append(zone)
    reader_parts.append(rest)
    return "".join(reader_parts), "".join(fixture_parts)


# ---------------------------------------------------------- 禁止表述扫描


def test_banned_claims_absent_from_reader_facing_docs():
    offenders: list[str] = []
    for doc in SCAN_DOCS:
        reader, _fixture = _strip_fixture_zones(_read(doc), doc)
        for phrase in BANNED_CLAIMS:
            if phrase in reader:
                offenders.append(f"{doc}: 读者面文本含禁止表述「{phrase}」")
    assert not offenders, "\n".join(offenders)


def test_banned_claims_quoted_only_in_explicit_fixture():
    text = _read(V06_RUNBOOK)
    assert "禁止表述" in text, "运行手册缺少「禁止表述」章节"
    assert FIXTURE_START in text, "运行手册缺少显式 禁止表述 fixture 区"
    _reader, fixture = _strip_fixture_zones(text, V06_RUNBOOK)
    for phrase in BANNED_CLAIMS:
        assert phrase in fixture, f"禁止表述 fixture 未逐条引用「{phrase}」"


# ---------------------------------------------------------- v0.6 运行手册内容合同


def test_runbook_defines_two_uncertainty_meanings():
    text = _read(V06_RUNBOOK)
    assert "Kriging 原生" in text and "估计标准差" in text, "缺少 Kriging 原生估计标准差定义"
    assert "σ² = λᵀγ₀ + μ" in text, "缺少 Kriging 原生方差公式"
    assert "经验误差尺度" in text, "缺少经验误差尺度定义"
    assert "折外残差" in text and "距离加权局部 RMSE" in text, "经验误差尺度必须定义为折外残差的距离加权局部 RMSE"
    assert "不是标准误" in text, "必须声明经验误差尺度不是标准误"


def test_runbook_documents_capability_matrix_and_legacy_state():
    text = _read(V06_RUNBOOK)
    for token in ("not_applicable", "LEGACY_RESULT_NOT_COMPUTED", "IDW", "普通 Kriging"):
        assert token in text, f"运行手册缺少能力矩阵/legacy 口径 {token}"


def test_runbook_documents_deterministic_sampling_and_direction_convention():
    text = _read(V06_RUNBOOK)
    for token in ("50,000", "SHA-256", "采样率", "种子",
                  "方位角", "[0°, 180°)", "倾角", "[-90°, 90°]"):
        assert token in text, f"运行手册缺少确定性采样/方向约定 {token}"


def test_runbook_distinguishes_fold_and_full_data_parameter_origins():
    text = _read(V06_RUNBOOK)
    for token in ("automatic_candidate", "final_full_data_fit",
                  "manual_confirmed", "user_prior", "legacy_auto_fold_fit"):
        assert token in text, f"运行手册缺少参数来源 {token}"


def test_runbook_documents_anisotropy_confirmation_contract():
    text = _read(V06_RUNBOOK)
    for token in ("诊断建议", "人工确认", "不可变", "S Rᵀ", "z_scale"):
        assert token in text, f"运行手册缺少各向异性确认合同 {token}"


def test_runbook_documents_anomaly_support_measure():
    text = _read(V06_RUNBOOK)
    for token in ("显式阈值", "4 邻接", "6 邻接", "Voronoi", "网格支持面积/体积估计"):
        assert token in text, f"运行手册缺少异常支持度量口径 {token}"


def test_runbook_documents_api_cli_and_browser_paths():
    text = _read(V06_RUNBOOK)
    for token in (
        "professional-diagnostics",
        "/api/analysis-jobs/",
        "/api/results/",
        "anomaly-extractions",
        "professional-comparisons",
        "professional-artifacts/",
        "geomodeling professional diagnose",
        "geomodeling professional confirm",
        "geomodeling professional inspect-result",
        "geomodeling professional extract-anomalies",
        "geomodeling professional compare",
        "专业分析台",
        "专业诊断",
    ):
        assert token in text, f"运行手册缺少入口 {token}"


def test_runbook_documents_failure_and_degradation_semantics():
    text = _read(V06_RUNBOOK)
    for token in ("fail-closed", "409", "NoData", "interrupted", "泄漏"):
        assert token in text, f"运行手册缺少失败/降级语义 {token}"


def test_runbook_documents_known_exclusions():
    text = _read(V06_RUNBOOK)
    for token in ("普适 Kriging", "协同 Kriging", "指示 Kriging", "Bootstrap", "贝叶斯",
                  "时间预测", "斜切", "GOCAD", "瓦斯", "跨案例", "iServer 自动发布"):
        assert token in text, f"运行手册缺少明确不做项 {token}"


def test_runbook_has_no_absolute_paths_or_credential_literals():
    text = _read(V06_RUNBOOK)
    assert not re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", text), "运行手册不得含盘符绝对路径"
    assert "ADMIN_PASSWORD" not in text
    assert "BEGIN" not in text or "PRIVATE KEY" not in text


# ---------------------------------------------------------- 既有文档的 v0.6 同步


def test_readme_documents_v06_capability_cli_and_runbook_link():
    text = _read(README_DOC)
    assert "v0.6" in text, "README 当前能力缺少 v0.6 条目"
    for token in ("geomodeling professional diagnose",
                  "geomodeling professional confirm",
                  "geomodeling professional inspect-result",
                  "geomodeling professional extract-anomalies",
                  "geomodeling professional compare"):
        assert token in text, f"README CLI 清单缺少 {token}"
    assert "docs/v0.6-professional-modeling-loop.md" in text, "README 文档导航缺少 v0.6 运行手册链接"
    assert "v0.5.0 已发布" in text and "d37eb94" in text, "README 发布基线未记录 v0.5.0 已发布"


def test_status_marks_v06_implemented_on_branch_and_v050_released():
    text = _read(STATUS_DOC)
    assert "feat/v0.6-professional-modeling" in text, "状态文档缺少 v0.6 分支标识"
    assert "已实现" in text, "状态文档缺少 v0.6 已实现口径"
    assert "v0.5.0" in text and "d37eb94" in text, "状态文档未把 v0.5.0 移入已发布"
    assert "待批准" in text, "状态文档必须保留 v0.6 PR/tag 待批准说明"


def test_architecture_documents_v06_professional_layer():
    text = _read(ARCH_DOC)
    for token in ("professional_contracts", "pair_sampling", "directional_variogram",
                  "anisotropy", "neighborhood", "uncertainty", "anomalies",
                  "comparison", "fold_artifacts", "analysis_jobs",
                  "professional_diagnostics", "anomaly_extractions", "v5"):
        assert token in text, f"架构文档缺少 v0.6 模块边界 {token}"


def test_contracts_document_v06_professional_data_contracts():
    text = _read(CONTRACTS_DOC)
    for token in ("50,000", "采样率", "种子", "方位角", "倾角",
                  "automatic_candidate", "final_full_data_fit",
                  "manual_confirmed", "legacy_auto_fold_fit",
                  "经验误差尺度", "网格支持面积/体积估计", "指纹", "幂等"):
        assert token in text, f"数据契约缺少 v0.6 专业合同 {token}"


def test_acceptance_documents_v06_commands():
    text = _read(ACCEPTANCE_DOC)
    assert "v0.6" in text, "验收文档缺少 v0.6 章节"
    for token in ("professional diagnose", "professional confirm",
                  "professional inspect-result", "professional extract-anomalies",
                  "professional compare"):
        assert token in text, f"验收命令缺少 CLI {token}"


def test_blueprint_moves_professional_modeling_into_current_implementation():
    text = _read(BLUEPRINT_DOC)
    assert "v0.6" in text, "蓝图缺少 v0.6 实现状态"
    assert "已实现" in text, "蓝图必须把专业建模增强移入当前实现"
    assert "未来" in text, "蓝图必须保留分期诚实（当前实现与未来设计分开陈述）"
