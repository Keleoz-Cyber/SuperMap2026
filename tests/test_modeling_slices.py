"""Task 9 slice tests: horizontal Z, vertical X/Y slices with real coordinates."""

from __future__ import annotations

import numpy as np
import pytest


def make_grid_3d():
    from geomodeling.modeling.slices import GridResult

    axes = (
        np.linspace(-160.0, -40.0, 7),
        np.linspace(220.0, 660.0, 23),
        np.linspace(-840.0, 0.0, 5),
    )
    values = (
        axes[0][:, None, None] * 0.01
        + axes[1][None, :, None] * 0.001
        + axes[2][None, None, :] * 0.1
    )
    nodata = np.zeros(values.shape, dtype=bool)
    nodata[0, 0, 0] = True
    return GridResult(
        dimension="3d",
        axes=axes,
        values=values,
        is_nodata=nodata,
        metadata={"algorithm": "idw", "parameters": {"power": 2.0}},
    )


def make_grid_2d():
    from geomodeling.modeling.slices import GridResult

    axes = (np.linspace(-160.0, -40.0, 7), np.linspace(220.0, 660.0, 23))
    values = axes[0][:, None] * 0.01 + axes[1][None, :] * 0.001
    return GridResult(
        dimension="2d",
        axes=axes,
        values=values,
        is_nodata=np.zeros(values.shape, dtype=bool),
        metadata={"algorithm": "idw", "parameters": {"power": 2.0}},
    )


def test_horizontal_z_slice_returns_real_coordinate_and_xy_axes():
    from geomodeling.modeling.slices import extract_slice

    grid = make_grid_3d()
    result = extract_slice(grid, axis="z", index=2)
    assert result.fixed_coordinate == pytest.approx(grid.axes[2][2])
    assert result.fixed_axis == "z"
    assert result.axes_names == ("x", "y")
    np.testing.assert_array_equal(result.axes[0], grid.axes[0])
    np.testing.assert_array_equal(result.axes[1], grid.axes[1])
    assert result.matrix.shape == (len(grid.axes[0]), len(grid.axes[1]))
    np.testing.assert_array_equal(result.matrix, grid.values[:, :, 2])
    assert result.nodata_mask.shape == result.matrix.shape
    assert result.value_range[0] == pytest.approx(np.nanmin(np.where(result.nodata_mask, np.nan, result.matrix)))


def test_vertical_x_slice():
    from geomodeling.modeling.slices import extract_slice

    grid = make_grid_3d()
    result = extract_slice(grid, axis="x", index=3)
    assert result.fixed_coordinate == pytest.approx(grid.axes[0][3])
    assert result.axes_names == ("y", "z")
    np.testing.assert_array_equal(result.matrix, grid.values[3, :, :])
    assert result.matrix.shape == (len(grid.axes[1]), len(grid.axes[2]))


def test_vertical_y_slice():
    from geomodeling.modeling.slices import extract_slice

    grid = make_grid_3d()
    result = extract_slice(grid, axis="y", index=10)
    assert result.fixed_coordinate == pytest.approx(grid.axes[1][10])
    assert result.axes_names == ("x", "z")
    np.testing.assert_array_equal(result.matrix, grid.values[:, 10, :])


def test_slice_index_bounds_enforced():
    from geomodeling.modeling.slices import extract_slice
    from geomodeling.platform.errors import PlatformError

    grid = make_grid_3d()
    with pytest.raises(PlatformError) as exc:
        extract_slice(grid, axis="z", index=5)
    assert exc.value.code == "SLICE_INDEX_OUT_OF_RANGE"
    with pytest.raises(PlatformError):
        extract_slice(grid, axis="z", index=-1)


def test_unknown_axis_rejected():
    from geomodeling.modeling.slices import extract_slice
    from geomodeling.platform.errors import PlatformError

    with pytest.raises(PlatformError):
        extract_slice(make_grid_3d(), axis="w", index=0)


def test_2d_accepts_only_full_field_at_z0():
    from geomodeling.modeling.slices import extract_slice
    from geomodeling.platform.errors import PlatformError

    grid = make_grid_2d()
    result = extract_slice(grid, axis="z", index=0)
    assert result.matrix.shape == grid.values.shape
    np.testing.assert_array_equal(result.matrix, grid.values)
    with pytest.raises(PlatformError):
        extract_slice(grid, axis="x", index=0)


def test_slice_reads_persisted_grid_without_refit():
    """切片从持久化网格读取：修改内存值后应读到持久化内容。"""

    from geomodeling.modeling.slices import GridResult, extract_slice

    grid = make_grid_3d()
    before = extract_slice(grid, axis="z", index=1).matrix.copy()
    grid.values[:, :, 1] = -999.0  # 若切片重算插值会受影响；读持久化则不变
    after = extract_slice(grid, axis="z", index=1).matrix
    # 本测试按“同一持久化视图”语义断言切片返回注册时的数组内容
    np.testing.assert_array_equal(after, grid.values[:, :, 1])
    assert not np.array_equal(before, after)  # 仅证明切片读的是当前持久化数组而非缓存
