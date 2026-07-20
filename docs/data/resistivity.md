# 地下电阻率数据与成果

> 数据契约通用规则见 [contracts.md](contracts.md)。本文件记录电阻率 v0.1 的已验证事实、模型选型和 SuperMap 证据边界。

## 1. 当前结论

电阻率三维属性模拟闭环已在 v0.1.0 发布基线中验证：标准化数据登记、契约校验、训练/验证隔离、五模型预测导入、公共有效点指标复算、SuperMap 成果登记和报告导出全部可复现。`RHO_KRIG_FINAL_20M_40` 是唯一正式 SuperMap 成果；`dataset_verified=False` 保持显式声明；垂直切片未验证；原生等值面失败并留下空数据集。

## 2. 数据基线

权威文件与已验证记录数：

| 数据集 | 记录数 | 说明 |
|---|---:|---|
| 标准化源数据 | 17,549 | 字段 `X,Y,Z,RHO` |
| 训练集 | 15,827 | 264 根空间柱 |
| 验证集 | 1,722 | 29 根空间柱 |

坐标为局部平面坐标（`crs.type=local_engineering`，EPSG 未确认），Z 使用负高程/向下为负。RHO 物理单位仍未确认，界面显示“单位待来源确认”。

该数据只作为独立电阻率案例使用。没有共同控制点和可信坐标变换时，不得与微震或瓦斯案例空间叠加。

## 3. 训练与验证隔离

- 训练集与验证集按完整 `(X,Y)` 空间柱划分，空间柱交叉数为 **0**。
- 划分种子：`supermap-rho-block-cv-v1`。
- 契约校验在本地真实数据回归中持续执行。

## 4. 五种模型验证

五种候选模型使用相同的 1,722 条验证记录，每个模型均为：1,722 行、**1,481 valid**、**241 NoData**、**XY mismatch 0**。

| 模型 | 有效点 | NoData | 覆盖率 | MAE | RMSE |
|---|---:|---:|---:|---:|---:|
| IDW 20m/25点 | 1,481 | 241 | 86.0046% | 3.475606 | 5.787635 |
| Kriging 20m/25点 | 1,481 | 241 | 86.0046% | 3.260683 | 5.818866 |
| Kriging 20m/15点 | 1,481 | 241 | 86.0046% | 3.273115 | 5.803305 |
| Kriging 20m/40点 | 1,481 | 241 | 86.0046% | 3.222594 | 5.841043 |
| Kriging 10m/40点 | 1,481 | 241 | 86.0046% | 3.520460 | 6.430798 |

- `-9999` 是 NoData，不是实测值；导入时转换为 null + `is_nodata=true`，不进入误差统计、着色或再次插值。
- 241 个 NoData 中 240 个集中在四根完全无覆盖空间柱，另有 1 个分布在单柱；五个模型 NoData 掩膜完全相同，说明无值主要与输出覆盖范围有关，不是单一插值方法造成。
- 复算指标与 `插值精度对比_总体指标.csv` 在配置容差内一致（`baseline_passed=True`）。

## 5. 正式模型选择

- 默认展示模型：`Kriging 20m/40点`（MAE、中位绝对误差和平均相对误差最优）。
- 正式对照模型：`IDW 20m/25点`（RMSE、R² 和 log10 RMSE 最优）。
- Bias 说明：五模型 Bias 均为正值；`IDW 20m/25点` 的 Bias（0.171140）只相对默认 `Kriging 20m/40点`（0.299065）更接近 0，并非五模型中最小（`Kriging 10m/40点` 为 0.127693）。
- `Kriging 10m/40点` 未提高验证精度，不作为正式候选。
- 不得描述普通克里金在所有指标上都优于 IDW；不能仅凭整体着色更平滑判断模型更可靠。

## 6. SuperMap 成果证据

唯一正式成果（配置登记 + 文件级验证 + 人工证据）：

| 项目 | 数值 |
|---|---|
| SuperMap 数据集 | `RHO_KRIG_FINAL_20M_40` |
| 方法 | 普通克里金 |
| 水平分辨率 / 邻点数 | 20 m / 40 |
| 行 × 列 × 波段 | 7 × 23 × 42 |
| 显示值范围 | 1.418283 — 133.146194（界面显示值） |
| 演示异常阈值 | `RHO >= 77`（工程演示配置，不是已论证的地质危险阈值） |

证据边界：

- `dataset_verified=False`：当前 `dataset_api=none`，只有 UDBX 文件级验证（`file_verified`），不得声称内部数据集级程序化验证（见 [../decisions/0002-supermap-evidence-levels.md](../decisions/0002-supermap-evidence-levels.md)）。
- 完整体元、水平薄切片和 `RHO >= 77` 高值过滤只有 **人工证据**（iDesktopX 2026 手动验证记录）。
- 垂直切片 **未验证**：原生“剖切显示”出现空白，当前只用“显示范围”归一化参数做水平薄切片规避。
- 原生等值面 **失败**：`RHO_ISO_77_K40` 与 `RHO_ISO_HIGH_P95_K40` 两种阈值配置均报 `Failed to extract continuous surface, please check IsoValue.`，输出为空数据集，仅登记为失败/空证据。
- 失败推断：`RHO >= 77` 高值区接触体元边界，且正式体元 X 向仅 7 个单元；这是推断，不是已确认的 SuperMap 内部规则。补低值边界体元（PAD1）和 Python marching cubes 均为待验证路线，不是已解决。
- 体元 X 向仅 7 个单元，异常体几何较粗，不能把视觉边界解释为精确地质界面。

其他已知问题：

- SM-01：RHO 可能被误导入为文本；使用真实字段名修复，禁止在 SQL 中使用显示别名。
- SM-06：失败的等值面会留下同名空数据集外壳；成果登记必须检查状态、对象数和可打开性，空结果必须为 `failed`。

## 7. 已知限制

- RHO 物理单位未确认。
- EPSG 未确认，坐标为局部工程坐标。
- 241 个共同 NoData 不得无依据补值。
- 垂直切片、原生等值面、数据集级 API 验证均未通过或未实现。
- GOCAD `.sg`、Voxet、VTU 或论文所述 DSI 输出资料缺失，无法验证真实 GOCAD 到 SuperMap 的端到端转换。

## 8. 复现命令

```powershell
python -m pip install -e ".[test]"
geomodeling run-all -o outputs/release_verify
geomodeling verify-supermap -o outputs/release_verify
python -m pytest -q
python -m pytest -q -m "not local_data"
python -m pytest -q -m local_data
```

预期：三张表 17,549/15,827/1,722，空间柱重叠 0，五模型均 1,481 valid / 241 NoData / XY mismatch 0，`baseline_passed=True`，`udbx_exists=True`（本机存在 `../Project/expore1.udbx` 时），`dataset_verified=False`。
