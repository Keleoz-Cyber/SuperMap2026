"""阶段 A 格式探针：程序生成 4x5x6 非对称 NetCDF v3（不接业务 API）。

三轴不同长度、不同方向梯度（i*1 + j*10 + k*100），含少量 -9999，
固定经纬度/高度包围盒。产物 probe-4x5x6.nc 为测试产物，不入 Git。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.io import netcdf_file

OUT = Path(__file__).resolve().parents[3] / "web" / "public" / "supermap-voxel-netcdf" / "probe" / "probe-4x5x6.nc"

NX, NY, NZ = 4, 5, 6
xs = np.linspace(119.9998, 120.0002, NX).astype(np.float32)
ys = np.linspace(29.9998, 30.0002, NY).astype(np.float32)
zs = np.linspace(-800.0, -100.0, NZ).astype(np.float32)

values = np.zeros((NX, NY, NZ), dtype=np.float32)
for i in range(NX):
    for j in range(NY):
        for k in range(NZ):
            values[i, j, k] = np.float32(10.0 + i * 1.0 + j * 10.0 + k * 100.0)
# 少量 -9999（非角点，避免破坏包围盒判定）
values[1, 2, 3] = np.float32(-9999.0)
values[2, 1, 4] = np.float32(-9999.0)

OUT.parent.mkdir(parents=True, exist_ok=True)
with netcdf_file(OUT, mode="w", version=1) as nc:
    nc.Conventions = "CF-1.8"
    nc.title = "v0.6.1 VoxelGridLayer3D phase-A asymmetric probe"
    nc.generator = "make_probe_netcdf.py v1"
    nc.createDimension("x", NX)
    nc.createDimension("y", NY)
    nc.createDimension("z", NZ)
    xv = nc.createVariable("x", "f", ("x",))
    yv = nc.createVariable("y", "f", ("y",))
    zv = nc.createVariable("z", "f", ("z",))
    rv = nc.createVariable("rho", "f", ("x", "y", "z"))
    xv.standard_name = "longitude"
    xv.units = "degrees_east"
    yv.standard_name = "latitude"
    yv.units = "degrees_north"
    zv.standard_name = "height"
    zv.units = "m"
    zv.positive = "up"
    rv.long_name = "probe intensity"
    rv.units = "unknown"
    rv.valid_min = np.float32(values[values > -9999.0].min())
    rv.valid_max = np.float32(values[values > -9999.0].max())
    rv._FillValue = np.float32(-9999.0)
    rv.missing_value = np.float32(-9999.0)
    xv[:] = xs
    yv[:] = ys
    zv[:] = zs
    rv[:] = values

print("written:", OUT, OUT.stat().st_size, "bytes")

# 读回核验：轴单调、方向梯度、-9999 位置、_FillValue 类型
with netcdf_file(OUT, mode="r", mmap=True) as nc:
    back = nc.variables["rho"][:].copy()
    assert back.shape == (NX, NY, NZ), back.shape
    assert back.dtype.kind == "f" and back.dtype.itemsize == 4, back.dtype  # NetCDF XDR 大端 float32
    assert isinstance(nc.variables["rho"]._FillValue, np.float32), type(nc.variables["rho"]._FillValue)
    assert nc.variables["rho"]._FillValue == np.float32(-9999.0)
    for name, n in (("x", NX), ("y", NY), ("z", NZ)):
        axis = nc.variables[name][:].copy()
        assert len(axis) == n and np.all(np.diff(axis) > 0), name
    assert back[1, 2, 3] == -9999.0 and back[2, 1, 4] == -9999.0
    # 方向核验：X 步进 1、Y 步进 10、Z 步进 100（排除转置/翻转）
    assert back[1, 0, 0] - back[0, 0, 0] == np.float32(1.0)
    assert back[0, 1, 0] - back[0, 0, 0] == np.float32(10.0)
    assert back[0, 0, 1] - back[0, 0, 0] == np.float32(100.0)
    print("readback OK: dims/dtype/fill/gradient verified")
