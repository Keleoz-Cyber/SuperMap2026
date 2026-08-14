# GeoModelingPlatform 项目完整说明

> 更新时间：2026-08-14；适用源码版本：0.9.3。本文是当前项目说明的唯一权威入口。版本是否正式发布以 [GitHub Releases](https://github.com/Keleoz-Cyber/SuperMap2026/releases) 为准，历史过程以 Git 记录为准。

## 1. 项目定位

GeoModelingPlatform 是“上传数据后完成校验、调参建模、空间验证、成果分析和三维展示”的浏览器平台，不是单一插值脚本，也不是只展示预制模型的三维网页。

目标用户包括地质/GIS 学生、需要检查专业证据的建模人员，以及需要快速判断方法、结果和可信度的评委。平台把原本分散的数据处理、算法试验、证据检查和 SuperMap 三维表达收敛到同一条可追溯流程：

```text
选择案例或上传数据
  → 字段映射与质量门禁
  → 选择算法并调参
  → 空间交叉验证
  → 候选比较与适用性判断
  → 正式成果选择和物化
  → 三维体、等值面和 X/Y/Z 切片
  → 统计、规则、AI 与证据导出
```

任何阶段失败都必须给出原因；禁止用空图、点云或线框冒充正式体渲染成果。

## 2. 当前功能与创新点

| 功能区 | 当前能力 |
|---|---|
| 首页与案例 | 三案例入口、关键发现、统一主导航、回收站 |
| 数据接入 | CSV、Excel、预置案例、微震 DAT；字段映射、预览、来源登记 |
| 质量门禁 | 类型、有限值、NoData、重复坐标、空间柱、样本量、来源 SHA-256 |
| 调参实验室 | IDW、普通克里金、DSI-like、随机森林、克里金残差随机森林 |
| 模型比较 | 空间折分、公共有效集、兼容性检查、严格排名与行动建议 |
| 专业建模 | 方向半变异函数、变异函数拟合、人工确认各向异性、旋转邻域 |
| 成果工作台 | 完整场、Volume/Contour/X/Y/Z Slice、统计、异常和模型证据 |
| 解释与导出 | 确定性规则、可选 AI 研判、正式成果、证据 ZIP 和发布状态 |

主要创新点：

1. 数据—算法—验证—三维—证据的纵向闭环，而非单点工具拼接。
2. 以整 XY 柱空间折分和公共有效集保证候选比较公平，避免同柱泄漏。
3. 将普通克里金、随机森林和克里金残差校正放入同一生命周期，并显式防止验证泄漏。
4. 设置算法适用性门；系统不仅“能运行”，还会拒绝样本不足或空间组不足的模型。
5. SuperMap 三维场与后端权威切片、统计、异常和数据血统一致联动。
6. 来源哈希、不可变参数快照、工件清单和发布回执形成可审计证据链。
7. 对 DSI-like、局部坐标、模型离散度和 AI 解释设置清晰命名边界。
8. 将高低异常转成“事实—可能解释—潜在影响—建议核查”链，并与三维异常体双向定位；专业规则失配时安全降级为纯数值事实。

## 3. 技术架构

```text
Vue 3 + TypeScript 浏览器应用
  │ REST / JSON / multipart / ZIP
FastAPI 应用
  ├─ 案例、数据、实验、任务、候选、成果
  ├─ 插值、机器学习预测与专业分析
  ├─ 切片、统计、规则和 AI 辅助研判
  └─ RenderAsset、发布状态与证据链
  │
SQLite + 不可变文件工件
  │
SuperMap iServer / SuperMap3D / iDesktopX（表达与发布层）
```

技术栈：Python 3.12、FastAPI、Pydantic、SQLAlchemy、pandas、NumPy、SciPy、scikit-learn、PyArrow；Vue 3、TypeScript、Element Plus、ECharts、Vue Router、Vite；pytest、Vitest 和 Playwright。

核心后端边界：

- `geomodeling.platform`：Case、DatasetVersion、Experiment、Run、CandidateResult、FormalSelection、持久化任务和补偿事务。
- `geomodeling.modeling`：IDW、普通克里金、DSI-like、机器学习、空间折分、指标和规则网格。
- `geomodeling.analysis`：质量、分布、剖面、模型、残差和异常。
- `geomodeling.platform.geological_interpretation`：版本化电阻率、微震速度和瓦斯含量解释规则；不调用外部 AI，不重算模型。
- `geomodeling.microseismic`：DAT 解析、局部 XYZ、一次全局 3σ、黄金门禁和重复坐标聚合。
- `geomodeling.publishing`：iServer 探测、RenderAsset、NetCDF、历史 S3M 兼容和浏览器回执。
- `geomodeling.api.routes`：只负责 HTTP 校验、调用领域服务和 DTO 转换。

专业建模模块包括 `professional_contracts`、`pair_sampling`、`directional_variogram`、`anisotropy`、`neighborhood`、`uncertainty`、`anomalies`、`comparison` 和 `fold_artifacts`。渲染模块包括 `render_contracts`、`render_coordinates`、`render_assets`、`netcdf_volume`、`legacy_render_sources` 和 `rendering` API；SQLite `render_assets` 表登记身份、状态与哈希。

前端按 `views/`、全局外壳、案例/上传/实验/比较、渲染、成果/分析和类型化 `api/` 分层。Mock 数据只用于自动化测试，不进入生产业务。

## 4. 数据生命周期与通用合同

```text
原文件
  → SourceManifest（大小、SHA-256、来源）
  → DatasetVersion（字段、单位和坐标映射）
  → 质量门禁
  → Experiment（用户意图）
  → Run（不可变参数快照）
  → CandidateResult（OOF、指标和网格）
  → FormalSelection
  → Materialized Result / RenderAsset
  → Export / PublicationEvidence
```

必须遵守：

- 原文件只读，所有派生数据携带来源哈希和规则版本。
- 坐标、单位或 Z 方向无证据时标记未知，不得猜测 EPSG。
- 无效值保留原 token 与源行；NoData 与真实数值分开，不得偷偷改成 0。
- 电阻率历史导出中的 `-9999` 只在适配层转为 `null + is_nodata=true`。
- 运行参数创建后不可变；关键数据、折分、OOF、成果和证据读取前复核大小与 SHA-256。
- 数据库登记与工件落盘使用补偿事务；公开 DTO、日志和导出不暴露本机路径或凭据。
- 候选比较必须使用相同数据版本、折分指纹和公共有效集；正式选择要求 Run 与 CandidateResult 均为 `succeeded`。

## 5. 内置案例

### 5.1 地下电阻率

- 内置源：`example_data/地下电阻率节点_标准化.csv`，字段 `X,Y,Z,RHO`，17,549 行，坐标唯一且全部有限。
- 坐标：局部工程坐标、未声明 EPSG，Z 向下为负；RHO 单位 **Ω·m**，范围约 1.032113–149.984。
- 算法：IDW、普通克里金、DSI-like、随机森林空间回归和克里金残差随机森林。
- 冻结普通克里金基线：exponential、neighbor=24、RMSE=6.454476；规则网格 7×23×42、间距 20 m。完整基线身份在 `config/presets/resistivity-official-baseline.json`。
- 历史五模型导出仅作溯源：1,722 条验证记录中公共有效 1,481、NoData 241、XY mismatch 0。
- DSI-like 是“IDW 初始场 + 离散邻域平滑 + 观测点硬约束”的工程近似，**不等同 GOCAD DSI**。

### 5.2 微震波速

- 正式源为 22 个 DAT；2,006 条源记录中 2,005 条有限。`W8.dat` 的 `1.#QNAN0` 保留溯源，不改 0、不插值填补。
- `WL/2(km)` 按已确认规则换算 `depth_m = WL_half_km × 1000`，显示坐标 `z_local_m = -depth_m`；Vx 单位 km/s。
- 一次全局 3σ 使用样本标准差 `ddof=1`：剔除 80 条（深度 72、速度 8），得到 1,925 条黄金候选。
- 按完全相同局部 XYZ 分组并取算术平均，13 个冲突组使 1,925 条候选坍缩为 1,911 个唯一建模节点；黄金候选不被覆盖。
- 绝对原点、方位角和 CRS 未知；局部 XY 仅用于本案例。W28 只作来源冲突登记，不进入正式集合。
- 仅 22 个独立 XY 组，随机森林必须标为实验性；不得与电阻率或瓦斯叠加。
- 黄金哈希由配置和测试固定：候选 `4f7a0886…ae1513`，剔除表 `3752b2f6…872b1`；不一致即 fail-closed。

### 5.3 瓦斯含量

- 内置源：`example_data/煤层瓦斯三维插值点_合格58.csv`，字段 `X,Y,Z,CH4_content`，58 条合格样品、28 个 XY 位置、58 个唯一 XYZ。
- 坐标为局部线性米制、未声明 EPSG；属性单位 `ml/g`；源 SHA-256 由预置合同固定。
- 冻结基线为普通克里金 spherical、neighbor=24：RMSE=8.298439、MAE=6.552100、R²=−0.109659。
- 样本稀疏且 R² 为负，成果只作为稀疏采样下的解释性估计；机器学习适用性门拒绝该案例。
- 历史 iDesktopX 中 IDW 体元加载曾触发原生崩溃；这不能反推插值数值错误，也不约束当前 NetCDF 浏览器链。

三个案例的内置源均在 `example_data/`，字节级 SHA-256 由配置与测试锁定。私有论文原件、SuperMap 工作空间、运行数据库和凭据不进入仓库。

## 6. 算法、参数和验证

### 6.1 算法

- IDW：2D/3D、幂次、邻域点数、`z_scale` 和专业旋转邻域。
- 普通克里金：球状、指数和高斯变异函数；支持自动拟合或人工 nugget/sill/range。
- DSI-like：规则网格离散平滑近似，观测点硬约束不可关闭，失败不回退成 IDW 冒充成功。
- 随机森林空间回归：基于坐标派生特征和确定性随机种子。
- 克里金残差随机森林：只用内部折外克里金残差训练校正模型，避免验证泄漏。

机器学习必须先通过有效样本数、独立空间组和折分可行性门。若未优于普通克里金，界面明确显示，不强行推荐。随机森林“模型离散度”仅表示树模型分歧，不是概率置信区间。

### 6.2 空间验证与指标

- 按 XY 柱或明确空间组折分；同一柱不得同时进入训练和验证。
- 自动变异函数只在训练折拟合；最终完整场在全部有效建模数据上重新拟合并标为 `final_full_data_fit`。
- 候选排名使用公共有效集，并保存折分指纹；跨实验比较先检查变量、单位、维度、数据版本、折分和验证目标兼容性。
- 主要指标包括 RMSE、MAE、R²、Bias、Median ARE、覆盖率、有效数和 NoData 数。R² 越高越好，误差指标越低越好；稀疏分组时谨慎解释。

### 6.3 专业证据

- 经验半变异函数点对超过 50,000 时按距离层和方向层确定性抽样；种子由数据 SHA-256 与配置派生，并披露采样率。
- 方位角在 XY 平面由 +X 向 +Y，范围 `[0°, 180°)`；倾角范围 `[-90°, 90°]`。
- 参数来源区分 `automatic_candidate`、`final_full_data_fit`、`manual_confirmed`、`user_prior` 和 `legacy_auto_fold_fit`。
- 各向异性候选只是诊断建议；用户需人工确认不可变快照。空间变换为 `x′ = S Rᵀ x`；IDW 的 `z_scale` 仍只是距离权重参数。
- Kriging 原生估计标准差采用 `σ² = λᵀγ₀ + μ`；它不是未来事件风险的概率保证。
- 经验误差尺度是折外残差在显式邻域内的距离加权局部 RMSE，**不是标准误**。
- 异常连通区使用显式阈值：2D 为 4 邻接、3D 为 6 邻接；Voronoi 支持只称“网格支持面积/体积估计”，不是地质储量。
- 不适用能力返回 `not_applicable`；旧成果缺失专业计算返回 `LEGACY_RESULT_NOT_COMPUTED`，不伪造零值。

### 6.4 地质属性研判

成果页右侧以确定性规则为主，将同一成果网格的高、低值连通区组织为“数值事实 → 可能解释 → 潜在影响 → 建议核查”。电阻率优先展示低阻异常，微震速度优先展示低速度异常，瓦斯含量优先展示高值异常；卡片与三维标注共享组件 ID，高值为暖色、低值为冷色，可相互定位。

规则只翻译既有证据，不产生新数值，也不把分位异常升级为已确认地质对象。当前阈值是完整成果网格的 p25/p75，因此所有专业卡片均标记为探索性：低阻具有含水、裂隙、黏土等多解性；速度场不包含事件时间、位置或能量；瓦斯未登记矿区法定分级阈值。自定义属性没有受控规则时返回 `not_applicable`，只保留通用统计和技术证据。

DeepSeek 位于独立的“AI 辅助”标签，只消费结构化证据。未配置 API Key、网络失败或响应无效，都不影响地质研判、三维定位和建模主链。

## 7. 三维渲染、切片与 SuperMap

当前正式链：

```text
CandidateResult 规则网格
  → NetCDF classic/v3 RenderAsset
  → 隔离 iframe
  → SuperMap3D VoxelGridLayer3D
  → Volume / Contour / X/Y/Z Slice
```

RenderAsset 必须登记成果 ID、数据版本、网格哈希、维度、坐标、变量、单位、值域、NoData 和显示锚点。局部模型使用 `display_anchor_only` 放到浏览器可见位置，这不代表真实 EPSG 配准；`auxiliary points` 只能作为辅助/证据层。

父页面通过 `gmp-supermap-volume/v2` 发送完整状态和单调 `revision`；iframe 拒绝旧状态并回传能力、身份、相机和诊断。X/Y/Z 切片坐标与统计来自后端权威切片 API，导出合同为 `slice-analysis/v1`，标准差字段采用 `std_population`，前端 PNG 溯源标记为 `client_echarts_canvas`。`FRAME_READY` 的 `singleAxisSlice` 能力决定是否开放单轴控制。单轴切片隐藏其他轴是 SuperMap3D 12.1 本机探针事实，不是公开 API 保证；升级 SDK 后必须重测。

渲染遵守 `no silent fallback`：失败时显式诊断，不能改画点云或包围盒并声称体渲染成功。32^3/64^3 用于真实 SDK/GPU 性能门。历史 S3M 2.0 `PointCloudFile` 只保留严格兼容证据读取，不是当前原生体渲染主路径。

SuperMap 职责是 iDesktopX 人工复核、iServer 服务和 SuperMap3D 表达；平台职责是数据合同、建模、验证、NetCDF、分析、导出和证据链。iServer 离线时通用建模继续运行，发布状态必须如实为不可用或 `manual_required`。

官方参考：

- [SuperMap iServer 帮助](https://help.supermap.com/iServer/1201/zh/)
- [SuperMap iDesktopX 帮助](https://help.supermap.com/iDesktopX/zh/)

URL 中的 `1201` 是官方文档路径；演示时仍应核对本机产品构建号、SDK、许可证和服务元数据。

## 8. 运行与维护

### 8.1 Windows 免安装包

下载 `GeoModelingPlatform-0.9.3-win-x64.zip`，完整解压到可写目录，双击 `启动平台.cmd`，浏览器打开 <http://127.0.0.1:8000/>；结束后双击 `停止平台.cmd`。包内含运行时、前端、SuperMap3D SDK、SQLite、三个内置案例和 `portable-manifest.json` 完整性清单。

首次启动从只读模板复制 `runtime` 工作目录；用户数据只写入该目录。端口身份不明、包内哈希不符或文件损坏时启动器 fail-closed。诊断命令：

```cmd
GeoModelingPlatform.exe doctor
```

### 8.2 源码开发

以下为 **PowerShell**：

```powershell
python -m pip install -e ".[api,test]"
npm --prefix web ci
python -m geomodeling.cli demo-check
powershell -ExecutionPolicy Bypass -File scripts\start_demo.ps1
```

SuperMap3D SDK 预检：

```powershell
python scripts/install_supermap3d.py --destination web/public/SuperMap3D-2026 --verify-only --expected-sha256 d69dadab01fc452a79f1fa88a46aced3cf29885df7bf4febbd6f24ce5b578120
```

专业维护入口：

```powershell
geomodeling professional diagnose --help
geomodeling professional confirm --help
geomodeling professional inspect-result --help
geomodeling professional extract-anomalies --help
geomodeling professional compare --help
python -m geomodeling.cli microseismic derive --help
python -m geomodeling.cli microseismic import-case --help
python -m geomodeling.render_cli import-csv --help
```

运行数据由 `GEOMODELING_DATA_DIR` 指定；iServer 与 AI 凭据只允许通过环境变量传入。需要诊断 NetCDF 时按 `source_contract`、`netcdf_export`、`asset_identity`、`sdk_runtime`、`camera_or_bounds`、`browser_or_gpu`、`message_protocol` 七类定位。资产若由 `creating` 恢复为 `interrupted`，必须显式 `retry_failed`，不得静默覆盖。

### 8.3 便携包制作

```powershell
python -m pip install -e ".[api,package]"
python scripts/build_portable.py
```

输出到 `release/`，并进行中文/空格路径移动验收。`build/`、`release/`、运行数据库、日志和缓存均不进入 Git。

## 9. 测试、CI 与验收

本地完整质量门：

```powershell
python -m pytest -q -m "not local_data"
python -m pytest -q -m local_data
npm --prefix web run test:unit
npm --prefix web run type-check
npm --prefix web run build
npm --prefix web run test:e2e
npm --prefix web run test:e2e:live -- e2e-live/platform-live.spec.ts
git diff --check
```

`local_data` 只在相邻只读研究资料存在时运行，并核对前后源哈希不变。需要 SuperMap SDK/GPU 的规格只属于本机发布门，不得用 Mock 冒充。

GitHub Actions 采用双速策略：普通 push/PR 运行快速 Python 合同、完整前端单元测试、类型检查和构建；`v*` 标签或人工 `workflow_dispatch` 运行完整后端、Mock E2E 与真实 FastAPI/SQLite/Worker Live E2E。发布前仍应人工确认：

- `demo-check` 无阻断，8000/8090 端口和服务身份正确；
- 三案例、上传、调参、比较、成果、切片、导出和返回路径可用；
- 1920×1080、1440×900 和 390×844 没有关键截断或横向溢出；
- Volume/Contour/Slice 有真实像素变化，iServer 离线时界面如实降级；
- 截图、视频、Release 包和源码来自同一版本。

测试代码属于工程质量合同：应保留在 Git 仓库和比赛“工程源代码”目录，但不进入免安装运行包。

## 10. 答辩演示路线

主路线使用电阻率案例，建议 6–8 分钟：

1. 首页说明问题、平台闭环和三案例角色；
2. 查看电阻率数据质量与来源；
3. 展示 IDW、普通克里金或机器学习参数；
4. 展示空间交叉验证、公共有效集和候选差异；
5. 选择正式成果，在同一三维场切换 Volume/Contour/Slice；
6. 查看切片统计、异常和模型证据；
7. 展示来源哈希、数据血统和导出；
8. 用微震说明领域派生，用瓦斯说明适用性门会拒绝不可靠模型。

演示前一天完成全量测试和备用截图；开机后执行 `demo-check`；上台前关闭睡眠/更新并确认浏览器、端口、iServer 和离线兜底。路线 A 为通用上传建模，路线 B 为内置电阻率成果；iServer 故障时继续路线 A，不虚报在线发布。

## 11. 比赛提交

依据 [SuperMap 杯开发组要求](http://www.giscontest.com/cn/view-1000-382.aspx)，最终单层 ZIP 根目录至少包含：

1. `工程源代码/`
2. `数据/`
3. `运行文件/`
4. `作品文档/`
5. `代表性截图/`
6. 演示视频与 PPT

仓库保留源码、测试、CI、配置模板、脚本和必要技术证据；运行文件使用 Windows 免安装包，不复制整个开发仓库。不要提交 `.git`、`node_modules`、缓存、临时 SQLite、日志、`.env`、API Key、iServer 管理凭据、许可证或未授权的私有论文原件。

官方模板要求的 DOCX、数据说明 Excel、源代码目录说明、至少 3 张截图、1080p 演示视频和 PPT 需单独制作；仓库 Markdown 是内容源，不能替代正式模板。

## 12. 已知边界与禁止夸大

- 三案例使用独立局部坐标，没有共同控制点时不做跨案例融合。
- 微震绝对 CRS、原点和方位角未知；瓦斯稀疏成果不能表述成高置信度危险分区。
- 不实现普适/协同/指示 Kriging、任意斜切、时间预测或灾害预警。
- 各向异性由人工确认；方向候选只是诊断建议，不能直接当作真实地质方向。
- Kriging 标准差和模型离散度都不是概率置信区间。
- 异常连通区不是危险区，网格支持体积不是储量。
- DSI-like 不等同商业 GOCAD DSI。
- 通用成果 iServer 发布默认 `manual_required`；无实时对象级证据不得标为发布成功。
- AI 仅消费结构化证据并给出可选解释；无密钥、超时或失败不影响确定性建模主链。

## 13. 保留证据

- [v0.7.0 单轴切片技术探针](evidence/v0.7.0-single-axis-probe/)
- [v0.8.0 电阻率 DSI-like](evidence/v0.8.0-resistivity-dsi-like/)
- [v0.8.0 瓦斯案例](evidence/v0.8.0-batch-3-gas/)
- [v0.8.0 统计分析](evidence/v0.8.0-statistics-analysis/)
- [v0.9.0 三案例与浏览器产品](evidence/v0.9.0/)
- [v0.9.0 机器学习空间预测](evidence/v0.9.0-ml-spatial-prediction/)
- [v0.9.0 成果级分析](evidence/v0.9.0-result-analysis-live/)

旧版本运行手册、ADR、Agent 计划和重复说明已从当前工作树移除；技术决定和演进记录仍可由 tag、Release 和 Git 历史复原。
