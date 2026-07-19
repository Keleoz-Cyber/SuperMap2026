# Acceptance Notes

适用对象：当前 `main`（v0.1.0 电阻率基线 + 已合并的微震 v0.2a 审计底座）。

## 验收命令

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
python -m pytest -q -m "not local_data"
python -m pytest -q -m local_data
geomodeling run-all -o outputs/release_verify
geomodeling microseismic run-audit --config config/microseismic.yaml -o outputs/microseismic_verify
geomodeling verify-supermap -o outputs/release_verify
```

当前基线：全量 80 passed；便携 57 passed / 23 deselected；本地真实数据 23 passed / 57 deselected。测试数量只允许因真实新增测试而增加，任何减少或失败都必须调查。

## 电阻率验收口径

- 标准化/训练/验证行数：17,549 / 15,827 / 1,722。
- 训练空间柱 264、验证空间柱 29，重叠 0。
- 五份预测导出各 1,722 行，1,481 valid、241 NoData、XY mismatch 0。
- 复算指标与 `插值精度对比_总体指标.csv` 在配置容差内一致（`baseline_passed=True`）。
- SuperMap 配置成果 3 个，正式成果 1 个（`RHO_KRIG_FINAL_20M_40`）；本机存在 `../Project/expore1.udbx` 时 `udbx_exists=True`、`udbx_file_verified=True`。

## 微震验收口径

- 22 个 DAT（66,880 字节）、22 个 NUL 终止伪行。
- 2,006 条源记录（L1/L2/L3 = 823/819/364）、2,005 条有限数值（822/819/364）、1 条无效数值（W8 `1.#QNAN0`）。
- 三张标准表：3 / 23 / 2,006 行；W28 不在正式集合且序号与累计距离为空。
- 15 项契约检查通过，源文件 SHA-256 处理前后不变，无伪造 XY/Z，`validation_passed=True`。
- 退出码语义：只有契约检查失败（`validation_passed=False`）时 CLI 返回 1，且仍尽量输出诊断报告；`validation_passed=True` 时 `run-audit` 返回 0。downstream `geometry/cleaning/interpolation` gates 即使在退出码 0 时仍可保持阻断，退出码不代表可插值。

## 证据边界（必须保持显式）

- 微震审计 `validation_passed=True` **不解除** downstream gates：`geometry_blocked`、`cleaning_blocked`、`interpolation_blocked` 仍为 True，不能把审计通过解释为可插值。
- `dataset_verified=False`：没有受支持的 SuperMap 数据集 API 适配器，只声明文件级验证。
- 完整体元和水平切片为人工 iDesktopX 证据；垂直切片 `unverified`；原生等值面 `failed`，空数据集不进入正式成果。
- `RHO >= 77` 仅为演示阈值；RHO 物理单位和 EPSG 未确认。

## 未实现（当前 main）

- 微震二维/三维坐标重建、正式清洗与空间插值。
- 煤层瓦斯三维融合（CRS/高程/深度基准未确认前只允许属性统计）。
- DSI-like 插值内核与 GOCAD 工程转换。
- iDesktopX 控件自动化、Web 前端、账户体系、云部署和 iServer 发布。
