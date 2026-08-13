# 系统架构

## 1. 总体结构

```text
浏览器 Vue 应用
  │ REST / JSON / multipart / ZIP
FastAPI 应用
  ├─ 案例、数据、实验、任务、候选、成果
  ├─ 插值/预测与专业分析
  ├─ 切片、统计、规则和 AI 辅助研判
  └─ 发布与证据链
  │
SQLite + 文件工件目录
  │
SuperMap iServer / SuperMap3D / iDesktopX
```

系统采用“平台主链”和“SuperMap 表达层”解耦：上传、校验、建模、比较和导出不依赖 iServer 在线；三维原生渲染、服务发布和浏览器加载证据使用 SuperMap 能力。

## 2. 技术栈

- 后端：Python 3.12、FastAPI、Pydantic、SQLAlchemy、pandas、NumPy、SciPy、scikit-learn、PyArrow。
- 前端：Vue 3、TypeScript、Element Plus、ECharts、Vue Router、Vite。
- 三维：SuperMap3D/iClient3D、NetCDF `VoxelGridLayer3D`、可选 iServer 服务。
- 持久化：SQLite 业务库 + 不可变文件工件。
- 测试：pytest、Vitest、Vue Test Utils、Playwright。

## 3. 后端模块

### `geomodeling.platform`

平台领域层，负责：

- Case、DatasetVersion、Experiment、Run、CandidateResult、FormalSelection；
- 任务持久化、取消、重试和恢复；
- 上传补偿事务与不可变工件；
- 公共 DTO 和统一错误语义。

### `geomodeling.modeling`

建模算法层：

- 2D/3D IDW；
- 普通克里金与变异函数拟合；
- DSI-like 离散平滑近似；
- 随机森林空间回归；
- 克里金残差随机森林；
- 空间折分、公共有效集、指标和规则网格物化。

算法层不负责 HTTP 和数据库提交；任务层提供输入快照并登记输出。

v0.6 专业建模的稳定模块边界包括 `professional_contracts`、`pair_sampling`、`directional_variogram`、`anisotropy`、`neighborhood`、`uncertainty`、`anomalies`、`comparison` 和 `fold_artifacts`。SQLite v5 持久化 `analysis_jobs`、`professional_diagnostics`、`anomaly_extractions` 等专业分析记录；迁移只能前进，不在启动时静默降级。

### `geomodeling.analysis`

统计与成果解释层：质量、分布、空间剖面、模型比较、残差、异常和规则研判。所有分析响应携带数据/成果身份和计算版本。

### `geomodeling.microseismic`

微震领域适配器：DAT 清单、解析、局部 XYZ 派生、一次全局 3σ、黄金门禁、重复坐标聚合和领域证据导出。领域派生与通用建模层通过标准化表连接。

### `geomodeling.publishing`

SuperMap 与发布证据层：

- iServer 服务探测和身份校验；
- S3M 体元缓存兼容读取与 fail-closed 合同；
- 浏览器加载回执；
- 发布状态和刷新语义。

历史 S3M 点元读取只用于兼容证据；当前正式体渲染主路径是 NetCDF + SuperMap3D。

渲染资产的稳定模块边界为：`render_contracts` 定义合同，`render_coordinates` 管理局部坐标到显示锚点，`render_assets` 管理工件生命周期，`netcdf_volume` 生成 NetCDF classic/v3，`legacy_render_sources` 提供只读兼容，API `rendering` 路由公开资产和切片。SQLite `render_assets 表`登记身份、状态、工件哈希与诊断。

### `geomodeling.api.routes`

按资源拆分路由：`cases`、`datasets`、`experiments`、`runs`、`results`、`rendering`、`analysis`、`professional`、`result_analysis`、`ai_analysis`、`trash` 等。路由只做 HTTP 校验、调用领域服务和 DTO 转换。

## 4. 前端结构

- `views/`：路由级页面。
- `components/shell/`：全局外壳和稳定主导航。
- `components/cases/`、`upload/`、`experiments/`、`comparison/`：主建模流程。
- `components/rendering/`：SuperMap3D iframe、渲染协议和控制。
- `components/results/`、`analysis/`、`findings/`：成果、统计和研判。
- `api/`：类型化请求和 DTO。
- `mocks/`：单元与 Mock E2E 确定性夹具，不进入生产业务。

所有主页面共用一个全局头和命名路由。生产入口从 `web/src/main.ts` 开始；未被入口导入图使用的历史组件不保留。

## 5. 数据生命周期

```text
原文件
  → SourceManifest（大小、SHA-256、来源）
  → DatasetVersion（字段和单位映射）
  → 质量门禁
  → Experiment（用户意图）
  → Run（不可变参数快照）
  → CandidateResult（OOF、指标、网格）
  → FormalSelection
  → Materialized Result / RenderAsset
  → Export / PublicationEvidence
```

关键规则：

- 原文件只读；
- 运行参数创建后不可变；
- 数据、折分、OOF 和成果读取前校验哈希；
- 数据库登记与文件落盘使用补偿事务；
- 公开 API 不返回本机路径；
- 删除案例采用回收站语义，不直接破坏审计链。

## 6. 空间验证

- 空间折分按 XY 柱或明确空间组进行，禁止同一柱泄漏到训练和验证。
- 自动变异函数只在训练折拟合。
- 残差随机森林只使用内部折外克里金残差训练。
- 候选排名使用公共有效集，并保存折分指纹。
- 跨实验比较先判断变量、单位、维度、数据版本、折分和公共有效集兼容性。

## 7. 渲染协议

后端物化规则网格并登记 RenderAsset，前端通过独立 iframe 打开 SuperMap3D：

1. 页面请求 RenderAsset 和渲染 profile；
2. iframe 加载 NetCDF `VoxelGridLayer3D`；
3. 父页面发送 `gmp-supermap-volume/v2` 完整状态；
4. iframe 只接受更新的单调 `revision`；
5. Slice 状态必须来自权威切片 API；
6. iframe 回传能力、身份、相机和诊断；
7. 失败显式显示，不采用伪渲染 fallback。

切片导出 schema 为 `slice-analysis/v1`；统计使用 `std_population`，前端 PNG provenance 标记 `client_echarts_canvas`。`FRAME_READY` 的 `singleAxisSlice` 能力决定是否允许单轴控制；整体原则为 `no fallback`。

单轴切片隐藏另外两轴的行为有[本机技术探针](evidence/v0.7.0-single-axis-probe/)，但仍按未公开 API 能力管理。

## 8. AI 辅助研判

AI 只消费已经计算好的结构化证据，不直接读取私有源文件，也不替代确定性规则。请求是显式动作；凭据只从环境变量读取。未配置、超时或服务异常时返回类型化降级，成果和规则分析继续可用。

## 9. 配置与安全

- `.env.example` 只列变量名，不存真实值。
- 运行数据位于 `GEOMODELING_DATA_DIR`。
- iServer 管理凭据和 AI Key 不写入仓库、数据库、浏览器或导出包。
- 日志和错误响应对路径脱敏。
- 内置数据与基线配置使用 SHA-256 固定。

## 10. 测试分层

- pytest：领域合同、算法、迁移、API、工件与失败补偿。
- Vitest：组件、图表、渲染协议和页面状态。
- Mock E2E：前端完整流程的确定性回归。
- Live E2E：真实 FastAPI/SQLite/Worker。
- SuperMap 本机门：真实 SDK/GPU 和像素响应。

测试与生产源码一起保留，部署包按[比赛提交说明](contest-submission.md)分层。
