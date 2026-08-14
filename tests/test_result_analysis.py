"""v0.9.0 成果分析合同测试：DTO 严格校验、未知字段拒绝、非有限值 fail-closed。

当前合同依据：docs/architecture.md 与 docs/product-guide.md。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from geomodeling.modeling.slices import GridResult
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.result_analysis import (
    analyze_result_grid,
    composition_summary,
    finite_valid_values,
    result_thresholds,
)
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

    @pytest.mark.parametrize(
        ("path", "invalid_value"),
        [
            (("identity", "coordinate_type"), "invented_coordinates"),
            (("thresholds", "source"), "slice_local_guess"),
            (("depth_profile", "status"), "unknown"),
            (("findings", 0, "kind"), "unsupported_finding"),
            (("findings", 0, "confidence"), "certain"),
        ],
    )
    def test_rejects_unknown_public_enum_values(self, path, invalid_value):
        payload = _minimal_result_summary()
        target = payload
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = invalid_value
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

    def test_rejects_unknown_mode(self):
        payload = _minimal_ai_review()
        payload["mode"] = "freeform"
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


# ---------------------------------------------------------------------------
# Task 2: Result-grid statistics and depth evidence
# ---------------------------------------------------------------------------

def _axes3d(nx=2, ny=2, nz=2):
    return (
        np.linspace(0, 1, nx, dtype=float),
        np.linspace(0, 1, ny, dtype=float),
        np.linspace(0, 10, nz, dtype=float),
    )


def _make_3d_grid() -> GridResult:
    """2x2x2 grid with one NoData node. 7 valid nodes."""
    axes = _axes3d()
    values = np.array([
        [[1.0, 2.0], [3.0, 4.0]],
        [[5.0, 6.0], [7.0, 8.0]],
    ], dtype=float)
    is_nodata = np.zeros((2, 2, 2), dtype=bool)
    is_nodata[0, 0, 0] = True  # mark one as nodata
    return GridResult(
        dimension="3d",
        axes=axes,
        values=values,
        is_nodata=is_nodata,
        metadata={"algorithm": "idw", "coordinate_kind": "local_linear"},
    )


class TestResultGridStatistics:
    def test_valid_count_excludes_nodata(self):
        grid = _make_3d_grid()
        valid = finite_valid_values(grid.values, grid.is_nodata)
        assert valid.size == 7

    def test_thresholds_are_p25_p75(self):
        grid = _make_3d_grid()
        valid = finite_valid_values(grid.values, grid.is_nodata)
        low, high = result_thresholds(valid)
        expected = np.quantile(valid, [0.25, 0.75], method="linear")
        assert low == pytest.approx(float(expected[0]))
        assert high == pytest.approx(float(expected[1]))

    def test_composition_counts_sum_to_valid(self):
        grid = _make_3d_grid()
        valid = finite_valid_values(grid.values, grid.is_nodata)
        low, high = result_thresholds(valid)
        comp = composition_summary(grid.values, grid.is_nodata, low, high)
        total = sum(b.count for b in comp.buckets)
        assert total == 7
        ratio_sum = sum(b.ratio for b in comp.buckets)
        assert ratio_sum == pytest.approx(1.0)

    def test_depth_bins_cover_all_valid(self):
        grid = _make_3d_grid()
        summary = analyze_result_grid(
            grid,
            result_id="r1",
            grid_sha256="a" * 64,
            variable_name="RHO",
            variable_unit="ohm_m",
            depth_bins=2,
            component_limit=8,
            min_support_nodes=1,
        )
        assert summary.depth_profile.status == "applicable"
        total_valid = sum(b.valid_count for b in summary.depth_profile.bins)
        assert total_valid == 7

    def test_2d_depth_not_applicable(self):
        axes = (np.linspace(0, 1, 3), np.linspace(0, 1, 3))
        values = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]])
        is_nodata = np.zeros((3, 3), dtype=bool)
        grid = GridResult(
            dimension="2d", axes=axes, values=values, is_nodata=is_nodata, metadata={},
        )
        summary = analyze_result_grid(
            grid,
            result_id="r2d",
            grid_sha256="b" * 64,
            variable_name="RHO",
            variable_unit="ohm_m",
            depth_bins=4,
            component_limit=8,
            min_support_nodes=1,
        )
        assert summary.depth_profile.status == "not_applicable"
        assert summary.depth_profile.bins == []

    def test_zero_valid_raises(self):
        axes = _axes3d()
        values = np.full((2, 2, 2), float("nan"))
        is_nodata = np.zeros((2, 2, 2), dtype=bool)
        grid = GridResult(
            dimension="3d", axes=axes, values=values, is_nodata=is_nodata, metadata={},
        )
        with pytest.raises(PlatformError) as exc:
            analyze_result_grid(
                grid,
                result_id="r-empty",
                grid_sha256="c" * 64,
                variable_name="RHO",
                variable_unit="ohm_m",
            )
        assert exc.value.code == "RESULT_ANALYSIS_NO_VALID_CELLS"

    def test_nodata_and_nan_excluded_from_stats(self):
        axes = _axes3d()
        values = np.array([
            [[float("nan"), 2.0], [3.0, 4.0]],
            [[5.0, 6.0], [7.0, 8.0]],
        ], dtype=float)
        is_nodata = np.zeros((2, 2, 2), dtype=bool)
        is_nodata[1, 1, 1] = True  # nodata at different position than nan
        grid = GridResult(
            dimension="3d", axes=axes, values=values, is_nodata=is_nodata, metadata={},
        )
        summary = analyze_result_grid(
            grid,
            result_id="r-nan",
            grid_sha256="d" * 64,
            variable_name="RHO",
            variable_unit="ohm_m",
            depth_bins=2,
            component_limit=8,
            min_support_nodes=1,
        )
        assert summary.grid.valid_count == 6  # 8 - 1 nodata - 1 nan


# ---------------------------------------------------------------------------
# Task 3: Connected components and findings
# ---------------------------------------------------------------------------

def _make_two_region_grid() -> GridResult:
    """3x3x3 grid with two separated high-value regions above p75."""
    axes = (
        np.linspace(0, 2, 3, dtype=float),
        np.linspace(0, 2, 3, dtype=float),
        np.linspace(0, 2, 3, dtype=float),
    )
    values = np.ones((3, 3, 3), dtype=float)  # all 1.0 (low)
    # Region A: 4 face-connected nodes at x=0 corner, value 100
    values[0, 0, 0] = 100.0
    values[0, 0, 1] = 100.0
    values[0, 1, 0] = 100.0
    values[0, 1, 1] = 100.0
    # Region B: 4 face-connected nodes at x=2 corner, value 90
    values[2, 2, 1] = 90.0
    values[2, 2, 2] = 90.0
    values[2, 1, 2] = 90.0
    values[1, 2, 2] = 90.0
    is_nodata = np.zeros((3, 3, 3), dtype=bool)
    return GridResult(
        dimension="3d", axes=axes, values=values, is_nodata=is_nodata,
        metadata={"algorithm": "idw", "coordinate_kind": "local_linear"},
    )


class TestConnectedComponents:
    def test_high_and_low_components_have_unique_directional_identity(self):
        grid = _make_two_region_grid()
        summary = analyze_result_grid(
            grid,
            result_id="r-directions",
            grid_sha256="f" * 64,
            variable_name="RHO",
            variable_unit="Ω·m",
            depth_bins=2,
            component_limit=8,
            min_support_nodes=1,
        )

        assert summary.components_preview.rows
        assert summary.low_components_preview is not None
        assert summary.low_components_preview.rows
        assert {row.direction for row in summary.components_preview.rows} == {"high"}
        assert {row.direction for row in summary.low_components_preview.rows} == {"low"}
        assert {row.component_id for row in summary.components_preview.rows}.isdisjoint(
            {row.component_id for row in summary.low_components_preview.rows}
        )
        assert all(row.component_id > 1_000_000 for row in summary.low_components_preview.rows)
        assert summary.domain_interpretation is not None
        assert summary.domain_interpretation.profile == "resistivity"

    def test_two_regions_separated(self):
        grid = _make_two_region_grid()
        summary = analyze_result_grid(
            grid,
            result_id="r-sep",
            grid_sha256="e" * 64,
            variable_name="RHO",
            variable_unit="ohm_m",
            depth_bins=2,
            component_limit=8,
            min_support_nodes=1,
        )
        assert summary.components_preview.total >= 2
        assert summary.components_preview.returned >= 2

    def test_labels_a_b_assigned(self):
        grid = _make_two_region_grid()
        summary = analyze_result_grid(
            grid,
            result_id="r-sep",
            grid_sha256="e" * 64,
            variable_name="RHO",
            variable_unit="ohm_m",
            depth_bins=2,
            component_limit=8,
            min_support_nodes=1,
        )
        labels = [r.label for r in summary.components_preview.rows]
        assert "A" in labels
        if len(labels) >= 2:
            assert "B" in labels

    def test_sorted_by_support_descending(self):
        grid = _make_two_region_grid()
        summary = analyze_result_grid(
            grid,
            result_id="r-sep",
            grid_sha256="e" * 64,
            variable_name="RHO",
            variable_unit="ohm_m",
            depth_bins=2,
            component_limit=8,
            min_support_nodes=1,
        )
        measures = [r.support_measure for r in summary.components_preview.rows]
        assert measures == sorted(measures, reverse=True)

    def test_boundary_contact_detected(self):
        grid = _make_two_region_grid()
        summary = analyze_result_grid(
            grid,
            result_id="r-sep",
            grid_sha256="e" * 64,
            variable_name="RHO",
            variable_unit="ohm_m",
            depth_bins=2,
            component_limit=8,
            min_support_nodes=1,
        )
        # Both regions touch the grid boundary
        for row in summary.components_preview.rows:
            assert row.touches_grid_boundary is True

    def test_component_bounds_and_centroid(self):
        grid = _make_two_region_grid()
        summary = analyze_result_grid(
            grid,
            result_id="r-sep",
            grid_sha256="e" * 64,
            variable_name="RHO",
            variable_unit="ohm_m",
            depth_bins=2,
            component_limit=8,
            min_support_nodes=1,
        )
        for row in summary.components_preview.rows:
            assert len(row.bounds) == 3
            for b in row.bounds:
                assert len(b) == 2
            assert len(row.centroid) == 3


class TestFindings:
    def test_findings_contain_required_kinds(self):
        grid = _make_3d_grid()
        summary = analyze_result_grid(
            grid,
            result_id="r1",
            grid_sha256="a" * 64,
            variable_name="RHO",
            variable_unit="ohm_m",
            depth_bins=2,
            component_limit=8,
            min_support_nodes=1,
            algorithm="idw",
        )
        kinds = {f.kind for f in summary.findings}
        assert "dominant_depth_interval" in kinds
        assert "largest_high_component" in kinds
        assert "boundary_contact" in kinds
        assert "formal_model" in kinds
        assert "uncertainty_availability" in kinds

    def test_finding_has_evidence_and_limitations(self):
        grid = _make_3d_grid()
        summary = analyze_result_grid(
            grid,
            result_id="r1",
            grid_sha256="a" * 64,
            variable_name="RHO",
            variable_unit="ohm_m",
            depth_bins=2,
            component_limit=8,
            min_support_nodes=1,
        )
        for f in summary.findings:
            assert len(f.evidence) >= 1
            assert isinstance(f.limitations, list)
            assert f.confidence in ("high", "medium", "low")

    def test_finding_spatial_target(self):
        grid = _make_3d_grid()
        summary = analyze_result_grid(
            grid,
            result_id="r1",
            grid_sha256="a" * 64,
            variable_name="RHO",
            variable_unit="ohm_m",
            depth_bins=2,
            component_limit=8,
            min_support_nodes=1,
        )
        depth_finding = next(f for f in summary.findings if f.kind == "dominant_depth_interval")
        assert depth_finding.spatial_target is not None
        assert depth_finding.spatial_target.kind == "depth_bin"

    def test_findings_use_plain_language_for_people_not_report_jargon(self):
        grid = _make_3d_grid()
        summary = analyze_result_grid(
            grid,
            result_id="r1",
            grid_sha256="a" * 64,
            variable_name="RHO",
            variable_unit="ohm_m",
            depth_bins=2,
            component_limit=8,
            min_support_nodes=1,
            algorithm="ordinary_kriging",
            model_metrics={"rmse": 0.26826092589268974, "mae": 0.21278721948784854, "r2": 0.8442501479446578, "coverage": 1.0},
            common_valid_count=1911,
        )
        by_kind = {finding.kind: finding for finding in summary.findings}
        assert by_kind["dominant_depth_interval"].title == "哪个深度层高值最多"
        assert "这一层的高值比例最高" in by_kind["dominant_depth_interval"].statement
        assert by_kind["largest_high_component"].title == "最大的连续高值区"
        assert "模型坐标立方单位" in by_kind["largest_high_component"].statement
        assert "volume_coordinate_unit3" not in by_kind["largest_high_component"].statement
        assert "模型覆盖大小" in by_kind["largest_high_component"].limitations[0]
        assert by_kind["boundary_contact"].title == "哪些区域延伸到模型边缘"
        assert "实际范围可能比图上更大" in by_kind["boundary_contact"].statement
        assert by_kind["formal_model"].title == "当前使用普通克里金"
        assert by_kind["formal_model"].statement == (
            "共同参与比较的点有 1,911 个，RMSE 0.268，MAE 0.213，"
            "R² 0.844，覆盖率 100.0%"
        )
        assert by_kind["uncertainty_availability"].title == "误差参考"
        combined = " ".join(
            finding.title + " " + finding.statement + " " + " ".join(finding.limitations)
            for finding in summary.findings
        )
        assert "网格支持量最大的高值连通区" not in combined
        assert "不确定性证据状态" not in combined

    def test_no_prohibited_claims_in_findings(self):
        grid = _make_3d_grid()
        summary = analyze_result_grid(
            grid,
            result_id="r1",
            grid_sha256="a" * 64,
            variable_name="RHO",
            variable_unit="ohm_m",
            depth_bins=2,
            component_limit=8,
            min_support_nodes=1,
        )
        prohibited = ["储量", "含水性", "危险性", "成矿", "地质体积", "工程安全"]
        for f in summary.findings:
            text = f.statement + f.title
            for word in prohibited:
                assert word not in text, f"Finding {f.id} contains prohibited term: {word}"
