"""Task 4: evidence-rich theoretical variogram fitting (design §6.4, §17).

按 bin 点对数加权的有界最小二乘拟合 ``EmpiricalBin``（只用
``used_for_fit=True`` 的 bin，权重 = bin 点对数 / 总使用点对数），披露
``weighted_sse``、边界、收敛状态、残差与参数来源。可用 bin < 3、优化器
不收敛、参数非有限或结构方差到达非法下边界时以 ``VARIOGRAM_FIT_FAILED``
结构化失败，不回退旧固定 12-bin 拟合。人工确认参数执行同样的有限性与
范围校验，证据标记 ``manual_confirmed``。
"""

from __future__ import annotations

import math
import types

import numpy as np
import pytest

from geomodeling.modeling.directional_variogram import EmpiricalBin
from geomodeling.modeling.variogram import (
    ManualVariogramParameters,
    VariogramFitEvidence,
    fit_variogram_evidence,
    semivariance,
)
from geomodeling.platform.errors import PlatformError


def _bin(
    lower: float,
    upper: float,
    gamma: float | None,
    count: int,
    *,
    used: bool = True,
    mean: float | None = None,
) -> EmpiricalBin:
    center = (lower + upper) / 2.0
    return EmpiricalBin(
        lower_distance=lower,
        upper_distance=upper,
        center_distance=center,
        mean_distance=center if mean is None else mean,
        semivariance=gamma,
        pair_count=count,
        used_for_fit=used,
        exclusion_reason=None if used else "insufficient_pairs",
        direction=None,
    )


def _curve_bins(
    gammas: list[float | None],
    counts: list[int],
    *,
    max_distance: float = 20.0,
    used_flags: list[bool] | None = None,
) -> tuple[EmpiricalBin, ...]:
    edges = np.linspace(0.0, max_distance, len(gammas) + 1)
    flags = used_flags if used_flags is not None else [True] * len(gammas)
    return tuple(
        _bin(
            float(edges[i]),
            float(edges[i + 1]),
            gammas[i],
            int(counts[i]),
            used=flags[i],
        )
        for i in range(len(gammas))
    )


@pytest.fixture
def valid_bins() -> tuple[EmpiricalBin, ...]:
    """球状真值 nugget=0.1 / partial_sill=1.0 / range=12 的 4 个可用 bin。"""

    means = np.array([2.5, 7.5, 12.5, 17.5])
    gammas = semivariance(means, "spherical", 0.1, 1.0, 12.0)
    return _curve_bins([float(g) for g in gammas], [40, 80, 120, 60])


# ---------------------------------------------------------------------------
# 自动拟合证据（§6.4：目标函数、边界、收敛状态、残差、参数来源）
# ---------------------------------------------------------------------------


def test_fit_reports_weighted_objective_bounds_and_origin(valid_bins):
    evidence = fit_variogram_evidence(valid_bins, model="spherical")
    assert evidence.parameter_origin == "automatic_candidate"
    assert evidence.converged is True
    assert evidence.weighted_sse >= 0
    assert evidence.sill == pytest.approx(evidence.nugget + evidence.partial_sill)
    assert evidence.used_bin_indices == [0, 1, 2, 3]
    assert set(evidence.bounds) == {"nugget", "partial_sill", "range"}
    for low, high in evidence.bounds.values():
        assert math.isfinite(low) and math.isfinite(high) and low < high
    assert len(evidence.residuals) == 4


def test_fit_recovers_generative_spherical_parameters(valid_bins):
    evidence = fit_variogram_evidence(valid_bins, model="spherical")
    assert evidence.nugget == pytest.approx(0.1, abs=1e-6)
    assert evidence.partial_sill == pytest.approx(1.0, abs=1e-6)
    assert evidence.range == pytest.approx(12.0, abs=1e-6)


def test_weighted_sse_and_residuals_match_pair_count_weights(valid_bins):
    """目标函数 = Σ (bin 点对数 / 总点对数) × 残差²；残差逐 bin 对齐。"""

    evidence = fit_variogram_evidence(valid_bins, model="spherical")
    used = [valid_bins[i] for i in evidence.used_bin_indices]
    total = sum(b.pair_count for b in used)
    h = np.array([b.mean_distance for b in used])
    gamma = np.array([b.semivariance for b in used])
    fitted = semivariance(
        h, evidence.model, evidence.nugget, evidence.partial_sill, evidence.range
    )
    weights = np.array([b.pair_count / total for b in used])
    expected = float(np.sum(weights * (fitted - gamma) ** 2))
    assert evidence.weighted_sse == pytest.approx(expected, rel=1e-9)
    assert evidence.residuals == pytest.approx(list(fitted - gamma))


def test_fit_is_pair_count_weighted_not_plain():
    """同一曲线不同点对权重产生不同的加权目标函数（区别于旧无加权拟合）。"""

    means = np.array([2.5, 7.5, 12.5, 17.5])
    gammas = semivariance(means, "spherical", 0.1, 1.0, 12.0) + np.array(
        [0.0, 0.3, -0.2, 0.1]
    )
    even = _curve_bins([float(g) for g in gammas], [50, 50, 50, 50])
    skewed = _curve_bins([float(g) for g in gammas], [5, 400, 5, 5])
    even_fit = fit_variogram_evidence(even, model="spherical")
    skewed_fit = fit_variogram_evidence(skewed, model="spherical")
    assert skewed_fit.weighted_sse != pytest.approx(even_fit.weighted_sse)
    # 权重集中在 bin 1 时，该 bin 的残差应被压到接近 0
    assert abs(skewed_fit.residuals[1]) < abs(even_fit.residuals[1])


def test_excluded_bins_are_skipped_not_filled():
    """``used_for_fit=False`` 的 bin 不进拟合（不外推、不填充），索引原样披露。"""

    means = np.array([2.5, 7.5, 12.5, 17.5, 22.5, 27.5])
    gammas = semivariance(means, "exponential", 0.2, 2.0, 9.0)
    flags = [True, False, True, True, False, True]
    bins = _curve_bins(
        [float(g) for g in gammas], [30, 5, 30, 30, 0, 30],
        max_distance=30.0, used_flags=flags,
    )
    evidence = fit_variogram_evidence(bins, model="exponential")
    assert evidence.used_bin_indices == [0, 2, 3, 5]
    assert len(evidence.residuals) == 4
    assert evidence.partial_sill == pytest.approx(2.0, abs=1e-6)


def test_fit_evidence_is_deterministic(valid_bins):
    first = fit_variogram_evidence(valid_bins, model="gaussian")
    second = fit_variogram_evidence(valid_bins, model="gaussian")
    assert first.model_dump_json() == second.model_dump_json()


# ---------------------------------------------------------------------------
# 结构化失败（§17：可用 bin 不足、不收敛、非有限、非法边界）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("used_count", [0, 1, 2])
def test_fewer_than_three_usable_bins_fail_structured(used_count):
    """可用 bin < 3 → VARIOGRAM_FIT_FAILED，不静默回退旧固定 12-bin 拟合。"""

    flags = [True] * used_count + [False] * (4 - used_count)
    bins = _curve_bins([0.5, 1.0, 1.5, 1.8], [40, 40, 3, 0], used_flags=flags)
    with pytest.raises(PlatformError) as excinfo:
        fit_variogram_evidence(bins, model="spherical")
    assert excinfo.value.code == "VARIOGRAM_FIT_FAILED"
    assert excinfo.value.details["used_bin_count"] == used_count
    assert excinfo.value.details["required_bin_count"] == 3


def test_optimizer_failure_is_structured(monkeypatch, valid_bins):
    """优化器不收敛 → VARIOGRAM_FIT_FAILED（携带优化器消息），不产出证据。"""

    def _forced_failure(*args, **kwargs):
        return types.SimpleNamespace(
            success=False,
            message="forced non-convergence",
            x=np.array([0.0, 1.0, 1.0]),
            cost=0.0,
        )

    monkeypatch.setattr(
        "geomodeling.modeling.variogram.least_squares", _forced_failure
    )
    with pytest.raises(PlatformError) as excinfo:
        fit_variogram_evidence(valid_bins, model="spherical")
    assert excinfo.value.code == "VARIOGRAM_FIT_FAILED"
    assert "forced non-convergence" in str(excinfo.value.details)


def test_non_finite_fitted_parameters_fail(monkeypatch, valid_bins):
    def _nan_result(*args, **kwargs):
        return types.SimpleNamespace(
            success=True,
            message="ok",
            x=np.array([math.nan, 1.0, 1.0]),
            cost=0.0,
        )

    monkeypatch.setattr("geomodeling.modeling.variogram.least_squares", _nan_result)
    with pytest.raises(PlatformError) as excinfo:
        fit_variogram_evidence(valid_bins, model="spherical")
    assert excinfo.value.code == "VARIOGRAM_FIT_FAILED"


@pytest.mark.parametrize(
    "pinned_x",
    [
        np.array([0.5, 1e-9, 5.0]),  # partial_sill 压在非法下边界（无结构）
        np.array([0.5, 0.5, 1e-9]),  # range 压在非法下边界
    ],
)
def test_boundary_pinned_parameters_fail(monkeypatch, valid_bins, pinned_x):
    """优化器把参数压到非法下边界 → VARIOGRAM_FIT_FAILED（不允许接受）。"""

    def _pinned_result(*args, **kwargs):
        return types.SimpleNamespace(
            success=True, message="ok", x=pinned_x, cost=0.0
        )

    monkeypatch.setattr("geomodeling.modeling.variogram.least_squares", _pinned_result)
    with pytest.raises(PlatformError) as excinfo:
        fit_variogram_evidence(valid_bins, model="spherical")
    assert excinfo.value.code == "VARIOGRAM_FIT_FAILED"


def test_unknown_model_rejected(valid_bins):
    with pytest.raises(PlatformError) as excinfo:
        fit_variogram_evidence(valid_bins, model="cubic")
    assert excinfo.value.code == "VARIOGRAM_MODEL_UNKNOWN"


# ---------------------------------------------------------------------------
# 人工确认参数（§6.4：同样的有限性与范围校验，标记 manual_confirmed）
# ---------------------------------------------------------------------------


def test_manual_parameters_marked_manual_confirmed(valid_bins):
    evidence = fit_variogram_evidence(
        valid_bins,
        model="spherical",
        manual_parameters=ManualVariogramParameters(nugget=0.1, sill=1.1, range=12.0),
    )
    assert evidence.parameter_origin == "manual_confirmed"
    assert evidence.nugget == pytest.approx(0.1)
    assert evidence.partial_sill == pytest.approx(1.0)
    assert evidence.sill == pytest.approx(1.1)
    assert evidence.range == pytest.approx(12.0)
    assert evidence.converged is True  # 人工路径无优化器
    assert evidence.weighted_sse == pytest.approx(0.0, abs=1e-15)  # 真值参数
    assert evidence.used_bin_indices == [0, 1, 2, 3]
    assert evidence.bounds == {}  # 无优化边界；参数域校验与自动路径一致


@pytest.mark.parametrize(
    "nugget,sill,range_",
    [
        (0.5, 0.5, 10.0),  # sill == nugget → partial_sill = 0
        (0.6, 0.5, 10.0),  # sill < nugget → partial_sill < 0
        (-0.1, 1.0, 10.0),  # nugget < 0
        (0.1, 1.1, 0.0),  # range = 0
        (0.1, 1.1, -3.0),  # range < 0
        (0.1, math.nan, 10.0),  # 非有限 sill
        (0.1, 1.1, math.inf),  # 非有限 range
        (math.nan, 1.1, 10.0),  # 非有限 nugget
    ],
)
def test_manual_parameters_reject_invalid_values(valid_bins, nugget, sill, range_):
    with pytest.raises(PlatformError) as excinfo:
        fit_variogram_evidence(
            valid_bins,
            model="spherical",
            manual_parameters=ManualVariogramParameters(
                nugget=nugget, sill=sill, range=range_
            ),
        )
    assert excinfo.value.code == "VARIOGRAM_FIT_FAILED"


def test_manual_mode_requires_at_least_one_used_bin():
    bins = _curve_bins([0.5, 1.0, 1.5], [2, 1, 0], used_flags=[False, False, False])
    with pytest.raises(PlatformError) as excinfo:
        fit_variogram_evidence(
            bins,
            model="spherical",
            manual_parameters=ManualVariogramParameters(nugget=0.1, sill=1.0, range=5.0),
        )
    assert excinfo.value.code == "VARIOGRAM_FIT_FAILED"


# ---------------------------------------------------------------------------
# 证据契约完整性
# ---------------------------------------------------------------------------


def test_evidence_contract_rejects_inconsistent_sill():
    with pytest.raises(ValueError):
        VariogramFitEvidence(
            model="spherical",
            nugget=0.5,
            partial_sill=1.0,
            sill=2.0,  # ≠ nugget + partial_sill
            range=10.0,
            weighted_sse=0.0,
            converged=True,
            parameter_origin="automatic_candidate",
            used_bin_indices=[0, 1, 2],
            bounds={
                "nugget": (0.0, 8.0),
                "partial_sill": (1e-9, 8.0),
                "range": (1e-9, 40.0),
            },
            residuals=[0.0, 0.0, 0.0],
        )
