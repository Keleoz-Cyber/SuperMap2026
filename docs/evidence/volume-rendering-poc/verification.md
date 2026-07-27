# 连续体渲染最小案例验收记录

> 日期：2026-07-27。分支 `feat/volume-rendering-poc`，验收时 HEAD = `4d3ac7d`。
> 本记录只写实测事实，证据分层：单元测试 / Playwright Chromium 像素验证 / 本机真实 S3M 缓存浏览器验收。

## 1. 环境

- 本机：Windows，Chrome 150（`Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/150.0.0.0`），WebGL2 可用；
- GPU：`ANGLE (Intel, Intel(R) UHD Graphics (0x0000A788) Direct3D11 vs_5_0 ps_5_0, D3D11)`（`WEBGL_debug_renderer_info` 实测）；`devicePixelRatio = 1.5`；
- 平台：FastAPI 单进程 uvicorn（`--workers 1`），iServer 本机在线（8090）；
- `demo-check`：9 PASSED / 1 optional WARNING（凭据未设置），0 阻断；`iserver_optional` 与 `s3m_optional` 均 PASSED。

## 2. 单元测试（vitest）

`npm --prefix web run test:unit`：**16 files / 126 passed**（基线 110 + volume 16）。

- `volumeGrid.spec.ts`：7×21×48 完整笛卡尔重索引；错误 result_id / 数组不齐 / 非有限值 / 重复坐标拒收；常量场与物理线性梯度三线性重采样；8 位打包极值 0/255；退化/倒置/非有限值域打包报错；
- `VolumeRenderer.spec.ts`：runtime 创建、卸载 dispose 一次、阈值/透明度转发；
- `VolumeDemoView.spec.ts`：源/目标尺寸与「可视化重采样」披露、契约失败显示错误且无渲染器、控件 props 转发；
- `volumeRoute.spec.ts`：`/volume-demo` 仅直接 URL 可达、无导航入口；
- `voxelDemo.spec.ts`：公开夹具 7,056 行、7/21/48 唯一轴、过真实 `buildSourceVolume` 契约。

## 3. Playwright Chromium 像素验证（公开合成夹具）

`npm --prefix web run test:e2e -- volume-demo.spec.ts`：**1 passed**。

- 源 7 × 21 × 48 与目标 7 × 23 × 42 文本可见；canvas 可见；
- 阈值 0.18→0.62、透明度 0.55→0.90 后截图像素变化（before 8,041 B / after 5,237 B，`Buffer.compare != 0`）；
- 无 console/pageerror。

## 4. 本机真实 S3M 缓存浏览器验收

`GET /api/cases/resistivity/voxel-cells` 实测：`result_id=RHO_KRIG_FINAL_20M_40`、`source=iserver_s3m_cache`、`count=7056`、`tile_files=26`、`value_range=[2.2912676334381104, 127.28083801269531]`。

页面（`/#/volume-demo`，真实 Chrome 150）实测：

- 身份披露：成果 RHO_KRIG_FINAL_20M_40；源采样 `7 × 21 × 48 / 7,056`；显示纹理 `7 × 23 × 42 / 6,762`；采样值域 `2.291…–127.281…`；「局部坐标，不可跨案例叠加」；「可视化重采样，不是新的正式模型，也不是 VOLUME 精确逐单元导出」；
- 画面：连续半透明体（两处高值体块，见 `volume-demo.png`），非离散点云、非平行切片堆叠；
- 旋转：鼠标拖拽旋转后画面像素变化（7,902 B → 8,029 B），体结构保持连续；
- 控件：阈值 0.18→0.90 像素变化（14,479 B → 7,700 B）；透明度 0.90→0.10 像素变化（7,700 B → 7,662 B）；
- 控制台：0 errors / 0 warnings；
- 进出路由 10 次：每次恰好 1 个体渲染 canvas，无动画循环或 DOM 累积；
- 帧率：未借助浏览器性能工具测量，不做无依据承诺；本机交互流畅（主观观察，非测量值）。

### 验收中发现的两个真实缺陷与修复（均已测试先行修复并回归）

1. **片元着色器 `modelMatrix` 未声明**（Task 6 修复 `bd2d394` 内）：Three.js 片元不内建 `modelMatrix`，计划逐字着色器编译失败、画布恒黑。修复：CPU 侧求一次 `uModelInverse` 传入（网格静态）。
2. **高 DPR 下 ResizeObserver 正反馈**（本任务修复 `4d3ac7d`）：`renderer.setSize(w, h, false)` 不钉 canvas CSS 尺寸，`devicePixelRatio=1.5` 时 canvas 属性像素持续撑大容器，实测 canvas 高 33,554,433 px、画布全黑。修复：恢复默认 `updateStyle=true` 钉住 CSS 尺寸，实测稳定 2043×840。

## 5. 回归

- 后端 `python -m pytest -q`：1167 passed（无缩减）；
- 前端 vitest 126 passed；type-check/build 通过；
- Mock E2E 全量 5 passed（volume-demo + 既有 4）；Live E2E 3 passed；
- `git diff --check` 通过；危险文件扫描零命中（无 UDBX/缓存/私有数据/凭据/运行时 DB/dist 入库）。

## 6. 结论与非声明边界

This proves browser-side continuous rendering of the validated S3M cache sample field.
It does not prove a cell-exact VOLUME export, a new interpolation result, geological accuracy,
native SuperMap GPU volume rendering, or cross-case coordinate alignment.

- 纹理为「可视化重采样」（三线性，仅用于显示）：源为 S3M 缓存采样值域 `2.291–127.281`，不得冒充登记 VOLUME 精确值域 `1.418283–133.146194`；
- 本案例不构成新正式成果；不写数据库、不产生成果记录；
- `/volume-demo` 仅直接 URL 访问，首页/导航无入口；
- 是否接入成果工作台、复用微震网格、获取 VOLUME 精确单元、传递函数编辑：留待单独决策，本案例不预授权。
