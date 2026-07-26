"""Task 4: bounded anisotropy candidate suggestions (design §7.1, §17).

``suggest_anisotropy`` 只比较 ``supported`` 方向拟合，返回至多 3 个候选
（主方向、次方向/垂向支持度、range 比例、使用的方向 bin 与点对数、稳定
性警告）。候选 status 恒为 ``diagnostic_suggestion``：平台不自动宣称地
质主方向、不写确认记录、不改实验参数。unsupported 方向只披露、不参与
候选比较。
"""

from __future__ import annotations

import numpy as np
import pytest

from geomodeling.modeling.directional_variogram import EmpiricalBin
from geomodeling.modeling.professional_contracts import DirectionSpec
from geomodeling.modeling.professional_diagnosis import (
    AnisotropySuggestion,
    DirectionalFit,
    suggest_anisotropy,
)
from geomodeling.modeling.variogram import (
    VariogramFitEvidence,
    fit_variogram_evidence,
    semivariance,
)

PAIRS_PER_BIN = 120
N_BINS = 6


def _direction(azimuth: float, dip: float | None = None, tolerance: float = 15.0) -> DirectionSpec:
    if dip is None:
        return DirectionSpec(
            dimension="2d", azimuth_deg=azimuth, azimuth_tolerance_deg=tolerance
        )
    return DirectionSpec(
        dimension="3d",
        azimuth_deg=azimuth,
        dip_deg=dip,
        azimuth_tolerance_deg=tolerance,
        dip_tolerance_deg=tolerance,
    )


def _supported_fit(
    direction_id: str,
    azimuth: float,
    range_: float,
    *,
    dip: float | None = None,
    max_distance: float = 60.0,
) -> DirectionalFit:
    """按指数真值曲线（nugget=0.1 / partial_sill=1.0）构造方向拟合证据。

    指数模型渐近逼近基台、无平台段，任意 range 在固定 bin 布局下均可
    辨识（球状模型短 range 时上升段 bin 过少会导致解不唯一）。
    """

    edges = np.linspace(0.0, max_distance, N_BINS + 1)
    means = (edges[:-1] + edges[1:]) / 2.0
    gammas = semivariance(means, "exponential", 0.1, 1.0, range_)
    direction = _direction(azimuth, dip)
    bins = tuple(
        EmpiricalBin(
            lower_distance=float(edges[i]),
            upper_distance=float(edges[i + 1]),
            center_distance=float(means[i]),
            mean_distance=float(means[i]),
            semivariance=float(gammas[i]),
            pair_count=PAIRS_PER_BIN,
            used_for_fit=True,
            exclusion_reason=None,
            direction=direction,
        )
        for i in range(N_BINS)
    )
    evidence = fit_variogram_evidence(bins, model="exponential")
    return DirectionalFit(
        direction_id=direction_id,
        direction=direction,
        status="supported",
        fit=evidence,
        used_pair_count=PAIRS_PER_BIN * N_BINS,
    )


def _unsupported(direction_id: str, azimuth: float, dip: float | None = None, pairs: int = 10) -> DirectionalFit:
    return DirectionalFit(
        direction_id=direction_id,
        direction=_direction(azimuth, dip),
        status="unsupported_insufficient_pairs",
        fit=None,
        used_pair_count=pairs,
    )


@pytest.fixture
def direction_fits() -> list[DirectionalFit]:
    return [
        _supported_fit("az000", 0.0, 30.0),
        _supported_fit("az090", 90.0, 10.0),
        _supported_fit("az045", 45.0, 12.0),
    ]


# ---------------------------------------------------------------------------
# 候选语义（§7.1：建议而非确认）
# ---------------------------------------------------------------------------


def test_direction_candidate_never_marks_itself_confirmed(direction_fits):
    result = suggest_anisotropy(direction_fits)
    assert result.candidates
    assert all(c.status == "diagnostic_suggestion" for c in result.candidates)


def test_major_direction_is_longest_range_with_ratio(direction_fits):
    result = suggest_anisotropy(direction_fits)
    assert isinstance(result, AnisotropySuggestion)
    top = result.candidates[0]
    assert top.rank == 1
    assert top.major_direction_id == "az000"
    assert top.major_azimuth_deg == pytest.approx(0.0)
    assert top.major_dip_deg is None  # 2D 无倾角
    assert top.secondary_direction_id == "az090"
    assert top.major_range == pytest.approx(30.0, rel=0.05)
    assert top.secondary_range == pytest.approx(10.0, rel=0.05)
    assert top.major_minor_range_ratio == pytest.approx(3.0, rel=0.1)
    assert top.used_direction_ids == ["az000", "az090"]
    assert top.used_bin_indices == [0, 1, 2, 3, 4, 5]
    assert top.used_pair_count == 2 * PAIRS_PER_BIN * N_BINS
    assert top.secondary_support_pairs == PAIRS_PER_BIN * N_BINS


def test_candidates_cover_distinct_majors_in_range_order(direction_fits):
    result = suggest_anisotropy(direction_fits)
    assert [c.major_direction_id for c in result.candidates] == [
        "az000",
        "az045",
        "az090",
    ]
    assert [c.rank for c in result.candidates] == [1, 2, 3]


def test_candidates_are_capped_at_three():
    fits = [
        _supported_fit(f"az{i:03d}", float(i), 30.0 - i * 0.1)
        for i in (0, 30, 60, 90, 120)
    ]
    result = suggest_anisotropy(fits)
    assert len(result.candidates) == 3
    assert result.compared_direction_ids == [
        "az000",
        "az030",
        "az060",
        "az090",
        "az120",
    ]


# ---------------------------------------------------------------------------
# unsupported 方向：披露但不参与比较
# ---------------------------------------------------------------------------


def test_unsupported_direction_is_disclosed_but_never_compared(direction_fits):
    fits = direction_fits + [_unsupported("az120", 120.0)]
    result = suggest_anisotropy(fits)
    assert result.skipped_direction_ids == ["az120"]
    assert "az120" not in result.compared_direction_ids
    assert all("az120" not in c.used_direction_ids for c in result.candidates)


def test_3d_vertical_support_and_ratio_reported():
    fits = [
        _supported_fit("h000", 0.0, 40.0, dip=0.0),
        _supported_fit("h090", 90.0, 20.0, dip=0.0),
        _supported_fit("v000", 0.0, 5.0, dip=90.0),
    ]
    result = suggest_anisotropy(fits)
    top = result.candidates[0]
    assert top.major_direction_id == "h000"
    assert top.secondary_direction_id == "h090"
    assert top.vertical_direction_id == "v000"
    assert top.vertical_range == pytest.approx(5.0, rel=0.05)
    assert top.major_vertical_range_ratio == pytest.approx(8.0, rel=0.1)
    assert top.vertical_support_pairs == PAIRS_PER_BIN * N_BINS
    assert top.used_direction_ids == ["h000", "h090", "v000"]


def test_3d_unsupported_vertical_marks_candidate_without_vertical():
    fits = [
        _supported_fit("h000", 0.0, 40.0, dip=0.0),
        _supported_fit("h090", 90.0, 20.0, dip=0.0),
        _unsupported("v000", 0.0, dip=90.0),
    ]
    result = suggest_anisotropy(fits)
    assert result.skipped_direction_ids == ["v000"]
    top = result.candidates[0]
    assert top.major_direction_id == "h000"
    assert top.secondary_direction_id == "h090"
    assert top.vertical_direction_id is None
    assert top.major_vertical_range_ratio is None
    assert "vertical_direction_unsupported" in top.warnings


# ---------------------------------------------------------------------------
# 退化支持与稳定性警告
# ---------------------------------------------------------------------------


def test_single_supported_direction_cannot_establish_anisotropy():
    result = suggest_anisotropy([_supported_fit("az000", 0.0, 30.0)])
    assert len(result.candidates) == 1
    only = result.candidates[0]
    assert only.status == "diagnostic_suggestion"
    assert only.secondary_direction_id is None
    assert only.major_minor_range_ratio is None
    assert "single_supported_direction" in only.warnings


def test_no_supported_direction_yields_zero_candidates():
    result = suggest_anisotropy(
        [_unsupported("az000", 0.0), _unsupported("az090", 90.0)]
    )
    assert result.candidates == []
    assert result.compared_direction_ids == []
    assert result.skipped_direction_ids == ["az000", "az090"]
    assert "no_supported_direction" in result.warnings


def test_range_pinned_at_disclosed_upper_bound_warns():
    pinned_evidence = VariogramFitEvidence(
        model="spherical",
        nugget=0.1,
        partial_sill=4.9,
        sill=5.0,
        range=120.0,  # == 披露上界：滞后窗内不可识别
        weighted_sse=0.01,
        converged=True,
        parameter_origin="automatic_candidate",
        used_bin_indices=[0, 1, 2, 3, 4, 5],
        bounds={
            "nugget": (0.0, 8.0),
            "partial_sill": (1e-9, 8.0),
            "range": (1e-9, 120.0),
        },
        residuals=[0.0] * 6,
    )
    pinned = DirectionalFit(
        direction_id="az000",
        direction=_direction(0.0),
        status="supported",
        fit=pinned_evidence,
        used_pair_count=PAIRS_PER_BIN * N_BINS,
    )
    result = suggest_anisotropy([pinned, _supported_fit("az090", 90.0, 10.0)])
    top = result.candidates[0]
    assert top.major_direction_id == "az000"
    assert "range_at_disclosed_upper_bound" in top.warnings


def test_weak_range_contrast_warns():
    fits = [
        _supported_fit("az000", 0.0, 10.5),
        _supported_fit("az090", 90.0, 10.0),
    ]
    result = suggest_anisotropy(fits)
    top = result.candidates[0]
    assert top.major_minor_range_ratio == pytest.approx(1.05, rel=0.05)
    assert "weak_range_contrast" in top.warnings


# ---------------------------------------------------------------------------
# 纯函数性与契约完整性
# ---------------------------------------------------------------------------


def test_suggestion_never_mutates_input_fits(direction_fits):
    before = [f.model_dump_json() for f in direction_fits]
    result = suggest_anisotropy(direction_fits)
    assert [f.model_dump_json() for f in direction_fits] == before
    assert isinstance(result, AnisotropySuggestion)


def test_supported_fit_requires_evidence():
    with pytest.raises(ValueError):
        DirectionalFit(
            direction_id="az000",
            direction=_direction(0.0),
            status="supported",
            fit=None,
            used_pair_count=0,
        )
