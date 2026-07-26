"""v0.6 Task 1：专业分析契约与算法能力矩阵。

设计依据 docs/superpowers/specs/2026-07-26-v0.6-professional-modeling-enhancements-design.md
§3.3 能力矩阵、§6.3 方向定义、§8.1 搜索邻域、§10.2 经验误差尺度、§12.1 异常配置。
"""

import math

import pytest
from pydantic import ValidationError

from geomodeling.modeling.professional_contracts import (
    AlgorithmCapabilities,
    AnomalyExtractionSpec,
    CapabilityState,
    DirectionSpec,
    EmpiricalUncertaintySpec,
    NeighborhoodSpec,
    VariogramDiagnosticSpec,
    ZScaleSpec,
    capabilities_for,
)
from geomodeling.platform.schemas import (
    ProfessionalConfirmationRequest,
    ProfessionalDiagnosisRequest,
)

# ---------------------------------------------------------------------------
# 能力矩阵（§3.3）
# ---------------------------------------------------------------------------


def test_algorithm_capabilities_are_explicit():
    assert capabilities_for("idw").native_kriging_std == "not_applicable"
    assert capabilities_for("idw").model_anisotropy == "not_applicable"
    assert capabilities_for("idw").search_neighborhood == "supported"
    assert capabilities_for("ordinary_kriging").native_kriging_std == "supported"


def test_capability_matrix_matches_design_exactly():
    expected = {
        "idw": {
            "empirical_variogram": "not_applicable",
            "model_anisotropy": "not_applicable",
            "z_scale_weight_distance": "supported",
            "search_neighborhood": "supported",
            "sector_neighbor_limits": "supported",
            "spatial_fold_inspection": "supported",
            "empirical_error_scale": "supported",
            "native_kriging_std": "not_applicable",
            "anomaly_extraction": "supported",
            "candidate_comparison": "supported",
        },
        "ordinary_kriging": {
            "empirical_variogram": "supported",
            "model_anisotropy": "supported",
            "z_scale_weight_distance": "supported",
            "search_neighborhood": "supported",
            "sector_neighbor_limits": "supported",
            "spatial_fold_inspection": "supported",
            "empirical_error_scale": "supported",
            "native_kriging_std": "supported",
            "anomaly_extraction": "supported",
            "candidate_comparison": "supported",
        },
    }
    for algorithm, fields in expected.items():
        record = capabilities_for(algorithm)
        assert record.algorithm == algorithm
        for name, state in fields.items():
            value = getattr(record, name)
            assert isinstance(value, CapabilityState), f"{algorithm}.{name} 必须是类型化状态"
            assert value == state, f"{algorithm}.{name}"


def test_not_applicable_is_typed_state_not_placeholder():
    state = capabilities_for("idw").native_kriging_std
    assert state is CapabilityState.NOT_APPLICABLE
    assert state is not None
    assert state != ""
    # 枚举只有两种状态：不存在用空数组/0/失败状态表达「不适用」的余地
    assert {item.value for item in CapabilityState} == {"supported", "not_applicable"}


def test_capability_records_are_immutable():
    record = capabilities_for("idw")
    assert isinstance(record, AlgorithmCapabilities)
    with pytest.raises(ValidationError):
        record.native_kriging_std = CapabilityState.SUPPORTED


def test_capabilities_for_rejects_unknown_algorithm():
    with pytest.raises(ValueError):
        capabilities_for("universal_kriging")


# ---------------------------------------------------------------------------
# DirectionSpec（§6.3）
# ---------------------------------------------------------------------------


def test_direction_spec_accepts_3d_with_explicit_tolerances():
    spec = DirectionSpec(
        dimension="3d",
        azimuth_deg=45,
        dip_deg=30,
        azimuth_tolerance_deg=10,
        dip_tolerance_deg=15,
    )
    assert spec.azimuth_deg == 45
    assert spec.dip_deg == 30
    assert spec.azimuth_tolerance_deg == 10
    assert spec.dip_tolerance_deg == 15


def test_direction_spec_2d_rejects_dip_and_dip_tolerance():
    with pytest.raises(ValidationError):
        DirectionSpec(dimension="2d", azimuth_deg=45, dip_deg=10)
    with pytest.raises(ValidationError):
        DirectionSpec(dimension="2d", azimuth_deg=45, dip_tolerance_deg=10)


def test_direction_spec_2d_rejects_roll_as_unknown_key():
    # 方向定义无滚转参数；extra="forbid" 直接拒绝
    with pytest.raises(ValidationError):
        DirectionSpec(dimension="2d", azimuth_deg=45, roll_deg=5)


def test_direction_spec_3d_requires_dip_and_dip_tolerance():
    with pytest.raises(ValidationError):
        DirectionSpec(dimension="3d", azimuth_deg=45)
    with pytest.raises(ValidationError):
        DirectionSpec(dimension="3d", azimuth_deg=45, dip_deg=0)


def test_direction_spec_azimuth_is_undirected_half_circle():
    DirectionSpec(dimension="2d", azimuth_deg=0)
    DirectionSpec(dimension="2d", azimuth_deg=179.999)
    # 方向无正反：180° 与 0° 同向，不予接受
    with pytest.raises(ValidationError):
        DirectionSpec(dimension="2d", azimuth_deg=180)
    with pytest.raises(ValidationError):
        DirectionSpec(dimension="2d", azimuth_deg=-1)


def test_direction_spec_dip_bounds():
    DirectionSpec(dimension="3d", azimuth_deg=10, dip_deg=-90, dip_tolerance_deg=10)
    DirectionSpec(dimension="3d", azimuth_deg=10, dip_deg=90, dip_tolerance_deg=10)
    with pytest.raises(ValidationError):
        DirectionSpec(dimension="3d", azimuth_deg=10, dip_deg=91, dip_tolerance_deg=10)
    with pytest.raises(ValidationError):
        DirectionSpec(dimension="3d", azimuth_deg=10, dip_deg=-91, dip_tolerance_deg=10)


def test_direction_spec_rejects_non_finite_angles():
    with pytest.raises(ValidationError):
        DirectionSpec(dimension="2d", azimuth_deg=math.nan)
    with pytest.raises(ValidationError):
        DirectionSpec(dimension="2d", azimuth_deg=math.inf)
    with pytest.raises(ValidationError):
        DirectionSpec(dimension="3d", azimuth_deg=10, dip_deg=math.nan, dip_tolerance_deg=10)


def test_direction_spec_tolerances_are_explicit_finite_positive():
    with pytest.raises(ValidationError):
        DirectionSpec(dimension="2d", azimuth_deg=10, azimuth_tolerance_deg=0)
    with pytest.raises(ValidationError):
        DirectionSpec(dimension="2d", azimuth_deg=10, azimuth_tolerance_deg=-5)
    with pytest.raises(ValidationError):
        DirectionSpec(dimension="2d", azimuth_deg=10, azimuth_tolerance_deg=math.nan)
    with pytest.raises(ValidationError):
        DirectionSpec(dimension="3d", azimuth_deg=10, dip_deg=0, dip_tolerance_deg=math.inf)


# ---------------------------------------------------------------------------
# NeighborhoodSpec（§8.1）
# ---------------------------------------------------------------------------


def test_neighborhood_rejects_impossible_sector_capacity():
    with pytest.raises(ValidationError):
        NeighborhoodSpec(
            radii=[100, 50, 25],
            azimuth_deg=30,
            dip_deg=10,
            roll_deg=0,
            min_neighbors=9,
            max_neighbors=16,
            sector_count=4,
            max_per_sector=2,
        )


def test_neighborhood_sector_capacity_boundary_is_inclusive():
    # 4 × 2 = 8 >= 8：恰好装得下最少邻点数时合法
    NeighborhoodSpec(radii=(100, 50), min_neighbors=8, max_neighbors=8, sector_count=4, max_per_sector=2)


def test_neighborhood_defaults_match_plan():
    spec = NeighborhoodSpec(radii=(100, 50))
    assert spec.azimuth_deg == 0
    assert spec.dip_deg is None
    assert spec.roll_deg is None
    assert spec.min_neighbors == 3
    assert spec.max_neighbors == 24
    assert spec.sector_count == 4
    assert spec.max_per_sector == 8


def test_neighborhood_rejects_min_greater_than_max():
    with pytest.raises(ValidationError):
        NeighborhoodSpec(radii=(100, 50), min_neighbors=5, max_neighbors=4)
    NeighborhoodSpec(radii=(100, 50), min_neighbors=4, max_neighbors=4)


def test_neighborhood_rejects_non_positive_or_non_finite_radii():
    for bad_radii in [(0, 50), (100, -1), (math.nan, 50), (100, math.inf), (100, 50, 0)]:
        with pytest.raises(ValidationError):
            NeighborhoodSpec(radii=bad_radii)


def test_neighborhood_rejects_wrong_radii_arity():
    with pytest.raises(ValidationError):
        NeighborhoodSpec(radii=(100,))
    with pytest.raises(ValidationError):
        NeighborhoodSpec(radii=(100, 50, 25, 10))


def test_neighborhood_2d_rejects_dip_and_roll():
    with pytest.raises(ValidationError):
        NeighborhoodSpec(radii=(100, 50), dip_deg=10)
    with pytest.raises(ValidationError):
        NeighborhoodSpec(radii=(100, 50), roll_deg=10)


def test_neighborhood_3d_accepts_dip_roll_within_bounds():
    NeighborhoodSpec(radii=(100, 50, 25), dip_deg=-90, roll_deg=180)
    NeighborhoodSpec(radii=(100, 50, 25), dip_deg=90, roll_deg=-180)
    with pytest.raises(ValidationError):
        NeighborhoodSpec(radii=(100, 50, 25), dip_deg=91)
    with pytest.raises(ValidationError):
        NeighborhoodSpec(radii=(100, 50, 25), roll_deg=181)


def test_neighborhood_rejects_non_finite_angles():
    with pytest.raises(ValidationError):
        NeighborhoodSpec(radii=(100, 50), azimuth_deg=math.nan)
    with pytest.raises(ValidationError):
        NeighborhoodSpec(radii=(100, 50, 25), dip_deg=math.inf)
    with pytest.raises(ValidationError):
        NeighborhoodSpec(radii=(100, 50, 25), roll_deg=math.nan)


def test_neighborhood_forbids_unknown_keys():
    with pytest.raises(ValidationError):
        NeighborhoodSpec(radii=(100, 50), smoothing=1)


# ---------------------------------------------------------------------------
# VariogramDiagnosticSpec（§6）
# ---------------------------------------------------------------------------


def test_variogram_diagnostic_defaults():
    spec = VariogramDiagnosticSpec()
    assert spec.lag_count == 12
    assert spec.max_distance is None
    assert spec.min_pairs_per_bin == 30
    assert spec.max_pairs == 50_000
    assert spec.directions == ()


def test_variogram_lag_count_bounds():
    VariogramDiagnosticSpec(lag_count=4)
    VariogramDiagnosticSpec(lag_count=48)
    with pytest.raises(ValidationError):
        VariogramDiagnosticSpec(lag_count=3)
    with pytest.raises(ValidationError):
        VariogramDiagnosticSpec(lag_count=49)


def test_variogram_max_distance_must_be_finite_positive():
    VariogramDiagnosticSpec(max_distance=250.0)
    with pytest.raises(ValidationError):
        VariogramDiagnosticSpec(max_distance=0)
    with pytest.raises(ValidationError):
        VariogramDiagnosticSpec(max_distance=-5)
    with pytest.raises(ValidationError):
        VariogramDiagnosticSpec(max_distance=math.inf)
    with pytest.raises(ValidationError):
        VariogramDiagnosticSpec(max_distance=math.nan)


def test_variogram_pair_caps():
    VariogramDiagnosticSpec(max_pairs=100, min_pairs_per_bin=2)
    with pytest.raises(ValidationError):
        VariogramDiagnosticSpec(max_pairs=99)
    with pytest.raises(ValidationError):
        VariogramDiagnosticSpec(max_pairs=500_001)
    with pytest.raises(ValidationError):
        VariogramDiagnosticSpec(min_pairs_per_bin=1)
    with pytest.raises(ValidationError):
        VariogramDiagnosticSpec(min_pairs_per_bin=10_001)


def test_variogram_directions_are_typed_specs():
    direction = DirectionSpec(dimension="2d", azimuth_deg=45)
    spec = VariogramDiagnosticSpec(directions=(direction,))
    assert spec.directions[0].azimuth_deg == 45
    with pytest.raises(ValidationError):
        VariogramDiagnosticSpec(directions=({"azimuth_deg": 45},))


def test_variogram_forbids_unknown_keys():
    with pytest.raises(ValidationError):
        VariogramDiagnosticSpec(robust=True)


# ---------------------------------------------------------------------------
# ZScaleSpec（IDW 权重距离，v0.5 语义）
# ---------------------------------------------------------------------------


def test_z_scale_default_matches_v05():
    assert ZScaleSpec().z_scale == 1.0


def test_z_scale_bounds():
    ZScaleSpec(z_scale=0.5)
    ZScaleSpec(z_scale=20.0)
    with pytest.raises(ValidationError):
        ZScaleSpec(z_scale=0)
    with pytest.raises(ValidationError):
        ZScaleSpec(z_scale=-1)
    with pytest.raises(ValidationError):
        ZScaleSpec(z_scale=20.5)


def test_z_scale_rejects_non_finite():
    with pytest.raises(ValidationError):
        ZScaleSpec(z_scale=math.inf)
    with pytest.raises(ValidationError):
        ZScaleSpec(z_scale=math.nan)


# ---------------------------------------------------------------------------
# EmpiricalUncertaintySpec（§10.2）
# ---------------------------------------------------------------------------


def test_empirical_uncertainty_supports_local_rmse_usage():
    spec = EmpiricalUncertaintySpec(min_neighbors=2, max_neighbors=2, power=2)
    assert spec.min_neighbors == 2
    assert spec.max_neighbors == 2
    assert spec.power == 2
    assert spec.neighborhood is None  # 默认复用候选搜索邻域


def test_empirical_uncertainty_rejects_inconsistent_neighbors():
    with pytest.raises(ValidationError):
        EmpiricalUncertaintySpec(min_neighbors=5, max_neighbors=4)


def test_empirical_uncertainty_power_must_be_finite_positive():
    with pytest.raises(ValidationError):
        EmpiricalUncertaintySpec(power=0)
    with pytest.raises(ValidationError):
        EmpiricalUncertaintySpec(power=math.nan)
    with pytest.raises(ValidationError):
        EmpiricalUncertaintySpec(power=math.inf)
    with pytest.raises(ValidationError):
        EmpiricalUncertaintySpec(power=9)


def test_empirical_uncertainty_explicit_neighborhood_is_typed():
    spec = EmpiricalUncertaintySpec(neighborhood={"radii": (100, 50)})
    assert isinstance(spec.neighborhood, NeighborhoodSpec)


def test_empirical_uncertainty_forbids_unknown_keys():
    with pytest.raises(ValidationError):
        EmpiricalUncertaintySpec(global_rmse_fallback=True)


# ---------------------------------------------------------------------------
# AnomalyExtractionSpec（§12.1）
# ---------------------------------------------------------------------------


def test_anomaly_extraction_minimal_usage():
    spec = AnomalyExtractionSpec(direction="high", threshold=9)
    assert spec.min_support_nodes == 1
    assert spec.empirical_error_max is None
    assert spec.kriging_std_max is None


def test_anomaly_direction_is_literal_high_or_low():
    AnomalyExtractionSpec(direction="low", threshold=9)
    with pytest.raises(ValidationError):
        AnomalyExtractionSpec(direction="up", threshold=9)


def test_anomaly_threshold_must_be_finite():
    AnomalyExtractionSpec(direction="low", threshold=-3.5)  # 负阈值是合法值阈值
    with pytest.raises(ValidationError):
        AnomalyExtractionSpec(direction="high", threshold=math.nan)
    with pytest.raises(ValidationError):
        AnomalyExtractionSpec(direction="high", threshold=math.inf)


def test_anomaly_uncertainty_gates_must_be_finite_positive():
    for field_name in ("empirical_error_max", "kriging_std_max"):
        for bad in (0, -1, math.inf, math.nan):
            with pytest.raises(ValidationError):
                AnomalyExtractionSpec(direction="high", threshold=9, **{field_name: bad})
        AnomalyExtractionSpec(direction="high", threshold=9, **{field_name: 2.5})


def test_anomaly_min_support_nodes_and_unknown_keys():
    with pytest.raises(ValidationError):
        AnomalyExtractionSpec(direction="high", threshold=9, min_support_nodes=0)
    with pytest.raises(ValidationError):
        AnomalyExtractionSpec(direction="high", threshold=9, color="red")


# ---------------------------------------------------------------------------
# platform.schemas 专业请求契约（API 层浅校验，严格校验在建模层）
# ---------------------------------------------------------------------------


def test_professional_diagnosis_request_is_shallow_and_strict():
    assert ProfessionalDiagnosisRequest().variogram == {}
    request = ProfessionalDiagnosisRequest(variogram={"lag_count": 8})
    assert request.variogram["lag_count"] == 8
    with pytest.raises(ValidationError):
        ProfessionalDiagnosisRequest(dataset_id="dv_1")  # 身份只能来自 URL 路径


def test_professional_confirmation_requires_exactly_one_choice():
    ProfessionalConfirmationRequest(keep_isotropic=True, note="保持各向同性")
    ProfessionalConfirmationRequest(anisotropy={"azimuth_deg": 45}, note="确认主方向")
    with pytest.raises(ValidationError):
        ProfessionalConfirmationRequest(note="什么都没选")
    with pytest.raises(ValidationError):
        ProfessionalConfirmationRequest(keep_isotropic=True, anisotropy={"azimuth_deg": 45}, note="矛盾")
    with pytest.raises(ValidationError):
        ProfessionalConfirmationRequest(keep_isotropic=True)  # note 必填
