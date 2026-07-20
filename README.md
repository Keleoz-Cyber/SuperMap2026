# GeoModelingPlatform

> 地矿属性模拟与三维建模平台（超图杯项目）

本目录是代码开发根目录。原始论文、原始数据和标准化数据继续保存在相邻的只读目录 `../超图杯资料` 中，不在代码项目中复制或修改。

## 项目目标

建设面向超图杯答辩的浏览器建模平台：用户上传 CSV、Excel 或受支持的专业文本数据，完成字段映射、质量校验、二维/三维插值调参、空间验证、成果展示和报告导出。第一版（v0.1.0）已打通地下电阻率从标准数据到 SuperMap 三维成果的闭环；当前 `main` 还包含微震 v0.2a 数据审计底座。

电阻率、微震、瓦斯及后续新增属性作为**独立案例**复用平台能力。没有共同坐标依据时不得空间叠加，不做无证据的多源融合。

## 当前能力

- 电阻率数据登记与契约校验：17,549 / 15,827 / 1,722 行，训练/验证空间柱重叠 0。
- 五种模型预测导入与公共有效点指标复算：每个模型 1,481 valid、241 NoData、XY mismatch 0，`baseline_passed=True`。
- 模型任务、SuperMap 成果登记与证据等级管理：`RHO_KRIG_FINAL_20M_40` 为唯一正式成果，`dataset_verified=False`。
- 微震数据审计（v0.2a）：22 个 DAT 清单与哈希、2,006 条源记录标准化、三张标准表、一维累计距离、契约验证、问题清单和审计报告。
- 便携测试（CI）与本地真实数据回归测试分层。

## 下一阶段方向

- 浏览器界面 + Python FastAPI 建模后端 + SuperMap iServer 发布的混合架构。
- 通用 CSV/XLSX 上传、二维/三维字段映射和独立案例管理。
- IDW、普通 Kriging 的手动调参和网格搜索，使用空间隔离验证生成模型排行榜。
- 二维地图、三维体元、切片和阈值过滤展示，保留完整数据与参数证据链。
- 微震局部坐标、深度和有效值规则已形成设计输入，但当前代码尚未实现二维/三维坐标重建与插值。

完整目标、边界和分期见 [docs/product-blueprint.md](docs/product-blueprint.md)。当前实现状态与未来设计必须分开陈述。

## 安装

```powershell
python -m pip install -e ".[test]"
```

## 快速验证

```powershell
python -m pytest -q
python -m pytest -q -m "not local_data"
python -m pytest -q -m local_data
geomodeling run-all -o outputs/release_verify
geomodeling verify-supermap -o outputs/release_verify
geomodeling microseismic run-audit --config config/microseismic.yaml -o outputs/microseismic_verify
```

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
geomodeling microseismic run-audit --help
```

默认配置位于 `config/default.yaml`（电阻率）和 `config/microseismic.yaml`（微震）。运行后生成数据登记、验证报告、指标复算、SuperMap 证据、问题清单、审计 JSONL 和验收摘要。

## 文档导航

- [docs/product-blueprint.md](docs/product-blueprint.md)：浏览器建模平台的唯一产品与开发蓝图
- [docs/architecture.md](docs/architecture.md)：系统架构与模块边界
- [docs/acceptance.md](docs/acceptance.md)：验收命令与证据口径
- [docs/data/contracts.md](docs/data/contracts.md)：数据契约
- [docs/data/resistivity.md](docs/data/resistivity.md)：电阻率数据与成果事实
- [docs/data/microseismic.md](docs/data/microseismic.md)：微震审计事实与冲突
- [docs/status/current-status.md](docs/status/current-status.md)：当前开发状态与下一阶段门槛
- [docs/decisions/0001-technology-stack.md](docs/decisions/0001-technology-stack.md)：技术栈 ADR
- [docs/decisions/0002-supermap-evidence-levels.md](docs/decisions/0002-supermap-evidence-levels.md)：SuperMap 证据等级 ADR
- [tests/fixtures/README.md](tests/fixtures/README.md)：便携测试样本说明

## SuperMap iServer

- 本机部署：`D:\supermap\supermap-iserver-2026-windows-x64-deploy\supermap-iserver-2026-windows-x64-deploy`
- 最新官方帮助：<https://help.supermap.com/iServer/1201/zh/>
- 默认管理入口：<http://localhost:8090/iserver/admin-ui/home/>

本机根目录构建标识为`12.1.0.0`。网址路径中的`1201`不作为文档过期或版本不匹配的判据；接口开发以该最新官方帮助和本机运行时探测为准。详细环境说明见[docs/product-blueprint.md](docs/product-blueprint.md#8-supermap-iserver-环境)。

## 原始资料保护

- `../超图杯资料` 只读：不移动、不改名、不覆盖、不清洗、不删除。
- 派生成果只写入本项目内被 Git 忽略的 `outputs/`、`artifacts/`、`logs/`。
- 原始 DAT、PDF、XLSX、图片、UDB/UDBX、完整派生观测表、缓存和密钥不提交 Git；派生数据绝不覆盖标准化源数据。
