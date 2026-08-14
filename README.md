# GeoModelingPlatform

面向 SuperMap 杯答辩的浏览器三维地质属性建模平台：上传数据后，可完成字段映射、质量校验、插值/预测调参、空间交叉验证、候选比较、三维成果与正交切片展示，以及带来源哈希的证据导出。

当前版本：**0.9.3**。发布包与历史版本见 [GitHub Releases](https://github.com/Keleoz-Cyber/SuperMap2026/releases)。

## 直接体验

评测组使用 Windows x64 免安装包：下载 `GeoModelingPlatform-0.9.3-win-x64.zip`，完整解压后双击 `启动平台.cmd`。包内已包含 Python 运行时、前端、SuperMap3D SDK、SQLite 和三个内置案例，无需安装 Python、Node.js、Docker 或 iServer。

默认地址：<http://127.0.0.1:8000/>；退出时双击 `停止平台.cmd`。

## 核心能力

- 数据接入：CSV、Excel、内置案例和微震 DAT 领域派生。
- 建模算法：IDW、普通克里金、DSI-like、随机森林空间回归、克里金残差随机森林。
- 可信验证：整 XY 柱空间折分、公共有效集、折分指纹、成果与证据哈希校验。
- 专业分析：半变异函数、人工确认各向异性、旋转邻域、误差尺度，以及电阻率、微震速度和瓦斯含量的高低异常地质研判。
- 成果表达：SuperMap3D NetCDF 体渲染、Volume、Contour、X/Y/Z Slice、统计与三维联动。
- 交付能力：正式成果选择、SQLite 持久化、证据 ZIP、Windows 免安装发行包。

三个内置案例分别用于完整三维建模、领域数据派生和稀疏样本适用性判断；它们使用彼此独立的局部坐标，不能直接叠加为同一真实地理空间。

## 源码启动

以下命令均在 **PowerShell** 中运行：

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

## 文档

- [项目完整说明](docs/project-guide.md)：产品、架构、数据、算法、SuperMap、运行、验收、交付和边界的唯一权威说明。
- [验收证据](docs/evidence/)：真实浏览器、模型、分析与 SuperMap 技术探针的保留证据。
- [演示数据说明](demo/README.md)与[测试夹具说明](tests/fixtures/README.md)：目录级使用合同。

历史设计、旧版本运行手册和过程说明不在当前工作树重复维护；需要时通过 Git tag、Release 和提交历史追溯。

## 重要边界

- DSI-like 是离散平滑工程近似，不等同 GOCAD DSI。
- 微震绝对 CRS 未知；瓦斯样本稀疏且基线 R² 为负；不能夸大空间结论。
- 高低异常来自成果网格 p25/p75 分位阈值，只是探索性线索；低阻不能直接认定含水，速度异常不等于微震事件或断层，高瓦斯含量分位不等于法定危险等级。
- 随机森林离散度不是概率置信区间；AI 只补充解释确定性证据，不替代规则、模型和人工判断。
- 通用成果发布默认 `manual_required`；iServer 离线不影响建模主链，但不得虚报发布成功。
- 仅支持 X/Y/Z 正交切片，不提供任意斜切。

测试代码属于工程质量证据，应保留在源码仓库；运行包不包含测试缓存、开发数据库、日志、密钥或私有研究原件。
