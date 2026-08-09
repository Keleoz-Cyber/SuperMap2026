# GeoModelingPlatform

> 地矿属性模拟与三维建模平台（超图杯项目）

本目录是代码开发根目录。原始论文和原始数据继续保存在相邻的只读资料目录中（见文末「原始资料保护」），不在代码项目中复制或修改；三个官方案例的标准化散点源已随 v0.8.0 第三批字节冻结内置到 `example_data/`（见「当前能力」）。

## 项目目标

建设面向超图杯答辩的浏览器建模平台：用户上传 CSV、Excel 或受支持的专业文本数据，完成字段映射、质量校验、二维/三维插值调参、空间验证、成果展示和报告导出。第一版（v0.1.0）已打通地下电阻率从标准数据到 SuperMap 三维成果的闭环；当前代码还包含微震 v0.2a 数据审计底座、已随 v0.5.0 发布的微震第二案例建模闭环、v0.6 专业建模增强、v0.7.0 统一案例工作台，以及 v0.8.0 电阻率散点预置迁移与 DSI-like 工程近似插值、统计与空间分析中心、第三批瓦斯预置案例与三案例数据内置化（本分支）。

电阻率、微震、瓦斯及后续新增属性作为**独立案例**复用平台能力。没有共同坐标依据时不得空间叠加，不做无证据的多源融合。

## 当前能力

- **v0.9.0 答辩级视觉产品与全流程体验重构（本分支，发布候选）**：全站重构为「深地极光」综合指挥舱形态，视觉完成以真实数据 + 真实浏览器截图为验收门。设计与验收口径见 [设计规格](docs/superpowers/specs/2026-08-10-v0.9.0-visual-product-redesign-design.md) 与 [实施计划](docs/superpowers/plans/2026-08-10-v0.9.0-visual-product-redesign.md)。
  - **全局产品壳与 S1 设计系统**：`AppShell/AppHeader` 持久壳（品牌、案例上下文、服务状态、全局「导入数据 / 新建建模」、答辩模式入口、回收站），S1「深地极光」token（墨绿黑画布、低饱和青结构色、少量核心金、四案例辅助色：电阻率金 / 微震紫 / 瓦斯翡翠 / 自定义青），统一动效 token 并支持 `prefers-reduced-motion`；`AsyncState` 统一加载/空/错误/离线/降级/NoData 六类状态（每个状态回答「发生了什么/受影响能力/下一步」）。
  - **首页综合指挥舱**：案例轨（官方案例 + 用户项目 + 自定义数据固定入口）+ 中央三维主舞台（当前案例官方/主打成果的 NetCDF 原生体渲染，复用统一 RenderAsset 链）+ 右侧关键发现（`buildPresentationFindings` 从分析摘要确定性生成，每条含结论/证据/溯源/可信状态/限制，支持「定位到三维」）+ 底部证据带（质量组成环图、模型指标、异常支持占比、溯源）；案例切换时变量、单位、辅助色、三维、发现、图表整体联动；身份一律来自所选案例 DTO，绝不跨案例取用；无成果时显示解释性空态，绝不回退装饰假场景。
  - **案例工作台四阶段**：数据概览 / 建模实验 / 成果分析 / 证据与报告统一阶段导航，禁用阶段显式说明原因；每个状态恰好一个主动作（继续数据准备 > 查看成果 > 新建实验；错误态为返回首页）。
  - **数据接入与准备同屏工作台**：文件接入 → 字段映射 → 质量检查 → 建模确认四阶段同屏；左侧真实文件预览、中央测点空间预览（只用映射列有限值）、右侧映射诊断、底部质量组成（环图仅有效/无效口径，阻断/警告分级）；坐标未知声明局部线性，绝不编造 EPSG；放弃/恢复语义不变。
  - **调参实验室**：参数区 / 实验画布（测点散点预览）/ 候选摘要（预计网格、验证折数、组合数与 50 上限风险）/ 实验队列四区；`RunPipeline` 五段流水线（校验→折分→插值→评估→物化）只从持久化状态与粗进度推导，粗进度阶段恒标注「阶段估计」。
  - **模型比较证据面**：RMSE/MAE 分组柱状与 R²/Bias 独立标度分轴；参数差异表只标真实不同行；不兼容/重复指纹/指标不足时不渲染排名图（fail-closed）；双候选兼容深度比较保留。
  - **成果与分析融合工作台**：三维主视图 + 关键发现 + 混合证据坞（质量/分布/模型指标/趋势剖面/残差，ECharts 懒挂载与卸载释放）+ 模型评估摘要 + 证据与溯源抽屉（导出/发布）；**图表—三维双向联动**：趋势图点击（含空白处最近分箱）驱动对应轴正交切片，切片移动反向切换证据标签；XY 区域过滤等渲染器不支持的能力显示类型化通知，绝不伪报定位成功；选择控制器在案例/成果身份切换时立即失效旧选择。
  - **答辩模式**：固定六章节（平台总览 → 电阻率 → 微震速度 → 瓦斯含量 → 自定义数据 → 创新点与已知边界），键盘 ←/→/Escape 与章节目录直达；案例章节复用真实指挥舱场景与发现（只读，无编辑/危险操作）；数据不可用章节显示显式降级面板且保持可导航；服务离线显示真实状态横幅。
  - **响应式与无障碍**：1440×900 / 1280×800 / 834×1112 / 390×844 四档零横向溢出（像素级门）；手机档案例轨为横向紧凑选择条、三维与发现优先；单一 main 地标、跳转链接、图标按钮可访问名称、每页唯一主动作合同测试锁定。
  - **边界不变**：三案例数据哈希、模型身份、单位（Ω·m / km/s / ml/g）、局部线性坐标与 `display_anchor_only` 语义不变；官方成果保护、回收站、质量门禁、渲染协议 v2 行为不变；无新增地质结论、无假图、无点云冒充体渲染。
  - 证据：真实 SDK/GPU 验收（三案例指挥舱切换渲染、图表→三维联动、答辩模式、手机视口）见 [docs/evidence/v0.9.0/](docs/evidence/v0.9.0/)。

- **v0.8.0 瓦斯预置案例与三案例数据内置化 · 第三批（本分支，发布候选）**：三个官方案例的标准化散点源统一内置 `example_data/` 并以字节级 SHA-256 冻结合同锁定（`.gitattributes` 对这些 CSV 关闭文本规范化，任意平台检出字节一致）：电阻率 `地下电阻率节点_标准化.csv`（17,549 行 `X,Y,Z,RHO`，Ω·m，`04c5914d…`）、微震 `微震局部三维点_3Sigma_去重均值_1911.csv`（1,911 行，km/s，CRLF+BOM，`4011de85…`）、瓦斯 `瓦斯含量_合格样品.csv`（58 行 `X,Y,Z,CH4_content`，ml/g，CRLF+BOM，`f7d6f03d…`；28 个 XY 采样位置，Z∈[121.0375,175.656]，CH4∈[0.05,34.3]）。三案例 seed CLI（`python -m geomodeling.preset_cli seed-resistivity / seed-microseismic / seed-gas`）默认源全部解析到仓库内置 `example_data/`，无需任何外部私有源；公开 DTO 只输出逻辑来源与哈希，浏览器不接触绝对路径。瓦斯正式启用 `gas_content` 分析 profile（ml/g），官方基线冻结于 `config/presets/gas-official-baseline.json`：真实 58 行源跑 IDW/普通克里金候选、spatial_kfold 5 折（seed=20260723，整根 XY 柱分组）评审，winner `ordinary_kriging` spherical/neighbor=24（RMSE=8.298439、MAE=6.552100、R²=−0.109659、Bias=−0.068618，公共有效 58——58 点稀疏采样下 R² 为负，如实记为解释性估计）；规则网格 151×333×12 @[20,20,5] m（603,396 节点，值全有限、零 NoData），经统一 `Case → DatasetVersion → Experiment → Run → CandidateResult → materialize → FormalSelection` 链与 NetCDF 原生体渲染资产登记。DSI-like 条件评估通过但仅作对照候选，不参与官方选择。瓦斯坐标为局部线性米制，不做 EPSG 地理配准；不输出「瓦斯危险/安全」规范结论；不接入 AI/iServer；旧 legacy 瓦斯卡（“暂缓”）已退役，首页三预置卡统一为 `builtin_preset` 案例工作台。
- **v0.8.0 电阻率散点迁移与 DSI-like（本分支，发布候选）**：电阻率从只读 `builtin_legacy` 迁移为统一 `builtin_preset` 散点预置案例（案例 ID `resistivity` 不变）——标准化散点源内置在 `example_data/地下电阻率节点_标准化.csv`（17,549 行 `X,Y,Z,RHO`，局部工程坐标，字节级 SHA-256 冻结合同），运行时登记 SHA-256 指纹；`preset_cli seed-resistivity` 唯一生产入口经 `Case → DatasetVersion → Experiment → Run → CandidateResult → materialize → FormalSelection` 链登记官方成果（只读、幂等、指纹不符绝不覆盖）。官方基线冻结于 `config/presets/resistivity-official-baseline.json`：winner `ordinary_kriging` exponential/neighbor=24（RMSE=6.454476、MAE=3.251899、R²=0.923093，生产 `spatial_kfold` 5 折 seed=20260723），网格 7×23×42 @20 m。新算法 **DSI-like 离散平滑插值**（IDW 初始场 + 邻域加权平滑 + 观测点硬约束的工程近似，**不等同 GOCAD DSI**）与 IDW、普通 Kriging 共用统一实验/候选/NetCDF 体渲染链；首页卡、参数编辑器与成果页全复用统一组件。旧 S3M/legacy 渲染端点一律 410 `LEGACY_RESISTIVITY_RETIRED`，旧 legacy 电阻率页与首页残留入口已移除；旧资产只读保留待单独清理任务。
- **v0.7.0 统一案例工作台 · 第一批（本分支）**：微震第二案例改为开箱可用的 **CSV 预置**案例——内置的 1,911 节点 CSV（`example_data/微震局部三维点_3Sigma_去重均值_1911.csv`，字节级 SHA-256 冻结合同，局部测线坐标、Vx 单位 km/s）经固定 27 成员**普通克里金**候选矩阵（3 变异函数 × 3 邻域 × 3 `z_scale`，固定种子空间 5 折、公共有效集 1,910 点）评审冻结官方基线（`config/presets/microseismic-official-baseline.json`：exponential / neighbor=12 / z_scale=2.0，RMSE=0.2681、MAE=0.2126、R²=0.8446；`z_scale` 是距离实验参数，不代表已确认地质各向异性）；维护命令 `python -m geomodeling.preset_cli analyze-microseismic / seed-microseismic` 经正常 `Case → DatasetVersion → Experiment → Run → CandidateResult → materialize → FormalSelection` 链登记官方成果（幂等、指纹不符绝不覆盖、失败补偿不留半成品），官方成果走 v0.6.1 的 **NetCDF** 原生体渲染资产链（35×47×82 网格，变量 `Vx`，display_anchor_only 显示锚点，非真实地理配准）。电阻率、微震预置、用户上传三类案例以 `builtin_legacy` / **`builtin_preset`** / `user_upload` 统一身份进入同一案例工作台（`/#/cases/:caseId`，`/case/resistivity` 兼容重定向）；首页入口与命令全部由工作台 DTO 驱动。微震 **DAT** 导入向导、路由与 HTTP 端点已**退出产品面**（历史运行时文件与派生服务层保留，CLI 不受影响；历史成果经通用结果 URL 只读查看，领域证据导出契约不变）。
- **v0.7.0 渲染与剖面分析 · 第二批（本分支）**：体渲染 iframe 协议升级 `gmp-supermap-volume/v2`（单调 `revision` 完整渲染状态，过期忽略；slice 模式只接受权威剖面响应的 axis/index/coordinate/relativePosition；`FRAME_READY` 上报 `singleAxisSlice` 能力；单轴切片负坐标隐藏非活动轴为 SDK 12.1 实测技术，证据 `docs/evidence/v0.7.0-single-axis-probe/`）；渲染默认值按来源驱动（内置电阻率 log + native-spectrum，候选成果 linear + viridis，log 不可用显式说明）；`GET /api/render-assets/{id}/slice-analysis` 权威剖面与统计（`std_population` ddof=0、numpy-linear 分位数、valid+nodata=total）；`POST .../slice-exports` 原子导出 `slice-analysis.zip`（`slice-analysis/v1`，CSV 真实 x,y,z 轴列、统计与 API 一致、manifest 哈希齐备，PNG 为 `client_echarts_canvas` 展示工件）；常驻工具栏（模式/色带/标度/滤波/不透明度/光照/渐变透明度/包围盒）+ X/Y/Z 正交切片控件 + ECharts 剖面热力图与统计；三来源共用 RenderAsset API 与组件；no fallback——失败只显式报错，无回退渲染器。
- **v0.6 专业建模增强（本分支）**：全向/方向经验半变异函数诊断（点对确定性采样，种子=数据 SHA-256+配置，≤50,000 点对上限并披露采样率）；球状/指数/高斯三模型按 bin 点对数加权的有界最小二乘拟合证据（`weighted_sse`/收敛/边界/参数来源）；各向异性候选仅作诊断建议，**人工确认**后写入不可变快照（改参数必生成新快照）；Kriging 各向异性变换 `x′ = S Rᵀ x`（legacy `z_scale` 归一化，不叠加）；旋转椭圆/椭球+扇区搜索邻域（IDW 与普通 Kriging 共用选择器，IDW 权重仍用 `z_scale` 距离）；普通 Kriging 原生估计标准差（`σ² = λᵀγ₀ + μ`，微负钳制/显著负值 NoData/lstsq 标记）；所有算法基于折外残差的经验误差尺度（距离加权局部 RMSE，非标准误）；空间折分检查（整柱不泄漏，泄漏 fail-closed）；显式阈值异常连通区（2D 4 邻接/3D 6 邻接，Voronoi「网格支持面积/体积估计」，非储量）；单候选联动与双候选兼容比较（兼容才显示指标差）；SQLite v5 五张专业表与 `analysis_jobs` 持久化任务；专业证据 ZIP（`professional/` 目录，声明缺失或哈希不符 409 fail-closed）；能力矩阵区分 IDW 与普通 Kriging（`not_applicable` 类型化），旧候选返回 `LEGACY_RESULT_NOT_COMPUTED`。浏览器专业诊断工作台与专业分析台、API、CLI（`geomodeling professional`）三入口齐备。运行手册见 [docs/v0.6-professional-modeling-loop.md](docs/v0.6-professional-modeling-loop.md)。
- **v0.5 微震第二案例建模闭环（已发布，v0.5.0）**：微震 DAT 派生内核（CLI `geomodeling microseismic derive` / `import-case` 与 v0.5 时代浏览器向导共用）：22 DAT → 2,006 源记录 → 2,005 有限 → 一次全局 3σ（`ddof=1`）剔除 80 → 1,925 候选 → 算术平均聚合 1,911 建模节点；黄金门禁逐字节锁定两张派生表 SHA-256，不过即阻断。调参（IDW/普通克里金、`z_scale` 实验参数）、空间验证、成果工作台三层诊断图层与证据导出复用 v0.4 平台；发布登记保持 `manual_required`。注：v0.7.0 起 DAT 浏览器导入退出产品面，改由 CSV 预置案例承载微震第二案例；派生服务层与 CLI 保留。运行手册见 [docs/v0.5-microseismic-loop.md](docs/v0.5-microseismic-loop.md)。
- **v0.4 通用建模平台**：CSV/XLSX 上传（50 MiB / 50 万行上限）、字段映射（2D/3D）、质量门禁（阻断/警告+显式确认）、IDW 与普通克里金调参（手动 + ≤50 组合有限网格搜索）、空间折分验证、公共有效掩膜排行榜、SQLite 持久化任务（取消/重试/重启恢复）、成果完整场与 X/Y/Z 切片、附理由的正式选择、证据 ZIP 导出、发布登记（manual_required）。运行说明见 [docs/v0.4-generic-modeling-loop.md](docs/v0.4-generic-modeling-loop.md)。
- **v0.3.1 内置电阻率案例（v0.8.0 起类型化退役）**：旧 S3M/legacy 产品路径（legacy 卡、旧三维工作台、legacy 渲染端点）已退出产品面，端点返回 410 `LEGACY_RESISTIVITY_RETIRED`，旧资产只读保留待清理；电阻率现由 v0.8.0 散点预置案例承载。历史闭环含义、运行方式与实测证据见 [docs/v0.3-iserver-loop.md](docs/v0.3-iserver-loop.md)。
- 电阻率数据登记与契约校验：17,549 / 15,827 / 1,722 行，训练/验证空间柱重叠 0（v0.8.0 起作为源溯源事实记录，官方验证合同为生产 spatial_kfold 5 折 seed=20260723）。
- 五种模型预测导入与公共有效点指标复算（历史 v0.1 基线，旧链）：每个模型 1,481 valid、241 NoData、XY mismatch 0，`baseline_passed=True`。
- 模型任务、SuperMap 成果登记与证据等级管理（历史旧链）：`RHO_KRIG_FINAL_20M_40` 为旧链唯一正式成果，`dataset_verified=False`。
- 微震数据审计（v0.2a）：22 个 DAT 清单与哈希、2,006 条源记录标准化、三张标准表、一维累计距离、契约验证、问题清单和审计报告；v0.5 以 `domain_adapter` 预设接入平台（`config/presets/microseismic.json`，`adapter_id=microseismic_dat_v05`）。
- 测试分层：后端便携测试（CI）+ 本机真实数据回归（`local_data`）+ 前端 vitest + Playwright mock 冒烟。

瓦斯已随 v0.8.0 第三批代码化为内置预置案例（见上）；仓库外的人工派生表与 iDesktopX 体元崩溃证据仅保留为历史来源证据（见 [docs/data/gas.md](docs/data/gas.md)），不得描述成仓库功能。微震人工派生表已转为 v0.5 黄金回归来源，不再只是外部证据。以[当前状态](docs/status/current-status.md)为准。

## 下一阶段方向

- 浏览器界面 + Python FastAPI 建模后端 + SuperMap iServer 发布的混合架构。
- 通用 CSV/XLSX 上传、二维/三维字段映射和独立案例管理。
- IDW、普通 Kriging 的手动调参和网格搜索，使用空间隔离验证生成模型排行榜。
- 二维地图、三维体元、切片和阈值过滤展示，保留完整数据与参数证据链。
- 第一个开发里程碑用现有电阻率成果打通“iServer发布 → FastAPI状态接口 → 浏览器加载”的纵向闭环；微震为第二案例，瓦斯为第三案例（已随 v0.8.0 第三批接入内置预置）。

完整目标、边界和分期见 [docs/product-blueprint.md](docs/product-blueprint.md)。当前实现状态与未来设计必须分开陈述。

## 安装

```powershell
python -m pip install -e ".[test]"
# 浏览器平台（v0.4）需要：
python -m pip install -e ".[api,test]"
# 三维体渲染 SDK（v0.6.1 起为 SuperMap3D，不入库；--help 查看参数）：
python scripts/install_supermap3d.py --help
```

## 快速验证

```powershell
python -m pytest -q
python -m pytest -q -m "not local_data"
python -m pytest -q -m local_data
npm --prefix web ci
npm --prefix web run test:unit
npm --prefix web run type-check
npm --prefix web run build
npm --prefix web run test:e2e
geomodeling run-all -o outputs/release_verify
geomodeling verify-supermap -o outputs/release_verify
geomodeling microseismic run-audit --config config/microseismic.yaml -o outputs/microseismic_verify
geomodeling microseismic derive --source-dir <DAT目录> -o outputs/microseismic_v05_verify
```

v0.4 浏览器平台（iServer 可选，通用建模不依赖它）：

```powershell
cd web; npm install; npm run build; cd ..
python -m uvicorn geomodeling.api.app:app --host 127.0.0.1 --port 8000 --workers 1
# 浏览器打开 http://127.0.0.1:8000/
```

## v0.4.1 答辩演示

```powershell
geomodeling demo-check                 # 启动前检查（阻断/警告分级）
scripts/start_demo.ps1 -CheckOnly -NoBrowser   # 只检查不启动
scripts/start_demo.ps1                 # 检查 + 单进程启动 + 打开浏览器
```

演示数据为唯一权威样例 `demo/platform_demo_3d.csv`（SHA-256 固定，首页「下载演示数据」获取）。完整演示流程、双路线与故障恢复见 [docs/v0.4.1-demo-runbook.md](docs/v0.4.1-demo-runbook.md)。

便携测试只使用 `tests/fixtures/` 中的人工小样本，可在 GitHub Actions 中运行；`local_data` 测试依赖相邻只读资料目录，资料不存在时会明确 skip。详细验收口径见 [docs/acceptance.md](docs/acceptance.md)。

## CLI 入口

每个命令单独一行执行；`--help` 可查看参数：

```powershell
geomodeling --help
geomodeling validate-data --help
geomodeling import-predictions --help
geomodeling compute-metrics --help
geomodeling register-supermap-results --help
geomodeling verify-supermap --help
geomodeling create-model --help
geomodeling list-models --help
geomodeling select-models --help
geomodeling export-reports --help
geomodeling run-all --help
geomodeling microseismic --help
geomodeling microseismic inventory --help
geomodeling microseismic parse --help
geomodeling microseismic validate --help
geomodeling microseismic export-reports --help
geomodeling microseismic derive --help
geomodeling microseismic import-case --help
geomodeling microseismic run-audit --help
geomodeling professional --help
geomodeling professional diagnose --help
geomodeling professional confirm --help
geomodeling professional inspect-result --help
geomodeling professional extract-anomalies --help
geomodeling professional compare --help
```

默认配置位于 `config/default.yaml`（电阻率）和 `config/microseismic.yaml`（微震）。运行后生成数据登记、验证报告、指标复算、SuperMap 证据、问题清单、审计 JSONL 和验收摘要。

## 文档导航

- [docs/product-blueprint.md](docs/product-blueprint.md)：浏览器建模平台的唯一产品与开发蓝图
- [docs/v0.6-professional-modeling-loop.md](docs/v0.6-professional-modeling-loop.md)：v0.6 专业建模运行手册（诊断/确认/折分/不确定性/异常/比较/导出）
- [docs/v0.5-microseismic-loop.md](docs/v0.5-microseismic-loop.md)：v0.5 微震第二案例运行手册（DAT 导入/派生/调参/导出/故障恢复）
- [docs/v0.4-generic-modeling-loop.md](docs/v0.4-generic-modeling-loop.md)：v0.4 通用建模运行说明（上传/门禁/调参/成果/导出）
- [docs/v0.3-iserver-loop.md](docs/v0.3-iserver-loop.md)：v0.3 iServer 纵向闭环运行说明与实测证据
- [docs/architecture.md](docs/architecture.md)：系统架构与模块边界
- [docs/acceptance.md](docs/acceptance.md)：验收命令与证据口径
- [docs/data/contracts.md](docs/data/contracts.md)：数据契约
- [docs/data/resistivity.md](docs/data/resistivity.md)：电阻率数据与成果事实
- [docs/data/microseismic.md](docs/data/microseismic.md)：微震审计事实与冲突
- [docs/data/gas.md](docs/data/gas.md)：瓦斯内置预置数据合同、坐标/单位口径与历史外部证据边界
- [docs/supermap-integration.md](docs/supermap-integration.md)：iServer、iClient3D和iDesktopX集成边界
- [docs/status/current-status.md](docs/status/current-status.md)：当前开发状态与下一阶段门槛
- [docs/decisions/0001-technology-stack.md](docs/decisions/0001-technology-stack.md)：技术栈 ADR
- [docs/decisions/0002-supermap-evidence-levels.md](docs/decisions/0002-supermap-evidence-levels.md)：SuperMap 证据等级 ADR
- [docs/decisions/0003-browser-platform-and-iserver.md](docs/decisions/0003-browser-platform-and-iserver.md)：浏览器平台与iServer纵向闭环ADR
- [tests/fixtures/README.md](tests/fixtures/README.md)：便携测试样本说明

## SuperMap iServer

- 本机部署：`D:\supermap\supermap-iserver-2026-windows-x64-deploy\supermap-iserver-2026-windows-x64-deploy`
- 最新官方帮助：<https://help.supermap.com/iServer/1201/zh/>
- 默认管理入口：<http://localhost:8090/iserver/admin-ui/home/>

本机根目录构建标识为`12.1.0.0-260626-9297`。网址路径中的`1201`不作为文档过期或版本不匹配的判据。**2026-07-22 v0.3 实测**：iServer 已启动并完成初始化（试用许可至 2026-09-20），`WorkSpace.smwu` 已发布 data/map/3D 三服务；全局 `CATALINA_*` 环境变量污染会导致启动异常，须先清理。产品包内的iClient示例页只是“不包含iClient”的占位提示；v0.3 前端 SDK 经 `scripts/fetch_iclient3d.py` 从官方 npm 包获取。详细事实与已知问题见[docs/supermap-integration.md](docs/supermap-integration.md) 与 [docs/v0.3-iserver-loop.md](docs/v0.3-iserver-loop.md)。

## 开发 Agent 入口

开始开发前按顺序阅读：`README.md` → [当前状态](docs/status/current-status.md) → [产品蓝图](docs/product-blueprint.md) → [SuperMap集成说明](docs/supermap-integration.md) → 对应案例数据文档。论文只作来源证据，不能覆盖这些已确认规则。

发布基线：v0.5.0 已发布（tag `v0.5.0`，merge `d37eb94`），见 [v0.5 运行手册](docs/v0.5-microseismic-loop.md)；更早基线 v0.4.1（tag `v0.4.1`）与 v0.4.0（tag `v0.4.0`，merge `b95f12b`）已发布，v0.4.1 演示加固见 [运行手册](docs/v0.4.1-demo-runbook.md) 与 [通用建模契约](docs/v0.4-generic-modeling-loop.md)；v0.6 专业建模增强、v0.7.0 统一案例工作台与 v0.8.0 电阻率散点迁移 + DSI-like 已发布；v0.8.1 纳入统计与空间分析中心及第三批瓦斯预置案例；**v0.9.0 视觉产品重构为发布候选（`feat/v0.9.0-visual-product`，PR 待合并，验收见 [evidence/v0.9.0](docs/evidence/v0.9.0/)）**。历史 `v0.8.0` tag 保持不变。

## 原始资料保护

- `../超图杯资料` 只读：不移动、不改名、不覆盖、不清洗、不删除。
- 派生成果只写入本项目内被 Git 忽略的 `outputs/`、`artifacts/`、`logs/`。
- 原始 DAT、PDF、XLSX、图片、UDB/UDBX、完整派生观测表、缓存和密钥不提交 Git；派生数据绝不覆盖标准化源数据。
