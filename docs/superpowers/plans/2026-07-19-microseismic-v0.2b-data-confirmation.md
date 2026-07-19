# Microseismic v0.2b Data Confirmation Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create one beginner-friendly Chinese Markdown guide that records microseismic v0.2b evidence, decisions, downstream gates, and the exact conditions for starting cleaning or 2D/3D interpolation.

**Architecture:** The deliverable is a single self-contained Markdown file organized from known facts to unresolved questions, evidence registration, gate decisions, and a glossary. It reads existing v0.2a contracts and reports as evidence but does not alter code, source data, configuration, or generated outputs.

**Tech Stack:** Markdown, PowerShell, ripgrep, Git

---

## File map

- Create: `docs/microseismic_v0.2b_data_confirmation.md` — the only user-facing confirmation guide and evidence register.
- Read: `docs/superpowers/specs/2026-07-19-microseismic-v0.2b-data-confirmation-design.md` — approved structure and acceptance criteria.
- Read: `docs/data/microseismic.md` — merged v0.2a facts, conflicts, and downstream gates.
- Read: `config/microseismic.yaml` — formal point membership, intervals, expected counts, and registered cleaning conflicts.
- Read: `docs/data/contracts.md` — data contract boundaries and null/NoData semantics.
- Read: `docs/status/current-status.md` — current blockers and the authorized next stage.
- Do not modify: `src/`, `tests/`, `config/`, `../超图杯资料/`, `outputs/`, or `artifacts/`.

## Spec coverage map

- 已确认事实、使用方式和安全边界：Task 1。
- 四张确认卡和固定决策状态：Task 2。
- 证据规则、证据登记表、决策状态总表和 v0.2b 启动门槛：Task 3。
- 面向非专业读者的术语解释、查找顺序和填写自检：Task 4。
- 验收标准与仓库卫生：Task 5。
- 非目标：所有任务均不得研究出新专业结论、修改原始资料、生成 XY/Z、清洗数据、运行微震插值、修改代码或配置、推送、合并、打标签或创建 Release。

### Task 1: Create the guide frame and fixed fact baseline

**Files:**
- Create: `docs/microseismic_v0.2b_data_confirmation.md`
- Reference: `docs/data/microseismic.md` (v0.2a verified facts and conflicts)
- Reference: `config/microseismic.yaml` (formal points, intervals, expected counts)
- Reference: `docs/data/contracts.md` (contract boundaries)

- [ ] **Step 1: Reconfirm the source anchors before writing**

Run:

```powershell
rg -n "2,006|2,005|W28|WL/2|823/818|823/819|3.59|3.99|linear interpolation|nearest 5 point IDW" docs/data/microseismic.md docs/data/contracts.md config/microseismic.yaml
```

Expected: matches show the 2,006/2,005/1 row-count chain, W28 exclusion, unconfirmed `WL/2(km)`, count conflict, and the two cleaning methods. Stop if the sources no longer agree with the approved design.

- [ ] **Step 2: Create the document header and usage boundary**

Create the file with this opening structure:

```markdown
# 微震 v0.2b 数据确认清单与证据登记

> 用途：帮助非专业使用者根据现有资料逐项确认 v0.2b 的数据条件。
> 本文档记录证据和决定，不替代原始数据、论文或资料提供者说明。

## 1. 怎么使用这份文档

1. 先阅读“已确认事实”，不要重复修改 v0.2a 已验证的数据事实。
2. 按四张确认卡查找资料，并把每条证据登记到统一证据表。
3. 只有证据足以形成可执行规则时，才把状态改为“已确认”。
4. 没有证据时保留“未确认”；存在矛盾时填写“存在冲突”。
5. 最后根据启动门槛更新下游阻断状态。

### 安全边界

- 原始 DAT、XLSX、PDF 和图片只读。
- 不根据示意图像素生成精确坐标或方位角。
- 不把 `WL/2(km)` 直接改名为深度或 Z。
- 不把无效值改成 0，也不覆盖原始记录。
- “审计通过”只说明已登记事实内部一致，不代表已经可以三维插值。
```

- [ ] **Step 3: Add the verified fact baseline**

Add a table headed `## 2. 已确认事实（不需要再次猜测）` with these exact facts and boundaries:

```markdown
| 编号 | 已确认事实 | 当前处理 |
|---|---|---|
| F-01 | 共有 22 个正式 DAT 文件，对应 22 个正式测点。 | 原始文件只读并登记 SHA-256。 |
| F-02 | 共有 2,006 条真实源记录，其中 2,005 条为有限数值，1 条为无效数值。 | 两种统计口径分别保留。 |
| F-03 | W8.dat 第 2 行的 Vx 原 token 为 `1.#QNAN0`。 | 保留原文并标记无效；不改 0、不删除、不自动填补。 |
| F-04 | 文件源记录 L1/L2/L3 为 823/819/364；有限数值为 822/819/364。 | 不移动记录迎合论文计数。 |
| F-05 | W28 没有正式 DAT，不属于正式 L3。 | 只作冲突登记；不进入累计距离、清洗或模型。 |
| F-06 | 当前只有一维沿线累计距离：L1=1150 m、L2=2305 m、L3=1455 m。 | 不把沿线距离当作 X/Y。 |
| F-07 | 当前没有可信的绝对 X/Y/Z、原点、方位角或 CRS。 | 二维/三维几何继续阻断。 |
```

- [ ] **Step 4: Add the initial gate overview**

Add `## 3. 当前阻断总览` with a beginner explanation and this table:

```markdown
| 下游工作 | 当前状态 | 主要原因 |
|---|---|---|
| 二维/三维几何重建 | 阻断 | 缺少原点、方向、坐标系和 Z 换算。 |
| 正式数据清洗 | 阻断 | 异常值比例和处理方法存在冲突。 |
| 微震空间插值 | 阻断 | 几何与 `WL/2(km)` 含义尚未确认。 |
| 证据整理与接口占位 | 可开展 | 不生成坐标、不清洗、不插值即可。 |
```

- [ ] **Step 5: Verify and commit the baseline**

Run:

```powershell
rg -n "F-01|F-07|2,006|1.#QNAN0|W28|L1=1150" docs/microseismic_v0.2b_data_confirmation.md
git diff --check
```

Expected: all fixed facts are present; `git diff --check` produces no output and exits 0.

Commit:

```powershell
git add docs/microseismic_v0.2b_data_confirmation.md
git commit -m "docs: start microseismic v0.2b confirmation guide"
```

### Task 2: Add the four beginner-friendly confirmation cards

**Files:**
- Modify: `docs/microseismic_v0.2b_data_confirmation.md`

- [ ] **Step 1: Add a reusable status rule before the cards**

Insert the following status definitions:

```markdown
### 统一状态写法

- **未确认**：没有足够证据。
- **部分确认**：知道一部分，但仍缺公式、方向、基准或适用范围。
- **存在冲突**：不同来源不能同时成立。
- **已确认**：证据已经形成可执行、可复现的规则。
- **不适用**：有证据证明本项目不需要该项。
```

- [ ] **Step 2: Add confirmation card A for `WL/2(km)`**

Add `## 4. 确认卡 A：WL/2(km) 的含义和 Z 换算`, including:

```markdown
### 大白话解释

源文件只告诉我们这一列叫 `WL/2(km)`。列名和单位不足以证明它就是深度；还需要知道它代表什么、正方向、换算公式以及 Z=0 在哪里。

### 需要找到的答案

- [ ] `WL` 的完整名称和物理含义。
- [ ] 为什么数值除以 2。
- [ ] 数值增大表示更深、更高，还是其他方向。
- [ ] 从该字段到深度（m）的完整公式。
- [ ] 从深度到项目 Z 的符号规则和参考面。
- [ ] Vx 的正式物理含义和单位。

### 最低合格证据

原始数据字典、采集/处理说明、作者书面说明或可复现原始脚本，至少一种明确写出定义；如果要生成 Z，还必须同时给出公式、方向和参考面。

### 当前登记

- 状态：**未确认**
- 证据编号：无
- 暂定处理：保持源字段原名；`derived_depth_m` 和 `derived_z_m` 继续为空。
- 解除阻断条件：定义、单位、方向、公式和参考面全部确认。
```

- [ ] **Step 3: Add confirmation card B for geometry**

Add `## 5. 确认卡 B：测线原点、方向和坐标系`, explaining that intervals locate points only along a line. Include checkboxes for each line's control point, point-order direction, azimuth convention/value, coordinate unit, CRS/EPSG or local coordinate definition, line intersections, and Z datum. Set the initial status to `未确认`, with the rule that the compressed line image is schematic evidence only.

Include this plain-language example:

```markdown
例如，知道 W1 到 W2 相距 150 m，只能说明两点之间的距离；如果不知道 W1 在哪里、W1→W2 朝哪个方向，就无法算出 W2 的 X/Y。
```

- [ ] **Step 4: Add confirmation card C for cleaning**

Add `## 6. 确认卡 C：异常值识别与填补`, with three separate definitions:

```markdown
- **无效值**：无法作为有限数字使用，例如 `1.#QNAN0`。
- **异常值**：能够解析为数字，但根据明确规则判断不可信。
- **填补值**：为了形成连续数据，按批准方法计算出的新值。
```

Add checkboxes for the 80-row list or reproducible detection rule, denominator, approved method, neighborhood definition, edge handling, raw-value retention, audit fields, version, and approver. Preserve both candidates—linear interpolation and nearest-five-point IDW—without selecting either one.

- [ ] **Step 5: Add confirmation card D for count conflict**

Add `## 7. 确认卡 D：论文计数与文件计数冲突`, showing this comparison:

```markdown
| 来源/口径 | L1 | L2 | L3 | 总数 |
|---|---:|---:|---:|---:|
| 论文表格 | 823 | 818 | 364 | 2,005 |
| DAT 真实源记录 | 823 | 819 | 364 | 2,006 |
| DAT 有限数值 | 822 | 819 | 364 | 2,005 |
```

Explain that matching totals do not prove the same rows were counted. Require an author explanation, original processing note/script, or record-level list before changing the formal input set.

- [ ] **Step 6: Verify all card components and commit**

Run:

```powershell
rg -n "确认卡 A|确认卡 B|确认卡 C|确认卡 D|大白话解释|最低合格证据|解除阻断条件|无效值|异常值|填补值" docs/microseismic_v0.2b_data_confirmation.md
git diff --check
```

Expected: four cards and all beginner explanation anchors are present; no whitespace errors.

Commit:

```powershell
git add docs/microseismic_v0.2b_data_confirmation.md
git commit -m "docs: add microseismic v0.2b confirmation cards"
```

### Task 3: Add the evidence register and decision gates

**Files:**
- Modify: `docs/microseismic_v0.2b_data_confirmation.md`

- [ ] **Step 1: Add evidence-grade definitions**

Add `## 8. 证据等级` with four levels:

```markdown
| 等级 | 含义 | 能否单独解除阻断 |
|---|---|---|
| A | 原始数据字典、坐标成果表、采集说明、作者书面确认或可复现原始脚本。 | 可以，但必须覆盖该问题所需全部字段。 |
| B | 论文正文或表格的直接陈述，但缺少公式、基准或逐记录明细。 | 通常不可以，只能部分确认。 |
| C | 示意图、文件名、数值形态或一般专业习惯。 | 不可以，只能提出假设。 |
| D | 没有可核验来源的个人推测。 | 不可以。 |
```

- [ ] **Step 2: Add one unified evidence register**

Add `## 9. 证据登记表` with instructions to assign IDs sequentially (`MS-E001`, `MS-E002`, ...), followed by this initially usable table:

```markdown
| 证据编号 | 对应确认卡 | 来源文件/人员 | 精确位置 | 原文或事实摘要 | 支持的结论 | 等级 | 是否冲突 | 备注 |
|---|---|---|---|---|---|---|---|---|
| MS-E001 | D | v0.2a 原始 DAT 审计 | 22 个 DAT 汇总 | 源记录为 823/819/364，共 2,006 条。 | 文件事实计数 | A | 是，与论文表格冲突 | 已由哈希保护的源文件复算 |
| MS-E002 | D | 论文计数表 | 登记页码和表号后补充 | 表格写为 823/818/364，共 2,005 条。 | 论文陈述计数 | B | 是，与 DAT 文件事实冲突 | 当前不据此移动记录 |
```

The phrase “登记页码和表号后补充” is an explicit evidence-collection instruction, not a hidden conclusion; it must remain paired with status `存在冲突`.

- [ ] **Step 3: Add the decision summary**

Add `## 10. 决策状态总表`:

```markdown
| 确认项 | 当前状态 | 已采用证据 | 尚缺内容 | 阻断对象 |
|---|---|---|---|---|
| A：`WL/2(km)` 和 Z | 未确认 | 无 | 定义、单位、方向、公式、参考面 | 深度/Z、空间插值 |
| B：测线几何和 CRS | 未确认 | 点间距仅支持一维距离 | 原点、方向、方位角、坐标系、交点、Z 基准 | 二维/三维几何、空间插值 |
| C：清洗规则 | 存在冲突 | 论文材料存在两种方法陈述 | 80 条明细/规则、比例口径、正式方法、邻域定义 | 正式清洗 |
| D：计数冲突 | 存在冲突 | MS-E001、MS-E002 | 权威解释或逐记录清单 | 正式输入集合确认 |
```

- [ ] **Step 4: Add exact v0.2b start gates**

Add `## 11. v0.2b 启动判定` with three categories: work allowed now, cleaning prerequisites, and geometry/interpolation prerequisites. Include checkboxes for every prerequisite from the approved design and this final rule:

```markdown
只要必需项仍为“未确认”“部分确认”或“存在冲突”，对应的 downstream gate 就必须保持阻断。审计验证通过不能代替这些专业数据条件。
```

- [ ] **Step 5: Verify decision consistency and commit**

Run:

```powershell
rg -n "MS-E001|MS-E002|未确认|部分确认|存在冲突|已确认|不适用|downstream gate|启动判定" docs/microseismic_v0.2b_data_confirmation.md
git diff --check
```

Expected: evidence IDs, all five status values, and the final gate rule are present; no whitespace errors.

Commit:

```powershell
git add docs/microseismic_v0.2b_data_confirmation.md
git commit -m "docs: add microseismic evidence register and start gates"
```

### Task 4: Add the glossary and practical search procedure

**Files:**
- Modify: `docs/microseismic_v0.2b_data_confirmation.md`

- [ ] **Step 1: Add the beginner glossary**

Add `## 12. 术语小词典`. Define each item in one to three sentences using this project as the example:

- 测线、测点、沿线累计距离；
- 原点、方位角；
- CRS/EPSG、本地坐标系；
- 高程、深度、Z；
- 无效值、异常值、缺失值；
- 线性插值、IDW；
- 阻断条件、可追溯性。

The definitions must explicitly distinguish:

```markdown
高程通常描述相对某个高程基准“有多高”，深度通常描述从某个参考面“向下多远”，Z 是软件中的竖直坐标。三者只有在参考面和正负方向明确后才能互相换算。
```

and:

```markdown
IDW 会让距离近的已知点权重更大，但“距离”必须先有明确的几何定义。当前微震资料没有可信三维坐标，因此不能直接把三维 IDW 当作已确定方案。
```

- [ ] **Step 2: Add a practical evidence-search order**

Add `## 13. 建议查找顺序` with this order:

1. Search the paper for exact field definitions, formulas, units, coordinate descriptions, cleaning sections, and count tables.
2. Search `点间距.xlsx` only for interval and label evidence; do not infer absolute geometry.
3. Search DAT headers and raw rows for field names and record facts; do not infer undocumented physical meaning.
4. Search any acquisition notes, data dictionaries, coordinate result tables, scripts, or project reports.
5. If still unresolved, prepare one concise question per missing item for the source provider.

For each discovery, instruct the user to register the page/table/cell/line immediately rather than relying on memory.

- [ ] **Step 3: Add a final self-check section**

Add `## 14. 填写完成后的自检` with checkboxes that verify:

- every adopted conclusion has at least one evidence ID;
- evidence location is exact enough for another person to find;
- conflicting evidence is not deleted;
- no schematic image is treated as a precise coordinate source;
- no unknown value is written as 0;
- raw records remain unchanged;
- downstream gate statuses match the decision table;
- unconfirmed items remain visibly unconfirmed.

- [ ] **Step 4: Verify glossary coverage and commit**

Run:

```powershell
rg -n "测线|沿线累计距离|方位角|CRS/EPSG|高程|深度|线性插值|IDW|可追溯性|建议查找顺序|填写完成后的自检" docs/microseismic_v0.2b_data_confirmation.md
git diff --check
```

Expected: every glossary and workflow anchor is present; no whitespace errors.

Commit:

```powershell
git add docs/microseismic_v0.2b_data_confirmation.md
git commit -m "docs: explain microseismic terms and evidence workflow"
```

### Task 5: Perform final document validation

**Files:**
- Verify: `docs/microseismic_v0.2b_data_confirmation.md`
- Verify: `docs/superpowers/specs/2026-07-19-microseismic-v0.2b-data-confirmation-design.md`

- [ ] **Step 1: Check required structure**

Run:

```powershell
$file = 'docs/microseismic_v0.2b_data_confirmation.md'
$required = @(
  '已确认事实', '当前阻断总览', '确认卡 A', '确认卡 B',
  '确认卡 C', '确认卡 D', '证据等级', '证据登记表',
  '决策状态总表', 'v0.2b 启动判定', '术语小词典',
  '建议查找顺序', '填写完成后的自检'
)
$text = Get-Content -Raw -LiteralPath $file
$missing = $required | Where-Object { -not $text.Contains($_) }
if ($missing) { Write-Error ("Missing sections: " + ($missing -join ', ')); exit 1 }
Write-Output 'required_sections=13 missing=0'
```

Expected: `required_sections=13 missing=0`, exit 0.

- [ ] **Step 2: Check prohibited claims and local paths**

Run:

```powershell
$file = 'docs/microseismic_v0.2b_data_confirmation.md'
$matches = rg -n "[A-Za-z]:\\|EPSG:[0-9]+|WL/2\(km\) 就是深度|W28 是正式测点|1.#QNAN0 = 0" $file
if ($LASTEXITCODE -eq 0) { $matches; exit 1 }
Write-Output 'prohibited_claims=0 absolute_paths=0'
```

Expected: `prohibited_claims=0 absolute_paths=0`, exit 0. If a match appears inside a safety warning, rewrite the warning so it does not resemble an adopted claim.

- [ ] **Step 3: Check status and evidence completeness**

Run:

```powershell
$file = 'docs/microseismic_v0.2b_data_confirmation.md'
$text = Get-Content -Raw -LiteralPath $file
$checks = @{
  status_values = @('未确认','部分确认','存在冲突','已确认','不适用')
  evidence_ids = @('MS-E001','MS-E002')
  fixed_facts = @('2,006','2,005','1.#QNAN0','823/819/364','W28')
}
$missing = foreach ($group in $checks.Keys) {
  foreach ($value in $checks[$group]) {
    if (-not $text.Contains($value)) { "$group:$value" }
  }
}
if ($missing) { Write-Error ($missing -join ', '); exit 1 }
Write-Output 'status_evidence_facts_check=passed'
```

Expected: `status_evidence_facts_check=passed`, exit 0.

- [ ] **Step 4: Check repository hygiene**

Run:

```powershell
git diff --check origin/main...HEAD
git status --short
git ls-files | Where-Object { $_ -match '(?i)(\.dat$|\.xlsx$|\.xls$|\.pdf$|\.jpg$|\.jpeg$|(^|/)(outputs|artifacts|logs)/)' }
```

Expected: `git diff --check` has no output; status is clean after commits; the tracked-risk-file query has no output.

- [ ] **Step 5: Review the final diff and report scope**

Run:

```powershell
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
git diff origin/main...HEAD -- docs/microseismic_v0.2b_data_confirmation.md
```

Expected: only the approved design, implementation plan, and confirmation guide are part of this documentation work; no source data, code, configuration, or generated output changes appear.

Report the file path, commits, validation outputs, current gate statuses, and the next evidence item the user should investigate first. Do not push, merge, tag, or create a Release unless separately requested.
