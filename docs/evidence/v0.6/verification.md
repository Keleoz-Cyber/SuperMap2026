# v0.6 专业建模增强发布候选验证证据

> 验证日期：2026-07-26/27。分支 `feat/v0.6-professional-modeling`，基线已发布 v0.5.0（merge `d37eb94`）。
> 本文分三层：便携 CI 证据、本机私有数据回归、真实浏览器彩排。所有数字为当场实测。

## 1. 便携 CI 证据（无私有数据）

| 命令 | 退出码 | 实测结果 |
|---|---:|---|
| `python -m pip install -e ".[api,test]"` | 0 | geomodeling-platform 0.6.0 |
| `python -m pytest -q` | 0 | **1153 passed**（197.6s） |
| `python -m pytest -q -m "not local_data"` | 0 | **1124 passed**, 29 deselected |
| `npm --prefix web ci` | 0 | 198 packages |
| `npm --prefix web run test:unit` | 0 | **97 passed**（9 文件） |
| `npm --prefix web run type-check` | 0 | vue-tsc 无错误 |
| `npm --prefix web run build` | 0 | built in 9.40s |
| `npm --prefix web run test:e2e`（Mock） | 0 | **4 passed** |
| `npm --prefix web run test:e2e:live`（CI 同款隔离 env） | 0 | **3 passed**（26.3s，无 uvicorn 残留） |
| `git diff --check origin/main...HEAD` | 0 | 无空白错误 |
| `python -m pytest tests/test_v06_ci_contract.py -q` | 0 | 7 passed（三 job 锁定） |

已知 flake（非本分支引入）：`test_distinct_configs_create_separate_snapshots`（同时间戳排序不定），本次全量未复现。

合成结构验收（`test_professional_synthetic_structures.py`，8 测试）：2D 30° 伸长场（真值变程比 3.0，实测方位 30° 精确命中、比 2.84/3.31）；3D 方位 60°/倾角 0°场（真值比 3.0/2.0，实测比 1.97/2.14）；各向同性对照无强方向宣称（经验判据 0.183 < 0.25 容差）；异常连通区计数与支持度量精确断言；人工确认与 legacy 指标有差异（不宣称普适必胜）。

## 2. 本机私有数据回归（`local_data`）

- `python -m pytest -q -m "local_data"` → **29 passed**。
- 微震黄金回归：22 DAT / 66,880 bytes；2,006/2,005/80/1,925/1,911；两个黄金 SHA-256 与钉值一致；22 个 DAT 处理前后 SHA-256 全部不变。

## 3. 真实微震专业流程（CLI + 全新数据目录）

- `import-case`：计数 2,006/2,005/80/1,925/1,911；golden_passed；standardized 1,911 行。
- `professional diagnose`：点对 1,825,005 → 分层抽样 50,000（采样率 2.74%，种子由数据 SHA-256+配置派生）；best_model=gaussian（weighted_sse 最优）。
- `professional confirm`（spherical + 保持各向同性 + note）：不可变快照 + 指纹。
- IDW 专业实验（邻域 800³）：run succeeded，RMSE **0.24799** / MAE 0.19436 / R² **0.86557** / coverage 99.84%（OOF 1908/1911）；经验误差覆盖率 94.02%。
- Kriging 专业实验（确认快照，spherical 自动候选）：RMSE **0.27456** / R² **0.83685** / 值域 [0.15, 3.081]；原生标准差范围 [0.206, 0.973]。
- `extract-anomalies`（高值阈值）：连通区 2（47 节点）。
- `compare`（IDW vs Kriging）：compatible=true，common_valid=1908，指标差同口径重算。
- CLI 八份 JSON 输出绝对路径扫描：零命中。

### 数值病态如实登记

诊断 best_model=**gaussian** 的确认在真实微震数据上产生 Kriging 数值爆炸（nugget≈0 + 高斯近零滞后平坦 + 密集垂向采样 → RMSE 204,916、值域 ±10⁷ 级）；平台如实上报指标并保留失败证据，不拦截模型选择。spherical 确认同流程数值稳定（RMSE 0.2746）。边界：平台不替用户裁决模型适用性，确认前必须人工审阅拟合证据——这正是人工确认设计的本意。

## 4. 真实浏览器彩排（uvicorn 单进程 + 全新 `GEOMODELING_DATA_DIR`，真实 22 DAT）

截图在 `docs/evidence/v0.6/v06-01..11*.png`（无个人路径出镜）。

1. 导入 22 真实 DAT（201，mapped；2,006/2,005/1/80/1,925/1,911），质量门禁 1 条 EXTREME_VALUES 警告确认后放行。
2. **诊断工作台**（v06-01）：点对 50,000/1,825,005（2.7%）、经验半变异函数图（三模型拟合线）、方向系列（0°/90°/垂向）、12 bin 逐行点对数、3 个各向异性候选（含稳定性警告）。
3. **人工确认**（v06-02）：不可变确认快照 90c5fd33（spherical + 保持各向同性 + note 说明不采用病态 gaussian）。
4. **专业实验表单**（v06-03）：确认快照联动、旋转椭球邻域（半径/方位角/扇区）、经验不确定性控件。
5. **IDW 专业实验**（v06-04）：邻域 800³，RMSE **0.248** / R² **0.866** / 覆盖率 **99.8%**（1908）。
6. **Kriging 专业实验**（v06-09）：确认 + 邻域 800³，RMSE **0.275** / R² **0.834** / 覆盖率 **99.8%**（1908）。
7. **专业分析台**（v06-05）：能力矩阵（IDW 的 native_kriging_std=not_applicable）、参数来源区分（fold_training_subsets vs final_full_data_fit）、折分检查（5 折无泄漏、折 0 训练 1562/验证 349、残差散点）、OOF 1911/1911。
8. **经验误差尺度图层**（v06-06）：独立图例值域 0.046~0.817（与预测值图例分开）。
9. **Kriging 标准差图层**（v06-10）：独立图例值域 0.206~0.973，1214/1331 有效、1199 个互异值。
10. **异常提取**（v06-07）：高值阈值 2.0，预览 797 节点 → 保存提取 b2154d6c（1 连通区、值域 2.0017~2.9686、触边界标记）；Kriging 成果另存 2342a687（阈值 2.2，721 节点）。
11. **双候选比较**（v06-08）：同实验两 IDW 候选（power 2/3），比较指纹 + 成对公共有效 1908 + 指标差（ΔRMSE 0.00031）+ 场差摘要（1214 节点）。
12. **证据导出**（v06-11）：Kriging 成果 ZIP **29 项** = 标准 7 + domain_evidence 7 + professional 15（诊断/方向变异函数/拟合模型/确认快照/邻域/折分/OOF/残差摘要/经验误差元数据/原生标准差元数据/异常提取/manifest），manifest 含 professional 节（capabilities/confirmation_id/diagnosis_id/逐文件哈希）。

## 5. 历史回归

- `demo-check`（exit 0，warning）：0 阻断；7 PASSED；3 optional WARNING（iServer 离线）。
- `run-all`（exit 0）：电阻率 17,549/15,827/1,722；五模型 xy_mismatch=0；`baseline_passed=True`。
- `verify-supermap`（exit 0）：iServer 离线仅文件级证据，`dataset_verified=False`，未虚报。

## 6. 安全扫描

- `git status --short`：仅 `docs/evidence/v0.6/`（截图+本文）与 `.gitignore` 增补 `var/demo_v06/`。
- `git ls-files` 危险模式（`.dat/.udbx/sqlite3/var/outputs/artifacts/.env`）：零命中。
- 凭据/本机路径扫描：文档与代码零命中；CLI 输出零命中。

## 7. 已知边界

- iServer 全程离线（契约内降级）；通用成果发布仍 `manual_required`。
- gaussian 自动候选在密集垂向采样数据上可能病态（如实登记，人工确认须审阅拟合证据）。
- 排行榜专业参数（anisotropy/neighborhood 嵌套对象）在表格中显示为 `[object Object]`（仅展示层，参数与指纹正确）。
- 比较面板当前列出同实验候选；跨实验比较有后端与 CLI 支撑（实测 compatible=true）。
- 微震 XY 为局部工程坐标（非 EPSG）；z_scale 为实验参数；不做自动地质解释、置信区间、预测预警。
