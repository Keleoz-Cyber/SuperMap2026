# 微震数据审计与标准化

> 数据契约通用规则见 [contracts.md](contracts.md)。本文件记录微震 v0.2a 数据审计底座的已验证事实、冲突登记和 downstream gates。v0.2b 数据确认的设计见 [../superpowers/specs/2026-07-19-microseismic-v0.2b-data-confirmation-design.md](../superpowers/specs/2026-07-19-microseismic-v0.2b-data-confirmation-design.md)，确认清单见 [../microseismic_v0.2b_data_confirmation.md](../microseismic_v0.2b_data_confirmation.md)。

## 1. 当前结论

微震 v0.2a 已合并到 `main`（PR #2），完成数据审计与标准化底座：22 个 DAT 全部可读取、可追溯，2,006 条源记录进入标准表，三张标准表、一维累计距离、契约验证、问题清单和审计报告均可复现。当前**没有**可信 X/Y/Z，不能进行二维/三维重建、正式清洗或空间插值。

## 2. 原始文件读取

- 22 个正式 DAT 文件，共 **66,880 字节**，ASCII 空白分隔文本，表头为 `WL/2(km)  Vx`。
- 每个文件末尾含有 1 个 **NUL 终止伪行**，共 22 个；通用文本读取器因此可能误判为二进制。解析器显式识别 NUL 伪行且不计入样本，并在 `source_manifest.json` 中逐文件登记。
- 处理前后 22 个原始文件 SHA-256 完全一致；原始目录只读，不修改、不移动、不清洗。

## 3. 记录数口径

三个层次必须分开：

| 口径 | L1 | L2 | L3 | 合计 |
|---|---:|---:|---:|---:|
| 通用初读行（含 NUL 伪行） | — | — | — | 2,028 |
| 真实源记录 | 823 | 819 | 364 | **2,006** |
| 有限有效数值 | 822 | 819 | 364 | **2,005** |
| 无效数值 | 1 | 0 | 0 | **1** |

关系：2,028 = 2,006 + 22 个 NUL 伪行；2,005 = 2,006 − 1 条 W8 无效数值。

## 4. W8 特殊值

`W8.dat` 源文件第 2 行 Vx 为旧式 Windows/MSVC NaN token `1.#QNAN0`。处理规则：

- 原 token 原样保留在 `velocity_samples.csv`，并保留原始 `WL/2(km)` token、文件名和源行号；
- `is_numeric_valid=false`，标准化数值字段为空，不进入 2,005 条有限统计；
- **不改 0、不静默删除、不自动插值覆盖**；
- 与论文所述“删除 80 条异常值”是两回事，不得混淆；
- 问题代码 `SOURCE_SPECIAL_NAN_TOKEN`。

## 5. 测线、测点与 W28

- 正式测点 22 个：L1 = W1—W9（9），L2 = W12—W20（9），L3 = W24—W27（4）；每个正式测点唯一对应一个 DAT。
- **W28 仅作冲突登记**：没有正式 DAT，不属于正式 L3；`sequence_on_line` 和 `cumulative_s_m` 为**空值**（不是 0）；关联的 350 m 点间距仅保留为冲突证据；不进入正式集合、累计距离、样本、清洗集合或模型。

## 6. 三张标准表

完整本地输出写入被 Git 忽略的 `outputs/microseismic_v0.2a/`：

| 表 | 行数 | 内容 |
|---|---:|---|
| `survey_lines.csv` | 3 | 测线、起止点、点数、记录统计、几何状态与来源置信 |
| `survey_points.csv` | 23 | 22 个正式测点 + W28 冲突登记行 |
| `velocity_samples.csv` | 2,006 | 每条真实源记录一行，可反查源文件与源行号 |

配套输出：`source_manifest.json`、`microseismic_validation.json`、`microseismic_issue_list.json/.md`、`microseismic_data_quality.md`、`microseismic_data_dictionary.md`、`microseismic_audit_summary.md` 和审计 JSONL。

## 7. 一维累计距离

v0.2a 只允许一维沿测线距离 `cumulative_s_m`，点间距来自 `点间距.xlsx`，点序来自正式配置：

| 测线 | 点间距（m） | 最大累计距离 |
|---|---|---:|
| L1 | 150/100/100/50/50/150/250/300 | **1,150 m** |
| L2 | 275/275/250/195/110/600/300/300 | **2,305 m** |
| L3 | 800/320/335 | **1,455 m** |

正式测点保持 1-based 点序和实际累计距离；首测点累计为 0。未确认的 `x_local_m`、`y_local_m`、`derived_depth_m`、`derived_z_m` 一律为空并带状态字段，不填 0。

## 8. 来源冲突

以下冲突并列保留，不得私自消解：

- **论文计数冲突**（`LINE_COUNT_CONFLICT`）：论文表格 `823/818/364=2,005` 与文件事实（源记录 `823/819/364=2,006`，有限数值 `822/819/364=2,005`）不一致；不得移动记录以迎合论文。
- **清洗比例冲突**（`CLEANING_RATE_CONFLICT`）：论文称删除 80 条异常值、占 3.59%，但 80/2,005 ≈ 3.99%。
- **清洗方法冲突**（`CLEANING_METHOD_CONFLICT`）：材料分别出现线性插值与邻近 5 点 IDW 两种方法；v0.2a 不选择正式规则、不生成正式清洗结果、不删除或覆盖源记录。
- **W28 冲突**（`L3_W28_SOURCE_CONFLICT`、`L3_W28_INTERVAL_EXCLUDED`）：见第 5 节。

## 9. Downstream gates

审计验证通过只表示已登记事实内部一致，**不代表**具备三维插值条件。当前门槛状态：

- `geometry_blocked=True`（`ABSOLUTE_COORDINATES_UNAVAILABLE`、`DEPTH_Z_DERIVATION_UNCONFIRMED`、`LINE_AZIMUTH_UNCONFIRMED`）
- `cleaning_blocked=True`（`CLEANING_METHOD_CONFLICT`、`CLEANING_RATE_CONFLICT`）
- `interpolation_blocked=True`（上述几何问题 + `WL_HALF_MEANING_UNCONFIRMED`）

## 10. v0.2b 前置确认

下一阶段是**数据确认**，不是直接开始三维插值开发。待确认项：

1. `WL/2(km)` 完整物理含义、单位、正方向、到深度/Z 的公式与参考面；
2. 测线原点、点序方向、方位角约定与数值、CRS/EPSG 或完整本地坐标定义、三条测线交点关系、Z 基准；
3. 80 条异常值清单或可复现规则、比例口径、正式填补方法与邻域定义；
4. 论文与文件计数冲突的权威解释与正式输入集合。

确认流程、证据等级和启动门槛见 [../microseismic_v0.2b_data_confirmation.md](../microseismic_v0.2b_data_confirmation.md)。

## 11. 复现命令

```powershell
geomodeling microseismic inventory --config config/microseismic.yaml -o outputs/microseismic_verify
geomodeling microseismic parse --config config/microseismic.yaml -o outputs/microseismic_verify
geomodeling microseismic validate --config config/microseismic.yaml -o outputs/microseismic_verify
geomodeling microseismic run-audit --config config/microseismic.yaml -o outputs/microseismic_verify
python -m pytest -q -m local_data
```

预期：22 个 DAT、22 个 NUL 终止符、2,006 源记录（823/819/364）、2,005 有效数值（822/819/364）、1 条无效数值（W8 `1.#QNAN0` 可追溯）、W28 不在正式集合、15 项契约检查通过、源文件 SHA-256 不变、无伪造 XY/Z，`validation_passed=True`。阻断问题使命令返回非零退出码，但仍输出诊断报告。
