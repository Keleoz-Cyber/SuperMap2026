# 普通 Kriging 技术验证门（v0.4 Task 7）

> 日期：2026-07-23。本文件记录局部普通 Kriging 实现在进入平台前的技术验证结果，是设计文档 §7.2 要求的“技术验证门”证据。

## 验证环境

- Python 3.12.3，NumPy（以 `tests/fixtures/kriging_reference.json` 记录版本为准），SciPy（同上）
- 固定随机种子：20260723（`kriging_reference.json.seed`）
- 实现：`src/geomodeling/modeling/variogram.py`、`src/geomodeling/modeling/kriging.py`

## 验证用例与结果

| 用例 | 方法 | 容差 MAE | 实测 MAE | 结论 |
|---|---|---:|---:|---|
| 二维常数场 | 30 训练点，10 查询点，自动拟合 spherical | 1e-9 | 1.78e-15（max abs err） | 通过 |
| 二维平面场 | 6×11 网格训练，3 查询点，spherical + 12 邻居 | 0.05 | 0.00165 | 通过 |
| 三维光滑场 | 150 随机训练点，25 个扰动查询点，spherical + 16 邻居 | 0.35 | 0.00458 | 通过 |

实测自动拟合参数（记录于 `kriging_reference.json`）：

- 平面场：nugget≈0，partial_sill≈11.57，range≈874.1；
- 三维光滑场：nugget≈0，partial_sill≈1.03，range≈1652.6。

运行时间（单次查询批）：平面 3 点 ≈ 0.3 ms；三维 25 点 ≈ 1.1 ms。内存峰值未单独计量（局部邻域求解，按 ≤128 邻居的 (n+1)×(n+1) 系统，规模有界）。

## 契约覆盖（全部有测试）

- 增广普通 Kriging 方程组权重和为 1（`test_weights_sum_to_one_via_augmented_system`）；
- 常数场精确复现；二维平面与三维光滑场满足固定容差；
- 三种变异函数（spherical / exponential / gaussian）零滞后与远基台行为、参数边界（nugget≥0、partial_sill>0、range>0、nugget+partial_sill 有限）；
- 经验变异函数：≤50,000 确定性抽样对、12 等宽滞后桶、种子可复算；自动拟合只在训练折内进行（调用方折分 runner 保证验证行不进入 fit）；
- `neighbor_count` / `search_radius` 约束生效；`min_neighbors` 不足输出 NoData（不伪造值）；
- 奇异邻域回退 `numpy.linalg.lstsq` 并计入 `singular_fallback_count`；
- manual 模式要求完整三元组且 sill（总基台值）> nugget，内部以 `partial_sill = sill - nugget` 传入，与 auto 语义一致；
- 相同数据与参数预测逐位一致（确定性）；
- 分块预测（20,000/块）边界取消协作检查（`RUN_CANCELED`）。

## 参数边界（暴露给前端的可支持范围）

| 参数 | 范围 | 默认 |
|---|---|---|
| variogram_model | spherical / exponential / gaussian | spherical |
| variogram_mode | auto / manual | auto |
| nugget | ≥ 0（manual 必填） | — |
| sill（总基台） | > nugget（manual 必填） | — |
| range | > 0（manual 必填） | — |
| neighbor_count | 4–128 | 24 |
| search_radius | > 0 或不限 | 不限 |
| min_neighbors | 3–32 | 4 |

## 已知限制（如实声明）

- 本实现是**局部普通 Kriging**（有界邻域 + 三种变异函数 + 有界自动拟合），不是通用地质统计包：不支持泛克里金、协同克里金、各向异性变异函数或趋势项；
- 自动拟合对弱结构/纯噪声数据可能给出近零 partial_sill（行为如实记录在诊断中）；
- 大邻域（接近 128）下单点求解为稠密 129×129 系统，成本有界但非零；
- 搜索半径过小或数据稀疏时 NoData 增多是契约行为，不视为错误。
