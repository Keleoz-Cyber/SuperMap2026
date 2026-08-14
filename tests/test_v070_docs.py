"""当前渲染与切片协议必须只在权威文档（README + 技术架构）中维护。"""

from pathlib import Path

DOCS = (Path("README.md"), Path("docs/architecture.md"))


def _corpus() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in DOCS)


def test_current_docs_cover_rendering_contract():
    corpus = _corpus()
    for token in (
        "gmp-supermap-volume/v2",
        "slice-analysis/v1",
        "std_population",
        "client_echarts_canvas",
        "singleAxisSlice",
        "no silent fallback",
    ):
        assert token in corpus, f"当前文档缺少 {token}"


def test_current_docs_do_not_describe_v1_as_current_protocol():
    for path in DOCS:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "gmp-supermap-volume/v1" in line:
                assert any(marker in line for marker in ("取代", "历史", "升级", "v2"))
