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

- 开发交接资料已经就位。
- MVP 工程已初始化为 Python 包，核心代码位于 `src/geomodeling/`。
- 已实现电阻率数据登记、契约校验、训练/验证空间柱检查、五种预测结果导入、NoData 处理、统一指标复算、SuperMap 成果登记和报告导出。
- 原始资料只读；代码生成的数据、缓存和成果写入本项目下被忽略的 `artifacts/`、`outputs/`、`logs/` 等目录。

## 安装与测试

```powershell
pip install -e .[test]
pytest -q
```

也可以不安装包，直接在项目根目录运行：

```powershell
$env:PYTHONPATH='src'
python -m geomodeling.cli --help
Remove-Item Env:PYTHONPATH
```

## MVP 运行

```powershell
$env:PYTHONPATH='src'
python -m geomodeling.cli run-all -o outputs/mvp_smoke
Remove-Item Env:PYTHONPATH
```

默认配置位于 `config/default.yaml`。运行后会生成数据登记、验证报告、指标复算、SuperMap 成果清单和模型元数据；不会修改 `../超图杯资料`。
