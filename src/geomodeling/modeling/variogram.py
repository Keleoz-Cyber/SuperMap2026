"""Semivariogram models and bounded auto-fitting for local ordinary Kriging.

Three models (spherical / exponential / Gaussian) with explicit parameter
bounds. Empirical semivariograms use at most 50,000 deterministic pairs and
12 equal-width lag bins. Auto-fit is always executed inside a training
fold — never once on the full dataset before cross-validation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.distance import pdist, squareform

from geomodeling.platform.errors import PlatformError

VARIOGRAM_MODEL_UNKNOWN = "VARIOGRAM_MODEL_UNKNOWN"
VARIOGRAM_FIT_FAILED = "VARIOGRAM_FIT_FAILED"

MODELS = ("spherical", "exponential", "gaussian")
N_BINS = 12
MAX_PAIRS = 50_000


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
    """Equal-width lag binning; returns (centers, mean_gamma, pair_counts)."""

    coordinates = np.asarray(coordinates, dtype="float64")
    values = np.asarray(values, dtype="float64")
    dh, dv = _pair_distances(coordinates, values, seed, max_pairs)
    h_max = float(dh.max()) if dh.size else 1.0
    edges = np.linspace(0.0, h_max, n_bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2.0
    gammas = np.zeros(n_bins)
    counts = np.zeros(n_bins, dtype="int64")
    indices = np.clip(np.digitize(dh, edges) - 1, 0, n_bins - 1)
    for idx in range(n_bins):
        members = indices == idx
        counts[idx] = int(members.sum())
        gammas[idx] = float(dv[members].mean()) if counts[idx] else np.nan
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
