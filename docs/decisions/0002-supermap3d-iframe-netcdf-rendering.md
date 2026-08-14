# ADR-0002 SuperMap3D 隔离 iframe 与 NetCDF 体渲染链

- 状态：已接受
- 日期：2026-08-05（v0.6.1 起），2026-08-15 补记
- 取代：v0.3 的 iDesktopX 体元缓存 + 点元表达路线（S3M 兼容读取保留为证据层）

## 背景

SuperMap3D SDK 以全局变量方式加载（Cesium 系），直接集成进 Vue 应用会造成全局污染、升级困难与不可控崩溃；历史 v0.3 路线把体元缓存解析为采样点用点集合显示，不是原生连续体渲染，存在夸大风险。三维画面还必须与后端切片/统计引用同一份成果，防止"看一个模型、统计另一个模型"。

## 决策

- 渲染主链：候选规则网格 -> 确定性 NetCDF classic/v3 写包 -> 内容寻址 RenderAsset（五元身份唯一，`nc-<hash32>`）-> 隔离 iframe -> `VoxelGridLayer3D` -> Volume/Contour/Slice。
- SDK 不入库、不进 Vue 打包：`scripts/install_supermap3d.py` 安装并钉住 `SuperMap3D.js` SHA-256；构建期对 iframe 运行时与 SDK 计算内容哈希注入 URL 查询串，升级即换 URL，旧缓存永不命中。
- 父页面与 iframe 用版本化协议 `gmp-supermap-volume/v2` 通信（postMessage 四重校验、单调 revision、失败回滚）；渲染成功以画布像素探针确认。
- `no silent fallback`：渲染失败显式诊断，禁止退化为点云/包围盒/静态图冒充成功。
- 32^3/64^3 基准网格 + 真实 SDK/GPU 作为发布门；Mock 只验证协议接线。

## 后果

- 正面：主应用与 SDK 解耦，SDK 升级不破坏业务代码；画面与后端共享成果身份与哈希；缓存升级安全。
- 代价：iframe 协议需要双向严格校验与超时治理；像素探针依赖真实 GPU 环境，CI 只能覆盖到 mock 层。
- 已知限制：单轴切片隐藏其他轴是 12.1 本机探针事实而非公开 API 保证，SDK 升级后必须重测（探针证据见 evidence/v0.7.0-single-axis-probe）。
