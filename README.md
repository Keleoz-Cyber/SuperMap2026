# GeoModelingPlatform

GeoModelingPlatform 是面向 SuperMap 杯答辩的浏览器三维地质属性建模平台。用户可以上传 CSV、Excel 或受支持的专业数据，完成字段映射、质量校验、插值调参、空间交叉验证、候选比较、三维成果展示、切片分析和证据导出。

当前源码版本为 **0.9.0**。版本发布状态以 GitHub Releases 为准；本文只描述当前代码能力，不记录临时分支或 PR 状态。

## 已实现能力

- 数据接入：CSV、Excel、内置预置案例和微震领域派生数据。
- 数据门禁：字段映射、类型和有限值检查、空间柱检查、来源哈希与数据血统。
- 插值与预测：IDW、普通克里金、DSI-like 工程近似、随机森林空间回归、克里金残差随机森林。
- 专业建模：经验半变异函数、变异函数拟合、人工确认的各向异性、旋转邻域、克里金标准差、经验误差和异常连通区。
- 可靠比较：空间分折、公共有效集、折分指纹、候选完整性校验和跨实验比较。
- 成果展示：SuperMap3D NetCDF 体渲染、Volume/Contour/X/Y/Z Slice、切片统计、图表与三维联动。
- 分析与解释：质量、分布、空间剖面、模型指标、规则研判和可选 AI 辅助研判。
- 持久化与导出：SQLite 任务状态、正式成果选择、成果 ZIP、专业证据和来源哈希。
- 演示保障：启动前检查、Mock E2E、真实 FastAPI Live E2E，以及本机真实 SuperMap SDK 验收规格。

## 三个内置案例

| 案例 | 输入与坐标 | 当前用途 | 重要边界 |
|---|---|---|---|
| 地下电阻率 | 17,549 个 `X,Y,Z,RHO` 散点，局部工程坐标，Ω·m | 三维插值、DSI-like、机器学习预测、体渲染和切片 | 不等同真实地理坐标；DSI-like 不等同 GOCAD DSI |
| 微震波速 | 1,911 个去异常并聚合后的局部三维节点，km/s | 普通克里金、实验性随机森林、专业诊断和三维展示 | 只有 22 个独立 XY 组；没有绝对地理配准 |
| 瓦斯含量 | 58 个合格样品、28 个 XY 采样位置，ml/g | 稀疏样本插值与三维展示 | 负 R² 如实保留；样本量不足，不开放机器学习 |

内置数据位于 `example_data/`，字节级 SHA-256 由测试锁定。原始私有研究资料、SuperMap 工作空间、运行数据库和凭据不进入仓库。

## 快速启动

以下命令均为 **PowerShell**：

```powershell
cd <仓库路径>
python -m pip install -e ".[api,test]"
npm --prefix web install
python -m geomodeling.cli demo-check
powershell -ExecutionPolicy Bypass -File scripts\start_demo.ps1
```

默认访问地址：<http://127.0.0.1:8000/>。项目约定演示只使用 8000 端口；若端口被旧版本占用，先确认进程身份，不要直接启动第二套服务。

手动开发启动：

```powershell
npm --prefix web run build
python -m uvicorn geomodeling.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

运行时数据目录可通过 `GEOMODELING_DATA_DIR` 指定。SuperMap/iServer、DeepSeek 等凭据只能通过环境变量提供，禁止写入源码、SQLite、日志或导出包。

## 常用命令

```powershell
python -m geomodeling.cli --help
python -m geomodeling.cli demo-check
python -m geomodeling.cli run-all -o outputs\verify
python -m geomodeling.cli verify-supermap -o outputs\verify
python -m geomodeling.cli microseismic --help
python -m geomodeling.cli microseismic derive --help
python -m geomodeling.cli microseismic import-case --help
python -m geomodeling.cli professional --help
geomodeling professional diagnose --help
geomodeling professional confirm --help
geomodeling professional inspect-result --help
geomodeling professional extract-anomalies --help
geomodeling professional compare --help
python -m geomodeling.cli render-grid --help
python -m geomodeling.preset_cli --help
```

三个内置案例维护入口：

```powershell
python -m geomodeling.preset_cli seed-resistivity
python -m geomodeling.preset_cli seed-microseismic
python -m geomodeling.preset_cli seed-gas
```

## 测试与构建

测试代码属于项目质量合同，应保留在 Git 仓库和“工程源代码”交付目录中；它们不进入面向运行的部署目录。

```powershell
python -m pytest -q -m "not local_data"
python -m pytest -q -m local_data
npm --prefix web run test:unit
npm --prefix web run type-check
npm --prefix web run build
npm --prefix web run test:e2e
```

真实 SDK 测试依赖本机 SuperMap 环境、隔离运行库和显式配置，不应在缺少条件时冒充已验证。

## 文档导航

- [当前状态](docs/status/current-status.md)
- [产品蓝图](docs/product-blueprint.md)
- [系统架构](docs/architecture.md)
- [验收标准](docs/acceptance.md)
- [SuperMap 与 iServer 集成](docs/supermap-integration.md)
- [比赛提交与文件保留规则](docs/contest-submission.md)
- [数据契约](docs/data/contracts.md)
- [电阻率数据](docs/data/resistivity.md)
- [微震数据](docs/data/microseismic.md)
- [瓦斯数据](docs/data/gas.md)
- [v0.4.1 演示运行手册](docs/v0.4.1-demo-runbook.md)
- [v0.6 专业建模运行手册](docs/v0.6-professional-modeling-loop.md)
- [v0.6.1 NetCDF 原生体渲染手册](docs/v0.6.1-netcdf-native-rendering-runbook.md)

当前保留的真实验收证据：

- [v0.9.0 产品与三案例浏览器证据](docs/evidence/v0.9.0/)
- [v0.9.0 机器学习空间预测证据](docs/evidence/v0.9.0-ml-spatial-prediction/)
- [v0.9.0 成果级分析证据](docs/evidence/v0.9.0-result-analysis-live/)
- [SuperMap3D 单轴切片技术探针](docs/evidence/v0.7.0-single-axis-probe/)

更早版本的过程计划、截图和实验记录已从当前工作树清理，仍可通过 Git 标签、Release 和历史提交追溯。

简要发布基线：v0.4.0 已由 merge `b95f12b` 发布；v0.5.0 已发布（merge `d37eb94`）；v0.6.0、v0.6.1、v0.7.0、v0.8.0 和 v0.8.1 的能力均已进入当前源码。完整历史以 GitHub Releases 为准。

## 能力边界

- 预置案例使用彼此独立的局部工程坐标，不能直接跨案例空间叠加。
- DSI-like 是离散平滑工程近似，不宣称复现商业 GOCAD DSI。
- 随机森林“模型离散度”只是树模型分歧参考，不表示概率意义上的可信范围。
- 微震随机森林属于实验性能力；瓦斯样本不满足机器学习适用性门。
- 通用上传成果默认 `manual_required`，不虚报自动发布到 iServer。
- 仅支持 X/Y/Z 正交切片，不提供任意斜切。
- AI 辅助研判是可选解释层；无密钥或调用失败时必须显式降级，不影响确定性建模主链。

## 比赛交付

SuperMap 杯开发组要求提供工程源代码、运行数据、B/S 运行文件、作品文档、截图、演示视频和 PPT。仓库与最终提交包不是同一个概念：仓库保留测试和 CI，运行包排除测试缓存、开发数据库、日志与密钥。具体清单见[比赛提交说明](docs/contest-submission.md)。
