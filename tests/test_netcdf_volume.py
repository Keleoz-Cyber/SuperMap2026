"""v0.6.1 Task 6: deterministic NetCDF classic/v3 volume package writer tests.

``write_netcdf_package`` 把校验过的规则网格写成确定性 NetCDF classic/v3 体包
（volume.nc + manifest.json + checksums.sha256）：维度恰为 x/y/z，标量变量名
由属性名安全派生（不固定 rho），Float32 存储，NoData 在属性与存储单元均为
-9999.0，``values[i,j,k]`` C 序不转置不翻轴；内容寻址文件不含时间戳与绝对路径。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
from scipy.io import netcdf_file

import geomodeling.platform.netcdf_volume as netcdf_volume
from geomodeling.platform.errors import PlatformError
from geomodeling.platform.netcdf_volume import write_netcdf_package
from geomodeling.platform.render_contracts import (
    DisplayAnchor,
    RenderGridSource,
    ValidatedGrid,
)

GRID_SHA = "a" * 64
ANCHOR = DisplayAnchor()
PACKAGE_FILES = {"volume.nc", "manifest.json", "checksums.sha256"}


def make_grid(
    shape: tuple[int, int, int] = (4, 5, 3), *, nodata_cells: tuple = ()
) -> tuple[tuple[np.ndarray, ...], np.ndarray, np.ndarray, ValidatedGrid]:
    """非对称网格：每维长度不同、每轴步进 1/10/100，转置或翻轴立即可见。"""

    axes = (
        np.linspace(0.0, 30.0, shape[0]),
        np.linspace(200.0, 240.0, shape[1]),
        np.linspace(-60.0, 0.0, shape[2]),
    )
    i, j, k = np.indices(shape)
    values = (10.0 + i + 10.0 * j + 100.0 * k).astype("float64")
    is_nodata = np.zeros(shape, dtype=bool)
    for cell in nodata_cells:
        is_nodata[cell] = True
    return axes, values, is_nodata, _validated(axes, values, is_nodata)


def _validated(axes, values, is_nodata) -> ValidatedGrid:
    valid = values[~is_nodata]
    finite = valid[np.isfinite(valid)]
    return ValidatedGrid(
        axes=axes,
        values=values,
        is_nodata=is_nodata,
        valid_min=float(finite.min()),
        valid_max=float(finite.max()),
    )


def make_source(property_name: str = "Vx", units: str = "km/s") -> RenderGridSource:
    return RenderGridSource(
        source_kind="candidate_result",
        source_id="result-vx-1",
        grid_path=Path("render-sources/unused/grid.npz"),
        grid_sha256=GRID_SHA,
        property_name=property_name,
        units=units,
        coordinate_kind="local_linear",
        dimension="3d",
    )


def read_checksums(stage: Path) -> dict[str, str]:
    lines = (stage / "checksums.sha256").read_text(encoding="utf-8").strip().splitlines()
    return dict(line.split("  ", 1)[::-1] for line in lines)


# ---------------------------------------------------------------------------
# 结构与 manifest v2（计划钉死的断言）
# ---------------------------------------------------------------------------


def test_package_is_netcdf_classic_with_exact_xyz_dimensions(tmp_path):
    axes, values, is_nodata, grid = make_grid()
    stage = tmp_path / "stage"

    manifest = write_netcdf_package(stage, make_source(), grid, ANCHOR)

    nc_path = stage / "volume.nc"
    assert nc_path.read_bytes()[:4] == b"CDF\x01"  # NetCDF classic
    with netcdf_file(nc_path, "r", mmap=False) as nc:
        assert set(nc.dimensions) == {"x", "y", "z"}
        assert nc.dimensions == {"x": 4, "y": 5, "z": 3}
        variable_name = manifest["variable_name"]
        assert variable_name == "Vx"
        assert nc.variables["Vx"].dimensions == ("x", "y", "z")
        assert nc.variables["Vx"].data.dtype.itemsize == 4
        assert float(nc.variables["Vx"]._FillValue) == -9999.0
        assert nc.variables["Vx"].units == b"km/s"
        for axis_name in ("x", "y", "z"):
            axis_var = nc.variables[axis_name]
            assert axis_var.dimensions == (axis_name,)
            assert axis_var.data.dtype.itemsize == 4
    assert manifest["property_name"] == "Vx"
    assert manifest["units"] == "km/s"
    assert manifest["geolocation_status"] == "display_anchor_only"


def test_manifest_v2_field_by_field(tmp_path):
    axes, values, is_nodata, grid = make_grid()
    stage = tmp_path / "stage"

    manifest = write_netcdf_package(stage, make_source(), grid, ANCHOR)

    assert set(manifest) == {
        "format",
        "version",
        "renderer",
        "source_kind",
        "source_id",
        "grid_sha256",
        "netcdf_sha256",
        "variable_name",
        "property_name",
        "units",
        "dimension_names",
        "shape",
        "dtype",
        "fill_value",
        "valid_count",
        "nodata_count",
        "value_range",
        "encoded_value_range",
        "layer_bounds_degrees",
        "z_bounds_metres",
        "display_transform",
        "render_coordinate_contract",
        "geolocation_status",
        "sdk_target",
    }
    assert manifest["format"] == "supermap-voxel-netcdf"
    assert manifest["version"] == 2
    assert manifest["renderer"] == "supermap_voxelgrid_netcdf"
    assert manifest["source_kind"] == "candidate_result"
    assert manifest["source_id"] == "result-vx-1"
    assert manifest["grid_sha256"] == GRID_SHA
    nc_path = stage / "volume.nc"
    assert manifest["netcdf_sha256"] == hashlib.sha256(nc_path.read_bytes()).hexdigest()
    assert manifest["variable_name"] == "Vx"
    assert manifest["dimension_names"] == ["x", "y", "z"]
    assert manifest["shape"] == [4, 5, 3]
    assert manifest["dtype"] == "float32"
    assert manifest["fill_value"] == -9999.0
    assert manifest["valid_count"] == 60
    assert manifest["nodata_count"] == 0
    # values = 10 + i + 10j + 100k：整数场 float64/float32 均精确
    assert manifest["value_range"] == [10.0, 253.0]
    assert manifest["encoded_value_range"] == [10.0, 253.0]
    bounds = manifest["layer_bounds_degrees"]
    assert set(bounds) == {"west", "south", "east", "north"}
    assert bounds["west"] < bounds["east"]
    assert bounds["south"] < bounds["north"]
    with netcdf_file(nc_path, "r", mmap=False) as nc:
        x_back = nc.variables["x"].data
        y_back = nc.variables["y"].data
    assert bounds["west"] == pytest.approx(float(x_back[0]), abs=1e-5)
    assert bounds["east"] == pytest.approx(float(x_back[-1]), abs=1e-5)
    assert bounds["south"] == pytest.approx(float(y_back[0]), abs=1e-5)
    assert bounds["north"] == pytest.approx(float(y_back[-1]), abs=1e-5)
    assert manifest["z_bounds_metres"] == [-60.0, 0.0]
    transform = manifest["display_transform"]
    assert transform["contract"] == "wgs84_display_anchor_v1"
    assert transform["origin_x"] == pytest.approx(15.0)
    assert transform["origin_y"] == pytest.approx(220.0)
    assert transform["anchor_longitude"] == 120.0
    assert transform["anchor_latitude"] == 30.0
    assert transform["anchor_height"] == 0.0
    assert transform["metres_per_degree_lon"] > 0.0
    assert transform["metres_per_degree_lat"] > 0.0
    assert manifest["render_coordinate_contract"] == "wgs84_display_anchor_v1"
    assert manifest["sdk_target"] == "SuperMap3D 12.1.0"


def test_checksums_register_volume_and_manifest(tmp_path):
    _, _, _, grid = make_grid()
    stage = tmp_path / "stage"

    manifest = write_netcdf_package(stage, make_source(), grid, ANCHOR)

    entries = read_checksums(stage)
    assert entries == {
        "volume.nc": manifest["netcdf_sha256"],
        "manifest.json": hashlib.sha256(
            (stage / "manifest.json").read_bytes()
        ).hexdigest(),
    }
    assert {p.name for p in stage.iterdir()} == PACKAGE_FILES


# ---------------------------------------------------------------------------
# NoData 编码
# ---------------------------------------------------------------------------


def test_nodata_cells_stored_as_fill_and_counted(tmp_path):
    cells = ((0, 0, 0), (3, 4, 2), (1, 2, 1))
    axes, values, is_nodata, grid = make_grid(nodata_cells=cells)
    stage = tmp_path / "stage"

    manifest = write_netcdf_package(stage, make_source(), grid, ANCHOR)

    assert manifest["valid_count"] == 60 - 3
    assert manifest["nodata_count"] == 3
    # 掩膜盖住原最小值 (0,0,0)=10 与最大值 (3,4,2)=253
    assert manifest["value_range"] == [11.0, 252.0]
    assert manifest["encoded_value_range"] == [11.0, 252.0]
    with netcdf_file(stage / "volume.nc", "r", mmap=False) as nc:
        back = nc.variables["Vx"].data.copy()
    assert np.all(back[is_nodata] == np.float32(-9999.0))
    assert np.all(back[~is_nodata] != np.float32(-9999.0))
    # 有效单元与 float64 源的 float32 舍入逐位一致（读写无损）
    assert np.array_equal(back[~is_nodata], values[~is_nodata].astype(np.float32))


# ---------------------------------------------------------------------------
# 轴序/布局
# ---------------------------------------------------------------------------


def test_non_symmetric_grid_proves_no_transpose_or_flip(tmp_path):
    """X 步进 1、Y 步进 10、Z 步进 100；任一轴交换/翻转都会破坏这些等式。"""

    axes, values, is_nodata, grid = make_grid()
    stage = tmp_path / "stage"

    write_netcdf_package(stage, make_source(), grid, ANCHOR)

    with netcdf_file(stage / "volume.nc", "r", mmap=False) as nc:
        back = nc.variables["Vx"].data.copy()
        x_back = nc.variables["x"].data
        y_back = nc.variables["y"].data
        z_back = nc.variables["z"].data
    assert back.shape == (4, 5, 3)
    assert float(back[1, 0, 0] - back[0, 0, 0]) == pytest.approx(1.0)
    assert float(back[0, 1, 0] - back[0, 0, 0]) == pytest.approx(10.0)
    assert float(back[0, 0, 1] - back[0, 0, 0]) == pytest.approx(100.0)
    assert float(back[3, 4, 2]) == pytest.approx(253.0)
    assert float(back[0, 0, 0]) == pytest.approx(10.0)
    # 坐标轴严格递增；z 轴不经度变换（仅加锚点高程 0.0），float32 精确
    assert np.all(np.diff(x_back) > 0)
    assert np.all(np.diff(y_back) > 0)
    assert np.all(np.diff(z_back) > 0)
    assert np.array_equal(z_back, axes[2].astype(np.float32))


# ---------------------------------------------------------------------------
# 变量名派生
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("property_name", "expected_variable"),
    [
        ("Vx", "Vx"),
        ("Apparent Resistivity", "Apparent_Resistivity"),
        ("属性", "__"),
        ("3rd-power", "value_3rd_power"),
    ],
)
def test_variable_name_derived_from_property_not_fixed_rho(
    tmp_path, property_name, expected_variable
):
    _, _, _, grid = make_grid()
    stage = tmp_path / "stage"
    source = make_source(property_name=property_name, units="unknown")

    manifest = write_netcdf_package(stage, source, grid, ANCHOR)

    assert manifest["variable_name"] == expected_variable
    assert manifest["variable_name"] != "rho"
    assert manifest["property_name"] == property_name
    with netcdf_file(stage / "volume.nc", "r", mmap=False) as nc:
        var = nc.variables[expected_variable]
        assert var.dimensions == ("x", "y", "z")
        # 属性原文以 UTF-8 字节落进 long_name（NetCDF 文本属性必须 ASCII 安全写入）
        assert var.long_name == property_name.encode("utf-8")


# ---------------------------------------------------------------------------
# Float32 填充碰撞
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("colliding", [-9999.0, -9999.0000001])
def test_valid_value_colliding_with_float32_fill_rejected(tmp_path, colliding):
    """有效值在 float32 下落到 -9999 即与填充值不可区分，fail-closed。"""

    axes, values, is_nodata, _ = make_grid()
    values[2, 2, 2] = colliding
    grid = _validated(axes, values, is_nodata)

    with pytest.raises(PlatformError) as excinfo:
        write_netcdf_package(tmp_path / "stage", make_source(), grid, ANCHOR)
    assert excinfo.value.code == "RENDER_FILL_VALUE_COLLISION"
    assert excinfo.value.http_status == 409


def test_all_nodata_rejected(tmp_path):
    axes, values, is_nodata, _ = make_grid()
    is_nodata = np.ones(values.shape, dtype=bool)
    values = np.full(values.shape, np.nan)
    with pytest.raises(PlatformError) as excinfo:
        write_netcdf_package(
            tmp_path / "stage",
            make_source(),
            ValidatedGrid(
                axes=axes,
                values=values,
                is_nodata=is_nodata,
                valid_min=float("nan"),
                valid_max=float("nan"),
            ),
            ANCHOR,
        )
    assert excinfo.value.code == "RENDER_NO_VALID_VALUES"


# ---------------------------------------------------------------------------
# 确定性与无泄露
# ---------------------------------------------------------------------------


def test_repeated_write_is_byte_deterministic_and_path_free(tmp_path):
    _, _, _, grid = make_grid(nodata_cells=((0, 0, 0),))
    source = make_source()
    stage_a = tmp_path / "stage-a"
    stage_b = tmp_path / "stage-b"

    manifest_a = write_netcdf_package(stage_a, source, grid, ANCHOR)
    manifest_b = write_netcdf_package(stage_b, source, grid, ANCHOR)

    assert manifest_a == manifest_b
    for name in PACKAGE_FILES:
        assert (stage_a / name).read_bytes() == (stage_b / name).read_bytes()
    # 内容寻址文件不含绝对路径与时间戳字段
    manifest_text = (stage_a / "manifest.json").read_text(encoding="utf-8")
    checksums_text = (stage_a / "checksums.sha256").read_text(encoding="utf-8")
    assert str(stage_a) not in manifest_text
    assert str(stage_a) not in checksums_text
    for key in manifest_a:
        lowered = key.lower()
        assert "time" not in lowered
        assert "date" not in lowered
        assert "created" not in lowered


# ---------------------------------------------------------------------------
# 损坏回读 fail-closed
# ---------------------------------------------------------------------------


def test_corrupted_volume_fails_readback_closed(tmp_path, monkeypatch):
    """写入端产出损坏文件时，回读校验必须失败而不是发布坏包。"""

    def garbage_writer(nc_path, *_args, **_kwargs):
        nc_path.write_bytes(b"CDF\x01" + b"\x00" * 127)  # 截断的损坏 classic 文件

    monkeypatch.setattr(netcdf_volume, "_write_volume_nc", garbage_writer)
    _, _, _, grid = make_grid()

    with pytest.raises(PlatformError) as excinfo:
        write_netcdf_package(tmp_path / "stage", make_source(), grid, ANCHOR)
    assert excinfo.value.code == "RENDER_NETCDF_READBACK_FAILED"
    assert excinfo.value.http_status == 500
