"""v0.9.0 成果分析合同测试：DTO 严格校验、未知字段拒绝、非有限值 fail-closed。

设计依据：docs/superpowers/specs/2026-08-10-v0.9.0-result-analysis-integration-design.md §5, §9。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from geomodeling.platform.result_analysis_contracts import (
    RESULT_ANALYSIS_VERSION,
    ResultAnalysisSummary,
)
from geomodeling.platform.ai_analysis_contracts import (
    PROMPT_VERSION,
    AIReview,
    EvidencePacket,
)


# ---------------------------------------------------------------------------
# Minimal valid fixtures
# ---------------------------------------------------------------------------

def _minimal_result_summary() -> dict:
    return {
        "identity": {
            "result_id": "r1",
            "grid_sha256": "a" * 64,
            "analysis_version": RESULT_ANALYSIS_VERSION,
            "dimension": "3d",
            "coordinate_type": "local_linear",
        },
        "variable": {"name": "RHO", "unit": "ohm_m"},
        "grid": {
            "shape": [2, 2, 2],
            "valid_count": 7,
            "nodata_count": 1,
            "min": 1.0,
            "max": 10.0,
            "mean": 5.0,
            "median": 5.0,
            "p25": 3.0,
            "p75": 7.0,
        },
        "thresholds": {
            "low": 3.0,
            "high": 7.0,
            "source": "full_grid_quartile",
            "method": "numpy_linear_p25_p75",
        },
        "composition": {
            "buckets": [
                {"category": "low", "count": 2, "ratio": 0.2857142857142857},
                {"category": "normal", "count": 3, "ratio": 0.42857142857142855},
                {"category": "high", "count": 2, "ratio": 0.2857142857142857},
            ]
        },
        "depth_profile": {
            "status": "applicable",
            "bins": [
                {"z_lower": 0.0, "z_upper": 5.0, "valid_count": 4, "mean": 4.0, "high_count": 1, "high_ratio": 0.25},
                {"z_lower": 5.0, "z_upper": 10.0, "valid_count": 3, "mean": 6.5, "high_count": 1, "high_ratio": 0.3333333333333333},
            ],
        },
        "components_preview": {
            "threshold": 7.0,
            "connectivity_rule": "face_2d4_3d6_v1",
            "total": 2,
            "returned": 2,
            "rows": [
                {
                    "rank": 1,
                    "label": "A",
                    "component_id": 1,
                    "support_node_count": 1,
                    "support_measure": 8.0,
                    "support_unit": "volume_coordinate_unit3",
                    "bounds": [[0.0, 1.0], [0.0, 1.0], [5.0, 5.0]],
                    "centroid": [1.0, 1.0, 5.0],
                    "value_min": 10.0,
                    "value_max": 10.0,
                    "value_mean": 10.0,
                    "touches_grid_boundary": False,
                },
                {
                    "rank": 2,
                    "label": "B",
                    "component_id": 2,
                    "support_node_count": 1,
                    "support_measure": 4.0,
                    "support_unit": "volume_coordinate_unit3",
                    "bounds": [[0.0, 0.0], [1.0, 1.0], [0.0, 0.0]],
                    "centroid": [0.0, 1.0, 0.0],
                    "value_min": 8.0,
                    "value_max": 8.0,
                    "value_mean": 8.0,
                    "touches_grid_boundary": True,
                },
            ],
        },
        "model_evidence": {
            "algorithm": "ordinary_kriging",
            "metrics": {"rmse": 0.5, "mae": 0.3, "r2": 0.9},
            "common_valid_count": 100,
            "formal_selection_id": None,
            "formal_selection_note": None,
        },
        "findings": [
            {
                "id": "finding-1",
                "kind": "dominant_depth_interval",
                "title": "高值主要集中在深层",
                "statement": "第二层段高值占比最高",
                "evidence": [{"name": "high_ratio", "value": 0.3333333333333333}],
                "confidence": "medium",
                "limitations": ["局部坐标系"],
                "spatial_target": {"kind": "depth_bin", "depth_bin_index": 1},
            }
        ],
        "provenance": {
            "grid_sha256": "a" * 64,
            "calculation_version": RESULT_ANALYSIS_VERSION,
            "threshold_method": "numpy_linear_p25_p75",
        },
    }


def _minimal_evidence_packet() -> dict:
    return {
        "identity": {
            "result_id": "r1",
            "grid_sha256": "a" * 64,
            "calculation_version": RESULT_ANALYSIS_VERSION,
            "dimension": "3d",
            "coordinate_type": "local_linear",
        },
        "variable": {"name": "RHO", "unit": "ohm_m"},
        "result_grid": {
            "statistics": {"valid_count": 7, "nodata_count": 1, "min": 1.0, "max": 10.0, "mean": 5.0, "p25": 3.0, "p75": 7.0},
            "thresholds": {"low": 3.0, "high": 7.0, "method": "numpy_linear_p25_p75"},
            "composition": {"buckets": [
                {"category": "low", "count": 2, "ratio": 0.286},
                {"category": "normal", "count": 3, "ratio": 0.429},
                {"category": "high", "count": 2, "ratio": 0.286},
            ]},
            "depth_profile": {"status": "applicable", "bins": [
                {"z_lower": 0.0, "z_upper": 5.0, "valid_count": 4, "mean": 4.0, "high_count": 1, "high_ratio": 0.25},
            ]},
        },
        "spatial_components": [
            {"label": "A", "component_id": 1, "support_node_count": 1, "support_measure": 8.0, "value_max": 10.0, "value_mean": 10.0, "touches_grid_boundary": False},
        ],
        "current_slice": {"axis": "z", "coordinate": 0.0, "valid_count": 4, "mean": 4.0, "high_count": 1, "high_ratio": 0.25},
        "model_evidence": {"algorithm": "ordinary_kriging", "common_valid_count": 100, "rmse": 0.5, "mae": 0.3, "r2": 0.9, "coverage": 0.95, "formal_selection_id": None},
        "uncertainty": {"availability": "available", "empirical_error_mean": 0.3, "kriging_std_mean": None},
        "input_quality": {"validated_count": 100, "total_count": 120, "coverage": 0.833},
        "constraints": {
            "prohibited_claims": ["含水性", "危险性", "储量"],
            "known_limitations": ["局部坐标系", "属性单位依赖输入"],
        },
    }


def _minimal_ai_review() -> dict:
    return {
        "spatial_pattern": {"summary": "高值集中在深层南部", "evidence_refs": ["component-1", "depth_bin-0"]},
        "model_reliability": {"summary": "Kriging 模型公共有效指标良好", "evidence_refs": ["model_evidence"]},
        "uncertainty_and_risk": {"summary": "经验误差尺度可用", "evidence_refs": ["uncertainty"]},
        "review_and_next_checks": {"summary": "建议复核边界组件", "evidence_refs": ["component-1"]},
        "consensus": {
            "consensus": "高值区集中在深层，模型可靠",
            "disagreements": [],
            "recommended_checks": ["复核边界接触组件"],
            "decision_options": [
                {"label": "维持当前模型", "trigger": "指标达标", "benefit": "无需额外计算", "cost": "不改善边界不确定性", "evidence_refs": ["model_evidence"]},
            ],
            "limitations": ["局部坐标系"],
        },
        "evidence_hash": "abc123",
        "prompt_version": PROMPT_VERSION,
        "provider": "deepseek",
        "model": "deepseek-chat",
        "mode": "quick",
    }


# ---------------------------------------------------------------------------
# ResultAnalysisSummary contract tests
# ---------------------------------------------------------------------------

class TestResultAnalysisContract:
    def test_minimal_valid(self):
        summary = ResultAnalysisSummary.model_validate(_minimal_result_summary())
        assert summary.identity.result_id == "r1"
        assert summary.grid.valid_count == 7

    def test_rejects_nan_in_grid(self):
        payload = _minimal_result_summary()
        payload["grid"]["mean"] = float("nan")
        with pytest.raises(ValidationError):
            ResultAnalysisSummary.model_validate(payload)

    def test_rejects_inf_in_grid(self):
        payload = _minimal_result_summary()
        payload["grid"]["max"] = float("inf")
        with pytest.raises(ValidationError):
            ResultAnalysisSummary.model_validate(payload)

    def test_rejects_unknown_field(self):
        payload = _minimal_result_summary()
        payload["unexpected"] = True
        with pytest.raises(ValidationError):
            ResultAnalysisSummary.model_validate(payload)

    def test_rejects_nan_in_thresholds(self):
        payload = _minimal_result_summary()
        payload["thresholds"]["low"] = float("nan")
        with pytest.raises(ValidationError):
            ResultAnalysisSummary.model_validate(payload)

    def test_rejects_nan_in_depth_bin(self):
        payload = _minimal_result_summary()
        payload["depth_profile"]["bins"][0]["mean"] = float("nan")
        with pytest.raises(ValidationError):
            ResultAnalysisSummary.model_validate(payload)

    def test_rejects_nan_in_component(self):
        payload = _minimal_result_summary()
        payload["components_preview"]["rows"][0]["value_max"] = float("inf")
        with pytest.raises(ValidationError):
            ResultAnalysisSummary.model_validate(payload)

    def test_rejects_unknown_field_in_nested(self):
        payload = _minimal_result_summary()
        payload["grid"]["extra"] = 1
        with pytest.raises(ValidationError):
            ResultAnalysisSummary.model_validate(payload)

    def test_2d_not_applicable_depth(self):
        payload = _minimal_result_summary()
        payload["identity"]["dimension"] = "2d"
        payload["depth_profile"]["status"] = "not_applicable"
        payload["depth_profile"]["bins"] = []
        summary = ResultAnalysisSummary.model_validate(payload)
        assert summary.depth_profile.status == "not_applicable"
        assert summary.depth_profile.bins == []


# ---------------------------------------------------------------------------
# EvidencePacket contract tests
# ---------------------------------------------------------------------------

class TestEvidencePacketContract:
    def test_minimal_valid(self):
        packet = EvidencePacket.model_validate(_minimal_evidence_packet())
        assert packet.identity.result_id == "r1"

    def test_rejects_unknown_field(self):
        payload = _minimal_evidence_packet()
        payload["unexpected"] = True
        with pytest.raises(ValidationError):
            EvidencePacket.model_validate(payload)

    def test_rejects_nan_in_statistics(self):
        payload = _minimal_evidence_packet()
        payload["result_grid"]["statistics"]["mean"] = float("nan")
        with pytest.raises(ValidationError):
            EvidencePacket.model_validate(payload)

    def test_valid_evidence_ids(self):
        packet = EvidencePacket.model_validate(_minimal_evidence_packet())
        ids = packet.valid_evidence_ids
        assert "component-1" in ids
        assert "result_grid" in ids
        assert "current_slice" in ids
        assert "depth_bin-0" in ids


# ---------------------------------------------------------------------------
# AIReview contract tests
# ---------------------------------------------------------------------------

class TestAIReviewContract:
    def test_minimal_valid(self):
        review = AIReview.model_validate(_minimal_ai_review())
        assert review.mode == "quick"

    def test_rejects_unknown_field(self):
        payload = _minimal_ai_review()
        payload["unexpected"] = True
        with pytest.raises(ValidationError):
            AIReview.model_validate(payload)

    def test_rejects_nan_in_evidence_hash(self):
        payload = _minimal_ai_review()
        payload["evidence_hash"] = float("nan")
        with pytest.raises(ValidationError):
            AIReview.model_validate(payload)

    def test_rejects_empty_evidence_ref(self):
        payload = _minimal_ai_review()
        payload["spatial_pattern"]["evidence_refs"] = ["component-1", ""]
        with pytest.raises(ValidationError):
            AIReview.model_validate(payload)


# ---------------------------------------------------------------------------
# JSON contract fixtures (4 states)
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / "fixtures_result_analysis"


class TestJsonFixtures:
    """Validate that the four deterministic JSON fixtures parse correctly."""

    @pytest.mark.parametrize("fixture_name", [
        "3d_normal.json",
        "2d_not_applicable.json",
        "no_uncertainty.json",
        "ai_not_configured.json",
    ])
    def test_fixture_parses(self, fixture_name: str):
        fixture_path = FIXTURE_DIR / fixture_name
        assert fixture_path.is_file(), f"Missing fixture: {fixture_path}"
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        summary = ResultAnalysisSummary.model_validate(data)
        assert summary.identity.analysis_version == RESULT_ANALYSIS_VERSION
