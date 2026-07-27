"""Task 3: omnidirectional/directional empirical variograms (design §6).

经典经验半变异函数 γ(h) = (1/2N(h)) Σ[Z(xi)−Z(xj)]²，点对来自 Task 2
``sample_pairs``（种子 ``seed_from_contract(data_sha256, canonical_config)``）。
bin 区间以 ``linspace(0, max_distance, lag_count+1)`` 为界；恰好落在内部
边界上的点对归入下侧 bin（与实施计划 Task 3 手算示例一致），最后一个 bin
闭右端，超出 ``max_distance`` 的点对不进入任何 bin。低于
``min_pairs_per_bin`` 的 bin 披露半变异值但不进拟合；方向 bin 点对不足时
标记 unsupported，不外推。

注：计划 Task 3 示例原文使用 ``lag_count=2, min_pairs_per_bin=1``，但
Task 1 已提交契约固定 ``lag_count ≥ 4``、``min_pairs_per_bin ≥ 2``
（tests/test_professional_contracts.py），因此手算测试改用
``lag_count=4, min_pairs_per_bin=2``，数值与示例完全等价（bin 索引平移）。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from geomodeling.modeling.directional_variogram import (
    EmpiricalBin,
    EmpiricalVariogram,
    compute_empirical_variogram,
)
from geomodeling.modeling.pair_sampling import seed_from_contract
from geomodeling.modeling.professional_contracts import (
    DirectionSpec,
    VariogramDiagnosticSpec,
)
from geomodeling.platform.errors import PlatformError

DATA_SHA = "0" * 64


def _line_points() -> tuple[np.ndarray, np.ndarray]:
    """三点共线手算夹具：点对距离 {1, 2, 1}，半变异 {2, 8, 2}。"""

    points = np.array([[0, 0], [1, 0], [2, 0]], dtype=float)
    values = np.array([0, 2, 4], dtype=float)
    return points, values


def test_empirical_variogram_matches_hand_calculation():
    """计划 Task 3 手算示例（按契约合法参数平移 bin 索引）。

    edges = [0, 0.5, 1, 1.5, 2]；d=1 的两个点对（γ=2）落入 bin 1，
    d=2 的点对（γ=8）落入闭右端的 bin 3。
    """

    points, values = _line_points()
    spec = VariogramDiagnosticSpec(lag_count=4, max_distance=2, min_pairs_per_bin=2)
    result = compute_empirical_variogram(
        points, values, spec, data_sha256=DATA_SHA, cancel=lambda: False
    )
    omni = result.omnidirectional
    assert len(omni) == 4
    assert omni[0].pair_count == 0
    assert omni[1].pair_count == 2
    assert omni[1].semivariance == pytest.approx(2.0)
    assert omni[3].pair_count == 1
    assert omni[3].semivariance == pytest.approx(8.0)


def test_bin_metadata_fields_are_disclosed():
    """每个 bin 披露下界/上界/中心、实际平均距离、点对数与拟合归属。"""

    points, values = _line_points()
    spec = VariogramDiagnosticSpec(lag_count=4, max_distance=2, min_pairs_per_bin=2)
    result = compute_empirical_variogram(
        points, values, spec, data_sha256=DATA_SHA, cancel=lambda: False
    )
    used = result.omnidirectional[1]
    assert isinstance(used, EmpiricalBin)
    assert used.lower_distance == pytest.approx(0.5)
    assert used.upper_distance == pytest.approx(1.0)
    assert used.center_distance == pytest.approx(0.75)
    assert used.mean_distance == pytest.approx(1.0)
    assert used.used_for_fit is True
    assert used.exclusion_reason is None
    assert used.direction is None  # 全向 bin 不携带方向

    empty = result.omnidirectional[0]
    assert empty.pair_count == 0
    assert empty.semivariance is None
    assert math.isnan(empty.mean_distance)
    assert empty.used_for_fit is False
    assert empty.exclusion_reason == "empty_bin"

    insufficient = result.omnidirectional[3]
    assert insufficient.used_for_fit is False
    assert insufficient.exclusion_reason == "insufficient_pairs"
    assert insufficient.semivariance == pytest.approx(8.0)  # 披露但不进拟合
    assert insufficient.mean_distance == pytest.approx(2.0)


def test_interior_boundary_pairs_join_lower_bin_and_final_bin_is_closed():
    """恰好等于内部边界的距离归入下侧 bin；d == max_distance 落入末 bin。"""

    points = np.array([[0, 0], [0.5, 0], [1.0, 0], [1.5, 0], [2.0, 0]], dtype=float)
    values = np.arange(5, dtype=float)
    spec = VariogramDiagnosticSpec(lag_count=4, max_distance=2, min_pairs_per_bin=2)
    result = compute_empirical_variogram(
        points, values, spec, data_sha256=DATA_SHA, cancel=lambda: False
    )
    # 距离 0.5×4、1.0×3、1.5×2、2.0×1：边界值全部归入下侧（首个 bin 含 0）
    assert [b.pair_count for b in result.omnidirectional] == [4, 3, 2, 1]


def test_max_distance_defaults_to_max_sampled_pair_distance():
    points, values = _line_points()
    spec = VariogramDiagnosticSpec(lag_count=4, min_pairs_per_bin=2)
    result = compute_empirical_variogram(
        points, values, spec, data_sha256=DATA_SHA, cancel=lambda: False
    )
    assert result.omnidirectional[-1].upper_distance == pytest.approx(2.0)
    assert sum(b.pair_count for b in result.omnidirectional) == 3


def test_pairs_beyond_max_distance_are_excluded_from_all_bins():
    points, values = _line_points()
    spec = VariogramDiagnosticSpec(lag_count=4, max_distance=1.5, min_pairs_per_bin=2)
    result = compute_empirical_variogram(
        points, values, spec, data_sha256=DATA_SHA, cancel=lambda: False
    )
    # d=2 的点对超出 max_distance，不被夹入末 bin
    assert sum(b.pair_count for b in result.omnidirectional) == 2
    assert result.omnidirectional[2].pair_count == 2  # edges (0.75, 1.125]
    assert result.omnidirectional[2].semivariance == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# 方向归属（§6.3：无向锐角；2D 仅方位角；3D 方位角+倾角）
# ---------------------------------------------------------------------------


def test_direction_azimuth_treats_d_and_minus_d_as_same_direction():
    """+X 与 -X 的点对属于同一方向（无向方位角）。"""

    points = np.array([[0, 0], [1, 0], [-1, 0], [0, 1]], dtype=float)
    values = np.array([0.0, 1.0, 1.0, 5.0])
    spec = VariogramDiagnosticSpec(
        lag_count=4,
        max_distance=2,
        min_pairs_per_bin=2,
        directions=(DirectionSpec(dimension="2d", azimuth_deg=0, azimuth_tolerance_deg=10),),
    )
    result = compute_empirical_variogram(
        points, values, spec, data_sha256=DATA_SHA, cancel=lambda: False
    )
    direction_bins = result.directional[0]
    assert all(b.direction == spec.directions[0] for b in direction_bins)
    # X 轴点对：(0,1)、(0,2) 距离 1（γ=0.5 各）→ bin 1；(1,2) 距离 2 → bin 3
    assert direction_bins[1].pair_count == 2
    assert direction_bins[1].semivariance == pytest.approx(0.5)
    assert direction_bins[1].used_for_fit is True
    assert direction_bins[3].pair_count == 1
    assert sum(b.pair_count for b in direction_bins) == 3  # Y 轴点对被排除


def test_direction_azimuth_wraps_undirected_at_180():
    """175° 的实际方向与 0° 方向的无向夹角为 5°。"""

    theta = math.radians(5)
    points = np.array([[0, 0], [math.cos(theta), -math.sin(theta)]], dtype=float)
    values = np.array([0.0, 1.0])
    spec = VariogramDiagnosticSpec(
        lag_count=4,
        max_distance=2,
        min_pairs_per_bin=2,
        directions=(
            DirectionSpec(dimension="2d", azimuth_deg=0, azimuth_tolerance_deg=10),
            DirectionSpec(dimension="2d", azimuth_deg=30, azimuth_tolerance_deg=10),
        ),
    )
    result = compute_empirical_variogram(
        points, values, spec, data_sha256=DATA_SHA, cancel=lambda: False
    )
    assert sum(b.pair_count for b in result.directional[0]) == 1  # 175° ≡ −5°
    assert sum(b.pair_count for b in result.directional[1]) == 0  # 与 30° 差 35°


def test_azimuth_tolerance_boundary_is_inclusive():
    """恰好等于容差边界的点对被纳入（含浮点噪声护栏），略超出即排除。"""

    on_edge = math.radians(15)
    beyond = math.radians(15.05)
    points = np.array(
        [
            [0, 0],
            [math.cos(on_edge), math.sin(on_edge)],
            [math.cos(beyond), math.sin(beyond)],
        ],
        dtype=float,
    )
    values = np.array([0.0, 1.0, 2.0])
    spec = VariogramDiagnosticSpec(
        lag_count=4,
        max_distance=2,
        min_pairs_per_bin=2,
        directions=(DirectionSpec(dimension="2d", azimuth_deg=0, azimuth_tolerance_deg=15),),
    )
    result = compute_empirical_variogram(
        points, values, spec, data_sha256=DATA_SHA, cancel=lambda: False
    )
    counts = [b.pair_count for b in result.directional[0]]
    assert sum(counts) == 1  # 只有恰好 15° 的点对


def test_2d_directional_bins_match_hand_calculation():
    """2D 方向 bin 手算：X 向 3 个点对、Y 向 1 个点对进入各自方向。"""

    points = np.array([[0, 0], [2, 0], [0, 3], [4, 0]], dtype=float)
    values = np.array([1.0, 5.0, 9.0, 3.0])
    spec = VariogramDiagnosticSpec(
        lag_count=4,
        max_distance=4,
        min_pairs_per_bin=2,
        directions=(
            DirectionSpec(dimension="2d", azimuth_deg=0, azimuth_tolerance_deg=20),
            DirectionSpec(dimension="2d", azimuth_deg=90, azimuth_tolerance_deg=20),
        ),
    )
    result = compute_empirical_variogram(
        points, values, spec, data_sha256=DATA_SHA, cancel=lambda: False
    )
    # 全向：距离 {2, 3, 4, √13≈3.606, 2}（d=5 超出 max_distance）
    omni = result.omnidirectional
    assert [b.pair_count for b in omni] == [0, 2, 1, 2]
    assert omni[1].semivariance == pytest.approx((8 + 2) / 2)  # d=2 的两个点对
    assert omni[2].semivariance == pytest.approx(32.0)  # d=3
    assert omni[3].semivariance == pytest.approx((2 + 8) / 2)  # d=4 与 d=√13

    x_bins, y_bins = result.directional
    # X 向点对：(0,1) d=2 γ=8、(1,3) d=2 γ=2、(0,3) d=4 γ=2
    assert x_bins[1].pair_count == 2
    assert x_bins[1].semivariance == pytest.approx(5.0)
    assert x_bins[1].used_for_fit is True
    assert x_bins[3].pair_count == 1
    assert x_bins[3].used_for_fit is False
    assert x_bins[3].exclusion_reason == "unsupported_insufficient_pairs"
    # Y 向仅 (0,2) d=3 γ=32（其余点对方位角差 > 20°）
    assert y_bins[2].pair_count == 1
    assert y_bins[2].semivariance == pytest.approx(32.0)
    assert sum(b.pair_count for b in y_bins) == 1


def test_3d_direction_applies_azimuth_and_dip_gates():
    """3D 方向同时施加方位角与倾角容差；倾角按无向线取 |dip|。"""

    points = np.array(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float
    )
    values = np.array([0.0, 1.0, 2.0, 3.0])
    spec = VariogramDiagnosticSpec(
        lag_count=4,
        max_distance=2,
        min_pairs_per_bin=2,
        directions=(
            DirectionSpec(
                dimension="3d", azimuth_deg=0, dip_deg=0,
                azimuth_tolerance_deg=15, dip_tolerance_deg=15,
            ),
            DirectionSpec(
                dimension="3d", azimuth_deg=0, dip_deg=90,
                azimuth_tolerance_deg=15, dip_tolerance_deg=15,
            ),
        ),
    )
    result = compute_empirical_variogram(
        points, values, spec, data_sha256=DATA_SHA, cancel=lambda: False
    )
    horizontal, vertical = result.directional
    # 水平 X 向：仅 O→A（d=1，γ=0.5）；Y 向被方位角拒绝、垂向被倾角拒绝
    assert horizontal[1].pair_count == 1
    assert horizontal[1].semivariance == pytest.approx(0.5)
    assert sum(b.pair_count for b in horizontal) == 1
    # 垂向：仅 O→C（d=1，γ=4.5）；铅直线方位角未定义，按 0° 约定处理
    assert vertical[1].pair_count == 1
    assert vertical[1].semivariance == pytest.approx(4.5)
    assert sum(b.pair_count for b in vertical) == 1
    # 全向不受方向门控影响：bin 1 有 3 个单位距离点对
    assert result.omnidirectional[1].pair_count == 3
    assert result.omnidirectional[1].semivariance == pytest.approx(7.0 / 3.0)


def test_dip_tolerance_boundary_is_inclusive():
    on_edge = math.radians(20)
    beyond = math.radians(20.05)
    points = np.array(
        [
            [0, 0, 0],
            [math.cos(on_edge), 0, math.sin(on_edge)],
            [math.cos(beyond), 0, math.sin(beyond)],
        ],
        dtype=float,
    )
    values = np.array([0.0, 1.0, 2.0])
    base = dict(dimension="3d", azimuth_deg=0, dip_deg=0, azimuth_tolerance_deg=30)
    spec = VariogramDiagnosticSpec(
        lag_count=4,
        max_distance=2,
        min_pairs_per_bin=2,
        directions=(
            DirectionSpec(dip_tolerance_deg=20, **base),
            DirectionSpec(dip_tolerance_deg=15, **base),
        ),
    )
    result = compute_empirical_variogram(
        points, values, spec, data_sha256=DATA_SHA, cancel=lambda: False
    )
    assert sum(b.pair_count for b in result.directional[0]) == 1  # 恰好 20° 纳入
    assert sum(b.pair_count for b in result.directional[1]) == 0  # 超出 15° 全部排除


def test_direction_with_too_few_pairs_is_unsupported_without_extrapolation():
    """方向 bin 点对不足：全部标记 unsupported，semivariance 不外推。"""

    points = np.array([[0, 0], [2, 0], [0, 3], [4, 0]], dtype=float)
    values = np.array([1.0, 5.0, 9.0, 3.0])
    spec = VariogramDiagnosticSpec(
        lag_count=4,
        max_distance=4,
        min_pairs_per_bin=2,
        directions=(DirectionSpec(dimension="2d", azimuth_deg=45, azimuth_tolerance_deg=5),),
    )
    result = compute_empirical_variogram(
        points, values, spec, data_sha256=DATA_SHA, cancel=lambda: False
    )
    for b in result.directional[0]:
        assert b.pair_count == 0
        assert b.semivariance is None
        assert b.used_for_fit is False
        assert b.exclusion_reason == "unsupported_insufficient_pairs"


# ---------------------------------------------------------------------------
# 采样元数据、确定性与取消
# ---------------------------------------------------------------------------


def test_sampling_metadata_is_disclosed_beside_bins():
    points, values = _line_points()
    spec = VariogramDiagnosticSpec(lag_count=4, max_distance=2, min_pairs_per_bin=2)
    result = compute_empirical_variogram(
        points, values, spec, data_sha256=DATA_SHA, cancel=lambda: False
    )
    assert isinstance(result, EmpiricalVariogram)
    sampling = result.sampling
    assert sampling.total_pair_count == 3
    assert sampling.used_pair_count == 3
    assert sampling.sampled is False
    assert sampling.sampling_rate == 1.0
    canonical = spec.model_dump_json().encode("utf-8")
    assert sampling.seed == seed_from_contract(DATA_SHA, canonical)


def test_sampled_path_is_capped_deterministic_and_discloses_rate():
    rng = np.random.default_rng(20260726)
    points = rng.uniform(-50, 50, size=(300, 2))
    values = np.sin(points[:, 0] / 10) + points[:, 1] / 25
    spec = VariogramDiagnosticSpec(lag_count=8, min_pairs_per_bin=2, max_pairs=100)
    first = compute_empirical_variogram(
        points, values, spec, data_sha256=DATA_SHA, cancel=lambda: False
    )
    second = compute_empirical_variogram(
        points, values, spec, data_sha256=DATA_SHA, cancel=lambda: False
    )
    sampling = first.sampling
    assert sampling.total_pair_count == 300 * 299 // 2
    assert sampling.used_pair_count == 100
    assert sampling.sampled is True
    assert sampling.sampling_rate == pytest.approx(100 / (300 * 299 // 2))
    assert first.sampling.indices.tobytes() == second.sampling.indices.tobytes()
    assert sum(b.pair_count for b in first.omnidirectional) == 100
    assert [b.semivariance for b in first.omnidirectional] == [
        b.semivariance for b in second.omnidirectional
    ]


def test_full_result_is_deterministic_across_calls():
    points = np.array([[0, 0], [2, 0], [0, 3], [4, 0]], dtype=float)
    values = np.array([1.0, 5.0, 9.0, 3.0])
    spec = VariogramDiagnosticSpec(
        lag_count=4,
        max_distance=4,
        min_pairs_per_bin=2,
        directions=(DirectionSpec(dimension="2d", azimuth_deg=0, azimuth_tolerance_deg=20),),
    )
    first = compute_empirical_variogram(
        points, values, spec, data_sha256=DATA_SHA, cancel=lambda: False
    )
    second = compute_empirical_variogram(
        points, values, spec, data_sha256=DATA_SHA, cancel=lambda: False
    )
    for a, b in zip(first.omnidirectional, second.omnidirectional):
        assert (a.pair_count, a.semivariance) == (b.pair_count, b.semivariance)
    for a, b in zip(first.directional[0], second.directional[0]):
        assert (a.pair_count, a.semivariance) == (b.pair_count, b.semivariance)


def test_cancellation_raises_run_canceled_immediately():
    points, values = _line_points()
    spec = VariogramDiagnosticSpec(lag_count=4, max_distance=2, min_pairs_per_bin=2)
    with pytest.raises(PlatformError) as excinfo:
        compute_empirical_variogram(
            points, values, spec, data_sha256=DATA_SHA, cancel=lambda: True
        )
    assert excinfo.value.code == "RUN_CANCELED"


def test_cancellation_is_checked_inside_variogram_batches():
    """cancel 在 sample_pairs 阶段放行、在变异函数批量计算中触发。"""

    points, values = _line_points()
    spec = VariogramDiagnosticSpec(lag_count=4, max_distance=2, min_pairs_per_bin=2)
    calls = {"n": 0}

    def flip_cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 2  # sample_pairs 两次检查后，本模块批次检查发现取消

    with pytest.raises(PlatformError) as excinfo:
        compute_empirical_variogram(
            points, values, spec, data_sha256=DATA_SHA, cancel=flip_cancel
        )
    assert excinfo.value.code == "RUN_CANCELED"
    assert excinfo.value.details["completed_pairs"] == 0


# ---------------------------------------------------------------------------
# 输入校验与退化数据
# ---------------------------------------------------------------------------


def test_single_point_yields_disclosed_empty_bins():
    spec = VariogramDiagnosticSpec(lag_count=4, max_distance=2, min_pairs_per_bin=2)
    result = compute_empirical_variogram(
        np.zeros((1, 2)), np.zeros(1), spec, data_sha256=DATA_SHA, cancel=lambda: False
    )
    assert result.sampling.total_pair_count == 0
    for b in result.omnidirectional:
        assert b.pair_count == 0
        assert b.semivariance is None
        assert b.used_for_fit is False
        assert b.exclusion_reason == "empty_bin"


def test_values_length_mismatch_rejected():
    points, _ = _line_points()
    spec = VariogramDiagnosticSpec(lag_count=4, max_distance=2, min_pairs_per_bin=2)
    with pytest.raises(PlatformError) as excinfo:
        compute_empirical_variogram(
            points, np.zeros(2), spec, data_sha256=DATA_SHA, cancel=lambda: False
        )
    assert excinfo.value.code == "VARIOGRAM_INPUT_INVALID"


def test_non_finite_inputs_rejected():
    points, values = _line_points()
    spec = VariogramDiagnosticSpec(lag_count=4, max_distance=2, min_pairs_per_bin=2)
    with pytest.raises(PlatformError) as excinfo:
        compute_empirical_variogram(
            points, np.array([0.0, math.nan, 4.0]), spec,
            data_sha256=DATA_SHA, cancel=lambda: False,
        )
    assert excinfo.value.code == "VARIOGRAM_INPUT_INVALID"
    bad_points = points.copy()
    bad_points[1, 0] = math.inf
    with pytest.raises(PlatformError) as excinfo:
        compute_empirical_variogram(
            bad_points, values, spec, data_sha256=DATA_SHA, cancel=lambda: False
        )
    assert excinfo.value.code == "VARIOGRAM_INPUT_INVALID"


def test_unsupported_coordinate_dimension_rejected():
    spec = VariogramDiagnosticSpec(lag_count=4, max_distance=2, min_pairs_per_bin=2)
    with pytest.raises(PlatformError) as excinfo:
        compute_empirical_variogram(
            np.zeros((3, 4)), np.zeros(3), spec, data_sha256=DATA_SHA, cancel=lambda: False
        )
    assert excinfo.value.code == "VARIOGRAM_INPUT_INVALID"


def test_direction_dimension_must_match_points():
    points, values = _line_points()
    spec = VariogramDiagnosticSpec(
        lag_count=4,
        max_distance=2,
        min_pairs_per_bin=2,
        directions=(
            DirectionSpec(
                dimension="3d", azimuth_deg=0, dip_deg=0,
                azimuth_tolerance_deg=15, dip_tolerance_deg=15,
            ),
        ),
    )
    with pytest.raises(PlatformError) as excinfo:
        compute_empirical_variogram(
            points, values, spec, data_sha256=DATA_SHA, cancel=lambda: False
        )
    assert excinfo.value.code == "VARIOGRAM_INPUT_INVALID"
