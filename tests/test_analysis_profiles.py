"""v0.8.0 第二批 Task 1：分析 profile 判定与响应骨架合同测试。

断言（计划 Task 1）：电阻率/微震/瓦斯按 ``mapping`` 的
``value_name``/``value_unit``/``dimension`` 判定启用；字段缺失或 2D 数据
降级 ``generic_3d`` 并给出逐条禁用理由；判定绝不读取 ``case_id``；响应
模型在验证层拒绝 NaN/Inf，序列化只含有限值。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from geomodeling.analysis import resolve_analysis_profile
from geomodeling.analysis.profiles import (
    PROFILE_GAS_CONTENT,
    PROFILE_GENERIC_3D,
    PROFILE_MICROSEISMIC_VELOCITY,
    PROFILE_RESISTIVITY,
)
from geomodeling.analysis.schemas import (
    CALCULATION_VERSION,
    AnalysisSummaryResponse,
    HistogramBin,
    NumericSummary,
    QualitySummary,
)

# 既有数据形态事实：电阻率预置 profile_json.mapping（单位注记未确认，不得
# 作为判定条件）
RESISTIVITY_MAPPING = {
    "dimension": "3d",
    "x": "X",
    "y": "Y",
    "z": "Z",
    "value": "RHO",
    "value_name": "RHO",
    "value_unit": "RHO 单位待来源确认",
    "coordinate_kind": "local_linear",
}

# 既有数据形态事实：微震预置 profile_json.mapping
MICROSEISMIC_MAPPING = {
    "dimension": "3d",
    "x": "X_LOCAL_M",
    "y": "Y_LOCAL_M",
    "z": "Z_LOCAL_M",
    "value": "VX_KM_S",
    "value_name": "Vx",
    "value_unit": "km/s",
    "coordinate_kind": "local_linear",
}

SPECIALIZED_MODULE_IDS = {"depth_slices", "axis_trends", "gradient", "threshold_zones"}


# ---------------------------------------------------------------------------
# profile 判定
# ---------------------------------------------------------------------------


def test_resistivity_profile_declares_log_distribution_and_depth_modules():
    profile = resolve_analysis_profile({"mapping": {"value_name": "RHO"}})
    assert profile.profile_id == "resistivity"
    assert {"distribution", "depth_slices", "model_comparison"} <= set(profile.modules)

    # 真实预置 mapping（单位注记未确认）同样判定为电阻率，且无禁用理由
    real = resolve_analysis_profile({"mapping": RESISTIVITY_MAPPING})
    assert real.profile_id == "resistivity"
    assert real.specialized is True
    assert real.disabled_reasons == []
    distribution = next(s for s in real.module_specs if s.module_id == "distribution")
    assert "对数" in distribution.description


def test_missing_domain_fields_falls_back_to_generic_profile():
    profile = resolve_analysis_profile({"mapping": {"value": "value"}})
    assert profile.profile_id == "generic_3d"
    assert profile.disabled_reasons


def test_microseismic_profile_requires_vx_name_and_km_s_unit():
    profile = resolve_analysis_profile({"mapping": MICROSEISMIC_MAPPING})
    assert profile.profile_id == "microseismic_velocity"
    assert {
        "distribution",
        "axis_trends",
        "gradient",
        "spatial_anomaly",
        "profile_slices",
        "model_comparison",
    } <= set(profile.modules)
    assert profile.disabled_reasons == []

    # 仅 value_name=Vx、单位不符（微震 Vx 单位恒为 km/s，绝不静默换算）
    wrong_unit = resolve_analysis_profile(
        {"mapping": {**MICROSEISMIC_MAPPING, "value_unit": "m/s"}}
    )
    assert wrong_unit.profile_id == "generic_3d"
    reason = next(
        r
        for r in wrong_unit.disabled_reasons
        if r.profile_id == "microseismic_velocity"
    )
    assert "value_unit=km/s" in reason.missing
    assert "km/s" in reason.reason


def test_gas_content_profile_registered():
    for value_name in ("CH4", "gas", "gas_content"):
        profile = resolve_analysis_profile(
            {"mapping": {"dimension": "3d", "value_name": value_name}}
        )
        assert profile.profile_id == "gas_content"
        assert {
            "distribution",
            "threshold_zones",
            "depth_slices",
            "spatial_anomaly",
        } <= set(profile.modules)


def test_2d_mapping_degrades_to_generic_with_3d_reason():
    mapping = {
        "dimension": "2d",
        "x": "X",
        "y": "Y",
        "value": "RHO",
        "value_name": "RHO",
    }
    profile = resolve_analysis_profile({"mapping": mapping})
    assert profile.profile_id == "generic_3d"
    # 专属模块声明需要 3D，降级后一律不出现
    assert not SPECIALIZED_MODULE_IDS & set(profile.modules)
    reason = next(r for r in profile.disabled_reasons if r.profile_id == "resistivity")
    assert "dimension=3d" in reason.missing
    assert "3D" in reason.reason


def test_generic_profile_lists_disabled_reason_for_every_specialized_profile():
    profile = resolve_analysis_profile(
        {"mapping": {"dimension": "3d", "value": "VALUE", "value_name": "UNKNOWN"}}
    )
    assert profile.profile_id == PROFILE_GENERIC_3D
    assert profile.specialized is False
    reasons = {r.profile_id: r for r in profile.disabled_reasons}
    assert set(reasons) == {
        PROFILE_RESISTIVITY,
        PROFILE_MICROSEISMIC_VELOCITY,
        PROFILE_GAS_CONTENT,
    }
    for reason in reasons.values():
        assert reason.reason.strip()
        assert reason.missing
    assert "value_name=RHO" in reasons[PROFILE_RESISTIVITY].missing
    assert "value_name=Vx" in reasons[PROFILE_MICROSEISMIC_VELOCITY].missing


def test_profile_resolution_never_reads_case_id():
    base = {"mapping": MICROSEISMIC_MAPPING}
    with_top_case_id = {
        "case_id": "case-resistivity-official",
        "mapping": MICROSEISMIC_MAPPING,
    }
    with_nested_case_id = {
        "mapping": {**MICROSEISMIC_MAPPING, "case_id": "case-resistivity-official"}
    }
    results = [
        resolve_analysis_profile(payload)
        for payload in (base, with_top_case_id, with_nested_case_id)
    ]
    # case_id 即使指向电阻率官方案例，输出也逐位一致、只由 mapping 决定
    assert results[0] == results[1] == results[2]
    assert all(r.profile_id == "microseismic_velocity" for r in results)


# ---------------------------------------------------------------------------
# 响应骨架：有限性兜底
# ---------------------------------------------------------------------------


def _valid_response_kwargs() -> dict:
    return {
        "dataset_id": "ds-1",
        "case_id": "case-1",
        "analysis_profile": "resistivity",
        "profile_version": 1,
        "variable": {"name": "RHO", "unit": "RHO 单位待来源确认"},
        "quality": {
            "row_count": 3,
            "valid_count": 3,
            "invalid_count": 0,
            "duplicate_coordinate_count": 0,
            "bounds": {"x": (0.0, 120.0), "z": (0.0, 813.4)},
        },
        "statistics": {
            "count": 3,
            "min": 1.4,
            "max": 133.1,
            "mean": 42.0,
            "median": 31.2,
            "std": 19.4,
            "quantiles": {
                "p05": 8.1,
                "p25": 23.4,
                "p50": 31.2,
                "p75": 52.7,
                "p95": 88.2,
            },
        },
        "modules": [],
        "provenance": {
            "source_sha256": "abc123",
            "dataset_version": 1,
            "generated_at": "2026-08-09T00:00:00Z",
            "calculation_version": CALCULATION_VERSION,
        },
    }


def test_analysis_summary_response_accepts_finite_skeleton():
    response = AnalysisSummaryResponse(**_valid_response_kwargs())
    dumped = response.model_dump()
    assert dumped["analysis_profile"] == "resistivity"
    assert dumped["variable"] == {"name": "RHO", "unit": "RHO 单位待来源确认"}
    assert dumped["provenance"]["calculation_version"] == CALCULATION_VERSION


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_numeric_summary_rejects_non_finite(bad):
    with pytest.raises(ValidationError):
        NumericSummary(count=1, mean=bad)


def test_histogram_bin_rejects_non_finite_bounds():
    with pytest.raises(ValidationError):
        HistogramBin(lower=float("nan"), upper=1.0, count=1)
    with pytest.raises(ValidationError):
        HistogramBin(lower=0.0, upper=float("inf"), count=1)


def test_quality_bounds_reject_non_finite():
    with pytest.raises(ValidationError):
        QualitySummary(bounds={"z": (0.0, float("inf"))})


def test_response_rejects_nested_non_finite_statistics():
    kwargs = _valid_response_kwargs()
    kwargs["statistics"] = {"count": 1, "mean": float("nan")}
    with pytest.raises(ValidationError):
        AnalysisSummaryResponse(**kwargs)
