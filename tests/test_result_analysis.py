"""成果网格分析合同与纯计算回归。"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from geomodeling.platform.result_analysis_contracts import ResultAnalysisSummary


def _minimal_result_summary() -> dict:
    return {
        "identity": {
            "result_id": "result-1",
            "grid_sha256": "a" * 64,
            "analysis_version": "result_analysis.v1",
            "dimension": "3d",
            "coordinate_type": "local_linear",
        },
        "variable": {"name": "RHO", "unit": "ohm_m"},
        "grid": {
            "shape": [2, 2, 2],
            "total_count": 8,
            "valid_count": 8,
            "nodata_count": 0,
            "min": 1.0,
            "max": 8.0,
            "mean": 4.5,
            "median": 4.5,
            "p25": 2.75,
            "p75": 6.25,
        },
        "thresholds": {
            "low": 2.75,
            "high": 6.25,
            "source": "full_result_grid",
            "method": "numpy_linear_p25_p75",
        },
        "composition": {
            "buckets": [
                {"kind": "low", "count": 2, "ratio": 0.25},
                {"kind": "normal", "count": 4, "ratio": 0.5},
                {"kind": "high", "count": 2, "ratio": 0.25},
            ]
        },
        "depth_profile": {"status": "available", "bins": []},
        "components_preview": {
            "threshold": 6.25,
            "connectivity_rule": "face_2d4_3d6_v1",
            "total": 0,
            "returned": 0,
            "rows": [],
        },
        "model_evidence": {
            "algorithm": "ordinary_kriging",
            "metrics": {"rmse": 1.0, "r2": 0.9},
            "common_valid_count": 8,
            "formal_selection": True,
            "uncertainty_status": "unavailable",
        },
        "findings": [],
        "provenance": {
            "grid_sha256": "a" * 64,
            "calculation_version": "result_analysis.v1",
            "threshold_method": "numpy_linear_p25_p75",
        },
    }


def test_result_analysis_contract_accepts_minimal_response() -> None:
    summary = ResultAnalysisSummary.model_validate(_minimal_result_summary())

    assert summary.identity.result_id == "result-1"
    assert summary.grid.valid_count == 8
    assert summary.model_config["frozen"] is True


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("grid", "mean"), float("nan")),
        (("thresholds", "high"), float("inf")),
        (("model_evidence", "metrics"), {"rmse": float("-inf")}),
    ],
)
def test_result_analysis_contract_rejects_non_finite(path: tuple[str, ...], value) -> None:
    payload = copy.deepcopy(_minimal_result_summary())
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValidationError):
        ResultAnalysisSummary.model_validate(payload)


def test_result_analysis_contract_rejects_unknown_fields() -> None:
    payload = _minimal_result_summary()
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        ResultAnalysisSummary.model_validate(payload)
