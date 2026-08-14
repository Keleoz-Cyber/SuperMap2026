# GeoModelingPlatform

浏览器三维地质属性建模与空间分析平台（SuperMap 杯作品）：选择内置案例或上传 CSV/Excel 数据，依次完成字段映射、质量门禁、多算法调参、空间交叉验证与候选比较，物化为三维属性场后在 SuperMap3D 中体渲染、切片与统计分析，最终产出地质研判和带来源哈希的可审计证据包。

当前版本：**1.0.0**；发布包与历史版本见 [GitHub Releases](https://github.com/Keleoz-Cyber/SuperMap2026/releases)。

## 平台闭环

```text
选择案例 / 上传数据
  -> 字段映射与质量门禁
  -> 选择算法并调参（IDW / 普通克里金 / DSI-like / 随机森林 / 克里金残差随机森林）
  -> 整 XY 柱空间交叉验证
  -> 公共有效集候选比较与适用性判断
  -> 正式成果选择与物化
  -> SuperMap3D 体渲染 / 等值面 / X/Y/Z 正交切片
  -> 统计分析、地质研判（规则 + 可选 AI）
  -> 证据 ZIP 导出与发布状态登记
```

任何阶段失败都显式给出原因；禁止用空图、点云或线框冒充体渲染成果（no silent fallback）。

## 直接体验（Windows 免安装包）

评测机器使用 Windows x64 免安装包：下载 `GeoModelingPlatform-1.0.0-win-x64.zip`，完整解压后双击 `启动平台.cmd`。包内已含 Python 运行时、前端、SuperMap3D SDK、SQLite 和三个内置案例，无需安装 Python、Node.js、Docker 或 iServer。

- 默认地址：<http://127.0.0.1:8000/>；结束后双击 `停止平台.cmd`
- 完整性诊断：`GeoModelingPlatform.exe doctor`
- 可选 AI 研判：右上角「AI 设置」配置自己的 DeepSeek API Key（不配置不影响任何主链功能）

## 三个内置案例

| 案例 | 数据规模 | 属性 | 用途 | 主要边界 |
|---|---|---|---|---|
| 地下电阻率 | 17,549 个唯一 XYZ 节点 | RHO（Ω·m） | 主演示：多算法比较、三维成果、机器学习对照 | 局部工程坐标，无 EPSG |
| 微震波速 | 2,006 源记录 -> 1,911 建模节点 | Vx（km/s） | 领域派生链：DAT 解析、3σ、黄金哈希、聚合 | 仅 22 个 XY 组；绝对 CRS 未知 |
| 瓦斯含量 | 58 条合格样品 | CH4（ml/g） | 稀疏样本适用性门：系统拒绝不可靠模型 | 基线 R² 为负，仅作探索性解释 |

三案例使用彼此独立的局部坐标，不能叠加为同一真实地理空间。

## 核心能力

- 数据接入：CSV、Excel、内置案例和微震 DAT 领域派生；原子上传、字段映射、质量门禁（blocker 阻断、warning 需精确确认）。
- 建模算法：IDW、普通克里金（含原生估计方差）、DSI-like（仅 3D 的工程近似）、随机森林空间回归、克里金残差随机森林（防泄漏两段式）。
- 可信验证：整 XY 柱空间折分、折分指纹、公共有效集指标、折外残差证据、泄漏检查 fail-closed。
- 专业分析：方向半变异函数与证据拟合、人工确认各向异性（不可变快照）、旋转扇区邻域、经验误差尺度、异常连通区提取与双候选比较。
- 成果表达：SuperMap3D NetCDF 体渲染（Volume / Contour / Slice）、X/Y/Z 正交切片权威统计、统计分析中心、首页指挥舱与确定性发现卡。
- 地质研判：版本化确定性规则（p25/p75 探索性异常）优先，DeepSeek 仅作可选辅助解释；AI 失败不影响主链。
- 交付能力：正式成果选择、SQLite 持久化与任务恢复、证据 ZIP 导出、Windows 免安装发行包（SHA-256 完整性清单）。

## 源码启动（PowerShell）

```powershell
python -m pip install -e ".[api,test]"
npm --prefix web ci
python -m geomodeling.cli demo-check
powershell -ExecutionPolicy Bypass -File scripts\start_demo.ps1
```

常用维护入口：

```powershell
python -m geomodeling.cli --help
python -m geomodeling.cli microseismic derive --help
python -m geomodeling.cli microseismic import-case --help
geomodeling professional diagnose --help
geomodeling professional confirm --help
geomodeling professional inspect-result --help
geomodeling professional extract-anomalies --help
geomodeling professional compare --help
python -m geomodeling.cli render-grid --help
python -m geomodeling.preset_cli --help
```

## 技术栈

Python 3.12 · FastAPI · Pydantic · SQLAlchemy · SQLite · pandas / NumPy / SciPy / scikit-learn / PyArrow ｜ Vue 3 · TypeScript · Element Plus · ECharts · Vite ｜ SuperMap3D（iClient3D 2026）隔离 iframe 体渲染 · NetCDF classic/v3 ｜ pytest · Vitest · Playwright · GitHub Actions 双速 CI。

## 文档

文档遵循单一事实归属与合同测试治理，索引与规范见 [docs/README.md](docs/README.md)：

- [产品指南](docs/product-guide.md)：功能操作、三个内置案例、AI 配置与指标解释。
- [技术架构](docs/architecture.md)：分层架构、模块边界、数据生命周期、算法与验证、渲染链与术语。
- [API 与 CLI 参考](docs/api-reference.md)：全部 HTTP 端点、命令与环境变量。
- [运维手册](docs/operations.md)：免安装包、源码开发、打包发布、测试 CI 与故障排查。
- [比赛交付](docs/contest.md)：答辩演示路线、提交结构、特色口径与边界话术。
- [更新日志](CHANGELOG.md)与[验收证据](docs/evidence/)：版本演进与真实运行证据。

历史设计、旧版本运行手册和过程说明不在当前工作树重复维护；需要时通过 Git tag、Release 和提交历史追溯。

## 重要边界

- DSI-like 是离散平滑工程近似，不等同 GOCAD DSI。
- 微震绝对 CRS 未知；瓦斯样本稀疏且基线 R² 为负；不能夸大空间结论。
- 高低异常来自成果网格 p25/p75 分位阈值，只是探索性线索；低阻不能直接认定含水，速度异常不等于微震事件或断层，高瓦斯含量分位不等于法定危险等级。
- 随机森林离散度不是概率置信区间；AI 只补充解释确定性证据，不替代规则、模型和人工判断。
- 通用成果发布默认 `manual_required`；iServer 离线不影响建模主链，但不得虚报发布成功。
- 仅支持 X/Y/Z 正交切片，不提供任意斜切。

测试代码属于工程质量证据，应保留在源码仓库；运行包不包含测试缓存、开发数据库、日志、密钥或私有研究原件。
