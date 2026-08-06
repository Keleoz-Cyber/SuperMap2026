"""v0.7.0 第二批 Task 12：当前文档必须如实描述协议 v2 与剖面分析合同。

历史 v0.6.1 计划/运行手册保持版本化历史不变；当前受控文档（README、
architecture、supermap-integration、current-status）必须覆盖协议 v2、
剖面导出格式、权威统计口径、PNG provenance、单轴能力与 no fallback。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURRENT_DOCS = [
    ROOT / "README.md",
    ROOT / "docs" / "architecture.md",
    ROOT / "docs" / "supermap-integration.md",
    ROOT / "docs" / "status" / "current-status.md",
]


def _corpus() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in CURRENT_DOCS)


def test_current_docs_cover_v070_rendering_contract():
    corpus = _corpus()
    for token in (
        "gmp-supermap-volume/v2",
        "slice-analysis/v1",
        "std_population",
        "client_echarts_canvas",
        "singleAxisSlice",
        "no fallback",
    ):
        assert token in corpus, f"当前文档缺少 {token}"


def test_current_docs_do_not_describe_v1_as_current_protocol():
    # v1 只允许以历史/取代/升级语义出现（v0.6.1 计划与运行手册为版本化历史）
    for path in CURRENT_DOCS:
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "gmp-supermap-volume/v1" in line:
                assert any(
                    marker in line for marker in ("取代", "历史", "升级", "v2", "supersed")
                ), f"{path.name} 仍以当前语义描述 v1 协议：{line.strip()}"
