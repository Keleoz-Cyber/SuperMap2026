# 当前开发状态

> 更新时间：2026-08-05（v0.7.0 统一案例工作台·第一批分支更新）。本文是开发人员和开发 Agent 判断“现在做到哪一步”的唯一状态入口。数据细节见 [电阻率](../data/resistivity.md)、[微震](../data/microseismic.md)、[瓦斯](../data/gas.md) 和 [数据契约](../data/contracts.md)；目标产品见 [产品蓝图](../product-blueprint.md)。

## 1. 状态分层

项目必须区分三类状态，禁止混报：

1. **代码已实现**：当前仓库能够通过命令和测试重复生成或验证；
2. **外部派生/人工验证**：在相邻只读资料目录或 iDesktopX 中已经完成，但尚未写入当前代码；
3. **目标能力**：产品蓝图要求实现，当前还没有代码和运行证据。

## 2. 当前代码已实现

- **v0.7.0 统一案例工作台 · 第一批（`feat/v0.7.0-unified-case-workspace` 分支，发布候选）**：
  - 微震 **CSV 预置**案例：受控入库 `data/presets/microseismic/microseismic-vx-1911.csv`（LF 归一化字节 SHA-256 `ea3917c2…`，溯源原始文件 `微震局部三维点_3Sigma_去重均值_1911.csv`；1,911 行、XYZ 唯一、全有限、局部测线坐标、Vx=km/s），合同校验 fail-closed（`PRESET_SOURCE_INVALID`）。
  - 官方**普通克里金**基线：`python -m geomodeling.preset_cli analyze-microseismic` 执行固定 27 成员候选矩阵（spherical/exponential/gaussian × 12/24/36 邻域 × z_scale 0.5/1/2，固定种子 20260723 空间 5 折，公共有效集 1,910/1,911）；评审冻结 `config/presets/microseismic-official-baseline.json`——winner `exponential/neighbor=12/z_scale=2.0`，RMSE=0.268062、MAE=0.212624、R²=0.844559、Bias=0.053333（z_scale 为距离实验参数，不代表已确认地质各向异性）；源/报告指纹不符或选择不可复算即 `PRESET_BASELINE_INVALID`，绝不覆盖既有成果。
  - `seed-microseismic`（唯一生产 seed 入口）经正常 `Case → DatasetVersion → Experiment → Run → CandidateResult → materialize → FormalSelection` 链登记官方成果：确定性 UUID5 身份、幂等复用、并发无双选择、失败补偿无半成品；官方成果按 v0.6.1 候选成果链显式创建 **NetCDF** 原生体渲染资产（网格 35×47×82=134,890 单元，变量 `Vx`，`display_anchor_only` 显示锚点，非真实地理配准）。
  - 统一案例工作台：电阻率（`builtin_legacy`）、微震预置（**`builtin_preset`**）、用户上传（`user_upload`）同一 `workspace_kind`/`capabilities`/primary_dataset/official_result DTO 与 `/#/cases/:caseId` 工作台壳；`/case/resistivity` 兼容重定向；首页全部由 DTO 驱动，无 case_id 分支。未 seed 时预置卡可见但能力全 false，工作台返回类型化 `PRESET_NOT_INITIALIZED`。
  - 微震 **DAT** 导入**退出产品面**：首页 DAT 文案、`MicroseismicImportView`、导入路由、`POST /api/cases/{id}/microseismic-imports` 与派生 GET 端点全部移除；历史运行时文件、派生服务层与 CLI 保留，历史 DAT 成果经通用结果 URL 只读查看，领域证据导出（`domain_evidence/` 七文件、哈希不符 409）契约不变。
  - 用户从预置数据版本新建实验拥有独立的 experiment/run/candidate 身份，官方正式选择不可被用户操作改写。
- **v0.7.0 渲染与剖面分析 · 第二批（`feat/v0.7.0-rendering-slice-analysis` 分支，发布候选）**：
  - iframe 协议 v2（`gmp-supermap-volume/v2`）：单调 `revision` 完整渲染状态，过期 revision 忽略；slice 模式必须携带权威 slice 载荷（axis/index/coordinate/relativePosition 一律来自剖面 API 响应），`FRAME_READY` 上报含 `singleAxisSlice` 的能力；单轴切片以负坐标隐藏非活动轴为 SDK 12.1 真实 GPU 实测技术（`docs/evidence/v0.7.0-single-axis-probe/`），非文档化 API 承诺。
  - 渲染默认值（render_profile）：内置电阻率 log + native-spectrum，候选成果 linear + viridis；权威有效值非全正时 log 显式禁用并说明，绝不平移原始值。
  - 权威剖面分析：`GET /api/render-assets/{id}/slice-analysis`（`std_population` ddof=0、numpy-linear 分位数、valid+nodata=total，服务端从原始网格重算）；`POST .../slice-exports` 原子导出 `slice-analysis.zip`（`slice-analysis/v1`：slice.csv 真实 x,y,z 轴列、statistics.json 与 API 一致、manifest.json 哈希齐备；PNG 为 `client_echarts_canvas` 展示工件）；三来源（候选成果/内置电阻率/微震预置）共用 RenderAsset API 与组件。
  - 常驻渲染工具栏：模式/色带/标度/滤波/不透明度/光照/渐变透明度/包围盒运行时可调（受控色带/标度与剖面热力图共享）；X/Y/Z 正交切片控件（change 150ms 防抖、commit 立即）；等值面输入仅 contour 模式；no fallback——能力失败/哈希不符/协议错误/SDK 缺失均显式错误，无回退渲染器。
  - 测试基线（Task 12 后实测，本分支）：后端便携 `1352 passed`、前端 vitest `208 passed`、Mock E2E `10 passed`、真实 SDK live `8 passed`（platform 2 + 32³/64³ + legacy + 微震预置 + 隔离帧 + 单轴探针）。
- **v0.1.0 电阻率基线**：17,549 / 15,827 / 1,722 行，训练/验证空间柱重叠0；五模型各1,481 valid、241 NoData、XY mismatch 0；`baseline_passed=True`。
- `RHO_KRIG_FINAL_20M_40` 是唯一登记为正式的 SuperMap 体元成果；`dataset_verified=False`，目前只有配置、文件和人工证据。
- **微震 v0.2a 审计底座**：22个DAT、2,006条源记录、2,005条有限值和1条无效值；三张标准表、一维累计距离、问题清单、审计报告及CLI已经合并。
- **v0.3 iServer 纵向闭环（本分支）**：
  - `geomodeling.publishing`：iServer 客户端（Token、非异常化探测）、运行时探测（服务列表/数据服务 VOLUME 元数据比对/三维场景与图层）、六级发布证据链、浏览器加载回执存储。
  - `geomodeling.api`（FastAPI）：`/api/health`、`/api/iserver/status`、`/api/cases`、`/api/cases/resistivity`（排行榜=配置+指标产物）、`/api/cases/resistivity/publish-status`（实时证据链）、`/api/cases/resistivity/points`（17,549 点云，`source=platform_csv`，含 SHA-256）、`/api/evidence/browser-load`；iServer 凭据只走环境变量，浏览器不持有。
  - `web/`（Vue 3 + Vite + TS + Element Plus + iClient3D for Cesium）：案例首页、电阻率三维工作台（模型排行榜、RHO 点云三维场景、阈值/色带/抽稀/Z夸张交互、体元包围盒、发布证据链、服务检查、失败与问题清单、数据血统）。
  - **S3M 体元缓存浏览器渲染**：iDesktopX「体元栅格生成缓存」（S3M 2.0，26 瓦片）已发布为 iServer 三维瓦片服务；`/api/cases/resistivity/voxel-cells` 经 iServer REST 逐瓦片获取并解析（`geomodeling.publishing.s3mb`，fail-closed 契约校验：头部/版本/文件类型/wDescript/格点有限性/数量/包围盒），浏览器自定义渲染 7,056 格并支持点云/体元/叠加切换。解析器仅针对本缓存格式，不宣称通用 S3MB 解析；缓存刷新语义见运行说明 §4.2。
  - 测试基线：`157 passed`（80 基线 + 77 新增便携测试；API/发布适配/S3M 解析契约均不依赖本机 iServer 或真实数据）。
  - 运行说明与实测证据：[../v0.3-iserver-loop.md](../v0.3-iserver-loop.md)。
- **v0.4.0 通用建模平台（已发布）**：2026-07-25 自 merge commit `b95f12b` 发布 annotated tag `v0.4.0`，main CI 与标签 CI 均成功。
  - 通用上传（CSV/XLSX）、字段映射、质量门禁、IDW/普通克里金调参（手动+有限网格搜索，50 组合硬上限）、空间折分验证、公共有效指标排行榜、SQLite v4 持久化任务（取消/重试/重启恢复、在途 run 唯一约束）、成果工件与 X/Y/Z 切片、正式选择、证据导出与发布记录（manual_required）。
  - v0.3.1 电阻率案例以 `builtin_legacy` 只读适配器保留，全部 legacy 路由与证据语义不变；统一错误封套，本机绝对路径不下发浏览器（含 legacy points/metric_source/local cache）。
  - 案例预设登记于 `config/presets/`（resistivity=builtin_legacy、microseismic=upload_required，预设不含绝对路径、不自动导入私有数据；microseismic 预设在 v0.5 升级为 `domain_adapter`，见下条）。
  - 发布时测试基线（2026-07-25）：后端 `381 passed` + 前端 vitest `31 passed` + Playwright mock 冒烟 `1 passed`；`local_data 23 passed`（原始数据哈希不变）。
  - 真实浏览器验收（2026-07-24，本机 uvicorn 单进程）：上传 3D 夹具 → 质量校验通过（144/144）→ IDW 网格 4/4 候选成功（公共有效 144）→ 普通克里金 2/2 候选成功（球状 RMSE 0.749 / 指数 RMSE 0.783）→ 完整场点云（1,331 单元值域渐变可见）→ Z/X/Y 切片真实坐标标签 → 正式选择（理由落库）→ 导出 ZIP 七文件（SHA-256 清单 + 1,331 行 grid.csv）→ 发布登记 manual_required；iServer 离线时 legacy 页降级为「未验证但模型不受影响」，点云照常。截图：`docs/evidence/v0.4/v04-01..09*.png`。
- **v0.4.1 演示加固（`feat/v0.4.1-demo-hardening` 分支，发布候选）**：页面导航死路消除（PageNavigation，加载失败页同样可返回首页）；唯一权威演示数据 `demo/platform_demo_3d.csv`（SHA-256 固定）+ 下载端点；`geomodeling demo-check` 启动前检查（阻断/警告分级）；`scripts/start_demo.ps1` 安全启动脚本；真实 FastAPI+SQLite Live E2E（CI `browser-live`）；答辩运行手册 `docs/v0.4.1-demo-runbook.md`。
  - 候选测试基线（2026-07-25，本分支）：后端 `420 passed`、前端 vitest `43 passed`、Mock E2E `2 passed`、Live E2E `1 passed`、`local_data 23 passed`（哈希不变）。
  - 真实 Windows 彩排（2026-07-25，全新 `var/demo_v041`）：路线 A 全流程走通（IDW 与克里金各 1/1 成功，公共有效 144，导出 ZIP 七文件 1,331 行）；路线 B iServer 在线六级证据链全 `ok=True`（含 browser_report）；iServer 关闭后路线 B 如实降级、路线 A 不受影响；杀进程重启后案例/实验/成果全部恢复。截图与登记：`docs/evidence/v0.4.1/`。
- 当前仓库瓦斯保持暂缓。
- **v0.5 微震第二案例建模闭环（已发布，v0.5.0）**：2026-07-26 自 merge commit `d37eb94` 发布 annotated tag `v0.5.0`；微震从“外部派生”移入代码化。
  - 派生内核：22 个正式 DAT → 2,006 源记录（823/819/364）→ 2,005 有限（822/819/364，W8 `1.#QNAN0` 唯一无效）→ 已确认局部三维（W16 原点、X 沿 L3 向 W24、Y 沿 L2 向 W20、`local_engineering_m` 非 EPSG；`depth_m=WL/2(km)×1000` 向下为正、`z_local_m=-depth_m`；规则版本 `microseismic_local_3d_v0.2b_confirmed_2026-07-20`，适配器 0.5.0）→ 一次全局 3σ（样本标准差 `ddof=1`、两遍顺序累加）剔除 80（深度 72、速度 8）→ 1,925 候选（792/783/350）→ 三 float 完全相等分组、算术平均聚合（13 冲突组/27 组内记录/坍缩 14，组内最大极差 0.913554 km/s）→ 1,911 唯一建模节点。
  - 黄金门禁：accepted/rejected 两张 canonical CSV（UTF-8 BOM + CRLF）SHA-256 逐字节锁定（`4f7a0886…ae1513` / `3752b2f6…872b1`），计数、分层、剔除原因、冲突组一并核对；任一检查失败即阻断导入，`downstream_gates` 全部保持 blocked。
  - 入口等价：浏览器首页微震卡 → `/cases/new?preset=microseismic` → 四步导入向导（选文件夹或 22 DAT → 核验 → 派生确认 → 质量门禁 → 建模）；CLI `geomodeling microseismic derive` 与 `import-case`；API `POST /api/cases/{id}/microseismic-imports`（multipart 22 DAT，201）、`GET /api/datasets/{id}/derivation`、`.../derivation/artifacts/{name}`（白名单）、`.../derivation/points?layer=accepted|rejected|aggregated&decimate=1`。导入原子化：失败补偿不留数据库行、正式目录或临时目录。
  - 平台接入：预设 `config/presets/microseismic.json`（`source=domain_adapter`、`adapter_id=microseismic_dat_v05`）；IDW 36 组合 / Kriging 27 组合网格搜索；`z_scale` 实验参数（预设 0.5/1/2，`0<z_scale≤20`，仅距离/邻域/变异函数拟合使用，不写回物理坐标）；默认 50 m 网格（X[-750,960] Y[-995,1310] Z[-4086.538,-37.5]，约 134,890 单元 < 100 万上限）；整根 XY 采样柱折分空间验证 + 按测线/测点分组诊断（不改变公共排名）。
  - 成果与导出：成果工作台三层诊断图层（1,911 节点默认开，1,925 候选与 80 剔除默认关）；导出 ZIP = 标准七文件 + `domain_evidence/` 七文件（`source_manifest.json`、`derivation_report.json`、五个分层 CSV），全部带 SHA-256；发布登记保持 `manual_required`。
  - 测试基线（Task 14 后实测，本分支）：后端 `564 passed`、前端 vitest `66 passed`、Mock E2E `3 passed`、Live E2E `2 passed`、`local_data 27 passed`。
  - 运行手册：[../v0.5-microseismic-loop.md](../v0.5-microseismic-loop.md)。
- **v0.6 专业建模增强（`feat/v0.6-professional-modeling` 分支，当前代码已实现（本分支），发布候选）**：
  - 专业诊断：全向/方向经验半变异函数（点对确定性采样，种子=数据 SHA-256+诊断配置，≤50,000 点对上限，DTO/工件披露总点对、实际点对、采样率与种子来源）；球状/指数/高斯三模型按 bin 点对数加权的有界最小二乘拟合证据（`weighted_sse`/收敛/边界）；方向约定 方位角 `[0°, 180°)`、倾角 `[-90°, 90°]`（2D 无倾角），方向 bin 支持不足标记 unsupported 不外推。
  - 各向异性：候选仅作诊断建议，人工确认写入不可变快照（改参数必新快照）；Kriging 变换 `x′ = S Rᵀ x`，legacy `z_scale` 归一化进尺度矩阵不叠加；参数来源区分 `automatic_candidate`（折内）/`final_full_data_fit`（全数据物化）/`manual_confirmed`（固定参数标记 `user_prior`）/`legacy_auto_fold_fit`（v0.5 旧候选）。
  - 邻域与插值：旋转椭圆/椭球+扇区搜索邻域（IDW 与普通 Kriging 共用选择器；IDW 权重仍用 `z_scale` 距离，邻域方向仅采样几何）；普通 Kriging 原生方差 `σ² = λᵀγ₀ + μ`（微负钳制计诊断、显著负值/非有限 NoData、lstsq 降级标记）；所有算法输出折外残差与经验误差尺度（距离加权局部 RMSE，非标准误）；空间折分检查（整柱不泄漏，泄漏整次运行 fail-closed）。
  - 异常与比较：显式阈值异常连通区（direction high/low、可选误差门槛、2D 4 邻接/3D 6 邻接、最小支持节点数；Voronoi「网格支持面积/体积估计」，非储量）；保存为不可变提取；双候选兼容指纹比较（兼容才显示同口径指标差，不兼容只独立查看）。
  - 平台与入口：SQLite v5 新增五表（`professional_diagnostics`/`professional_confirmations`/`professional_result_artifacts`/`anomaly_extractions`/`analysis_jobs`，部分唯一在途索引）；诊断与异常提取走 `analysis_jobs` 持久化任务（取消/重试/重启转 `interrupted`）；能力矩阵类型化 `not_applicable`，旧候选 `LEGACY_RESULT_NOT_COMPUTED`；专业证据 ZIP（`professional/` 目录，声明缺失或哈希不符 409 fail-closed）；浏览器专业诊断工作台 + 专业分析台、API（`professional-diagnostics`/`analysis-jobs`/`professional-comparisons`/白名单工件下载）、CLI（`geomodeling professional diagnose/confirm/inspect-result/extract-anomalies/compare`）三入口。
  - 测试基线（Task 23 后实测，本分支）：后端 `1153 passed`（便携 1124 + `local_data 29`）、前端 vitest `97 passed`、Mock E2E `4 passed`、Live E2E `3 passed`。
  - 运行手册：[../v0.6-professional-modeling-loop.md](../v0.6-professional-modeling-loop.md)。发布门说明：PR 未合并、tag/release 待批准。
- **连续体渲染 POC（已合并入 main，已被 v0.6.1 取代）**：独立 `/volume-demo` 曾把电阻率 S3M 缓存采样（7×21×48/7,056，采样值域 2.291–127.281）经三线性可视化重采样渲染为连续半透明体，本机验收通过。该 POC 已被 v0.6.1 的 SuperMap3D NetCDF 原生体渲染取代，其产品代码不进入 v0.6.1（Task 16 集成分支删除）；历史证据保留于 `docs/evidence/volume-rendering-poc/`。

- **v0.6.1 NetCDF 原生体渲染（`feat/v0.6.1-netcdf-native-rendering` 分支，当前代码已实现（本分支），发布候选）**：
  - 渲染器收敛：浏览器内唯一连续体渲染器为 SuperMap3D 12.1 `VoxelGridLayer3D` + 确定性 NetCDF classic/v3 体包（`volume.nc` + manifest v2 + checksums，同身份逐字节相同）；SuperMap3D 只加载于同源体渲染 iframe（`web/public/supermap-volume-frame/`，postMessage 协议 `gmp-supermap-volume/v1`，v0.7.0 第二批起升级为 v2 完整状态协议），Vue 父页只持有业务状态与控件、不加载任何旧全局 Cesium。点元只是显式标注的 auxiliary points（辅助/证据层），与体共用同一显示变换，绝不把失败的体渲染变成成功；失败语义为 no silent fallback，不存在任何回退渲染器。
  - 坐标契约：`wgs84_display_anchor_v1` 显示锚点（120°E / 30°N）把局部米制网格映射到规则 WGS84 显示网格；页面必须显示 `display_anchor_only`，不宣称真实地理配准。
  - 资产与 API：`render_assets` 表（SQLite v5→v6 事务迁移）；候选 `GET render-capability` / `POST|GET render-assets/netcdf`、legacy `GET /api/cases/resistivity/render-capability` / `POST|GET render-assets/netcdf`、不可变资产 `GET /api/render-assets/{id}/manifest` 与 `/volume.nc`；POST 是唯一创建路径（首个成功 201、ready 幂等 200、creating 409、failed/interrupted 须 `retry_failed=true` 显式重试），所有 GET 纯查询；manifest/grid/NetCDF 哈希双向核验，损坏资产原子隔离不自动删除（`RENDER_ASSET_CORRUPT`）。
  - legacy 边界：内置电阻率需经 `python -m geomodeling.render_cli import-csv` 登记权威规则网格才支持体渲染；未登记显示 `LEGACY_RENDER_SOURCE_NOT_REGISTERED` + auxiliary points 测点辅助层，绝不从散点自动重建正式网格、绝不重跑 Kriging。
  - 能力 fail-closed：2D、不规则轴、无源、全 NoData 源返回稳定能力/错误码；渲染源属性/单位来自数据集 profile（不固定 rho 语义）。
  - 取代关系：main 分支 PR #10 已合并入 main，其 `/volume-demo` 是被本方案取代的自研 WebGL2 光线步进 POC，属非产品路由（Task 16 集成分支将删除其产品代码）；自研光线步进渲染路径已被取代，旧 `Field3D`/`RhoScene3D` 与 index.html 旧全局 Cesium 已退出产品代码（`tests/test_v061_rendering_contract.py` 防护）。
  - 性能事实（Task 14 参考机实测，RTX 4070 Laptop）：32^3 与 64^3 真实 SDK 渲染 rendered <2s、交互稳定 <0.5s（远低于 30s/5s 发布门）；filter/opacity/Slice/Contour 四命令像素响应均超静帧噪声；证据存 `docs/evidence/v0.6.1-netcdf-native/`。
  - 明确不做：真实 CRS 配准、WebGPU、128^3、iServer/S3M 分发、iDesktopX DatasetVolume、移动端、散点自动重建正式网格、任何形式的回退渲染器。
  - 测试基线（Task 14 后实测，本分支）：后端便携 `1274 passed`、前端 vitest `157 passed`、Mock E2E `5 passed`、Live E2E 真实 SDK 32^3/64^3 各 `1 passed` + 既有 `3 passed`。
  - 运行手册：[../v0.6.1-netcdf-native-rendering-runbook.md](../v0.6.1-netcdf-native-rendering-runbook.md)。发布门说明：本分支实现完成，tag/release 待批准。

## 3. 外部派生与人工验证（尚未代码化）

| 案例 | 已有证据 | 当前边界 |
|---|---|---|
| 电阻率 | 已在iDesktopX复现完整体元、水平薄切片和阈值过滤；`WorkSpace.smwu` 已发布 iServer 三服务（人工 UI 步骤） | 垂直切片未正式验证；原生等值面失败；RHO单位和绝对EPSG未知；体元在三维服务中仅 ImageFileLayer，S3M 体渲染待缓存 |
| 微震 | 人工派生表（1,925候选/80剔除）已转为 v0.5 黄金回归来源：代码从原始 DAT 重新生成并逐字节锁定哈希；iDesktopX 人工复现保留为来源证据 | 绝对地理配准仍未知，不得跨案例叠加；iServer 自动发布保持 `manual_required` |
| 瓦斯 | 已生成58条合格三维候选样本（28个位置），三维点可在平面场景显示，并生成过IDW体元 | 体元加入三维场景会导致iDesktopX原生崩溃，当前暂缓作为正式演示案例 |

微震派生事实（现为黄金回归锁定口径）：

- `微震局部三维点_3Sigma_1925.csv`：1,925条，L1/L2/L3 = 792/783/350；
- `微震3Sigma剔除记录_80.csv`：80条，其中深度原因72条、速度原因8条；
- W8的`1.#QNAN0`在3σ之前已从2,006条源记录中排除，不填0、不插补；
- 局部坐标、深度和单位规则见[微震文档](../data/microseismic.md)。

瓦斯派生事实：

- 当前工程坐标约定：西安1980、6°分带、第20带、中央经线117°，带号坐标按EPSG:2334工作；
- 三维候选文件：`煤层瓦斯三维插值点_合格58.csv`，58条、28个位置；
- `Z = SURF_Z - (END_DEPTH - THICKNESS/2)`，其中`SURF_Z`来自现有DEM派生表；
- iDesktopX失败对象：`GAS_CH4_IDW_R1000_N12_P1`；点图层正常，体元加载在`Layer3DSettingVolume.setSliceCoordinate`链路崩溃；
- 该失败不能反推插值数值错误，也不能把体元登记为正式可视成果。

## 4. SuperMap/iServer环境

- 本机iServer目录存在，构建标识为`12.1.0.0-260626-9297`；
- **2026-07-22 v0.3 实测**：8090 已启动监听；管理员已初始化（凭据为本机密钥，不入库）；试用许可有效至 2026-09-20；`WorkSpace.smwu` 已通过管理 UI 发布 data/map/3D 三服务，`RHO_KRIG_FINAL_20M_40` 的 VOLUME 元数据与平台登记一致；
- 已知环境问题：全局 `CATALINA_*` 变量指向其他 Tomcat 会致 iServer 启动异常，须先清理（见 [v0.3 运行说明](../v0.3-iserver-loop.md) 3.1）；
- `workspaces` REST 快速发布在本机 500（管理 UI 正常），列为 ISSUE-V03-01；
- 产品包中的`iClient/for3D/webgl/examples/examples.html`只是“产品包不含iClient”的占位提示；v0.3 前端 SDK 来自官方 npm 包 `@supermap/iclient3d-vue-for-webgl`（`scripts/fetch_iclient3d.py` 获取，不入库）；
- REST、管理OpenAPI、三维缓存发布和iClient3D阅读顺序见[SuperMap集成说明](../supermap-integration.md)。

## 5. 当前开发主线

首个开发里程碑不是一次实现全部上传、调参和三类数据，而是完成可演示纵向闭环：

```text
现有电阻率成果
→ iServer启动/能力探测
→ 发布至少一个可访问服务
→ FastAPI返回案例、成果和发布状态
→ 浏览器加载SuperMap成果并显示参数、指标和证据
```

**v0.3 已打通该闭环**（运行证据见 [v0.3 运行说明](../v0.3-iserver-loop.md)）：iServer 启动与许可验证、`WorkSpace.smwu` 三服务发布、FastAPI 实时证据链接口、浏览器 iClient3D 三维场景与浏览器加载回执。遗留边界：体元真体渲染（S3M 缓存）、垂直切片 Web 验证、workspaces REST 程序化发布。

完成纵向闭环后，再依次加入通用CSV/XLSX上传、字段映射、IDW/Kriging计算、手动调参、网格搜索和空间验证。微震是第二个正式案例；瓦斯保留接口和数据证据，待平台主干完成后再处理体元兼容问题。

## 6. 明确未实现

- 任务队列、WebSocket进度；
- 通用CSV/XLSX上传的字段映射外扩展与数据版本管理；
- 微震绝对地理配准与跨案例空间叠加（需共同控制点证据）；
- iServer 程序化发布（REST workspaces POST，ISSUE-V03-01）、S3M 体元缓存发布与体渲染、垂直切片 Web 验证；
- 瓦斯体元稳定显示、原生等值面、DSI-like/GOCAD后端；
- 自动成矿概率、储量或地质结论。

## 7. 给开发 Agent 的判定规则

- 以本文和[产品蓝图](../product-blueprint.md)为当前事实入口；论文只作来源证据，不能覆盖已确认规则。
- 外部CSV存在或iDesktopX人工成功，不等于当前代码已经实现。
- 插值成功、文件导出成功、iServer发布成功、浏览器加载成功是四个独立状态。
- 三类案例没有共同控制点，不得叠加或描述成同一研究区多源融合。
- 瓦斯三维暂缓不能阻塞电阻率纵向闭环和通用平台开发。
