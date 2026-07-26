"""Task 6: rotated ellipse/ellipsoid sector neighborhood selection (design §8).

锚点：cKDTree 只用于安全外接半径（``max(radii)``）的有界候选查询；椭圆/椭球
判定在邻域自身旋转坐标中精确进行（边界包含）；扇区绕主轴方向等分；稳定排序
次键为标准数据 ``source_row``；少于 ``min_neighbors`` 返回空选择 +
``rejection_reason``，不扩大半径、不降低 ``min_neighbors``、不退化全局搜索。
``NEIGHBORS_INSUFFICIENT`` 覆盖返回形态（``select_neighbors``）与硬失败形态
（``require_neighbors``）。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from geomodeling.modeling.neighborhood import (
    NEIGHBORHOOD_INPUT_INVALID,
    NEIGHBORS_INSUFFICIENT,
    RUN_CANCELED,
    NeighborSelection,
    require_neighbors,
    select_neighbors,
)
from geomodeling.modeling.professional_contracts import NeighborhoodSpec
from geomodeling.platform.errors import PlatformError


def _spec_2d(**overrides) -> NeighborhoodSpec:
    base = dict(
        radii=(10.0, 10.0),
        azimuth_deg=0.0,
        min_neighbors=1,
        max_neighbors=8,
        sector_count=4,
        max_per_sector=8,
    )
    return NeighborhoodSpec(**{**base, **overrides})


def _spec_3d(**overrides) -> NeighborhoodSpec:
    base = dict(
        radii=(10.0, 10.0, 10.0),
        azimuth_deg=0.0,
        dip_deg=0.0,
        roll_deg=0.0,
        min_neighbors=1,
        max_neighbors=8,
        sector_count=4,
        max_per_sector=8,
    )
    return NeighborhoodSpec(**{**base, **overrides})


# ---------------------------------------------------------------------------
# 实施计划 Task 6 给定示例
# ---------------------------------------------------------------------------


def test_rotated_ellipse_excludes_bbox_false_positive():
    selected = select_neighbors(
        training=np.array([[0, 0], [2, 2], [3, 0]], dtype=float),
        query=np.array([0, 0], dtype=float),
        source_rows=np.array([0, 1, 2]),
        spec=NeighborhoodSpec(
            radii=(3, 1), azimuth_deg=45,
            min_neighbors=1, max_neighbors=8, sector_count=4, max_per_sector=2,
        ),
    )
    assert selected.source_rows.tolist() == [0, 1]


def test_equal_distance_tie_breaks_by_source_row():
    selected = select_neighbors(
        training=np.array([[1, 0], [-1, 0]], dtype=float),
        query=np.array([0, 0], dtype=float),
        source_rows=np.array([7, 3]),
        spec=NeighborhoodSpec(
            radii=(2, 2), azimuth_deg=0,
            min_neighbors=1, max_neighbors=2, sector_count=1, max_per_sector=2,
        ),
    )
    assert selected.source_rows.tolist() == [3, 7]


# ---------------------------------------------------------------------------
# 诊断字段与椭圆判定
# ---------------------------------------------------------------------------


def test_diagnostics_report_counts_and_weight_distances():
    selected = select_neighbors(
        training=np.array([[0, 0], [2, 2], [3, 0]], dtype=float),
        query=np.array([0, 0], dtype=float),
        source_rows=np.array([0, 1, 2]),
        spec=_spec_2d(radii=(3.0, 1.0), azimuth_deg=45.0, max_per_sector=2),
    )
    assert isinstance(selected, NeighborSelection)
    assert selected.candidate_count == 3  # [3,0] 在外接球内但椭球外
    assert selected.inside_count == 2
    assert selected.sector_counts == (2, 0, 0, 0)
    assert selected.rejection_reason is None
    assert selected.indices.tolist() == [0, 1]
    np.testing.assert_allclose(
        selected.weight_distances, [0.0, math.sqrt(8.0 / 9.0)], rtol=0.0, atol=1e-12
    )


def test_ellipsoid_boundary_is_inclusive():
    selected = select_neighbors(
        training=np.array([[3.0, 0.0], [0.0, 1.0], [3.5, 0.0]]),
        query=np.array([0.0, 0.0]),
        source_rows=np.array([0, 1, 2]),
        spec=_spec_2d(radii=(3.0, 1.0)),
    )
    # (3,0) 与 (0,1) 恰在椭圆边界上（归一化平方和恰为 1）；等距按 source_row 升序
    assert selected.source_rows.tolist() == [0, 1]
    assert selected.candidate_count == 2  # 3.5 超出外接半径
    assert selected.inside_count == 2


def test_safe_outer_radius_uses_max_semi_axis():
    selected = select_neighbors(
        training=np.array([[2.9, 0.05], [2.9, 0.4]]),
        query=np.array([0.0, 0.0]),
        source_rows=np.array([0, 1]),
        spec=_spec_2d(radii=(3.0, 0.5)),
    )
    # 两点都远超次半径 0.5 但在外接半径（主轴 3）内：候选 2、椭球内 1
    assert selected.candidate_count == 2
    assert selected.inside_count == 1
    assert selected.source_rows.tolist() == [0]


# ---------------------------------------------------------------------------
# 3D 椭球
# ---------------------------------------------------------------------------


def test_3d_ellipsoid_vertical_radius_membership():
    selected = select_neighbors(
        training=np.array(
            [
                [0.0, 0.0, 0.4],  # 垂向 0.4/0.5 → 内
                [0.0, 0.0, 0.6],  # 垂向 0.6/0.5 → 外
                [2.5, 0.0, 0.0],  # 主轴 2.5/3 → 内
                [0.0, 0.9, 0.4],  # 0.9² + 0.8² > 1 → 外
            ]
        ),
        query=np.array([0.0, 0.0, 0.0]),
        source_rows=np.array([10, 11, 12, 13]),
        spec=_spec_3d(radii=(3.0, 1.0, 0.5), min_neighbors=2, max_per_sector=2),
    )
    assert selected.source_rows.tolist() == [10, 12]
    assert selected.candidate_count == 4
    assert selected.inside_count == 2
    assert selected.sector_counts == (1, 1, 0, 0)


def test_3d_ellipsoid_follows_dip_rotation():
    # dip=90°：主轴从 +X 倾伏到 ±Z（R 第一列为 (0,0,−1)），椭球随旋转立起；
    # 不做旋转的实现会把 (0,0,1.8) 误判为垂向越界。
    selected = select_neighbors(
        training=np.array(
            [
                [0.0, 0.0, 1.8],  # 沿立起的主轴 1.8/2 → 内
                [0.0, 0.0, 2.5],  # 主轴 2.5/2 → 外，且超出外接半径
                [1.2, 0.0, 0.0],  # 旋转后的垂向 1.2/0.5 → 外
                [0.0, 0.8, 0.0],  # 次轴 0.8/1 → 内
            ]
        ),
        query=np.array([0.0, 0.0, 0.0]),
        source_rows=np.array([20, 21, 22, 23]),
        spec=_spec_3d(radii=(2.0, 1.0, 0.5), dip_deg=90.0, min_neighbors=2, max_per_sector=2),
    )
    assert selected.source_rows.tolist() == [23, 20]
    assert selected.candidate_count == 3
    assert selected.inside_count == 2


def test_3d_spec_without_dip_roll_defaults_to_horizontal():
    selected = select_neighbors(
        training=np.array([[0.0, 0.0, 0.4], [0.0, 0.0, 0.6]]),
        query=np.array([0.0, 0.0, 0.0]),
        source_rows=np.array([0, 1]),
        spec=NeighborhoodSpec(radii=(3.0, 1.0, 0.5), min_neighbors=1),
    )
    assert selected.source_rows.tolist() == [0]


# ---------------------------------------------------------------------------
# 扇区分配
# ---------------------------------------------------------------------------


def test_sector_assignment_2d_local_frame():
    selected = select_neighbors(
        training=np.array([[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0], [0.0, -1.0]]),
        query=np.array([0.0, 0.0]),
        source_rows=np.array([0, 1, 2, 3]),
        spec=_spec_2d(),
    )
    assert selected.inside_count == 4
    assert selected.sector_counts == (1, 1, 1, 1)


def test_sector_assignment_2d_pins_minor_axis_to_sector_one():
    selected = select_neighbors(
        training=np.array([[0.0, 1.0]]),
        query=np.array([0.0, 0.0]),
        source_rows=np.array([9]),
        spec=_spec_2d(),
    )
    assert selected.sector_counts == (0, 1, 0, 0)


def test_sector_frame_rotates_with_azimuth():
    # 方位角 45°：物理 80°/100° 的点在邻域局部角为 35°/55°，均落入扇区 0；
    # 不旋转的扇区划分会把它们放进扇区 1。
    selected = select_neighbors(
        training=np.array(
            [
                [math.cos(math.radians(80.0)), math.sin(math.radians(80.0))],
                [math.cos(math.radians(100.0)), math.sin(math.radians(100.0))],
            ]
        ),
        query=np.array([0.0, 0.0]),
        source_rows=np.array([0, 1]),
        spec=_spec_2d(azimuth_deg=45.0),
    )
    assert selected.inside_count == 2
    assert selected.sector_counts == (2, 0, 0, 0)


def test_sector_assignment_3d_around_major_axis():
    selected = select_neighbors(
        training=np.array(
            [
                [0.0, 1.0, 0.0],  # +次轴 → 扇区 0
                [0.0, 0.0, 1.0],  # +垂向 → 扇区 1
                [0.0, -1.0, 0.0],  # −次轴 → 扇区 2
                [0.0, 0.0, -1.0],  # −垂向 → 扇区 3
            ]
        ),
        query=np.array([0.0, 0.0, 0.0]),
        source_rows=np.array([0, 1, 2, 3]),
        spec=_spec_3d(radii=(10.0, 1.0, 1.0)),
    )
    assert selected.inside_count == 4
    assert selected.sector_counts == (1, 1, 1, 1)


def test_sector_assignment_3d_pins_vertical_to_sector_one():
    selected = select_neighbors(
        training=np.array([[0.0, 0.0, 1.0]]),
        query=np.array([0.0, 0.0, 0.0]),
        source_rows=np.array([9]),
        spec=_spec_3d(radii=(10.0, 1.0, 1.0)),
    )
    assert selected.sector_counts == (0, 1, 0, 0)


def test_per_sector_cap_keeps_nearest_and_reports_counts():
    selected = select_neighbors(
        training=np.array([[1.0, 0.0], [1.5, 0.0], [-2.0, 0.0]]),
        query=np.array([0.0, 0.0]),
        source_rows=np.array([10, 11, 12]),
        spec=_spec_2d(radii=(5.0, 5.0), sector_count=2, max_per_sector=1),
    )
    assert selected.source_rows.tolist() == [10, 12]
    assert selected.inside_count == 3
    assert selected.sector_counts == (1, 1)


# ---------------------------------------------------------------------------
# min/max 约束与不足处理
# ---------------------------------------------------------------------------


def test_max_neighbors_limits_merged_selection():
    selected = select_neighbors(
        training=np.array([[float(k), 0.0] for k in range(1, 6)]),
        query=np.array([0.0, 0.0]),
        source_rows=np.array([30, 31, 32, 33, 34]),
        spec=_spec_2d(sector_count=1, max_neighbors=3),
    )
    assert selected.source_rows.tolist() == [30, 31, 32]
    assert len(selected.indices) == 3
    assert selected.inside_count == 5


def test_below_min_neighbors_returns_empty_selection_without_expanding_radius():
    selected = select_neighbors(
        training=np.array([[0.5, 0.0], [1.9, 0.9]]),  # 第二点在外接半径之外，不得被纳入
        query=np.array([0.0, 0.0]),
        source_rows=np.array([40, 41]),
        spec=_spec_2d(radii=(2.0, 2.0), min_neighbors=2),
    )
    assert selected.rejection_reason == NEIGHBORS_INSUFFICIENT
    assert selected.indices.size == 0
    assert selected.source_rows.size == 0
    assert selected.weight_distances.size == 0
    assert selected.indices.dtype == np.int64
    assert selected.source_rows.dtype == np.int64
    assert selected.weight_distances.dtype == np.float64
    assert selected.candidate_count == 1
    assert selected.inside_count == 1
    assert selected.sector_counts == (1, 0, 0, 0)


def test_require_neighbors_raises_structured_error_when_insufficient():
    with pytest.raises(PlatformError) as excinfo:
        require_neighbors(
            training=np.array([[0.5, 0.0], [1.9, 0.9]]),
            query=np.array([0.0, 0.0]),
            source_rows=np.array([40, 41]),
            spec=_spec_2d(radii=(2.0, 2.0), min_neighbors=2),
        )
    assert excinfo.value.code == NEIGHBORS_INSUFFICIENT
    assert excinfo.value.details["min_neighbors"] == 2
    assert excinfo.value.details["inside_count"] == 1


def test_require_neighbors_returns_selection_when_satisfied():
    selected = require_neighbors(
        training=np.array([[1.0, 0.0]]),
        query=np.array([0.0, 0.0]),
        source_rows=np.array([7]),
        spec=_spec_2d(),
    )
    assert selected.rejection_reason is None
    assert selected.source_rows.tolist() == [7]


def test_empty_training_returns_rejection():
    selected = select_neighbors(
        training=np.empty((0, 2)),
        query=np.array([0.0, 0.0]),
        source_rows=np.empty(0, dtype=np.int64),
        spec=_spec_2d(),
    )
    assert selected.rejection_reason == NEIGHBORS_INSUFFICIENT
    assert selected.candidate_count == 0
    assert selected.inside_count == 0
    assert selected.sector_counts == (0, 0, 0, 0)


def test_query_beyond_outer_radius_has_no_candidates():
    selected = select_neighbors(
        training=np.array([[100.0, 100.0]]),
        query=np.array([0.0, 0.0]),
        source_rows=np.array([0]),
        spec=_spec_2d(radii=(2.0, 2.0)),
    )
    assert selected.rejection_reason == NEIGHBORS_INSUFFICIENT
    assert selected.candidate_count == 0


# ---------------------------------------------------------------------------
# 精确同点（allow_exact 参数位）、取消、输入校验、确定性
# ---------------------------------------------------------------------------


def test_exact_coincident_point_included_by_default_with_zero_distance():
    selected = select_neighbors(
        training=np.array([[0.0, 0.0], [1.0, 0.0]]),
        query=np.array([0.0, 0.0]),
        source_rows=np.array([5, 6]),
        spec=_spec_2d(radii=(2.0, 2.0), sector_count=1),
    )
    assert selected.source_rows.tolist() == [5, 6]
    np.testing.assert_array_equal(selected.weight_distances[0], 0.0)


def test_allow_exact_false_excludes_coincident_point():
    selected = select_neighbors(
        training=np.array([[0.0, 0.0], [1.0, 0.0]]),
        query=np.array([0.0, 0.0]),
        source_rows=np.array([5, 6]),
        spec=_spec_2d(radii=(2.0, 2.0), sector_count=1),
        allow_exact=False,
    )
    assert selected.source_rows.tolist() == [6]
    assert selected.inside_count == 1
    assert selected.candidate_count == 2


def test_cancel_raises_run_canceled():
    with pytest.raises(PlatformError) as excinfo:
        select_neighbors(
            training=np.array([[1.0, 0.0]]),
            query=np.array([0.0, 0.0]),
            source_rows=np.array([0]),
            spec=_spec_2d(),
            cancel=lambda: True,
        )
    assert excinfo.value.code == RUN_CANCELED
    assert excinfo.value.http_status == 409


def test_input_validation_rejects_dimension_mismatch():
    with pytest.raises(PlatformError) as excinfo:
        select_neighbors(
            training=np.array([[1.0, 0.0, 0.0]]),
            query=np.array([0.0, 0.0]),
            source_rows=np.array([0]),
            spec=_spec_2d(),
        )
    assert excinfo.value.code == NEIGHBORHOOD_INPUT_INVALID


def test_input_validation_rejects_source_rows_mismatch():
    with pytest.raises(PlatformError) as excinfo:
        select_neighbors(
            training=np.array([[1.0, 0.0]]),
            query=np.array([0.0, 0.0]),
            source_rows=np.array([0, 1, 2]),
            spec=_spec_2d(),
        )
    assert excinfo.value.code == NEIGHBORHOOD_INPUT_INVALID


def test_input_validation_rejects_non_finite_coordinates():
    with pytest.raises(PlatformError) as excinfo:
        select_neighbors(
            training=np.array([[1.0, 0.0]]),
            query=np.array([np.nan, 0.0]),
            source_rows=np.array([0]),
            spec=_spec_2d(),
        )
    assert excinfo.value.code == NEIGHBORHOOD_INPUT_INVALID


def test_selection_is_deterministic_for_identical_inputs():
    kwargs = dict(
        training=np.array([[0, 0], [2, 2], [3, 0], [1, 1], [-2, -1]], dtype=float),
        query=np.array([0, 0], dtype=float),
        source_rows=np.array([4, 3, 2, 1, 0]),
        spec=_spec_2d(radii=(3.0, 1.5), azimuth_deg=45.0),
    )
    first = select_neighbors(**kwargs)
    second = select_neighbors(**kwargs)
    np.testing.assert_array_equal(first.indices, second.indices)
    np.testing.assert_array_equal(first.source_rows, second.source_rows)
    np.testing.assert_array_equal(first.weight_distances, second.weight_distances)
    assert first.sector_counts == second.sector_counts
