# GeoModelingPlatform

> 地矿属性模拟与三维建模平台（超图杯项目）

本目录是代码开发根目录。原始论文、原始数据和标准化数据继续保存在相邻的只读目录 `../超图杯资料` 中，不在代码项目中复制或修改。

## 项目目标

建设面向超图杯答辩的浏览器建模平台：用户上传 CSV、Excel 或受支持的专业文本数据，完成字段映射、质量校验、二维/三维插值调参、空间验证、成果展示和报告导出。第一版（v0.1.0）已打通地下电阻率从标准数据到 SuperMap 三维成果的闭环；当前代码还包含微震 v0.2a 数据审计底座、已随 v0.5.0 发布的微震第二案例建模闭环，以及 v0.6 专业建模增强（`feat/v0.6-professional-modeling` 分支）。

电阻率、微震、瓦斯及后续新增属性作为**独立案例**复用平台能力。没有共同坐标依据时不得空间叠加，不做无证据的多源融合。

## 当前能力

- **v0.6 专业建模增强（本分支）**：全向/方向经验半变异函数诊断（点对确定性采样，种子=数据 SHA-256+配置，≤50,000 点对上限并披露采样率）；球状/指数/高斯三模型按 bin 点对数加权的有界最小二乘拟合证据（`weighted_sse`/收敛/边界/参数来源）；各向异性候选仅作诊断建议，**人工确认**后写入不可变快照（改参数必生成新快照）；Kriging 各向异性变换 `x′ = S Rᵀ x`（legacy `z_scale` 归一化，不叠加）；旋转椭圆/椭球+扇区搜索邻域（IDW 与普通 Kriging 共用选择器，IDW 权重仍用 `z_scale` 距离）；普通 Kriging 原生估计标准差（`σ² = λᵀγ₀ + μ`，微负钳制/显著负值 NoData/lstsq 标记）；所有算法基于折外残差的经验误差尺度（距离加权局部 RMSE，非标准误）；空间折分检查（整柱不泄漏，泄漏 fail-closed）；显式阈值异常连通区（2D 4 邻接/3D 6 邻接，Voronoi「网格支持面积/体积估计」，非储量）；单候选联动与双候选兼容比较（兼容才显示指标差）；SQLite v5 五张专业表与 `analysis_jobs` 持久化任务；专业证据 ZIP（`professional/` 目录，声明缺失或哈希不符 409 fail-closed）；能力矩阵区分 IDW 与普通 Kriging（`not_applicable` 类型化），旧候选返回 `LEGACY_RESULT_NOT_COMPUTED`。浏览器专业诊断工作台与专业分析台、API、CLI（`geomodeling professional`）三入口齐备。运行手册见 [docs/v0.6-professional-modeling-loop.md](docs/v0.6-professional-modeling-loop.md)。
- **v0.5 微震第二案例建模闭环（已发布，v0.5.0）**：浏览器首页微震卡「导入微震 DAT」四步向导（选文件夹或 22 DAT → 核验 → 派生确认 → 质量门禁 → 建模）与 CLI 双入口（`geomodeling microseismic derive` / `import-case`）共用同一派生内核：22 DAT → 2,006 源记录 → 2,005 有限 → 一次全局 3σ（`ddof=1`）剔除 80 → 1,925 候选 → 算术平均聚合 1,911 建模节点；黄金门禁逐字节锁定两张派生表 SHA-256，不过即阻断。调参（IDW/普通克里金、`z_scale` 实验参数）、空间验证、成果工作台三层诊断图层与证据导出复用 v0.4 平台；发布登记保持 `manual_required`。运行手册见 [docs/v0.5-microseismic-loop.md](docs/v0.5-microseismic-loop.md)。
- **v0.4 通用建模平台**：CSV/XLSX 上传（50 MiB / 50 万行上限）、字段映射（2D/3D）、质量门禁（阻断/警告+显式确认）、IDW 与普通克里金调参（手动 + ≤50 组合有限网格搜索）、空间折分验证、公共有效掩膜排行榜、SQLite 持久化任务（取消/重试/重启恢复）、成果完整场与 X/Y/Z 切片、附理由的正式选择、证据 ZIP 导出、发布登记（manual_required）。运行说明见 [docs/v0.4-generic-modeling-loop.md](docs/v0.4-generic-modeling-loop.md)。
- **v0.3.1 内置电阻率案例（只读保留）**：FastAPI 案例/成果/发布证据链接口 + 浏览器三维工作台（模型排行榜、RHO 点云、S3M 体元缓存自定义渲染、阈值过滤、证据链、服务检查）。闭环含义、运行方式与实测证据见 [docs/v0.3-iserver-loop.md](docs/v0.3-iserver-loop.md)。
- 电阻率数据登记与契约校验：17,549 / 15,827 / 1,722 行，训练/验证空间柱重叠 0。
- 五种模型预测导入与公共有效点指标复算：每个模型 1,481 valid、241 NoData、XY mismatch 0，`baseline_passed=True`。
- 模型任务、SuperMap 成果登记与证据等级管理：`RHO_KRIG_FINAL_20M_40` 为唯一正式成果，`dataset_verified=False`。
- 微震数据审计（v0.2a）：22 个 DAT 清单与哈希、2,006 条源记录标准化、三张标准表、一维累计距离、契约验证、问题清单和审计报告；v0.5 以 `domain_adapter` 预设接入平台（`config/presets/microseismic.json`，`adapter_id=microseismic_dat_v05`）。
- 测试分层：后端便携测试（CI）+ 本机真实数据回归（`local_data`）+ 前端 vitest + Playwright mock 冒烟。

仓库外的瓦斯人工派生证据尚未代码化：瓦斯已形成58条三维候选样本，但体元加载会触发iDesktopX原生崩溃，暂缓作为正式案例。微震人工派生表已转为 v0.5 黄金回归来源，不再只是外部证据。以[当前状态](docs/status/current-status.md)为准，不得把这些人工结果描述成仓库功能。

## 下一阶段方向

- 浏览器界面 + Python FastAPI 建模后端 + SuperMap iServer 发布的混合架构。
- 通用 CSV/XLSX 上传、二维/三维字段映射和独立案例管理。
- IDW、普通 Kriging 的手动调参和网格搜索，使用空间隔离验证生成模型排行榜。
- 二维地图、三维体元、切片和阈值过滤展示，保留完整数据与参数证据链。
- 第一个开发里程碑用现有电阻率成果打通“iServer发布 → FastAPI状态接口 → 浏览器加载”的纵向闭环；微震作为第二案例，瓦斯暂缓。

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
- [docs/data/gas.md](docs/data/gas.md)：瓦斯三维候选数据、坐标约定和崩溃边界
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

发布基线：v0.5.0 已发布（tag `v0.5.0`，merge `d37eb94`），见 [v0.5 运行手册](docs/v0.5-microseismic-loop.md)；更早基线 v0.4.1（tag `v0.4.1`）与 v0.4.0（tag `v0.4.0`，merge `b95f12b`）已发布，v0.4.1 演示加固见 [运行手册](docs/v0.4.1-demo-runbook.md) 与 [通用建模契约](docs/v0.4-generic-modeling-loop.md)；v0.6 专业建模增强为发布候选（本分支，PR/tag 待批准），见 [v0.6 运行手册](docs/v0.6-professional-modeling-loop.md)。

## 原始资料保护

- `../超图杯资料` 只读：不移动、不改名、不覆盖、不清洗、不删除。
- 派生成果只写入本项目内被 Git 忽略的 `outputs/`、`artifacts/`、`logs/`。
- 原始 DAT、PDF、XLSX、图片、UDB/UDBX、完整派生观测表、缓存和密钥不提交 Git；派生数据绝不覆盖标准化源数据。
