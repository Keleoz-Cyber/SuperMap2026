"""Task 2: deterministic bounded pair sampling (design §6.2).

总点对不超上限时全量（所有 ``i<j``、字典序）；超限时确定性分层抽样，
种子只来自数据 SHA-256 与诊断配置（``seed_from_contract``），不分配
``n×n`` 距离矩阵，有界批次内检查取消并抛出 ``RUN_CANCELED``。
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from geomodeling.modeling.pair_sampling import (
    PairSample,
    _draw_unique_ranks,
    sample_pairs,
    seed_from_contract,
)
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


def test_oversample_window_completes_without_coupon_collector(monkeypatch):
    """危险窗口回归：``max_pairs < total <= 4 * max_pairs`` 时 oversample_count == total。

    旧实现用 ``rng.integers`` 带放回重抽 + ``np.unique`` 去重补足，在该窗口退化为
    coupon-collector 循环（补足轮次随欠额减小而爆炸，实测挂起）。本测试用计数
    generator 断言实现不依赖反复重抽：初次抽取外加偶发补足，调用次数必须有界；
    旧实现会在第 5 次重抽时立即失败（毫秒级，跨平台，无需 signal/线程看门狗）。
    """

    n, max_pairs = 316, 49_000
    total = n * (n - 1) // 2  # 49_770，恰落在 (max_pairs, 4×max_pairs] 窗口内
    assert max_pairs < total <= 4 * max_pairs
    points = _points(n)  # 在打补丁前生成，避免包装器影响 fixture

    calls = 0
    real_default_rng = np.random.default_rng

    class _CountingGenerator:
        """只拦截 ``integers`` 计数，其余方法原样委托。"""

        def __init__(self, inner):
            self._inner = inner

        def integers(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls > 4:  # 初次抽取 + 偶发补足之外的重抽即 coupon-collector 退化
                raise AssertionError(
                    "pair-rank oversampling degenerated into a coupon-collector loop"
                )
            return self._inner.integers(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(
        np.random, "default_rng", lambda *a, **k: _CountingGenerator(real_default_rng(*a, **k))
    )

    result = sample_pairs(points, max_pairs=max_pairs, seed=7)
    assert result.sampled is True
    assert result.total_pair_count == total
    assert result.used_pair_count == max_pairs
    assert result.sampling_rate == pytest.approx(max_pairs / total)
    first, second = result.indices[:, 0], result.indices[:, 1]
    assert (first < second).all()  # 无反向点对
    assert np.unique(result.indices, axis=0).shape[0] == max_pairs  # 无重复点对
    order = np.lexsort((second, first))
    assert (order == np.arange(max_pairs)).all()  # 最终 (i, j) 字典序
    assert result.distance_strata.shape == (max_pairs,)
    # 与全量路径语义一致：选中点对是全集枚举的子集
    full = sample_pairs(points, max_pairs=total, seed=7)
    full_set = {tuple(row) for row in full.indices.tolist()}
    assert all(tuple(row) in full_set for row in result.indices.tolist())


def test_oversample_covering_total_returns_full_rank_universe():
    """oversample_count == total 的边界：ranks 必须是 ``0..total-1`` 全集
    （升序、无重复），与全量路径的点对全集语义一致，且任何 seed 下相同。"""

    total = 4_970
    expected = np.arange(total, dtype=np.int64)
    for seed in (0, 7, 2**63 - 1):
        ranks = _draw_unique_ranks(np.random.default_rng(seed), total, total)
        assert ranks.dtype == np.int64
        assert np.array_equal(ranks, expected)  # 点对全集、字典序、无重复
