"""Task 5 grid tests: derived grids, resolution contracts, cell caps."""

from __future__ import annotations

import numpy as np
import pytest


def make_points_2d(n=50, seed=1):
    rng = np.random.default_rng(seed)
    x = rng.uniform(-160.0, -40.0, n)
    y = rng.uniform(220.0, 660.0, n)
    return np.column_stack([x, y])


def make_points_3d(n=80, seed=2):
    rng = np.random.default_rng(seed)
    x = rng.uniform(-160.0, -40.0, n)
    y = rng.uniform(220.0, 660.0, n)
    z = rng.uniform(-840.0, 0.0, n)
    return np.column_stack([x, y, z])


def test_user_grid_covers_exact_bounds_2d():
    from geomodeling.modeling.grid import derive_grid
    from geomodeling.platform.schemas import GridSpec

    points = make_points_2d()
    spec = GridSpec(bounds=[(-160.0, -40.0), (220.0, 660.0)], resolution=[10.0, 20.0])
    grid = derive_grid(points, "2d", spec)
    assert grid.axes[0][0] == -160.0
    assert grid.axes[0][-1] == -40.0
    assert grid.axes[1][0] == 220.0
    assert grid.axes[1][-1] == 660.0
    assert grid.shape == (13, 23)
    assert grid.cell_count == 13 * 23


def test_user_grid_covers_exact_bounds_3d():
    from geomodeling.modeling.grid import derive_grid
    from geomodeling.platform.schemas import GridSpec

    points = make_points_3d()
    spec = GridSpec(bounds=[(-160.0, -40.0), (220.0, 660.0), (-840.0, 0.0)], resolution=[12.0, 44.0, 42.0])
    grid = derive_grid(points, "3d", spec)
    assert grid.shape == (11, 11, 21)
    assert grid.axes[2][0] == -840.0
    assert grid.axes[2][-1] == 0.0


def test_resolution_must_be_positive():
    from geomodeling.modeling.grid import derive_grid
    from geomodeling.platform.schemas import GridSpec
    from geomodeling.platform.errors import PlatformError

    points = make_points_2d()
    with pytest.raises(Exception):
        GridSpec(bounds=[(-160.0, -40.0), (220.0, 660.0)], resolution=[0.0, 20.0])
    with pytest.raises(Exception):
        GridSpec(bounds=[(-160.0, -40.0), (220.0, 660.0)], resolution=[10.0, -5.0])


def test_resolution_dimension_must_match():
    from geomodeling.modeling.grid import derive_grid
    from geomodeling.platform.schemas import GridSpec
    from geomodeling.platform.errors import PlatformError

    points = make_points_2d()
    spec = GridSpec(bounds=[(-160.0, -40.0), (220.0, 660.0)], resolution=[10.0, 20.0])
    with pytest.raises(PlatformError) as exc:
        derive_grid(points, "3d", spec)
    assert exc.value.code == "GRID_DIMENSION_MISMATCH"


def test_oversized_grid_rejected_before_allocation():
    from geomodeling.modeling.grid import derive_grid
    from geomodeling.platform.schemas import GridSpec
    from geomodeling.platform.errors import PlatformError

    points = make_points_3d()
    # 第一道防线：GridSpec 构造即拒绝超过上限的估算
    with pytest.raises(Exception, match="超过上限"):
        GridSpec(
            bounds=[(-160.0, -40.0), (220.0, 660.0), (-840.0, 0.0)],
            resolution=[0.001, 0.001, 0.001],
        )
    # 第二道防线：伪造输入（绕过模型校验）在 derive 处仍被拦下
    forged = GridSpec.model_construct(
        bounds=[(-160.0, -40.0), (220.0, 660.0), (-840.0, 0.0)],
        resolution=[0.01, 0.01, 0.01],
        max_cells=1_000_000,
    )
    with pytest.raises(PlatformError) as exc:
        derive_grid(points, "3d", forged)
    assert exc.value.code == "GRID_TOO_LARGE"


def test_default_grid_is_deterministic_and_capped():
    from geomodeling.modeling.grid import derive_grid

    points = make_points_3d()
    grid_a = derive_grid(points, "3d", None)
    grid_b = derive_grid(points, "3d", None)
    assert grid_a.shape == grid_b.shape
    for a, b in zip(grid_a.axes, grid_b.axes):
        np.testing.assert_array_equal(a, b)
    assert grid_a.cell_count <= 100_000
    # 长宽比保留：跨度最大的轴（本例 z，840）应获得最多节点
    spans = points.max(axis=0) - points.min(axis=0)
    assert grid_a.shape[int(np.argmax(spans))] == max(grid_a.shape)
    assert all(c >= 2 for c in grid_a.shape)


def test_default_grid_2d():
    from geomodeling.modeling.grid import derive_grid

    points = make_points_2d()
    grid = derive_grid(points, "2d", None)
    assert grid.cell_count <= 100_000
    assert grid.axes[0][0] <= points[:, 0].min()
    assert grid.axes[0][-1] >= points[:, 0].max()
    assert grid.axes[1][0] <= points[:, 1].min()
    assert grid.axes[1][-1] >= points[:, 1].max()


def test_non_divisible_resolution_still_covers_bounds_and_reports_actual():
    """不可整除分辨率：轴必须覆盖声明上下界，metadata 记录实际分辨率。"""

    from geomodeling.modeling.grid import derive_grid
    from geomodeling.platform.schemas import GridSpec

    points = make_points_2d()
    # 10 / 3 不可整除：旧实现节点止于 9（丢失上界 10）
    spec = GridSpec(bounds=[(0.0, 10.0), (0.0, 8.0)], resolution=[3.0, 2.0])
    grid = derive_grid(points, "2d", spec)

    assert grid.axes[0][0] == 0.0
    assert grid.axes[0][-1] == 10.0  # 上界必须被覆盖
    assert grid.axes[1][-1] == 8.0
    # 实际分辨率与轴一致：4 节点均匀覆盖 [0,10] → 10/3
    assert grid.resolution[0] == pytest.approx(10.0 / 3)
    assert grid.resolution[1] == pytest.approx(2.0)  # 可整除时保持声明值
    steps = [grid.axes[0][i + 1] - grid.axes[0][i] for i in range(len(grid.axes[0]) - 1)]
    assert all(s == pytest.approx(grid.resolution[0]) for s in steps)

    # 2D 结果 metadata 契约一致（materialize 使用同一 derive_grid）
    spec2 = GridSpec(bounds=[(-150.0, -60.0), (260.0, 580.0)], resolution=[7.0, 25.0])
    grid2 = derive_grid(points, "2d", spec2)
    for axis, (lo, hi), res in zip(grid2.axes, spec2.bounds, grid2.resolution):
        assert axis[0] == lo
        assert axis[-1] == hi
        if len(axis) > 1:
            assert (axis[-1] - axis[0]) / (len(axis) - 1) == pytest.approx(res)
