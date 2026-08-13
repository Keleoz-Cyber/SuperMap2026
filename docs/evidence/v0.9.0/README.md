# v0.9.0 视觉产品重构证据

本目录收录 v0.9.0（答辩级视觉产品与全流程体验重构）的真实浏览器证据。
产品目标见 `docs/product-blueprint.md`，验收口径见 `docs/acceptance.md`。

## 证据纪律

- 真实数据：三个官方案例均由仓库内置 `example_data/` 源经文档化 seed 命令生成，
  证据中的 `git_commit` 必须是测试代码提交的祖先。
- 真实渲染：只认 SuperMap3D `VoxelGridLayer3D + NetCDF` 原生体渲染的协议回执 +
  体积像素门（非背景体素、中央覆盖率、颜色标准差、最大连通区占比）；
  `scene.open` resolved、资产 ready 或纯协议成功均不视为视觉成功。
- 每个场景保留整页截图 + iframe 裁剪截图 + 像素统计 + 网络/控制台记录。
- 本目录不提交 `.runtime`、SQLite、真实私有 CSV、SDK 二进制或本机绝对路径。

## 目录结构

- `verification.md`：当次验收矩阵与测试实数；当前发布门以 `docs/acceptance.md` 为准。
- `run-<timestamp>-<id>/`：单次真实运行的证据包：
  - `v090-live-evidence.json`：run ID、git/SDK 身份、视口、逐场景像素统计、
    网络与控制台记录、官方成果身份（result/asset/grid/NetCDF 哈希）；
  - `home-<case>-page.png` / `home-<case>-iframe.png`：指挥舱三案例切换；
  - `linkage-gas-page.png`：图表→三维联动（趋势点击驱动切片）；
  - `presentation-resistivity-page.png`：答辩模式案例章节真实场景；
  - `phone-gas-page.png`：手机视口渲染与布局。
