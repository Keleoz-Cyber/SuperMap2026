"""Task 11: connected anomaly extraction and grid-support measure (design §12).

显式阈值掩膜 + 十字形 4/6 邻接连通 + Voronoi 网格支持面积/体积估计。
高值 ``value >= threshold``、低值 ``value <= threshold``（均含等号）；
NoData、非有限值与不满足不确定性门槛的节点不进入掩膜；请求不存在的
不确定性层结构化失败（``ANOMALY_UNCERTAINTY_UNAVAILABLE``）。支持度
量为逐节点 Voronoi 区间宽度乘积之和：内部边界取相邻轴坐标中点、最外
边界裁剪到网格 bounds；仅称「网格支持面积/体积估计」。
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from geomodeling.modeling import anomalies as anomalies_module
from geomodeling.modeling.anomalies import (
    ANOMALY_GRID_IRREGULAR,
    ANOMALY_INPUT_INVALID,
    ANOMALY_UNCERTAINTY_UNAVAILABLE,
    RUN_CANCELED,
    AnomalyComponent,
    AnomalyExtractionResult,
    UncertaintyLayer,
    extract_anomalies,
)
from geomodeling.modeling.professional_contracts import AnomalyExtractionSpec
from geomodeling.platform.errors import PlatformError


def _axes2d() -> tuple[np.ndarray, np.ndarray]:
    return (np.array([0.0, 1.0]), np.array([0.0, 1.0]))


def _axes3d() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return (
        np.array([0.0, 1.0]),
        np.array([0.0, 1.0]),
        np.array([0.0, 1.0]),
    )


# ---------------------------------------------------------------------------
# 连通性：2D 四邻接、3D 六邻接（实施计划 Task 11 给定示例）
# ---------------------------------------------------------------------------


def test_2d_diagonal_nodes_are_separate_under_four_connectivity():
    values = np.array([[10.0, 0.0], [0.0, 10.0]])
    result = extract_anomalies(
        axes=(np.array([0, 1]), np.array([0, 1])),
        values=values,
        is_nodata=np.zeros_like(values, dtype=bool),
        spec=AnomalyExtractionSpec(direction="high", threshold=9),
    )
    assert len(result.components) == 2
    # 两条轴均为 [0, 1]：每节点 Voronoi 宽度 0.5，单节点支持面积 0.25
    for component in result.components:
        assert component.support_node_count == 1
        assert component.support_measure == pytest.approx(0.25)
        assert component.support_unit == "area_coordinate_unit2"
        assert component.touches_grid_boundary


def test_3d_face_neighbors_join_under_six_connectivity():
    values = np.zeros((2, 2, 2), dtype=float)
    values[0, 0, 0] = 10.0
    values[1, 0, 0] = 11.0
    result = extract_anomalies(
        axes=(
            np.array([0.0, 1.0]),
            np.array([0.0, 1.0]),
            np.array([0.0, 1.0]),
        ),
        values=values,
        is_nodata=np.zeros_like(values, dtype=bool),
        spec=AnomalyExtractionSpec(direction="high", threshold=9),
    )
    assert len(result.components) == 1
    assert result.components[0].support_node_count == 2
    # 每节点 Voronoi 宽度 0.5 → 单节点支持体积 0.125，两节点 0.25
    assert result.components[0].support_measure == pytest.approx(0.25)
    assert result.components[0].support_unit == "volume_coordinate_unit3"


def test_3d_body_diagonal_nodes_are_separate_under_six_connectivity():
    """体对角接触不是面邻接：六邻接下不得合并。"""

    values = np.zeros((2, 2, 2), dtype=float)
    values[0, 0, 0] = 10.0
    values[1, 1, 1] = 10.0
    result = extract_anomalies(
        axes=_axes3d(),
        values=values,
        is_nodata=np.zeros_like(values, dtype=bool),
        spec=AnomalyExtractionSpec(direction="high", threshold=9),
    )
    assert len(result.components) == 2
    assert {c.support_node_count for c in result.components} == {1}


def test_2d_edge_diagonal_chain_does_not_merge_through_corners():
    """2D 锯齿链（仅角接触相连）在四邻接下保持为独立连通区。"""

    values = np.array(
        [
            [10.0, 0.0, 0.0],
            [0.0, 10.0, 0.0],
            [0.0, 0.0, 10.0],
        ]
    )
    result = extract_anomalies(
        axes=(np.array([0.0, 1.0, 2.0]), np.array([0.0, 1.0, 2.0])),
        values=values,
        is_nodata=np.zeros_like(values, dtype=bool),
        spec=AnomalyExtractionSpec(direction="high", threshold=9),
    )
    assert len(result.components) == 3


# ---------------------------------------------------------------------------
# 阈值掩膜：高/低含等号；NoData 不进入掩膜
# ---------------------------------------------------------------------------


def test_high_threshold_is_inclusive():
    """``value >= threshold`` 含等号；严格小于阈值的节点不进入掩膜。"""

    values = np.array([[9.0, 8.999], [8.999, 8.999]])
    result = extract_anomalies(
        axes=_axes2d(),
        values=values,
        is_nodata=np.zeros_like(values, dtype=bool),
        spec=AnomalyExtractionSpec(direction="high", threshold=9),
    )
    assert len(result.components) == 1
    assert result.components[0].support_node_count == 1
    assert result.components[0].value_min == pytest.approx(9.0)


def test_low_threshold_is_inclusive():
    """``value <= threshold`` 含等号；严格大于阈值的节点不进入掩膜。"""

    values = np.array([[9.0, 9.001], [9.001, 9.001]])
    result = extract_anomalies(
        axes=_axes2d(),
        values=values,
        is_nodata=np.zeros_like(values, dtype=bool),
        spec=AnomalyExtractionSpec(direction="low", threshold=9),
    )
    assert len(result.components) == 1
    assert result.components[0].support_node_count == 1
    assert result.components[0].value_max == pytest.approx(9.0)


def test_low_direction_selects_below_threshold_region():
    values = np.array([[1.0, 1.0], [10.0, 10.0]])
    result = extract_anomalies(
        axes=_axes2d(),
        values=values,
        is_nodata=np.zeros_like(values, dtype=bool),
        spec=AnomalyExtractionSpec(direction="low", threshold=5),
    )
    assert len(result.components) == 1
    assert result.components[0].support_node_count == 2
    assert result.components[0].value_max == pytest.approx(1.0)


def test_nodata_nodes_do_not_enter_mask_and_split_components():
    """整列 NoData 把一行异常切成两个连通区。"""

    axes = (np.array([0.0, 1.0, 2.0]), np.array([0.0, 1.0]))
    values = np.full((3, 2), 10.0)
    is_nodata = np.zeros((3, 2), dtype=bool)
    is_nodata[1, :] = True
    result = extract_anomalies(
        axes=axes,
        values=values,
        is_nodata=is_nodata,
        spec=AnomalyExtractionSpec(direction="high", threshold=9),
    )
    assert len(result.components) == 2
    assert {c.support_node_count for c in result.components} == {2}
    # 轴 [0,1,2] 端节点宽度 0.5，轴 [0,1] 宽度 0.5 → 单节点 0.25，两节点 0.5
    for component in result.components:
        assert component.support_measure == pytest.approx(0.5)
    assert result.diagnostics["excluded_nodata_count"] == 2
    assert result.diagnostics["eligible_node_count"] == 4


def test_value_statistics_over_component_nodes():
    values = np.array([[10.0, 12.0], [0.0, 0.0]])
    result = extract_anomalies(
        axes=_axes2d(),
        values=values,
        is_nodata=np.zeros_like(values, dtype=bool),
        spec=AnomalyExtractionSpec(direction="high", threshold=9),
    )
    assert len(result.components) == 1
    component = result.components[0]
    assert component.support_node_count == 2
    assert component.value_min == pytest.approx(10.0)
    assert component.value_max == pytest.approx(12.0)
    assert component.value_mean == pytest.approx(11.0)


# ---------------------------------------------------------------------------
# 不确定性门槛：掩膜排除、层 NoData 排除、缺失层结构化失败
# ---------------------------------------------------------------------------


def test_empirical_error_gate_excludes_nodes_and_layer_nodata():
    """超过经验误差上限的节点与层内 NoData 节点均不进入掩膜。

    网格 3×2，值全为 10；误差层 (1,0)=5 超过上限 2、(2,1) 为层内 NoData。
    剩余节点 {(0,0),(0,1),(1,1)} 连通、{(2,0)} 孤立 → 两个连通区。
    """

    axes = (np.array([0.0, 1.0, 2.0]), np.array([0.0, 1.0]))
    values = np.full((3, 2), 10.0)
    error_values = np.ones((3, 2))
    error_values[1, 0] = 5.0
    error_values[2, 1] = 1.0
    error_nodata = np.zeros((3, 2), dtype=bool)
    error_nodata[2, 1] = True
    result = extract_anomalies(
        axes=axes,
        values=values,
        is_nodata=np.zeros((3, 2), dtype=bool),
        spec=AnomalyExtractionSpec(direction="high", threshold=9, empirical_error_max=2.0),
        empirical_error_scale=UncertaintyLayer(values=error_values, is_nodata=error_nodata),
    )
    assert len(result.components) == 2
    assert sorted(c.support_node_count for c in result.components) == [1, 3]
    assert result.diagnostics["eligible_node_count"] == 4
    large = next(c for c in result.components if c.support_node_count == 3)
    # 大连通区节点 {(0,0),(0,1),(1,1)} 的误差尺度均为 1.0
    assert large.empirical_error_scale_min == pytest.approx(1.0)
    assert large.empirical_error_scale_max == pytest.approx(1.0)
    assert large.empirical_error_scale_mean == pytest.approx(1.0)
    # 未提供 Kriging 层 → 摘要为 None
    assert large.kriging_std_min is None
    assert large.kriging_std_max is None
    assert large.kriging_std_mean is None


def test_kriging_std_gate_excludes_nodes():
    """Kriging 原生标准差超过上限的节点不进入掩膜。

    网格 3×2，值全为 10；std(1,0)=3 超过上限 2，其余 ≤ 1.5。
    剩余 5 节点经 (0,0)-(0,1)-(1,1)-(2,1)-(2,0) 全部连通。
    """

    axes = (np.array([0.0, 1.0, 2.0]), np.array([0.0, 1.0]))
    values = np.full((3, 2), 10.0)
    std_values = np.ones((3, 2))
    std_values[1, 0] = 3.0
    std_values[2, 1] = 1.5
    result = extract_anomalies(
        axes=axes,
        values=values,
        is_nodata=np.zeros((3, 2), dtype=bool),
        spec=AnomalyExtractionSpec(direction="high", threshold=9, kriging_std_max=2.0),
        kriging_std=UncertaintyLayer(
            values=std_values, is_nodata=np.zeros((3, 2), dtype=bool)
        ),
    )
    assert len(result.components) == 1
    component = result.components[0]
    assert component.support_node_count == 5
    assert component.kriging_std_min == pytest.approx(1.0)
    assert component.kriging_std_max == pytest.approx(1.5)
    assert component.kriging_std_mean == pytest.approx(1.1)
    assert component.empirical_error_scale_min is None


def test_requesting_absent_kriging_layer_fails_closed():
    """请求了 Kriging 标准差门槛但不提供层 → 结构化失败，不得忽略门槛。"""

    values = np.full((2, 2), 10.0)
    with pytest.raises(PlatformError) as excinfo:
        extract_anomalies(
            axes=_axes2d(),
            values=values,
            is_nodata=np.zeros_like(values, dtype=bool),
            spec=AnomalyExtractionSpec(direction="high", threshold=9, kriging_std_max=1.0),
        )
    assert excinfo.value.code == ANOMALY_UNCERTAINTY_UNAVAILABLE
    assert excinfo.value.details["layer"] == "kriging_std"


def test_requesting_absent_empirical_layer_fails_closed():
    values = np.full((2, 2), 10.0)
    with pytest.raises(PlatformError) as excinfo:
        extract_anomalies(
            axes=_axes2d(),
            values=values,
            is_nodata=np.zeros_like(values, dtype=bool),
            spec=AnomalyExtractionSpec(
                direction="high", threshold=9, empirical_error_max=1.0
            ),
        )
    assert excinfo.value.code == ANOMALY_UNCERTAINTY_UNAVAILABLE
    assert excinfo.value.details["layer"] == "empirical_error_scale"


def test_layer_without_gate_only_summarizes_without_masking():
    """提供不确定性层但不设门槛：不做掩膜排除，仅给出摘要。"""

    values = np.full((2, 2), 10.0)
    error_values = np.array([[1.0, 2.0], [3.0, 4.0]])
    result = extract_anomalies(
        axes=_axes2d(),
        values=values,
        is_nodata=np.zeros_like(values, dtype=bool),
        spec=AnomalyExtractionSpec(direction="high", threshold=9),
        empirical_error_scale=UncertaintyLayer(
            values=error_values, is_nodata=np.zeros_like(values, dtype=bool)
        ),
    )
    assert len(result.components) == 1
    component = result.components[0]
    assert component.support_node_count == 4
    assert component.empirical_error_scale_min == pytest.approx(1.0)
    assert component.empirical_error_scale_max == pytest.approx(4.0)
    assert component.empirical_error_scale_mean == pytest.approx(2.5)


def test_uncertainty_layer_shape_mismatch_is_blocked():
    values = np.full((2, 2), 10.0)
    with pytest.raises(PlatformError) as excinfo:
        extract_anomalies(
            axes=_axes2d(),
            values=values,
            is_nodata=np.zeros_like(values, dtype=bool),
            spec=AnomalyExtractionSpec(direction="high", threshold=9, kriging_std_max=2.0),
            kriging_std=UncertaintyLayer(
                values=np.ones((3, 3)), is_nodata=np.zeros((3, 3), dtype=bool)
            ),
        )
    assert excinfo.value.code == ANOMALY_INPUT_INVALID


# ---------------------------------------------------------------------------
# 最小支持节点数过滤
# ---------------------------------------------------------------------------


def test_min_support_nodes_filters_small_components():
    """小于 ``min_support_nodes`` 的连通区被过滤，且计数入诊断。"""

    axes = (np.array([0.0, 1.0, 2.0, 3.0]), np.array([0.0, 1.0]))
    values = np.zeros((4, 2))
    values[0, 0] = 10.0
    values[2, 0] = 10.0
    values[3, 0] = 10.0
    result = extract_anomalies(
        axes=axes,
        values=values,
        is_nodata=np.zeros((4, 2), dtype=bool),
        spec=AnomalyExtractionSpec(direction="high", threshold=9, min_support_nodes=2),
    )
    assert len(result.components) == 1
    component = result.components[0]
    assert component.support_node_count == 2
    assert component.component_id == 1
    assert result.diagnostics["labeled_component_count"] == 2
    assert result.diagnostics["filtered_component_count"] == 1
    assert result.diagnostics["component_count"] == 1


# ---------------------------------------------------------------------------
# 规则网格合同：非单调/重复/NaN 轴阻断
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_axis",
    [
        np.array([1.0, 0.0]),  # 非单调（递减）
        np.array([0.0, 0.0]),  # 重复坐标
        np.array([0.0, np.nan]),  # NaN 坐标
    ],
    ids=["decreasing", "duplicate", "nan"],
)
def test_irregular_axes_are_blocked(bad_axis):
    values = np.full((2, 2), 10.0)
    with pytest.raises(PlatformError) as excinfo:
        extract_anomalies(
            axes=(bad_axis, np.array([0.0, 1.0])),
            values=values,
            is_nodata=np.zeros_like(values, dtype=bool),
            spec=AnomalyExtractionSpec(direction="high", threshold=9),
        )
    assert excinfo.value.code == ANOMALY_GRID_IRREGULAR


def test_field_shape_mismatch_is_blocked():
    values = np.full((2, 3), 10.0)
    with pytest.raises(PlatformError) as excinfo:
        extract_anomalies(
            axes=_axes2d(),
            values=values,
            is_nodata=np.zeros_like(values, dtype=bool),
            spec=AnomalyExtractionSpec(direction="high", threshold=9),
        )
    assert excinfo.value.code == ANOMALY_INPUT_INVALID


# ---------------------------------------------------------------------------
# 边界接触
# ---------------------------------------------------------------------------


def test_interior_component_does_not_touch_grid_boundary():
    axes = (np.array([0.0, 1.0, 2.0]), np.array([0.0, 1.0, 2.0]))
    values = np.zeros((3, 3))
    values[1, 1] = 10.0
    result = extract_anomalies(
        axes=axes,
        values=values,
        is_nodata=np.zeros_like(values, dtype=bool),
        spec=AnomalyExtractionSpec(direction="high", threshold=9),
    )
    assert len(result.components) == 1
    component = result.components[0]
    assert not component.touches_grid_boundary
    # 中间节点宽度：x 向 (0.5→1.5)=1，y 向 1 → 支持面积 1.0
    assert component.support_measure == pytest.approx(1.0)
    assert component.centroid == [pytest.approx(1.0), pytest.approx(1.0)]
    assert component.bounds == [(1.0, 1.0), (1.0, 1.0)]


def test_component_reaching_edge_touches_grid_boundary():
    axes = (np.array([0.0, 1.0, 2.0]), np.array([0.0, 1.0, 2.0]))
    values = np.zeros((3, 3))
    values[1, 1] = 10.0
    values[0, 1] = 10.0
    result = extract_anomalies(
        axes=axes,
        values=values,
        is_nodata=np.zeros_like(values, dtype=bool),
        spec=AnomalyExtractionSpec(direction="high", threshold=9),
    )
    assert len(result.components) == 1
    component = result.components[0]
    assert component.touches_grid_boundary
    # 节点 (0,1) 宽度 0.5×1，节点 (1,1) 宽度 1×1 → 1.5
    assert component.support_measure == pytest.approx(1.5)
    assert component.bounds == [(0.0, 1.0), (1.0, 1.0)]


# ---------------------------------------------------------------------------
# Voronoi 支持度量：解析已知面积/体积
# ---------------------------------------------------------------------------


def test_voronoi_support_area_on_irregular_axes():
    """非均匀轴全覆盖：支持面积 = 网格外接矩形面积，中心 = 几何中心。

    轴 x=[0,1,3] 的 Voronoi 宽度为 [0.5, 1.5, 1.0]（内部边界取中点
    0.5/2.0，外边界裁剪到 0/3），轴 y=[0,2] 宽度 [1, 1]；全覆盖连通区
    支持面积 = (0.5+1.5+1.0) × 2 = 6.0，几何中心 = (1.5, 1.0)。
    """

    axes = (np.array([0.0, 1.0, 3.0]), np.array([0.0, 2.0]))
    values = np.full((3, 2), 10.0)
    result = extract_anomalies(
        axes=axes,
        values=values,
        is_nodata=np.zeros_like(values, dtype=bool),
        spec=AnomalyExtractionSpec(direction="high", threshold=9),
    )
    assert len(result.components) == 1
    component = result.components[0]
    assert component.support_node_count == 6
    assert component.support_measure == pytest.approx(6.0)
    assert component.support_unit == "area_coordinate_unit2"
    assert component.centroid == [pytest.approx(1.5), pytest.approx(1.0)]
    assert component.bounds == [(0.0, 3.0), (0.0, 2.0)]
    assert component.touches_grid_boundary


def test_voronoi_support_volume_full_grid_3d():
    """均匀 3D 网格全覆盖：支持体积 = 网格外接长方体体积 2×2×2 = 8。"""

    axes = (
        np.array([0.0, 1.0, 2.0]),
        np.array([0.0, 1.0, 2.0]),
        np.array([0.0, 1.0, 2.0]),
    )
    values = np.full((3, 3, 3), 10.0)
    result = extract_anomalies(
        axes=axes,
        values=values,
        is_nodata=np.zeros_like(values, dtype=bool),
        spec=AnomalyExtractionSpec(direction="high", threshold=9),
    )
    assert len(result.components) == 1
    component = result.components[0]
    assert component.support_node_count == 27
    assert component.support_measure == pytest.approx(8.0)
    assert component.support_unit == "volume_coordinate_unit3"
    assert component.centroid == [
        pytest.approx(1.0),
        pytest.approx(1.0),
        pytest.approx(1.0),
    ]


def test_single_corner_node_support_volume_3d():
    """3D 角节点：三向 Voronoi 宽度各 0.5 → 支持体积 0.125。"""

    values = np.zeros((3, 3, 3))
    values[0, 0, 0] = 10.0
    result = extract_anomalies(
        axes=(
            np.array([0.0, 1.0, 2.0]),
            np.array([0.0, 1.0, 2.0]),
            np.array([0.0, 1.0, 2.0]),
        ),
        values=values,
        is_nodata=np.zeros_like(values, dtype=bool),
        spec=AnomalyExtractionSpec(direction="high", threshold=9),
    )
    assert len(result.components) == 1
    component = result.components[0]
    assert component.support_node_count == 1
    assert component.support_measure == pytest.approx(0.125)
    assert component.centroid == [
        pytest.approx(0.0),
        pytest.approx(0.0),
        pytest.approx(0.0),
    ]
    assert component.bounds == [(0.0, 0.0), (0.0, 0.0), (0.0, 0.0)]
    assert component.touches_grid_boundary


def test_result_shape_and_diagnostics():
    values = np.array([[10.0, 0.0], [0.0, 10.0]])
    result = extract_anomalies(
        axes=_axes2d(),
        values=values,
        is_nodata=np.zeros_like(values, dtype=bool),
        spec=AnomalyExtractionSpec(direction="high", threshold=9),
    )
    assert isinstance(result, AnomalyExtractionResult)
    assert all(isinstance(c, AnomalyComponent) for c in result.components)
    assert [c.component_id for c in result.components] == [1, 2]
    diagnostics = result.diagnostics
    assert diagnostics["direction"] == "high"
    assert diagnostics["threshold"] == pytest.approx(9.0)
    assert diagnostics["connectivity_rule"] == "face_2d4_3d6_v1"
    assert diagnostics["component_count"] == 2


# ---------------------------------------------------------------------------
# 取消语义与命名纪律
# ---------------------------------------------------------------------------


def test_cancel_aborts_with_structured_error():
    values = np.full((2, 2), 10.0)
    with pytest.raises(PlatformError) as excinfo:
        extract_anomalies(
            axes=_axes2d(),
            values=values,
            is_nodata=np.zeros_like(values, dtype=bool),
            spec=AnomalyExtractionSpec(direction="high", threshold=9),
            cancel=lambda: True,
        )
    assert excinfo.value.code == RUN_CANCELED
    assert excinfo.value.http_status == 409


def test_support_measure_naming_discipline():
    """支持度量仅称「网格支持面积/体积估计」，源码不得出现资源量措辞。"""

    source = inspect.getsource(anomalies_module).lower()
    for forbidden in ("reserve", "geological volume", "储量", "地质体积"):
        assert forbidden not in source
