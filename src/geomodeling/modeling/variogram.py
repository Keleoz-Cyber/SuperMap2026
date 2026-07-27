"""Semivariogram models and bounded auto-fitting for local ordinary Kriging.

Three models (spherical / exponential / Gaussian) with explicit parameter
bounds. Empirical semivariograms use at most 50,000 deterministic pairs and
12 equal-width lag bins. Auto-fit is always executed inside a training
fold — never once on the full dataset before cross-validation.

Lag binning is delegated to the shared typed core
:func:`geomodeling.modeling.directional_variogram.bin_pair_distances`
(v0.6): pairs exactly on an interior edge join the lower bin (pre-v0.6
``np.digitize`` put them in the upper bin — a measure-zero difference for
continuous data), and the legacy nearest-non-empty fill keeps all
``n_bins`` entries finite for the unweighted fit, preserving v0.5 numerics.

v0.6 adds the evidence-rich fit :func:`fit_variogram_evidence` (design
§6.4): pair-count-weighted bounded least squares over disclosed
``EmpiricalBin`` records (``used_for_fit=True`` only, actual mean distance
as abscissa), reporting the weighted objective, finite bounds, convergence
status, per-bin residuals and the parameter origin. Fewer than three usable
bins, optimizer non-convergence, non-finite parameters or a structural
variance pinned at the invalid lower boundary fail structured with
``VARIOGRAM_FIT_FAILED`` — never a silent fallback to the legacy fixed
12-bin fit. Manual confirmations run the same finiteness/range validation
and are marked ``manual_confirmed``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from pydantic import ConfigDict, model_validator
from scipy.optimize import least_squares
from scipy.spatial.distance import pdist, squareform

from geomodeling.modeling.directional_variogram import (
    EmpiricalBin,
    bin_pair_distances,
)
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.schemas import ContractModel

VARIOGRAM_MODEL_UNKNOWN = "VARIOGRAM_MODEL_UNKNOWN"
VARIOGRAM_FIT_FAILED = "VARIOGRAM_FIT_FAILED"

MODELS = ("spherical", "exponential", "gaussian")
N_BINS = 12
MAX_PAIRS = 50_000

#: 加权证据拟合的最少可用 bin 数（3 参数可辨识下限；§6.1/§17）。
MIN_FIT_BINS = 3

# 优化器参数下边界（与 legacy 一致）；落到该边界视为非法边界。
_FIT_PARAM_FLOOR = 1e-9
# 结构方差占 sill 的比例低于该值视为「无结构」非法下边界。
_RELATIVE_STRUCTURE_FLOOR = 1e-6
# 披露上界：sill 上限 = 4 × 最大使用 bin 半变异值（有限，可 JSON 序列化）。
_SILL_CAP_FACTOR = 4.0
# 披露上界：range 上限 = 2 × 使用 bin 最大平均距离（与 legacy 约定一致）。
_RANGE_SPAN_FACTOR = 2.0


@dataclass(frozen=True)
class VariogramModel:
    model: str
    nugget: float
    partial_sill: float
    range: float


def semivariance(
    h: np.ndarray,
    model: str,
    nugget: float,
    partial_sill: float,
    range_: float,
) -> np.ndarray:
    """Evaluate a semivariogram model; parameters are bounds-checked."""

    if model not in MODELS:
        raise PlatformError(VARIOGRAM_MODEL_UNKNOWN, f"未知变异函数模型：{model}")
    if nugget < 0:
        raise PlatformError(VARIOGRAM_FIT_FAILED, "nugget 必须 ≥ 0")
    if partial_sill <= 0:
        raise PlatformError(VARIOGRAM_FIT_FAILED, "partial_sill 必须 > 0")
    if range_ <= 0:
        raise PlatformError(VARIOGRAM_FIT_FAILED, "range 必须 > 0")
    if not np.isfinite(nugget + partial_sill):
        raise PlatformError(VARIOGRAM_FIT_FAILED, "nugget + partial_sill 必须有限")

    h = np.asarray(h, dtype="float64")
    if model == "spherical":
        r = np.minimum(h / range_, 1.0)
        return nugget + partial_sill * np.where(r < 1.0, 1.5 * r - 0.5 * r**3, 1.0)
    if model == "exponential":
        return nugget + partial_sill * (1.0 - np.exp(-h / range_))
    return nugget + partial_sill * (1.0 - np.exp(-((h / range_) ** 2)))


def _pair_distances(
    coordinates: np.ndarray, values: np.ndarray, seed: int, max_pairs: int
) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic pair distances/semivariances, capped at ``max_pairs``."""

    n = len(values)
    total = n * (n - 1) // 2
    if total <= max_pairs:
        dh = pdist(coordinates)
        dv = pdist(values[:, None]) ** 2 / 2.0
        return dh, dv
    rng = np.random.default_rng(seed)
    first = rng.integers(0, n, size=max_pairs)
    second = rng.integers(0, n, size=max_pairs)
    keep = first != second
    first, second = first[keep], second[keep]
    dh = np.linalg.norm(coordinates[first] - coordinates[second], axis=1)
    dv = (values[first] - values[second]) ** 2 / 2.0
    return dh, dv


def empirical_semivariogram(
    coordinates: np.ndarray,
    values: np.ndarray,
    *,
    n_bins: int = N_BINS,
    max_pairs: int = MAX_PAIRS,
    seed: int = 20260723,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Equal-width lag binning; returns (centers, mean_gamma, pair_counts).

    分箱委托 ``directional_variogram.bin_pair_distances``（点对恰在内部
    边界时归入下侧 bin；与旧 ``np.digitize`` 的上侧归属仅在测度零的
    边界命中时不同）。空桶仍按最近非空桶填充，保证拟合输入有限。
    """

    coordinates = np.asarray(coordinates, dtype="float64")
    values = np.asarray(values, dtype="float64")
    dh, dv = _pair_distances(coordinates, values, seed, max_pairs)
    h_max = float(dh.max()) if dh.size else 1.0
    if h_max <= 0.0:
        h_max = 1.0  # 全重合退化输入：保持非失败路径（分箱核心要求递增边界）
    edges = np.linspace(0.0, h_max, n_bins + 1)
    bins = bin_pair_distances(dh, dv, edges, min_pairs_per_bin=1)
    centers = np.fromiter((b.center_distance for b in bins), dtype="float64", count=n_bins)
    counts = np.fromiter((b.pair_count for b in bins), dtype="int64", count=n_bins)
    gammas = np.array(
        [b.semivariance if b.semivariance is not None else np.nan for b in bins],
        dtype="float64",
    )
    # 空桶用最近非空桶的 gamma 填充，保证拟合输入有限
    valid = counts > 0
    if not valid.any():
        raise PlatformError(VARIOGRAM_FIT_FAILED, "经验变异函数无有效滞后桶")
    nearest = np.interp(np.arange(n_bins), np.nonzero(valid)[0], gammas[valid])
    gammas = np.where(valid, gammas, nearest)
    return centers, gammas, counts


def fit_variogram(
    coordinates: np.ndarray,
    values: np.ndarray,
    model: str,
    *,
    seed: int = 20260723,
) -> VariogramModel:
    """Bounded least-squares auto-fit of one semivariogram model."""

    if model not in MODELS:
        raise PlatformError(VARIOGRAM_MODEL_UNKNOWN, f"未知变异函数模型：{model}")
    coordinates = np.asarray(coordinates, dtype="float64")
    values = np.asarray(values, dtype="float64")
    centers, gammas, _ = empirical_semivariogram(coordinates, values, seed=seed)

    span = float(centers.max()) if centers.size else 1.0
    variance = float(np.var(values)) if len(values) > 1 else 1.0
    initial = np.array([0.0, max(variance, 1e-6), max(span / 3.0, 1e-6)])

    def residuals(params: np.ndarray) -> np.ndarray:
        nugget, partial_sill, range_ = params
        return semivariance(centers, model, nugget, partial_sill, range_) - gammas

    result = least_squares(
        residuals,
        initial,
        bounds=([0.0, 1e-9, 1e-9], [np.inf, np.inf, max(span * 2.0, 1e-6)]),
    )
    if not result.success:
        raise PlatformError(VARIOGRAM_FIT_FAILED, f"变异函数拟合失败：{result.message}")
    nugget, partial_sill, range_ = (float(p) for p in result.x)
    if not np.isfinite(nugget + partial_sill):
        raise PlatformError(VARIOGRAM_FIT_FAILED, "拟合结果非有限")
    return VariogramModel(model=model, nugget=nugget, partial_sill=partial_sill, range=range_)


class VariogramFitEvidence(ContractModel):
    """一次理论变异函数拟合的不可变证据（设计 §6.4）。

    在实施计划列出的十项字段之外按 §6.4「保存…残差」增加
    ``residuals``（拟合值 − 经验值，与 ``used_bin_indices`` 对齐）。
    ``sill`` 恒等于 ``nugget + partial_sill``；``bounds`` 全为有限值
    （inf 会被 JSON 序列化为 null，失去披露意义）。``parameter_origin``
    四值语义见 §6.4：本模块只产生 ``automatic_candidate``（加权自动
    拟合）与 ``manual_confirmed``（人工确认校验路径）；
    ``legacy_auto_fold_fit``/``final_full_data_fit`` 由后续任务标记。
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True, frozen=True)

    model: Literal["spherical", "exponential", "gaussian"]
    nugget: float
    partial_sill: float
    sill: float
    range: float
    weighted_sse: float
    converged: bool
    parameter_origin: Literal[
        "automatic_candidate",
        "manual_confirmed",
        "legacy_auto_fold_fit",
        "final_full_data_fit",
    ]
    used_bin_indices: list[int]
    bounds: dict[str, tuple[float, float]]
    residuals: list[float]

    @model_validator(mode="after")
    def _check_evidence(self) -> "VariogramFitEvidence":
        for name in ("nugget", "partial_sill", "sill", "range", "weighted_sse"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} 必须为有限值")
        if self.nugget < 0:
            raise ValueError("nugget 必须 ≥ 0")
        if self.partial_sill <= 0:
            raise ValueError("partial_sill 必须 > 0")
        if self.range <= 0:
            raise ValueError("range 必须 > 0")
        if self.weighted_sse < 0:
            raise ValueError("weighted_sse 必须 ≥ 0")
        expected = self.nugget + self.partial_sill
        if abs(self.sill - expected) > 1e-9 * max(1.0, abs(expected)):
            raise ValueError("sill 必须等于 nugget + partial_sill")
        if len(self.residuals) != len(self.used_bin_indices):
            raise ValueError("residuals 必须与 used_bin_indices 等长")
        return self


class ManualVariogramParameters(ContractModel):
    """人工确认的变异函数参数（``sill`` 为总基台值，与 v0.5 manual 语义一致）。

    字段本身不设数值约束：有限性与范围校验统一在
    :func:`fit_variogram_evidence` 内以 ``VARIOGRAM_FIT_FAILED`` 结构化
    失败（与自动路径同一失败通道），而不是散落的 pydantic ValueError。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    nugget: float
    sill: float
    range: float


def _used_fit_bins(
    bins: Sequence[EmpiricalBin], *, required: int
) -> tuple[list[int], np.ndarray, np.ndarray, np.ndarray]:
    """收集 ``used_for_fit=True`` 的 bin；不足 ``required`` 个时结构化失败。"""

    used = [(index, bin_) for index, bin_ in enumerate(bins) if bin_.used_for_fit]
    if len(used) < required:
        raise PlatformError(
            VARIOGRAM_FIT_FAILED,
            "可用于拟合的 bin 不足，且不允许回退旧固定 12-bin 拟合",
            {"used_bin_count": len(used), "required_bin_count": required},
        )
    indices = [index for index, _ in used]
    h = np.array([float(bin_.mean_distance) for _, bin_ in used], dtype="float64")
    gamma = np.array(
        [float(bin_.semivariance) if bin_.semivariance is not None else math.nan for _, bin_ in used],
        dtype="float64",
    )
    counts = np.array([bin_.pair_count for _, bin_ in used], dtype="float64")
    if not np.isfinite(h).all() or not np.isfinite(gamma).all() or (counts <= 0).any():
        raise PlatformError(
            VARIOGRAM_FIT_FAILED,
            "参与拟合的 bin 缺少有限平均距离/半变异值或点对数",
            {"used_bin_indices": indices},
        )
    return indices, h, gamma, counts


def _validate_manual_parameters(manual: ManualVariogramParameters) -> tuple[float, float, float]:
    """人工参数的有限性与范围校验（§6.4：与自动拟合同一失败通道）。"""

    nugget = float(manual.nugget)
    sill = float(manual.sill)
    range_ = float(manual.range)
    for name, value in (("nugget", nugget), ("sill", sill), ("range", range_)):
        if not math.isfinite(value):
            raise PlatformError(
                VARIOGRAM_FIT_FAILED, f"人工变异函数参数必须为有限值：{name}"
            )
    if nugget < 0:
        raise PlatformError(VARIOGRAM_FIT_FAILED, "nugget 必须 ≥ 0")
    if sill <= nugget:
        raise PlatformError(
            VARIOGRAM_FIT_FAILED, "manual 模式要求 sill（总基台值）严格大于 nugget"
        )
    if range_ <= 0:
        raise PlatformError(VARIOGRAM_FIT_FAILED, "range 必须 > 0")
    return nugget, sill, range_


def fit_variogram_evidence(
    bins: Sequence[EmpiricalBin],
    model: str,
    *,
    manual_parameters: ManualVariogramParameters | None = None,
) -> VariogramFitEvidence:
    """对披露的经验 bin 做加权有界最小二乘拟合，返回完整证据（§6.4）。

    只使用 ``used_for_fit=True`` 的 bin，横坐标取实际平均距离，权重为
    bin 点对数占总使用点对数的比例。自动路径要求至少 ``MIN_FIT_BINS``
    个可用 bin；优化器不收敛、参数非有限、``partial_sill`` 或 ``range``
    到达非法下边界（结构方差占比 < 1e-6 视为无结构）均以
    ``VARIOGRAM_FIT_FAILED`` 结构化失败。人工路径跳过优化器，对确认参数
    执行同样的有限性/范围校验并仍按同一权重披露 ``weighted_sse`` 与残差
    （至少 1 个可用 bin），证据标记 ``manual_confirmed``。
    """

    if model not in MODELS:
        raise PlatformError(VARIOGRAM_MODEL_UNKNOWN, f"未知变异函数模型：{model}")
    manual = manual_parameters is not None
    indices, h, gamma, counts = _used_fit_bins(bins, required=1 if manual else MIN_FIT_BINS)
    weights = counts / counts.sum()

    if manual:
        nugget, sill, range_ = _validate_manual_parameters(manual_parameters)
        partial_sill = sill - nugget
        residuals = semivariance(h, model, nugget, partial_sill, range_) - gamma
        return VariogramFitEvidence(
            model=model,
            nugget=nugget,
            partial_sill=partial_sill,
            sill=sill,
            range=range_,
            weighted_sse=float(np.sum(weights * residuals**2)),
            converged=True,  # 人工路径无优化器
            parameter_origin="manual_confirmed",
            used_bin_indices=indices,
            bounds={},  # 无优化边界；参数域校验与自动路径一致
            residuals=[float(r) for r in residuals],
        )

    span = float(h.max())
    sill_cap = max(float(gamma.max()) * _SILL_CAP_FACTOR, 1e-6)
    range_upper = max(span * _RANGE_SPAN_FACTOR, 1e-6)
    lower = (0.0, _FIT_PARAM_FLOOR, _FIT_PARAM_FLOOR)
    upper = (sill_cap, sill_cap, range_upper)
    initial = np.array([0.0, max(float(gamma.max()), 1e-6), max(span / 3.0, 1e-6)])
    sqrt_weights = np.sqrt(weights)

    def weighted_residuals(params: np.ndarray) -> np.ndarray:
        nugget, partial_sill, range_ = params
        return sqrt_weights * (
            semivariance(h, model, nugget, partial_sill, range_) - gamma
        )

    result = least_squares(weighted_residuals, initial, bounds=(lower, upper))
    if not result.success:
        raise PlatformError(
            VARIOGRAM_FIT_FAILED,
            f"变异函数加权拟合不收敛：{result.message}",
            {"optimizer_message": str(result.message)},
        )
    nugget, partial_sill, range_ = (float(p) for p in result.x)
    sill = nugget + partial_sill
    if not all(math.isfinite(p) for p in (nugget, partial_sill, range_, sill)):
        raise PlatformError(VARIOGRAM_FIT_FAILED, "拟合参数非有限")
    if (
        partial_sill <= _FIT_PARAM_FLOOR
        or partial_sill <= _RELATIVE_STRUCTURE_FLOOR * sill
    ):
        raise PlatformError(
            VARIOGRAM_FIT_FAILED,
            "结构方差到达非法下边界（partial_sill ≈ 0，数据无可用空间结构）",
            {"nugget": nugget, "partial_sill": partial_sill, "range": range_},
        )
    if range_ <= _FIT_PARAM_FLOOR:
        raise PlatformError(
            VARIOGRAM_FIT_FAILED,
            "range 到达非法下边界（≈ 0）",
            {"nugget": nugget, "partial_sill": partial_sill, "range": range_},
        )
    residuals = semivariance(h, model, nugget, partial_sill, range_) - gamma
    weighted_sse = float(np.sum(weights * residuals**2))
    if not math.isfinite(weighted_sse):
        raise PlatformError(VARIOGRAM_FIT_FAILED, "加权目标函数非有限")
    return VariogramFitEvidence(
        model=model,
        nugget=nugget,
        partial_sill=partial_sill,
        sill=sill,
        range=range_,
        weighted_sse=weighted_sse,
        converged=True,
        parameter_origin="automatic_candidate",
        used_bin_indices=indices,
        bounds={
            "nugget": (lower[0], upper[0]),
            "partial_sill": (lower[1], upper[1]),
            "range": (lower[2], upper[2]),
        },
        residuals=[float(r) for r in residuals],
    )
