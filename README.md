# GeoModelingPlatform

> 地矿属性模拟与三维建模平台（超图杯项目）

本目录是代码开发根目录。原始论文、原始数据和标准化数据继续保存在相邻的只读目录 `../超图杯资料` 中，不在代码项目中复制或修改。

## 项目目标

建立可复现、可追溯的地下属性数据管理、插值验证和三维表达流程，并逐步接入微震测量、煤层瓦斯与 DSI-like 算法。第一版（v0.1.0）打通地下电阻率从标准数据到 SuperMap 三维成果的完整闭环；当前 `main` 在此基础上额外包含已合并的微震 v0.2a 数据审计底座。

## 当前能力

- 电阻率数据登记与契约校验：17,549 / 15,827 / 1,722 行，训练/验证空间柱重叠 0。
- 五种模型预测导入与公共有效点指标复算：每个模型 1,481 valid、241 NoData、XY mismatch 0，`baseline_passed=True`。
- 模型任务、SuperMap 成果登记与证据等级管理：`RHO_KRIG_FINAL_20M_40` 为唯一正式成果，`dataset_verified=False`。
- 微震数据审计（v0.2a）：22 个 DAT 清单与哈希、2,006 条源记录标准化、三张标准表、一维累计距离、契约验证、问题清单和审计报告。
- 便携测试（CI）与本地真实数据回归测试分层。

## 当前边界

- 微震只有一维沿线距离；没有可信 X/Y/Z，`geometry/cleaning/interpolation` downstream gates 均为阻断。
- RHO 物理单位、EPSG 未确认；微震 `WL/2(km)` 含义、测线原点/方位角/CRS、清洗规则未确认。
- SuperMap 垂直切片未验证；原生等值面失败/空结果；数据集级 API 验证未实现。
- 瓦斯、DSI-like、微震三维插值尚未实现；下一阶段是微震数据确认，不是直接开始三维插值开发。

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

```powershell
geomodeling --help
geomodeling validate-data / import-predictions / compute-metrics
geomodeling register-supermap-results / verify-supermap
geomodeling create-model / list-models / select-models
geomodeling export-reports / run-all
geomodeling microseismic inventory / parse / validate / export-reports / run-audit
```

默认配置位于 `config/default.yaml`（电阻率）和 `config/microseismic.yaml`（微震）。运行后生成数据登记、验证报告、指标复算、SuperMap 证据、问题清单、审计 JSONL 和验收摘要。

## 文档导航

- [docs/architecture.md](docs/architecture.md)：系统架构与模块边界
- [docs/acceptance.md](docs/acceptance.md)：验收命令与证据口径
- [docs/data/contracts.md](docs/data/contracts.md)：数据契约
- [docs/data/resistivity.md](docs/data/resistivity.md)：电阻率数据与成果事实
- [docs/data/microseismic.md](docs/data/microseismic.md)：微震审计事实与冲突
- [docs/status/current-status.md](docs/status/current-status.md)：当前开发状态与下一阶段门槛
- [docs/decisions/0001-technology-stack.md](docs/decisions/0001-technology-stack.md)：技术栈 ADR
- [docs/decisions/0002-supermap-evidence-levels.md](docs/decisions/0002-supermap-evidence-levels.md)：SuperMap 证据等级 ADR
- [docs/microseismic_v0.2b_data_confirmation.md](docs/microseismic_v0.2b_data_confirmation.md)：微震 v0.2b 数据确认清单与证据登记
- [docs/superpowers/specs/2026-07-19-microseismic-v0.2b-data-confirmation-design.md](docs/superpowers/specs/2026-07-19-microseismic-v0.2b-data-confirmation-design.md)：v0.2b 数据确认设计
- [docs/superpowers/plans/2026-07-19-microseismic-v0.2b-data-confirmation.md](docs/superpowers/plans/2026-07-19-microseismic-v0.2b-data-confirmation.md)：v0.2b 数据确认实施计划
- [tests/fixtures/README.md](tests/fixtures/README.md)：便携测试样本说明

## 原始资料保护

- `../超图杯资料` 只读：不移动、不改名、不覆盖、不清洗、不删除。
- 派生成果只写入本项目内被 Git 忽略的 `outputs/`、`artifacts/`、`logs/`。
- 原始 DAT、PDF、XLSX、图片、UDB/UDBX、完整派生观测表、缓存和密钥不提交 Git；派生数据绝不覆盖标准化源数据。
