"""Task 2: deterministic bounded pair sampling (design §6.2).

总点对不超上限时全量（所有 ``i<j``、字典序）；超限时确定性分层抽样，
种子只来自数据 SHA-256 与诊断配置（``seed_from_contract``），不分配
``n×n`` 距离矩阵，有界批次内检查取消并抛出 ``RUN_CANCELED``。
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from geomodeling.modeling.pair_sampling import PairSample, sample_pairs, seed_from_contract
from geomodeling.platform.errors import PlatformError


def _points(n: int, seed: int = 20260726) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(size=(n, 3)).astype(np.float64)


def _contract_config() -> bytes:
    return b'{"lag_count":12,"max_pairs":500}'


def test_small_dataset_uses_all_pairs_in_lexicographic_order():
    result = sample_pairs(np.arange(15, dtype=float).reshape(5, 3), max_pairs=50, seed=7)
    assert result.total_pair_count == 10
    assert result.sampled is False
    assert result.indices.tolist() == [
        [0, 1], [0, 2], [0, 3], [0, 4], [1, 2],
        [1, 3], [1, 4], [2, 3], [2, 4], [3, 4],
    ]
    assert result.indices.dtype == np.int64
    assert result.indices.shape == (10, 2)
    assert result.used_pair_count == 10
    assert result.sampling_rate == 1.0
    assert result.seed == 7
    assert result.distance_strata.shape == (10,)


def test_large_dataset_sampling_is_byte_deterministic():
    points = _points(400)
    data_sha = hashlib.sha256(points.tobytes()).hexdigest()
    config = _contract_config()
    first = sample_pairs(points, max_pairs=500, seed=seed_from_contract(data_sha, config))
    second = sample_pairs(points, max_pairs=500, seed=seed_from_contract(data_sha, config))
    assert first.indices.tobytes() == second.indices.tobytes()
    assert first.distance_strata.tobytes() == second.distance_strata.tobytes()
    assert np.unique(first.distance_strata).size > 1
    assert first.sampled is True


def test_sampled_path_hits_exact_cap_without_duplicate_or_reversed_pairs():
    points = _points(400)
    total = 400 * 399 // 2
    result = sample_pairs(points, max_pairs=500, seed=7)
    assert result.sampled is True
    assert result.total_pair_count == total
    assert result.used_pair_count == 500
    assert result.sampling_rate == pytest.approx(500 / total)
    assert result.seed == 7
    first, second = result.indices[:, 0], result.indices[:, 1]
    assert (first < second).all()  # 无反向点对
    assert np.unique(result.indices, axis=0).shape[0] == 500  # 无重复点对
    order = np.lexsort((second, first))
    assert (order == np.arange(500)).all()  # 最终 (i, j) 字典序
    assert result.distance_strata.shape == (500,)


def test_different_seed_changes_bounded_sample():
    points = _points(400)
    first = sample_pairs(points, max_pairs=500, seed=1)
    second = sample_pairs(points, max_pairs=500, seed=2)
    assert first.indices.tobytes() != second.indices.tobytes()


@pytest.mark.parametrize("n", [2, 3, 5, 100, 400])
def test_pair_count_formula(n):
    result = sample_pairs(_points(n), max_pairs=500, seed=11)
    assert result.total_pair_count == n * (n - 1) // 2


def test_total_equal_to_cap_uses_full_path():
    points = np.arange(30, dtype=float).reshape(10, 3)
    result = sample_pairs(points, max_pairs=45, seed=3)
    assert result.total_pair_count == 45
    assert result.sampled is False
    assert result.used_pair_count == 45
    assert result.sampling_rate == 1.0


def test_sampled_pairs_are_subset_of_full_enumeration():
    points = _points(40)
    full = sample_pairs(points, max_pairs=780, seed=9)
    sampled = sample_pairs(points, max_pairs=100, seed=9)
    assert sampled.sampled is True
    full_set = {tuple(row) for row in full.indices.tolist()}
    assert all(tuple(row) in full_set for row in sampled.indices.tolist())


def test_single_point_yields_empty_sample():
    result = sample_pairs(np.zeros((1, 3)), max_pairs=100, seed=1)
    assert result.total_pair_count == 0
    assert result.used_pair_count == 0
    assert result.sampled is False
    assert result.sampling_rate == 1.0
    assert result.indices.shape == (0, 2)
    assert result.indices.dtype == np.int64
    assert result.distance_strata.shape == (0,)


def test_two_dimensional_points_supported():
    points = np.arange(20, dtype=float).reshape(10, 2)
    result = sample_pairs(points, max_pairs=45, seed=5)
    assert result.used_pair_count == 45
    assert result.sampled is False


def test_cancellation_raises_run_canceled_on_sampled_path():
    with pytest.raises(PlatformError) as excinfo:
        sample_pairs(_points(400), max_pairs=500, seed=1, cancel=lambda: True)
    assert excinfo.value.code == "RUN_CANCELED"


def test_cancellation_raises_run_canceled_on_full_path():
    with pytest.raises(PlatformError) as excinfo:
        sample_pairs(_points(50), max_pairs=2000, seed=1, cancel=lambda: True)
    assert excinfo.value.code == "RUN_CANCELED"


def test_large_path_never_calls_pdist(monkeypatch):
    """内存有界证明：大数据路径不得调用 scipy pdist（全距离数组）。"""

    import scipy.spatial.distance

    def _boom(*args, **kwargs):
        raise AssertionError("pdist must not be called on the bounded path")

    monkeypatch.setattr(scipy.spatial.distance, "pdist", _boom)
    points = _points(400)
    result = sample_pairs(points, max_pairs=500, seed=seed_from_contract(
        hashlib.sha256(points.tobytes()).hexdigest(), _contract_config()
    ))
    assert result.used_pair_count == 500
    assert isinstance(result, PairSample)


def test_seed_from_contract_matches_documented_formula():
    data_sha = hashlib.sha256(b"points").hexdigest()
    config = _contract_config()
    digest = hashlib.sha256(data_sha.encode("ascii") + b"\0" + config).digest()
    expected = int.from_bytes(digest[:8], "big", signed=False)
    assert seed_from_contract(data_sha, config) == expected


def test_seed_from_contract_deterministic_and_config_sensitive():
    sha_a = hashlib.sha256(b"dataset-a").hexdigest()
    sha_b = hashlib.sha256(b"dataset-b").hexdigest()
    seed = seed_from_contract(sha_a, b"cfg-1")
    assert seed == seed_from_contract(sha_a, b"cfg-1")
    assert 0 <= seed < 2**64
    assert seed != seed_from_contract(sha_a, b"cfg-2")
    assert seed != seed_from_contract(sha_b, b"cfg-1")
