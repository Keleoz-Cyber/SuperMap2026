# GeoModelingPlatform

> 地矿属性模拟与三维建模平台（超图杯项目）

本目录是代码开发根目录。原始论文、原始数据和标准化数据继续保存在相邻的 `../超图杯资料` 目录中，不在代码项目中复制或修改。

## 开发入口

开始开发前按顺序阅读：

1. [Kimi 3 长程开发总提示词](./KIMI3_MASTER_PROMPT.md)
2. [开发交接包 README](./开发交接包/00_项目总览/README.md)
3. [MVP 功能清单](./开发交接包/01_需求与范围/MVP功能清单.md)
4. [数据契约](./开发交接包/03_数据规范/数据契约.md)
5. [SuperMap 已知问题](./开发交接包/05_SuperMap验证/已知问题.md)

## 资料位置

- [项目说明](../超图杯资料/项目说明.md)
- [三类数据开发方向与优先级](../超图杯资料/三类数据开发方向与优先级.md)
- [标准化数据目录](../超图杯资料/标准化数据)
- [参考资料目录](../超图杯资料/参考资料)

## 当前状态

- 电阻率数据与指标闭环：已在本机用真实资料验证。
- Python 包安装与 CLI：已验证。
- SuperMap UDBX 文件存在性：可由 `verify-supermap` 做文件级程序验证。
- SuperMap 内部数据集：当前未声称程序化 `dataset_verified`；只有接入真实受支持 API 并检查成功后才允许升级证据等级。
- 完整体元与水平切片：已有 iDesktopX 人工证据，登记为 `manual_evidence`。
- 垂直切片：未验证。
- 原生等值面：失败，两个空结果仅作失败证据。
- RHO 单位：待来源确认。
- 微震、瓦斯、DSI-like：暂缓，仅保留接口和边界说明。

原始资料只读；代码生成的数据、缓存和成果写入本项目下被忽略的 `artifacts/`、`outputs/`、`logs/` 等目录。

## 安装与测试

```powershell
python -m pip install -e ".[test]"
python -m pytest -q -m "not local_data"
python -m pytest -q -m local_data
python -m pytest -q
```

便携测试只使用 `tests/fixtures/` 中的人工小样本，可在 GitHub Actions 中运行。`local_data` 测试依赖相邻只读资料目录；资料不存在时会明确 skip。

## MVP 运行

```powershell
python -m geomodeling.cli run-all -o outputs/mvp_release_verify
python -m geomodeling.cli verify-supermap -o outputs/mvp_release_verify
```

模型任务命令：

```powershell
python -m geomodeling.cli list-models -o outputs/mvp_release_verify
python -m geomodeling.cli select-models -o outputs/mvp_release_verify
python -m geomodeling.cli select-models --default-model-id rho_kriging_20m_n40_v1 --comparison-model-id rho_idw_20m_n25_v1 -o outputs/mvp_release_verify
python -m geomodeling.cli create-model --model-id rho_idw_20m_n25_test --display-name "IDW test" --method IDW --parameters-json '{"resolution_xy_m":20,"neighbor_count":25}' -o outputs/mvp_release_verify
```

默认配置位于 `config/default.yaml`。运行后会生成数据登记、验证报告、指标复算、SuperMap 证据等级、视图配置、问题清单、审计 JSONL 和验收摘要；不会修改 `../超图杯资料`。
