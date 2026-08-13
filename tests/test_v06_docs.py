"""专业建模在统一项目说明中的合同。"""

from pathlib import Path

GUIDE = Path("docs/project-guide.md")


def _guide() -> str:
    assert GUIDE.exists()
    return GUIDE.read_text(encoding="utf-8")


def test_guide_documents_professional_module_boundaries():
    text = _guide()
    for token in (
        "professional_contracts",
        "pair_sampling",
        "directional_variogram",
        "anisotropy",
        "neighborhood",
        "uncertainty",
        "anomalies",
        "comparison",
        "fold_artifacts",
    ):
        assert token in text


def test_guide_documents_professional_evidence_contract():
    text = _guide()
    for token in (
        "50,000",
        "SHA-256",
        "[0°, 180°)",
        "[-90°, 90°]",
        "automatic_candidate",
        "final_full_data_fit",
        "manual_confirmed",
        "user_prior",
        "legacy_auto_fold_fit",
        "x′ = S Rᵀ x",
        "not_applicable",
        "LEGACY_RESULT_NOT_COMPUTED",
        "4 邻接",
        "6 邻接",
        "Voronoi",
    ):
        assert token in text, f"统一说明缺少专业合同 {token}"


def test_guide_documents_uncertainty_without_overclaiming():
    text = _guide()
    assert "σ² = λᵀγ₀ + μ" in text
    assert "经验误差尺度" in text
    assert "距离加权局部 RMSE" in text
    assert "不是标准误" in text
    assert "不是概率置信区间" in text


def test_readme_keeps_professional_cli_entries():
    text = Path("README.md").read_text(encoding="utf-8")
    for token in (
        "professional diagnose",
        "professional confirm",
        "professional inspect-result",
        "professional extract-anomalies",
        "professional compare",
    ):
        assert token in text
