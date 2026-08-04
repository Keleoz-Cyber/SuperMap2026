# 阶段 A 格式探针结论（4×5×6 合成 NetCDF v3）

> 日期：2026-08-04。页面：`/supermap-voxel-netcdf/index.html?source=probe&clean=1`。
> 驱动：`voxel-driver.mjs`（Playwright Chromium）；像素分析：`analyze_pixels.py`。
> 探针生成：`make_probe_netcdf.py`（产物 `web/public/supermap-voxel-netcdf/probe/probe-4x5x6.nc`，1320 B，gitignored）。

## 结论：探针通过

NetCDF v3 → `VoxelGridLayer3D` → VolumeRendering 彩色连续体渲染成立，参数变化均有像素级响应：

| 状态/转换 | 证据 |
|---|---|
| baseline 非背景像素 | 25,930 / 913,959（面板掩码外） |
| baseline→threshold（minFiltration 55%） | 17,685 像素变化 |
| threshold→opacity（opacityTransferFunction 常数 0.12） | 20,431 像素变化 |
| opacity→slice（Slice 模式） | 20,817 像素变化 |
| slice→contour（ContourValue 模式） | 11,620 像素变化 |
| 静止画面噪声基线 | 0 像素（无操作连拍逐像素一致） |

图层实测：`type=VoxelGridLayer3D`，tile 维度 4×5×6（无轴交换）、`_floor=-9999/_ceil=553`、体纹理 1 张、包围球落锚点。无 pageerror、无 4xx/5xx、无 GL 错误。

## 本机构建包（12.1.0 SVN 50939）六条实测 API 事实（与文档/直觉不同处）

1. **`startRender` 前置条件**：图层 `_frameState` 须已由渲染循环赋值（首帧之后），否则 `_initialize` 读 `.mode` 抛 TypeError。页面以有上限帧轮询 `_frameState` 非空后再调用。
2. **`layerBounds` 必须赋裸角度 `new SuperMap3D.Rectangle(w,s,e,n)`**：本构建包 `_computePosition` 内部对 `_dataBounds` 再调 `fromDegrees`；若按 JSDoc 惯例用 `Rectangle.fromDegrees` 会双重换算，体数据错位到 (2.1°E, 0.5°N)。`_dWidth = (east-west) * WGS84.maximumRadius` 只影响包围球半径，不影响绘制顶点（顶点来自正确的 `fromDegrees` 角点）。
3. **相机必须 `lookAt` 体数据中心**：`setView({destination, orientation})` 只摆位不指向，目标不在视轴上时全黑。
4. **`opaqueRate` 属性不进任何着色器 uniform（no-op）**：不透明度须经 `opacityTransferFunction`（构建 `_opacityTexture`）控制。交互滑块已改为重建该函数。
5. **色带分量为 0–1 浮点**（`addRGBPoint(value, r, g, b)`），0–255 量纲会得到近黑体。
6. **阈值 `minFiltration/maxFiltration` 经 uniform 闭包实时读取**，赋值即生效，无需重建命令。

另：命令执行经 `derivedCommands` 链（logDepth → … → hdr.command，frameState `_hdr=true`）逐帧真实执行——"命令不执行"的假象来自挂钩对象选错（Proxy/逐级挂钩实证）。
