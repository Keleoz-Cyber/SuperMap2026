# 技术架构

> 受众：开发者与技术评委。本文是架构分层、模块边界、数据生命周期、算法与验证体系、渲染链与术语的唯一权威说明。
>
> 更新时间：2026-08-25；适用版本：1.0.1。重大技术决策的背景与取舍见 [decisions/](decisions/)。

## 1. 总体架构

```text
┌──────────────────────────────────────────────────────────────┐
│ Vue 3 + TypeScript 浏览器前端                                  │
│ 首页指挥舱 / 上传 / 质量 / 调参 / 比较 / 成果 / 分析 / 三维渲染 │
└─────────────────────────────┬────────────────────────────────┘
                              │ REST / JSON / multipart / ZIP
┌─────────────────────────────▼────────────────────────────────┐
│ FastAPI 后端                                                  │
│ 数据合同 │ 领域服务 │ 算法 │ 空间验证 │ 分析 │ 渲染 │ AI       │
└─────────────────────────────┬────────────────────────────────┘
                              │
┌─────────────────────────────▼────────────────────────────────┐
│ SQLite + 不可变文件工件                                        │
│ 数据集 / 实验 / 运行 / 候选 / 正式成果 / RenderAsset / Export  │
└─────────────────────────────┬────────────────────────────────┘
                              │
┌─────────────────────────────▼────────────────────────────────┐
│ SuperMap 技术层                                               │
│ SuperMap3D 浏览器 SDK / iDesktopX 人工复核 / iServer 服务      │
└──────────────────────────────────────────────────────────────┘
```

| 层级 | 技术 |
|---|---|
| 前端 | Vue 3、TypeScript、Vue Router（哈希路由）、Element Plus、ECharts、Vite |
| 三维 | SuperMap3D 2026 浏览器 SDK、`VoxelGridLayer3D`、隔离 iframe |
| 后端 | Python 3.12、FastAPI、Pydantic、SQLAlchemy、Typer CLI |
| 数值与数据 | pandas、NumPy、SciPy、scikit-learn、PyArrow |
| 存储 | SQLite + 不可变文件工件 |
| 三维成果格式 | NetCDF classic/v3 RenderAsset |
| 自动化质量 | pytest、Vitest、Playwright、GitHub Actions 双速 CI |
| 发布 | Windows x64 / macOS ARM64 免安装 ZIP、SHA-256 完整性清单 |

## 2. 后端结构与模块边界

后端包 `src/geomodeling/` 分为根级模块与七个子包。核心纪律：路由层只做 HTTP 校验、服务调用与 DTO 转换；领域逻辑全部在服务层；公开输出一律走白名单 DTO，绝不外发本机绝对路径。

### 2.1 子包职责

- `geomodeling.platform`：平台核心。案例（Case）、数据版本（DatasetVersion）、实验（Experiment）、运行（Run）、候选（CandidateResult）、正式选择（FormalSelection）、持久化任务与补偿事务；含 SQLite 持久化（`db`/`tables`/`repositories`）、目录布局（`settings`）、上传与接入（`uploads`/`ingest`）、质量（`quality`）、实验展开与运行（`experiments`）、成果物化（`results`）、工作线程（`worker`/`jobs`）、案例生命周期（`case_lifecycle`）、数据准备状态机（`data_preparation`）、专业分析服务（`professional`/`analysis_jobs`）、渲染资产与 NetCDF（`render_assets`/`netcdf_volume`/`render_coordinates`/`render_profiles`/`legacy_render_sources`）、剖面分析（`slice_analysis`/`slice_exports`）、导出与发布（`exports`/`publications`）、预置案例（`*_preset`）、地质研判规则（`geological_interpretation`）、AI 研判（`ai_analysis`）、成果级分析（`result_analysis`）、候选比较（`candidate_comparisons`）、legacy 适配（`legacy_adapter`）、公开 DTO（`public_dto`）与错误封套（`errors`）。
- `geomodeling.modeling`：通用建模引擎。统一插值器协议（`base`：`fit -> predict(query, cancel)`，协作取消、分块预测）；五算法实现（`idw`/`kriging`/`dsi_like`/`random_forest`/`kriging_rf_residual`）；空间折分（`splits`）、折证据（`fold_artifacts`）、指标（`metrics`）、规则网格（`grid`）、切片（`slices`）、变异函数（`variogram`）与方向变异函数（`directional_variogram`）、点对采样（`pair_sampling`）、各向异性（`anisotropy`）、旋转邻域（`neighborhood`）、不确定性（`uncertainty`）、异常（`anomalies`）、比较（`comparison`）、ML 特征（`spatial_features`）与溯源（`provenance`）。
- `geomodeling.analysis`：统计与空间分析。profile 注册表按映射属性（而非案例 ID）判定领域模块；有限统计（分位、直方图、log10 直方图、空间网格聚合、逐轴剖面、Z 分层、p25/p75 阈值、梯度）。
- `geomodeling.api`：FastAPI 应用工厂 + 依赖解析 + 12 个路由模块（demo/cases/datasets/analysis/experiments/runs/results/result_analysis/ai_analysis/ai_settings/professional/rendering/trash/microseismic）。启动时恢复中断任务；前端 `web/dist` 存在时以 StaticFiles 托管。
- `geomodeling.microseismic`：微震 DAT 领域子系统：解析（parser）、审计合同（contracts）、局部 XYZ 派生（derivation）、3σ 过滤（filtering）、黄金门禁（golden）、聚合（aggregation）、规范输出（canonical）与平台原子导入适配器（platform_adapter）。
- `geomodeling.publishing`：iServer 发布边界：客户端（client）、探针（probe）、S3M 历史兼容（s3mb）、体元缓存合同（cache_contract/cache_manifest）与浏览器加载证据（evidence）。
- `geomodeling.integrations`：DeepSeek 外部服务受控适配（OpenAI 兼容 Chat Completions，JSON 模式，Key 只存服务端）。

### 2.2 根级模块

`cli.py`（主 CLI 与命令组挂载）、`preset_cli.py`（预置维护独立入口）、`professional_cli.py`、`render_cli.py`、`config.py`、`validation.py`/`metrics.py`/`model_tasks.py`/`registry.py`/`supermap.py`/`reports.py`/`schemas.py`（v0.1-v0.3 遗留验收链，由 `config/default.yaml` 驱动）、`demo_check.py`、`portable.py`（免安装启动器）、`audit.py`、`io.py`、`runtime_paths.py` 等。

专业建模模块合同清单：`professional_contracts`、`pair_sampling`、`directional_variogram`、`anisotropy`、`neighborhood`、`uncertainty`、`anomalies`、`comparison`、`fold_artifacts`。渲染模块合同清单：`render_contracts`、`render_coordinates`、`render_assets`、`netcdf_volume`、`legacy_render_sources` 与 `rendering` 路由；SQLite `render_assets` 表登记身份、状态与哈希。

## 3. 前端架构

- 单页应用：Vue 3 组合式 API + TypeScript 严格模式；13 条路由（哈希模式保证 FastAPI StaticFiles 托管下深链刷新不 404）；未匹配深链回首页。
- 状态管理：**无全局状态库**。除全局壳上下文（案例/阶段身份登记）与图表↔三维选择联动组合式控制器外，状态全部组件局部，并以"单调请求序号守卫"防止旧响应覆盖新请求。
- API 封装单点：`web/src/api/client.ts` 统一封装全部 HTTP；解析后端错误封套 `{error:{code,message,details}}`；上传 FormData、下载 blob + Content-Disposition。
- 长任务无 WebSocket：全部为 setInterval 轮询（运行/诊断/异常任务 1000ms，NetCDF 资产 2000ms），终态即停，组件卸载清理。
- 纪律：POST 是唯一显式变异入口；能力与状态刷新一律纯 GET；浏览器绝不计算统计结果；mock 数据只存在于自动化测试。

## 4. 数据生命周期与通用合同

```text
原文件
  -> SourceManifest（大小、SHA-256、来源）
  -> DatasetVersion（字段、单位和坐标映射）
  -> 质量门禁
  -> Experiment（用户意图）
  -> Run（不可变参数快照）
  -> CandidateResult（OOF、指标和网格）
  -> FormalSelection
  -> Materialized Result / RenderAsset
  -> Export / PublicationEvidence
```

必须遵守：

- 原始资料只读；所有派生数据携带来源哈希和规则版本。
- 来源可核验：源文件、关键工件、网格和证据都有 SHA-256，读取前复核大小与哈希。
- 参数不可变：Run 创建后参数快照不可被修改。
- 无证据不猜测：坐标、单位或 Z 方向无证据时标记未知，不得猜测 EPSG。
- NoData 不等于 0：无效 token（含微震 `1.#QNAN0`）保留原文与源行；历史电阻率导出的 `-9999` 只在适配层转为 `null + is_nodata=true`。
- 补偿事务：数据库登记与工件落盘任一步失败都清理本次残留，同时保留最初业务错误；公开 DTO、日志、SQLite、ZIP 与错误消息不暴露本机路径或凭据。
- 候选比较必须使用相同数据版本、折分指纹和公共有效集；正式选择要求 Run 与 CandidateResult 均为 `succeeded`。
- 失败关闭（fail-closed）：证据不完整或身份不一致时拒绝输出，而不是带病继续。

## 5. 持久化设计

- 存储：SQLite 单库（默认 `var/geomodeling/platform.sqlite3`，`GEOMODELING_DATA_DIR` 可覆盖）+ 不可变文件工件树（uploads/datasets/experiments/results/exports/render-assets/render-sources/comparisons/purge-quarantine/staging）。
- Schema 版本化迁移（SCHEMA_VERSION=8），事务内显式核验；启动时恢复中断运行、中断分析任务、损坏渲染资产与未完成的两阶段删除。
- 核心表：`cases`、`dataset_versions`、`quality_reports`、`experiments`、`runs`（部分唯一索引保证每实验至多一个进行中运行）、`candidate_results`、`formal_selections`、`exports`、`publications`、`professional_diagnostics`、`professional_confirmations`（不可变快照）、`professional_result_artifacts`、`anomaly_extractions`、`analysis_jobs`、`render_assets`（五元身份唯一，内容寻址）、`case_purge_operations`、`ai_analysis_records`。
- 约定：结构化字段一律 canonical JSON（排序键、紧凑分隔）；时间戳 UTC ISO-8601；仓储层 ORM 行不跨边界，状态迁移用显式比较更新。

## 6. 建模算法

统一协议：`Interpolator.validate_parameters / fit -> predict(query, cancel)`；预测分块（20,000/块）；类型化失败码（如 `RUN_CANCELED`、`KRIGING_VARIANCE_INVALID`、`DSI_LIKE_NOT_CONVERGED`、`ML_RESIDUAL_COVERAGE_INSUFFICIENT`）。

### 6.1 IDW 反距离加权

\[
\hat z(x_0)=\frac{\sum_i w_i z_i}{\sum_i w_i},\qquad w_i=\frac{1}{d(x_0,x_i)^p}
\]

cKDTree 邻域 + 距离幂加权；精确点（距离近于阈值）直接复现观测；邻点不足标 NoData，绝不造值。支持幂次、邻点数、搜索半径、最小邻点、`z_scale` 距离缩放（实验性参数，不是地质各向异性）与专业旋转椭圆/椭球扇区邻域。

### 6.2 普通克里金

\[
\hat z(x_0)=\sum_i\lambda_i z(x_i),\qquad \sum_i\lambda_i=1
\]

局部增广普通克里金系统（拉格朗日 μ）；奇异系统降级最小二乘并计数；**原生方差** `σ² = λᵀγ₀ + μ`（微负钳 0，显著负或非有限标 NoData）。变异函数模型 spherical/exponential/gaussian；auto 模式只在训练折内拟合；支持人工 nugget/sill/range 与规范各向异性变换（与 `z_scale` 互斥）。

### 6.3 DSI-like 离散平滑（仅 3D）

工程近似（**不等同 GOCAD DSI**）：IDW 初始场 -> 观测吸附最近节点（碰撞取均值）-> 稀疏图拉普拉斯迭代平滑（观测节点 Dirichlet 硬约束，不可关闭）-> 收敛门（未收敛即 `DSI_LIKE_NOT_CONVERGED`，绝不回退 IDW 冒充成功）-> 原观测点残差精确化（复算误差上限 1e-8，越界即失败）。盒外恒 NoData。

### 6.4 随机森林空间回归

确定性坐标派生特征 `spatial_features.v1`（2D 7 特征 / 3D 10 特征，中心化归一化）-> sklearn RandomForestRegressor（固定随机种子）。树间标准差作为 `model_dispersion` 辅助场——只表示树模型分歧，不是概率置信区间。

### 6.5 克里金残差随机森林

防泄漏两段式：内部空间折逐折拟合克里金 -> 折外（OOF）基线 -> OOF 残差训练随机森林 -> 全量重拟合基线；预测 = 基线 + 残差校正。OOF 覆盖不足即类型化失败。成果四场：`prediction`、`kriging_baseline`、`residual_correction`、`model_dispersion`。融合不保证优于克里金；真实电阻率验收中残差校正反而变差，系统如实显示。

## 7. 空间验证与可信证据体系

- **整 XY 柱空间折分**：3D 按量化容差内的相同 (X,Y) 分柱，同一柱的所有 Z 样本永不跨训练/验证侧；2D 按均匀网格单元分组；分组洗牌后贪心装桶保证每行恰好一次验证。分组不足即 `SPLIT_INSUFFICIENT_GROUPS`。
- **折分计划先行**：折分配表（fold_index/source_row/group_key/role/leakage_detected）在任何候选行持久化之前构建；行级或组级重叠即 `FOLD_LEAKAGE_DETECTED`，整个运行失败。
- **折分指纹**：canonical JSON（数据 SHA-256 + 验证规格 + 逐行折分配）的 SHA-256；候选指纹 = 算法/参数/网格/验证/专业上下文的 canonical JSON SHA-256（网格搜索上限 50 组合）。
- **公共有效集**：一次运行内所有成功候选非 NoData 预测点交集；全部公开指标只在公共掩膜上复算——候选不能靠标 NoData 买排名。
- **OOF 残差证据**：折外预测规范化落盘（`fold_assignments.parquet` + `out_of_fold_predictions.parquet`），度量引用两者 SHA-256；工件写校验为临时写 -> 回读校验 -> 原子替换。
- **自动变异函数只在训练折拟合**；最终完整场在全部有效建模数据上重拟合并标 `final_full_data_fit`。

## 8. 专业地统计

- **方向半变异函数**：全向 + 方向 γ(h)；点对超过 50,000 时按距离层与方向层确定性分层抽样，种子由数据 SHA-256 与配置派生（不依赖进程时间），证据中披露采样率。方位角在 XY 平面由 +X 向 +Y，范围 `[0°, 180°)`；倾角范围 `[-90°, 90°]`。
- **证据拟合**：三模型点对数加权有界最小二乘；可用 bin 不足、不收敛或贴非法下界即 `VARIOGRAM_FIT_FAILED`，绝不静默回退。
- **各向异性确认**：候选只是诊断建议（`diagnostic_suggestion`）；用户确认后形成不可变快照。空间变换 `x′ = S Rᵀ x`（R = Rz(方位角)·Ry(−倾角)·Rx(滚转)）；变换指纹为 canonical JSON SHA-256 前 16 位。
- **参数来源枚举**：`automatic_candidate`、`final_full_data_fit`、`manual_confirmed`、`user_prior`、`legacy_auto_fold_fit`。
- **克里金原生标准差**采用 `σ² = λᵀγ₀ + μ`，不是未来事件风险的概率保证；**经验误差尺度**是折外残差在显式邻域内的距离加权局部 RMSE，**不是标准误**；两者与模型离散度都**不是概率置信区间**。
- **旋转邻域**：安全外接球候选 -> 旋转坐标精确椭球判定 -> 等分扇区稳定截断；邻点不足返回拒绝原因，绝不扩半径或退化全局。
- **异常连通区**：显式阈值（高值 v≥t、低值 v≤t），2D 为 4 邻接、3D 为 6 邻接；逐连通区给出 Voronoi 支持面积/体积估计（明示是网格支持估计、不是储量）、加权质心、值统计与触界标记。不适用能力返回 `not_applicable`；旧成果缺失专业计算返回 `LEGACY_RESULT_NOT_COMPUTED`，不伪造零值。
- **双候选比较**：同数据版本、同折分指纹、同验证行身份、公共掩膜交集与值单位一致才给出指标差值，否则逐项列出不兼容字段。

## 9. 三维渲染链与 SuperMap 集成

当前正式链：

```text
CandidateResult 规则网格
  -> NetCDF classic/v3 RenderAsset
  -> 隔离 iframe
  -> SuperMap3D VoxelGridLayer3D
  -> Volume / Contour / X/Y/Z Slice
```

- **RenderAsset 合同**：登记成果 ID、数据版本、网格哈希、维度、坐标、变量、单位、值域、NoData 与显示锚点；五元身份（source_kind/source_id/grid_sha256/renderer/format_version）唯一，内容寻址（`nc-<hash32>`）；每次下发复核当前文件哈希，损坏资产原子隔离并类型化报错。
- **NetCDF 写包**：确定性输出（无时间戳、无绝对路径，同身份逐字节相同）；维度恰 x/y/z，Float32 坐标变量，NoData 属性与存储均为 -9999.0；写后回读校验 fail-closed。
- **显示锚**：局部米制网格经 `wgs84_display_anchor_v1` 映射到固定锚点附近的规则 WGS84 显示网格，状态 `display_anchor_only`——不代表真实 EPSG 配准；`auxiliary points` 只能作为辅助/证据层，不冒充体场。
- **隔离 iframe 协议 `gmp-supermap-volume/v2`**：父页面发送完整渲染状态与单调 revision，iframe 拒绝旧状态、失败回滚并回传能力/身份/相机/诊断；入站消息四重校验（origin/source/协议/requestId）。渲染成功以画布像素探针确认，初始化含 manifest 身份四元组与显示变换双重校验。
- **三种渲染模式**：Volume（体渲染）、Slice（单轴切片，相对位置只来自父侧权威剖面响应）、Contour（等值阈值）；支持色带传递函数、值域滤波、不透明度曲线与光照。
- **切片与剖面合同**：X/Y/Z 切片坐标与统计来自后端权威切片 API，合同为 `slice-analysis/v1`；标准差字段采用总体标准差 `std_population`；前端热力图 PNG 溯源标记为 `client_echarts_canvas`。`FRAME_READY` 能力中的 `singleAxisSlice` 决定是否开放单轴控制；单轴切片隐藏其他轴是 SuperMap3D 12.1 本机探针事实（非公开 API 保证），升级 SDK 后必须重测。
- **no silent fallback**：渲染失败显式诊断，不改画点云、包围盒或静态图片冒充体渲染成功。32^3/64^3 基准网格用于真实 SDK/GPU 性能门；历史 S3M 2.0 `PointCloudFile` 只保留严格兼容证据读取，不是当前主路径。
- **SuperMap 职责边界**：iDesktopX 人工复核、iServer 服务、SuperMap3D 表达；平台职责是数据合同、建模、验证、NetCDF、分析、导出与证据链。iServer 离线不影响建模主链；通用成果发布默认 `manual_required`，无实时对象级回执不得标为发布成功。
- **SDK 供给**：`scripts/install_supermap3d.py` 将官方 iClient3D 2026（SuperMap3D 12.1）安装到 `web/public/SuperMap3D-2026`，钉住 `SuperMap3D.js` 的 SHA-256，staging 原子替换，支持 `--verify-only`；SDK 不入库、不进 Vue 打包。构建期对 iframe 运行时与 SDK 计算内容哈希并注入 iframe URL 查询串，实现"warm-cache 升级即换 URL，旧缓存永不命中"。

官方参考：[SuperMap iServer 帮助](https://help.supermap.com/iServer/1201/zh/)、[SuperMap iDesktopX 帮助](https://help.supermap.com/iDesktopX/zh/)（URL 中的 `1201` 是官方文档路径；演示时仍应核对本机产品构建号与许可证）。

## 10. 成果分析与地质研判

- **成果级分析**（`result_analysis`）：只读已物化网格的确定性分析（值统计、NoData、结构异常连通区、深度剖面、与克里金基线的联动对比），LRU 缓存；结果与三维标注共享稳定组件 ID。
- **地质研判规则**（`geological_interpretation`，版本化 `geological_interpretation.v1`）：按属性域（电阻率/微震速度/瓦斯含量 × 高/低异常）将连通区组织为"数值事实 -> 可能解释 -> 潜在影响 -> 建议核查"；规则只翻译既有证据，不产生新数值；自定义属性无受控规则时安全降级通用分析。
- **AI 研判**（`ai_analysis` + `integrations/deepseek`）：确定性分析 -> 严格合同 EvidencePacket -> prompt（quick/review 两档）-> DeepSeek（JSON 模式、温度 0）-> 严格校验（禁用断言词表：含水/危险/储量等正向断言直接拒绝）-> 记录（相同证据哈希默认复用）。Key 只存服务端（环境变量、Windows 凭据管理器或 macOS 钥匙串），不进浏览器、日志、SQLite、导出包与 Git；AI 不可用时规则分析照常成功。

## 11. 错误处理与 fail-closed 纪律

统一错误封套 `{error:{code,message,details}}`；本地路径正则脱敏。以下情况一律拒绝继续而不是带病运行：

- 数据合同、字段映射或质量门禁不满足；
- 来源哈希、黄金表、候选工件或渲染资产哈希不一致；
- 空间组不足或折分不可行；
- Run 或 CandidateResult 未成功却尝试正式选择；
- 候选数据版本、验证目标或折分不兼容；
- 三维资产身份、网格或值域不一致；
- S3M 历史缓存不符合固定合同；
- 外部服务（iServer/DeepSeek）身份与预期不符。

## 12. 术语表

| 术语 | 解释 |
|---|---|
| 属性场 | 某个指标在二维或三维空间中的连续估计结果 |
| 规则网格 | 按固定 X/Y/Z 间距排列的预测单元 |
| 空间柱 | X、Y 相同而 Z 不同的一组垂向样本 |
| 折外预测 OOF | 样本只由未包含它的训练折进行预测 |
| 公共有效集 | 所有候选都成功预测的同一批验证记录 |
| 半变异函数 | 描述样本差异随空间距离和方向变化的函数 |
| 块金值 nugget | 极短距离误差或微尺度变化的表现 |
| 基台值 sill | 半变异函数趋于稳定时的水平 |
| 变程 range | 样本仍表现空间相关性的典型距离范围 |
| 各向异性 | 不同方向上的空间变化速度不同 |
| NoData | 缺失或无法预测，不等于数值 0 |
| RenderAsset | 经身份、网格、变量和值域登记的正式渲染资产 |
| Volume / Contour / Slice | 体渲染 / 等值阈值 / 单轴切片三种表达模式 |
| fail-closed | 条件或证据不满足时拒绝输出，而不是猜测或降级冒充 |
| 数据血统 | 从当前成果追溯到数据、参数、运行、模型和文件哈希的关系 |
| canonical JSON | 键排序、紧凑分隔的确定性 JSON 序列化（哈希与指纹的基础） |

## 13. 相关决策记录

- [ADR-0001 技术栈与浏览器优先架构](decisions/0001-technology-stack-and-browser-first.md)
- [ADR-0002 SuperMap3D 隔离 iframe 与 NetCDF 体渲染链](decisions/0002-supermap3d-iframe-netcdf-rendering.md)
- [ADR-0003 整 XY 柱空间折分与公共有效集](decisions/0003-spatial-fold-and-common-valid-set.md)
- [ADR-0004 SQLite 单库加不可变文件工件](decisions/0004-sqlite-immutable-artifacts.md)
- [ADR-0005 文档体系：单一事实归属与测试治理](decisions/0005-documentation-system.md)
