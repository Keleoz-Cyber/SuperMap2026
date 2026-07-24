# 当前开发状态

> 更新时间：2026-07-22（v0.3 分支更新）。本文是开发人员和开发 Agent 判断“现在做到哪一步”的唯一状态入口。数据细节见 [电阻率](../data/resistivity.md)、[微震](../data/microseismic.md)、[瓦斯](../data/gas.md) 和 [数据契约](../data/contracts.md)；目标产品见 [产品蓝图](../product-blueprint.md)。

## 1. 状态分层

项目必须区分三类状态，禁止混报：

1. **代码已实现**：当前仓库能够通过命令和测试重复生成或验证；
2. **外部派生/人工验证**：在相邻只读资料目录或 iDesktopX 中已经完成，但尚未写入当前代码；
3. **目标能力**：产品蓝图要求实现，当前还没有代码和运行证据。

## 2. 当前代码已实现

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
- **v0.4 通用建模平台（`feat/v0.4-generic-platform` 分支，开发中）**：
  - 通用上传（CSV/XLSX）、字段映射、质量门禁、IDW/普通克里金调参（手动+有限网格搜索，50 组合硬上限）、空间折分验证、公共有效指标排行榜、SQLite 持久化任务（取消/重试/重启恢复）、成果工件与 X/Y/Z 切片、正式选择、证据导出与发布记录（manual_required）。
  - v0.3.1 电阻率案例以 `builtin_legacy` 只读适配器保留，全部 legacy 路由与证据语义不变；统一错误封套且不回传本机路径。
  - 案例预设登记于 `config/presets/`（resistivity=builtin_legacy、microseismic=upload_required，预设不含绝对路径、不自动导入私有数据）。
  - 测试基线：后端 `360 passed` + 前端 vitest `31 passed` + Playwright mock 冒烟 `1 passed`；`local_data` 23 passed（原始数据哈希不变）。
- 当前仓库仍无微震三维派生表代码化；瓦斯保持暂缓。

## 3. 外部派生与人工验证（尚未代码化）

| 案例 | 已有证据 | 当前边界 |
|---|---|---|
| 电阻率 | 已在iDesktopX复现完整体元、水平薄切片和阈值过滤；`WorkSpace.smwu` 已发布 iServer 三服务（人工 UI 步骤） | 垂直切片未正式验证；原生等值面失败；RHO单位和绝对EPSG未知；体元在三维服务中仅 ImageFileLayer，S3M 体渲染待缓存 |
| 微震 | 已生成2,005条局部三维点；按3σ规则剔除80条后形成1,925条候选点，并已在SuperMap人工复现 | 生成脚本、规则配置、回归测试和插值评价尚未进入仓库 |
| 瓦斯 | 已生成58条合格三维候选样本（28个位置），三维点可在平面场景显示，并生成过IDW体元 | 体元加入三维场景会导致iDesktopX原生崩溃，当前暂缓作为正式演示案例 |

微震派生事实：

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
- 通用CSV/XLSX上传、字段映射和数据版本管理；
- Python二维/三维IDW、普通Kriging与网格搜索执行器；
- 微震局部三维和3σ规则的仓库内可复现实现、微震三维场景接入；
- iServer 程序化发布（REST workspaces POST，ISSUE-V03-01）、S3M 体元缓存发布与体渲染、垂直切片 Web 验证；
- 瓦斯体元稳定显示、原生等值面、DSI-like/GOCAD后端；
- 自动成矿概率、储量或地质结论。

## 7. 给开发 Agent 的判定规则

- 以本文和[产品蓝图](../product-blueprint.md)为当前事实入口；论文只作来源证据，不能覆盖已确认规则。
- 外部CSV存在或iDesktopX人工成功，不等于当前代码已经实现。
- 插值成功、文件导出成功、iServer发布成功、浏览器加载成功是四个独立状态。
- 三类案例没有共同控制点，不得叠加或描述成同一研究区多源融合。
- 瓦斯三维暂缓不能阻塞电阻率纵向闭环和通用平台开发。
