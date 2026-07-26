"""Task 7 tests: professional search neighborhoods in IDW.

契约要点（设计 §7.2 末段 / §8.2）：

- 旋转邻域只决定哪些点进入候选集合和扇区；IDW 权重继续使用 legacy
  ``(x, y, z × z_scale)`` 距离，绝不用椭球归一化距离；
- 邻点不足 → 该查询 NoData（整批不中断），NoData 原因入诊断；
- 诊断是有界汇总（候选数/椭球内数/扇区计数/最终使用数的聚合 +
  NoData 原因计数），不存逐查询邻点列表；
- 精确同点沿用 legacy 语义（距离 0 直接返回观测值）。
"""

from __future__ import annotations

import json

import numpy as np
import pytest


def _predict(coords, values, query, params, dimension):
    from geomodeling.modeling.idw import IDWInterpolator

    interpolator = IDWInterpolator()
    validated = interpolator.validate_parameters(params, dimension)
    return interpolator.fit(coords, values, validated).predict(query, cancel=lambda: False)


def test_rotated_neighborhood_changes_inclusion():
    # X 轴三点与 Y 轴三点到原点距离完全相同；扁椭圆按方位角只收其中一条轴
    coords = np.array(
        [
            [10.0, 0.0],
            [20.0, 0.0],
            [30.0, 0.0],
            [0.0, 10.0],
            [0.0, 20.0],
            [0.0, 30.0],
        ]
    )
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    query = np.array([[0.0, 0.0]])
    base = {
        "power": 2.0,
        "neighborhood": {
            "radii": [35.0, 5.0],
            "min_neighbors": 3,
            "sector_count": 1,
            "max_per_sector": 8,
            "max_neighbors": 24,
        },
    }
    along_x = _predict(coords, values, query, {**base, "neighborhood": {**base["neighborhood"], "azimuth_deg": 0.0}}, "2d")
    along_y = _predict(coords, values, query, {**base, "neighborhood": {**base["neighborhood"], "azimuth_deg": 90.0}}, "2d")
    assert not along_x.is_nodata.any()
    assert not along_y.is_nodata.any()
    # 只含 X 轴三点（值 1/2/3，距离 10/20/30）的 IDW 均值
    weights_x = 1.0 / np.array([10.0, 20.0, 30.0]) ** 2
    expected_x = float((weights_x * values[:3]).sum() / weights_x.sum())
    weights_y = 1.0 / np.array([10.0, 20.0, 30.0]) ** 2
    expected_y = float((weights_y * values[3:]).sum() / weights_y.sum())
    assert along_x.values[0] == pytest.approx(expected_x, rel=1e-12)
    assert along_y.values[0] == pytest.approx(expected_y, rel=1e-12)
    assert along_x.values[0] != pytest.approx(along_y.values[0])


def test_weights_use_physical_distance_not_ellipsoid_normalized():
    # A=(50,0) 与 B=(0,5) 在 (100,10) 椭圆内的归一化距离同为 0.5，
    # 物理距离为 50 与 5；权重若用归一化距离则二者等权（预测=均值 50）
    coords = np.array([[50.0, 0.0], [0.0, 5.0]])
    values = np.array([0.0, 100.0])
    query = np.array([[0.0, 0.0]])
    batch = _predict(
        coords,
        values,
        query,
        {
            "power": 2.0,
            "neighborhood": {
                "radii": [100.0, 10.0],
                "azimuth_deg": 0.0,
                "min_neighbors": 2,
                "sector_count": 1,
                "max_per_sector": 8,
                "max_neighbors": 24,
            },
        },
        "2d",
    )
    assert not batch.is_nodata[0]
    weights = 1.0 / np.array([50.0, 5.0]) ** 2
    expected = float((weights * values).sum() / weights.sum())
    assert batch.values[0] == pytest.approx(expected, rel=1e-12)
    assert batch.values[0] != pytest.approx(50.0)  # 归一化距离（错误）会给出等权均值


def test_weights_use_z_scaled_distance_while_selection_uses_physical_radii():
    # B=(0,0,3) 在物理半径 3.5 内（选择按物理坐标）；z_scale=2 后其权重距离
    # 为 6 —— 选择不被 z_scale 排除，但权重必须按 z 缩放距离计算
    coords = np.array([[4.0, 0.0, 0.0], [0.0, 0.0, 3.0]])
    values = np.array([0.0, 100.0])
    query = np.array([[0.0, 0.0, 0.0]])
    batch = _predict(
        coords,
        values,
        query,
        {
            "power": 2.0,
            "z_scale": 2.0,
            "neighborhood": {
                "radii": [10.0, 10.0, 3.5],
                "azimuth_deg": 0.0,
                "dip_deg": 0.0,
                "roll_deg": 0.0,
                "min_neighbors": 2,
                "sector_count": 1,
                "max_per_sector": 8,
                "max_neighbors": 24,
            },
        },
        "3d",
    )
    assert not batch.is_nodata[0]  # 选择用物理坐标：B 未被 z_scale 挤出椭球
    scaled_distances = np.array([4.0, 3.0 * 2.0])
    weights = 1.0 / scaled_distances**2
    expected = float((weights * values).sum() / weights.sum())
    assert batch.values[0] == pytest.approx(expected, rel=1e-12)
    # 若权重误用未缩放物理距离（4 与 3），结果不同
    unscaled = 1.0 / np.array([4.0, 3.0]) ** 2
    assert batch.values[0] != pytest.approx(float((unscaled * values).sum() / unscaled.sum()))


def test_insufficient_neighbors_produce_nodata_with_reason_counts():
    coords = np.array([[10.0, 0.0], [20.0, 0.0], [30.0, 0.0]])
    values = np.array([1.0, 2.0, 3.0])
    query = np.array([[0.0, 0.0], [1000.0, 1000.0]])  # 第二点远在椭球外
    batch = _predict(
        coords,
        values,
        query,
        {
            "power": 2.0,
            "neighborhood": {
                "radii": [35.0, 5.0],
                "min_neighbors": 3,
                "sector_count": 1,
                "max_per_sector": 8,
                "max_neighbors": 24,
            },
        },
        "2d",
    )
    # 整批不中断：近查询正常，远查询 NoData
    assert batch.is_nodata.tolist() == [False, True]
    assert np.isnan(batch.values[1])
    assert batch.diagnostics["nodata_reason_counts"] == {"neighbors_insufficient": 1}


def test_sector_truncation_insufficiency_produces_nodata():
    # 三点全在同一方向：4 扇区 × 每扇区 1 个 → 合并池只有 1 个 < min_neighbors
    coords = np.array([[10.0, 0.0], [20.0, 0.0], [30.0, 0.0]])
    values = np.array([1.0, 2.0, 3.0])
    query = np.array([[0.0, 0.0]])
    batch = _predict(
        coords,
        values,
        query,
        {
            "power": 2.0,
            "neighborhood": {
                "radii": [35.0, 5.0],
                "min_neighbors": 2,
                "sector_count": 4,
                "max_per_sector": 1,
                "max_neighbors": 24,
            },
        },
        "2d",
    )
    assert batch.is_nodata[0]
    assert batch.diagnostics["nodata_reason_counts"] == {"neighbors_insufficient": 1}
    summary = batch.diagnostics["search_neighborhood_summary"]
    assert summary["inside_count_total"] == 3  # 椭球判定通过 3 个，卡在扇区容量
    assert summary["sector_counts_total"] == [1, 0, 0, 0]
    assert summary["neighbors_used_total"] == 0


def test_neighborhood_diagnostics_are_bounded_aggregates():
    coords = np.array([[10.0, 0.0], [20.0, 0.0], [30.0, 0.0], [0.0, 10.0]])
    values = np.array([1.0, 2.0, 3.0, 4.0])
    query = np.array([[0.0, 0.0], [15.0, 0.0], [500.0, 500.0]])
    batch = _predict(
        coords,
        values,
        query,
        {
            "power": 2.0,
            "neighborhood": {
                "radii": [35.0, 12.0],
                "min_neighbors": 3,
                "sector_count": 4,
                "max_per_sector": 4,
                "max_neighbors": 6,
            },
        },
        "2d",
    )
    diagnostics = batch.diagnostics
    summary = diagnostics["search_neighborhood_summary"]
    # 聚合统计：候选数/椭球内数/扇区计数/最终使用数
    assert summary["candidate_count_total"] >= summary["inside_count_total"] >= 0
    assert len(summary["sector_counts_total"]) == 4
    assert sum(summary["sector_counts_total"]) <= summary["inside_count_total"]
    assert summary["neighbors_used_total"] >= 0
    assert 0 <= summary["neighbors_used_max"] <= 6
    assert diagnostics["max_neighbors_used"] == summary["neighbors_used_max"]
    assert diagnostics["nodata_reason_counts"]["neighbors_insufficient"] == 1
    # 有界汇总必须可 JSON 序列化（无 ndarray、无逐查询邻点列表）
    json.dumps(diagnostics)


def test_exact_sample_point_reproduced_in_neighborhood_path():
    coords = np.array([[10.0, 0.0], [20.0, 0.0], [30.0, 0.0], [0.0, 10.0]])
    values = np.array([1.0, 2.0, 3.0, 4.0])
    query = np.array([[20.0, 0.0]])  # 与训练点精确重合
    batch = _predict(
        coords,
        values,
        query,
        {
            "power": 2.0,
            "neighborhood": {
                "radii": [35.0, 12.0],
                "min_neighbors": 3,
                "sector_count": 4,
                "max_per_sector": 4,
                "max_neighbors": 6,
            },
        },
        "2d",
    )
    assert not batch.is_nodata[0]
    assert batch.values[0] == 2.0  # 距离 0 直接返回观测值，不做加权


def test_neighborhood_dimension_mismatch_rejected_at_validation():
    from geomodeling.modeling.idw import IDWInterpolator

    interpolator = IDWInterpolator()
    radii_3d = {"radii": [10.0, 10.0, 10.0], "dip_deg": 0.0, "roll_deg": 0.0}
    with pytest.raises(Exception):
        interpolator.validate_parameters({"neighborhood": radii_3d}, "2d")
    with pytest.raises(Exception):
        interpolator.validate_parameters({"neighborhood": {"radii": [10.0, 10.0]}}, "3d")


def test_neighborhood_spec_itself_is_validated():
    from geomodeling.modeling.idw import IDWInterpolator

    interpolator = IDWInterpolator()
    # 非法邻域（半径非正 / min > max / 扇区容量不足）在契约边界被拒绝
    with pytest.raises(Exception):
        interpolator.validate_parameters({"neighborhood": {"radii": [0.0, 5.0]}}, "2d")
    with pytest.raises(Exception):
        interpolator.validate_parameters(
            {"neighborhood": {"radii": [10.0, 5.0], "min_neighbors": 30, "max_neighbors": 4}},
            "2d",
        )
