# GeoModelingPlatform Documentation Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the repository documentation into one current, Chinese-first documentation set and directly delete superseded, duplicated, and temporary documents after preserving their unique information.

**Architecture:** Treat the current code, tests, merged PR evidence, and accepted ADRs as authoritative. Build three focused data documents plus one current-status document, update the entry, architecture, and acceptance documents to link to them, then remove source documents whose unique content has been migrated. Keep all changes on a dedicated branch so every deletion remains recoverable through Git.

**Tech Stack:** Markdown, Git, PowerShell, Python 3.12, pytest, repository CLI.

---

## File Structure

The completed repository should use these documentation responsibilities:

- `README.md`: project entry, quick start, current capabilities, boundaries, and navigation.
- `docs/architecture.md`: implemented module boundaries and data flow.
- `docs/acceptance.md`: repeatable verification commands and evidence-level rules.
- `docs/data/contracts.md`: shared raw/derived data, manifest, NoData, traceability, and validation rules.
- `docs/data/resistivity.md`: resistivity v0.1 facts, model comparison, chosen result, and SuperMap evidence.
- `docs/data/microseismic.md`: microseismic v0.2a facts, three tables, W8/W28 handling, 1D geometry, conflicts, and downstream gates.
- `docs/status/current-status.md`: completed milestones, current blockers, and the next authorized work.
- `docs/decisions/0001-technology-stack.md`: retained accepted technology ADR.
- `docs/decisions/0002-supermap-evidence-levels.md`: retained evidence-level ADR.
- `docs/superpowers/specs/2026-07-19-microseismic-v0.2b-data-confirmation-design.md`: retained because it governs the next data-confirmation task.
- `tests/fixtures/README.md`: retained as fixture-specific operational documentation.

The consolidation design and this execution plan may be deleted in the final cleanup commit after all requirements have been transferred into the retained documentation and PR description.

### Task 1: Protect the Current State and Build the Inventory

**Files:**
- Read: every tracked `*.md` and `*.txt` file.
- Create locally only: `artifacts/document-consolidation/inventory.md`.
- Do not modify any tracked file in this task.

- [ ] **Step 1: Verify the starting state**

Run:

```powershell
git status --short --branch
git log -3 --oneline --decorate
git rev-parse HEAD
git rev-parse origin/main
```

Expected: branch `main`, clean worktree, and local `main` contains commits `1599c11` and `fd2391f` even if it is ahead of `origin/main`. Do not reset, rebase, discard, or force-push these commits.

- [ ] **Step 2: Create the work branch from the current local main**

Run:

```powershell
git switch -c chore/docs-consolidation-v0.2
```

Expected: new branch starts from the current local `main`, preserving both design commits.

- [ ] **Step 3: Enumerate the complete document scope**

Run:

```powershell
$files = rg --files -g '*.md' -g '*.txt' | Sort-Object
$files
```

Expected: includes root documents, `docs/`, `开发交接包/`, and `tests/fixtures/README.md`; does not enumerate anything under `../超图杯资料`.

- [ ] **Step 4: Read every scoped document completely**

For each path from Step 3, read the complete file, not only headings or the first page. Record in `artifacts/document-consolidation/inventory.md`:

```markdown
| path | class | current purpose | unique information | destination | deletion reason |
|---|---|---|---|---|---|
| README.md | KEEP | project entry | install and CLI entry | README.md | |
```

Use only `KEEP`, `MERGE`, or `DELETE` in the class column. `MERGE` and `DELETE` rows must name the retained destination. The artifacts directory is ignored and must not be committed.

- [ ] **Step 5: Compare documentation statements with code and tests**

Check at minimum:

```powershell
rg -n "17549|15827|1722|1481|241|2006|2005|1.#QNAN0|W28|dataset_verified|WL/2" . --glob '*.md' --glob '!artifacts/**' --glob '!outputs/**'
rg -n "@app.command|microseismic|run-all|verify-supermap|select-models" src tests
```

When statements conflict, use this priority: current tested code; merged PR evidence and accepted ADR; current audit report; handover documents; old prompts and temporary plans. Preserve unresolved source conflicts instead of silently selecting one side.

### Task 2: Create the Canonical Data Documentation

**Files:**
- Create: `docs/data/contracts.md`.
- Create: `docs/data/resistivity.md`.
- Create: `docs/data/microseismic.md`.
- Source material: `开发交接包/03_数据规范/数据契约.md`, `开发交接包/05_SuperMap验证/已知问题.md`, `docs/progress.md`, `progress.md`, `findings.md`, `KIMI3_MASTER_PROMPT.md`, `KIMI3_MICROSEISMIC_V0.2A_PROMPT.md`, current code and tests.

- [ ] **Step 1: Create `docs/data/contracts.md`**

Write these exact sections and populate them only with currently supported facts:

```markdown
# 数据契约

## 1. 总原则
## 2. 原始资料与派生数据分层
## 3. 来源清单与 SHA-256
## 4. 电阻率标准表与预测表
## 5. 微震三张标准表
## 6. 无效值、NoData 与空值语义
## 7. 坐标、Z 和单位确认规则
## 8. 模型任务与成果登记
## 9. 版本、追溯和禁止事项
```

Required content:

- original materials are read-only and never overwritten;
- manifest paths are stable relative paths and hashes protect source identity;
- resistivity standardized/training/validation tables remain separate;
- `-9999` is NoData and never a measured value;
- microseismic standard tables are `survey_lines.csv`, `survey_points.csv`, and `velocity_samples.csv`;
- invalid raw tokens remain traceable and are not silently converted to zero;
- unknown XY/Z, sequence, or cumulative values remain null rather than fabricated zero values;
- formal model IDs use the validated safe-character contract;
- all derived values retain source, method, version, and inclusion flags.

- [ ] **Step 2: Create `docs/data/resistivity.md`**

Use these sections:

```markdown
# 地下电阻率数据与成果

## 1. 当前结论
## 2. 数据基线
## 3. 训练与验证隔离
## 4. 五种模型验证
## 5. 正式模型选择
## 6. SuperMap 成果证据
## 7. 已知限制
## 8. 复现命令
```

Record the verified facts:

- standardized/training/validation rows are 17,549/15,827/1,722;
- training and validation spatial-column overlap is 0;
- each model prediction has 1,722 rows, 1,481 valid values, 241 NoData values, and 0 XY mismatch;
- `RHO_KRIG_FINAL_20M_40` is the only formal SuperMap result;
- `dataset_verified=False` remains explicit;
- full voxel and horizontal slice evidence is manual evidence;
- vertical slice is unverified and native isosurfaces failed/empty;
- RHO physical unit remains unconfirmed unless a direct source is added;
- include the actual `geomodeling run-all` and `geomodeling verify-supermap` commands.

Copy the current recomputed model metrics from the existing verified documentation or generated report. Do not invent new precision or rerank models using memory.

- [ ] **Step 3: Create `docs/data/microseismic.md`**

Use these sections:

```markdown
# 微震数据审计与标准化

## 1. 当前结论
## 2. 原始文件读取
## 3. 记录数口径
## 4. W8 特殊值
## 5. 测线、测点与 W28
## 6. 三张标准表
## 7. 一维累计距离
## 8. 来源冲突
## 9. Downstream gates
## 10. v0.2b 前置确认
## 11. 复现命令
```

Required facts:

- 22 DAT files, 66,880 bytes, 22 trailing NUL pseudo-lines;
- 2,006 source records, 2,005 finite records, 1 invalid record;
- source counts L1/L2/L3 are 823/819/364 and finite counts are 822/819/364;
- `W8.dat` source line 2 preserves `1.#QNAN0` and is never replaced by 0 or silently imputed;
- 22 formal points plus W28 as conflict-only registration;
- W28 has null sequence and cumulative distance, retains conflict interval 350 m, and enters no model or cleaning set;
- cumulative maxima are L1=1,150 m, L2=2,305 m, L3=1,455 m;
- no X/Y/Z is generated;
- preserve the paper/file count conflict and cleaning-method/rate conflicts;
- display `geometry_blocked=True`, `cleaning_blocked=True`, and `interpolation_blocked=True` with their issue codes;
- link to the retained v0.2b confirmation design.

- [ ] **Step 4: Review data documents against tested constants**

Run:

```powershell
rg -n "17,549|15,827|1,722|1,481|241|2,006|2,005|1.#QNAN0|1,150|2,305|1,455|dataset_verified=False" docs/data
```

Expected: every required value appears in the appropriate canonical file, with commas used consistently for human-readable counts.

- [ ] **Step 5: Commit the canonical data documents**

Run:

```powershell
git add docs/data/contracts.md docs/data/resistivity.md docs/data/microseismic.md
git diff --cached --check
git commit -m "docs: consolidate resistivity and microseismic data guidance"
```

Expected: one documentation-only commit.

### Task 3: Rewrite the Entry, Architecture, Acceptance, and Status Documents

**Files:**
- Modify: `README.md`.
- Modify: `docs/architecture.md`.
- Modify: `docs/acceptance.md`.
- Create: `docs/status/current-status.md`.
- Read: current CLI help, source package tree, tests, ADRs, and the three files created in Task 2.

- [ ] **Step 1: Rewrite `README.md` as the only project entry**

Use this structure:

```markdown
# GeoModelingPlatform

## 项目目标
## 当前能力
## 当前边界
## 安装
## 快速验证
## CLI 入口
## 文档导航
## 原始资料保护
```

State that v0.1.0 is the released resistivity baseline and current `main` additionally contains the merged microseismic v0.2a audit foundation. Do not imply that microseismic 3D interpolation, gas integration, or DSI-like development is complete.

- [ ] **Step 2: Update `docs/architecture.md` to match the current package**

Keep the existing core module descriptions and add the implemented `geomodeling.microseismic` boundary: config, inventory, parser, geometry, contracts, issues, reports, service, and CLI. Separate implemented modules from future gas and DSI-like interfaces. Remove statements contradicted by current code.

- [ ] **Step 3: Update `docs/acceptance.md` from v0.1-only to current-main acceptance**

Include exact commands:

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
python -m pytest -q -m "not local_data"
python -m pytest -q -m local_data
geomodeling run-all -o outputs/release_verify
geomodeling microseismic run-audit --config config/microseismic.yaml -o outputs/microseismic_verify
geomodeling verify-supermap -o outputs/release_verify
```

Explain that audit validation passing does not clear downstream geometry, cleaning, or interpolation gates. Keep `dataset_verified=False` explicit.

- [ ] **Step 4: Create `docs/status/current-status.md`**

Use this structure:

```markdown
# 当前开发状态

## 已发布基线
## 已合并但未发布
## 当前正式成果
## 当前阻断
## 下一阶段顺序
## 明确未实现
```

Required state:

- v0.1.0 is the released resistivity baseline;
- microseismic v0.2a is merged but has no new tag or Release;
- the next activity is data confirmation, not 3D interpolation code;
- list WL/2 meaning, origin/azimuth/CRS, cleaning rule, and count conflict as confirmation items;
- list gas, DSI-like, vertical slice, native isosurface, and dataset-level SuperMap API verification as not implemented or unverified.

- [ ] **Step 5: Verify navigation targets exist**

Every local Markdown link in `README.md`, `docs/architecture.md`, `docs/acceptance.md`, and `docs/status/current-status.md` must target one of the retained files. Use repository-relative links and avoid absolute local machine paths.

- [ ] **Step 6: Commit the entry and current-state documents**

Run:

```powershell
git add README.md docs/architecture.md docs/acceptance.md docs/status/current-status.md
git diff --cached --check
git commit -m "docs: establish canonical project navigation and status"
```

Expected: one documentation-only commit.

### Task 4: Delete Superseded Documents and Repair References

**Files:**
- Delete after migration: `task_plan.md`.
- Delete after migration: `findings.md`.
- Delete after migration: `progress.md`.
- Delete after migration: `docs/progress.md`.
- Delete after migration: `KIMI3_MASTER_PROMPT.md`.
- Delete after migration: `KIMI3_MICROSEISMIC_V0.2A_PROMPT.md`.
- Delete after migration: all tracked Markdown files under `开发交接包/`, then remove empty directories.
- Delete after migration: `docs/superpowers/plans/2026-07-18-rho-mvp.md`.
- Delete at the end of execution: `docs/superpowers/specs/2026-07-19-document-consolidation-design.md` and this plan.
- Keep: both ADRs, the microseismic v0.2b confirmation design, and `tests/fixtures/README.md`.

- [ ] **Step 1: Complete the deletion audit before deleting**

For every deletion candidate, confirm its inventory row names a retained destination for every unique fact. If a fact has no destination, add it to the correct canonical document before continuing.

- [ ] **Step 2: Delete the superseded files with Git**

Use `git rm -- <exact path>` for tracked files. Do not use recursive wildcard deletion outside the repository. Before any directory-level removal, resolve the path and confirm it is under `GeoModelingPlatform`.

- [ ] **Step 3: Search for stale references**

Run:

```powershell
$deletedNames = @('task_plan.md','findings.md','progress.md','KIMI3_MASTER_PROMPT.md','KIMI3_MICROSEISMIC_V0.2A_PROMPT.md','开发交接包','2026-07-18-rho-mvp.md','2026-07-19-document-consolidation-design.md','2026-07-19-document-consolidation.md')
foreach ($name in $deletedNames) {
    rg -n --fixed-strings $name . --glob '!artifacts/**' --glob '!outputs/**'
}
```

Expected: no retained document links to or instructs readers to open a deleted file. Historical Git metadata does not need rewriting.

- [ ] **Step 4: Check the retained document set**

Run:

```powershell
rg --files -g '*.md' -g '*.txt' | Sort-Object
```

Expected retained set is limited to the canonical entry, architecture, acceptance, data, status, ADR, microseismic v0.2b design, and fixture documentation described in the File Structure section.

- [ ] **Step 5: Commit deletions and reference repairs**

Run:

```powershell
git add -A
git diff --cached --check
git commit -m "docs: remove superseded plans prompts and handover copies"
```

Expected: the commit contains only documentation deletions and documentation link repairs.

### Task 5: Run Full Verification and Publish an Open PR

**Files:**
- Inspect: complete diff from `origin/main` to `HEAD`.
- Do not modify code, tests, config, raw data, tags, or releases.

- [ ] **Step 1: Verify the diff is documentation-only**

Run:

```powershell
git diff --name-status origin/main...HEAD
git diff --check origin/main...HEAD
```

Expected: no files under `src/`, no Python test files, no YAML configuration, and no raw/source data changes. `git diff --check` has no output and exits 0.

- [ ] **Step 2: Run the full test suite**

Run:

```powershell
python -m pytest -q
```

Expected current baseline: 80 passed, unless the repository has legitimately added tests after this plan. Any failure blocks delivery.

- [ ] **Step 3: Run portable and local-real-data partitions**

Run:

```powershell
python -m pytest -q -m "not local_data"
python -m pytest -q -m local_data
```

Expected current baseline: 57 passed/23 deselected and 23 passed/57 deselected. Any reduction or failure requires investigation.

- [ ] **Step 4: Run resistivity and microseismic regressions**

Run:

```powershell
geomodeling run-all -o outputs/docs_consolidation_rho_verify
geomodeling microseismic run-audit --config config/microseismic.yaml -o outputs/docs_consolidation_micro_verify
```

Expected:

- resistivity baseline passes with 17,549/15,827/1,722 rows, 0 overlap, and five models each at 1,481 valid/241 NoData/0 XY mismatch;
- microseismic validation passes with 22 DAT, 2,006 source records, 2,005 valid numeric records, and 1 invalid numeric record.

- [ ] **Step 5: Validate all retained Markdown links**

Run this temporary, read-only checker from the repository root:

```powershell
@'
from pathlib import Path
import re

root = Path.cwd().resolve()
missing = []
for source in root.rglob("*.md"):
    if any(part in {".git", "outputs", "artifacts", ".pytest_cache"} for part in source.parts):
        continue
    text = source.read_text(encoding="utf-8")
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
        target = target.strip().split("#", 1)[0]
        if not target or "://" in target or target.startswith("#"):
            continue
        candidate = (source.parent / target).resolve()
        if not candidate.exists():
            missing.append((str(source.relative_to(root)), target))
print(f"missing_links={len(missing)}")
for item in missing:
    print(item)
raise SystemExit(1 if missing else 0)
'@ | python -
```

Expected: `missing_links=0`, exit 0.

- [ ] **Step 6: Check tracked-file safety**

Run:

```powershell
git ls-files | Where-Object { $_ -match '(?i)(\.dat$|\.xlsx?$|\.pdf$|\.jpe?g$|\.png$|\.udbx$|(^|/)(outputs|artifacts|logs)/|\.env$|\.pem$|\.key$)' }
```

Expected: no output.

- [ ] **Step 7: Review the final worktree and commit history**

Run:

```powershell
git status --short --branch
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
```

Expected: clean worktree and a small sequence of intentional documentation commits.

- [ ] **Step 8: Push and create the PR**

Push `chore/docs-consolidation-v0.2` and create an open, non-draft PR against `main`. Do not merge it, delete branches, create tags, or create a Release.

The PR body must include:

- target documentation structure;
- every deleted file and reason;
- destination of migrated unique information;
- verification commands and exact outcomes;
- explicit statement that `../超图杯资料`, source code, tests, config, and raw data were untouched;
- remaining unresolved product/data boundaries.

- [ ] **Step 9: Wait for CI and report**

Report branch, commits, PR URL/state, CI run IDs, retained document list, deleted document list with migration destinations, test results, regression results, link-check result, `git diff --check` result, tracked-file safety result, and all remaining boundaries. Keep the PR open for review.
