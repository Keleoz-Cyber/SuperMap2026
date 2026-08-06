"""v0.7.0 Batch 2 Task 3：权威正交剖面分析核心（图表方向 + 统计口径）。"""

from __future__ import annotations

import numpy as np
import pytest

from geomodeling.platform.slice_analysis import analyze_grid_slice


def make_grid():
    """shape (2,3,4)：values[ix,iy,iz] = 100*ix + 10*iy + iz；一个显式 NoData、
    一个 NaN、一个 +Inf（后两者按有效 NoData 处理，绝不进入统计）。"""

    axes = (
        np.array([0.0, 100.0]),
        np.array([0.0, 10.0, 20.0]),
        np.array([0.0, 1.0, 2.0, 3.0]),
    )
    values = np.zeros((2, 3, 4), dtype="float64")
    for ix in range(2):
        for iy in range(3):
            for iz in range(4):
                values[ix, iy, iz] = 100 * ix + 10 * iy + iz
    is_nodata = np.zeros((2, 3, 4), dtype=bool)
    is_nodata[0, 1, 2] = True
    values[1, 0, 1] = np.nan
    values[1, 2, 3] = np.inf
    return axes, values, is_nodata


@pytest.mark.parametrize(
    ("axis", "index", "row_axis", "column_axis", "shape"),
    [
        ("x", 1, "z", "y", (4, 3)),
        ("y", 1, "z", "x", (4, 2)),
        ("z", 2, "y", "x", (3, 2)),
    ],
)
def test_chart_orientation(axis, index, row_axis, column_axis, shape):
    result = analyze_grid_slice(*make_grid(), axis, index)
    assert (result.row_axis, result.column_axis) == (row_axis, column_axis)
    assert result.values.shape == shape
    assert result.nodata_mask.shape == shape
    assert np.all(np.diff(result.row_coordinates) > 0)
    assert np.all(np.diff(result.column_coordinates) > 0)


def test_fixed_coordinate_and_relative_position():
    axes, values, is_nodata = make_grid()
    result = analyze_grid_slice(axes, values, is_nodata, "z", 2)
    assert result.fixed_axis == "z"
    assert result.index == 2
    assert result.coordinate == 2.0
    assert result.sdk_relative_position == pytest.approx(2 / 3)
    middle = analyze_grid_slice(axes, values, is_nodata, "x", 1)
    assert middle.sdk_relative_position == pytest.approx(1.0)
    first = analyze_grid_slice(axes, values, is_nodata, "y", 0)
    assert first.sdk_relative_position == pytest.approx(0.0)


def test_matrix_values_match_orientation():
    axes, values, is_nodata = make_grid()
    result = analyze_grid_slice(axes, values, is_nodata, "z", 2)
    # values[row=y][column=x] = 100*x + 10*y + 2
    expected = np.array([[2, 102], [12, 112], [22, 122]], dtype="float64")
    valid = np.where(~result.nodata_mask, result.values, np.nan)
    assert np.allclose(valid, np.where(~result.nodata_mask, expected, np.nan), equal_nan=True)


def test_effective_nodata_merges_explicit_nan_and_inf():
    axes, values, is_nodata = make_grid()
    result = analyze_grid_slice(axes, values, is_nodata, "z", 1)
    # 本剖面无显式 NoData；NaN（x=1,y=0）必须计入有效掩膜；+Inf 在 z=3 不在本剖面
    assert result.nodata_mask.shape == (3, 2)
    assert result.nodata_mask[0, 1]
    assert not result.nodata_mask[1, 0]
    assert not result.nodata_mask[2, 1]


def test_statistics_population_std_and_linear_quantiles():
    axes, values, is_nodata = make_grid()
    result = analyze_grid_slice(axes, values, is_nodata, "z", 2)
    # 显式 NoData（x=0,y=1）排除 12.0；其余 5 个值全部有效
    valid = np.array([2.0, 22.0, 102.0, 112.0, 122.0])
    stats = result.statistics
    assert stats["total_count"] == 6
    assert stats["valid_count"] == 5
    assert stats["nodata_count"] == 1
    assert stats["min"] == pytest.approx(2.0)
    assert stats["max"] == pytest.approx(122.0)
    assert stats["mean"] == pytest.approx(float(valid.mean()))
    assert stats["std_population"] == pytest.approx(float(valid.std(ddof=0)))
    q = np.quantile(valid, [0.1, 0.5, 0.9], method="linear")
    assert stats["p10"] == pytest.approx(float(q[0]))
    assert stats["p50"] == pytest.approx(float(q[1]))
    assert stats["p90"] == pytest.approx(float(q[2]))


def test_statistics_skip_effective_nodata():
    axes, values, is_nodata = make_grid()
    result = analyze_grid_slice(axes, values, is_nodata, "z", 3)
    # 本剖面含一个 +Inf（x=1,y=2）计入有效 NoData；显式 NoData 在 z=2 不在本剖面
    valid = np.array([3.0, 13.0, 23.0, 103.0, 113.0])
    stats = result.statistics
    assert stats["total_count"] == 6
    assert stats["valid_count"] == 5
    assert stats["nodata_count"] == 1
    assert stats["mean"] == pytest.approx(float(valid.mean()))


def test_all_nodata_slice_returns_null_statistics():
    axes, values, is_nodata = make_grid()
    is_nodata[:] = True
    result = analyze_grid_slice(axes, values, is_nodata, "x", 0)
    stats = result.statistics
    assert stats["total_count"] == 12
    assert stats["valid_count"] == 0
    assert stats["nodata_count"] == 12
    for key in ("min", "max", "mean", "std_population", "p10", "p50", "p90"):
        assert stats[key] is None


def test_json_serializer_uses_none_for_masked_values():
    axes, values, is_nodata = make_grid()
    result = analyze_grid_slice(axes, values, is_nodata, "z", 1)
    payload = result.to_json_slice()
    flat = [v for row in payload["values"] for v in row]
    assert None in flat
    assert not any(isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))) for v in flat if v is not None)
    assert payload["nodata_mask"][0][1] is True
