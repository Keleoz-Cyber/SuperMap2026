"""Task 7 variogram tests: models, bounds, binning, deterministic auto-fit."""

from __future__ import annotations

import numpy as np
import pytest


def test_semivariogram_zero_lag_and_sill():
    from geomodeling.modeling.variogram import semivariance

    for model in ("spherical", "exponential", "gaussian"):
        gamma = semivariance(np.array([0.0, 1e-12, 1000.0]), model, 0.5, 2.0, 10.0)
        assert gamma[0] == pytest.approx(0.5)  # zero-lag = nugget
        assert np.isfinite(gamma).all()
        assert gamma[2] == pytest.approx(2.5, rel=0.05)  # 远端 ≈ nugget + partial_sill
        assert gamma[1] >= gamma[0] - 1e-9


def test_semivariogram_rejects_bad_parameters():
    from geomodeling.modeling.variogram import semivariance

    h = np.array([1.0])
    with pytest.raises(Exception):
        semivariance(h, "spherical", -0.1, 1.0, 10.0)
    with pytest.raises(Exception):
        semivariance(h, "spherical", 0.0, 0.0, 10.0)
    with pytest.raises(Exception):
        semivariance(h, "spherical", 0.0, 1.0, 0.0)
    with pytest.raises(Exception):
        semivariance(h, "not-a-model", 0.0, 1.0, 10.0)


def test_empirical_semivariogram_deterministic_binning():
    from geomodeling.modeling.variogram import empirical_semivariogram

    rng = np.random.default_rng(4)
    coords = rng.uniform(0, 100, size=(60, 2))
    values = rng.normal(5.0, 2.0, 60)
    centers_a, gammas_a, counts_a = empirical_semivariogram(coords, values, n_bins=12, seed=7)
    centers_b, gammas_b, counts_b = empirical_semivariogram(coords, values, n_bins=12, seed=7)
    np.testing.assert_array_equal(centers_a, centers_b)
    np.testing.assert_allclose(gammas_a, gammas_b)
    np.testing.assert_array_equal(counts_a, counts_b)
    assert len(centers_a) == 12
    assert counts_a.sum() == 60 * 59 // 2


def test_empirical_semivariogram_pair_cap_is_deterministic():
    from geomodeling.modeling.variogram import empirical_semivariogram

    rng = np.random.default_rng(5)
    coords = rng.uniform(0, 100, size=(400, 2))
    values = rng.normal(0.0, 1.0, 400)
    total_pairs = 400 * 399 // 2
    assert total_pairs > 50_000
    _, _, counts_a = empirical_semivariogram(coords, values, n_bins=12, seed=11, max_pairs=50_000)
    _, _, counts_b = empirical_semivariogram(coords, values, n_bins=12, seed=11, max_pairs=50_000)
    assert counts_a.sum() <= 50_000
    np.testing.assert_array_equal(counts_a, counts_b)


def test_auto_fit_recovers_spherical_parameters():
    from geomodeling.modeling.variogram import fit_variogram

    rng = np.random.default_rng(20260723)
    coords = rng.uniform(0, 200, size=(300, 2))
    # 用已知变异函数生成相关场（距离越近越相似）
    coords_sorted = coords[np.argsort(coords[:, 0])]
    base = np.sin(coords_sorted[:, 0] / 40.0) * 3.0
    noise = rng.normal(0, 0.2, 300)
    values = base + noise
    fitted = fit_variogram(coords_sorted, values, "spherical", seed=13)
    assert fitted.nugget >= 0
    assert fitted.partial_sill > 0
    assert fitted.range > 0
    assert np.isfinite(fitted.nugget + fitted.partial_sill)
    assert fitted.partial_sill > fitted.nugget  # 该数据应有明显结构方差
