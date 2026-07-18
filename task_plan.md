# Task Plan: GeoModelingPlatform MVP

## Goal
Build a runnable, verifiable, traceable first-version MVP for underground resistivity 3D property simulation management, with data registration, contract validation, model/task status, metric recomputation, SuperMap result registration, tests, and delivery documentation.

## Current Phase
Phase 6

## Phases

### Phase 1: 资料与环境核验
- [x] Read all required project and reference files listed in `KIMI3_MASTER_PROMPT.md`
- [x] Inspect repository structure and existing handover package
- [x] Check local Python, Node.js, package managers, Git, and SuperMap-related availability
- [x] Record constraints, data facts, and open questions in `findings.md`
- **Status:** complete

### Phase 2: 架构与工程初始化
- [x] Compare 2-3 feasible technical architectures against MVP constraints
- [x] Choose and document the initial technology stack in `docs/decisions/`
- [x] Create source, test, config, docs, artifacts/outputs structure
- [x] Initialize project dependencies and local Git hygiene
- **Status:** complete

### Phase 3: 数据与指标闭环
- [x] Implement dataset registry with SHA-256, schema, ranges, duplicate XYZ, null checks
- [x] Implement data contract validation for standardized source, training, and validation data
- [x] Import existing prediction results with `-9999` NoData handling
- [x] Recompute quality metrics on the common valid subset and compare to baseline files
- [x] Add automated contract, metric, status, and regression tests
- **Status:** complete

### Phase 4: 应用界面与 SuperMap 成果管理
- [x] Build a usable analysis/UI entry for datasets, model configs, metrics, and result status
- [x] Implement SuperMap datasource/dataset/result registration and error evidence tracking
- [x] Detect empty results and failed tasks with integrity checks
- [x] Produce machine-readable metadata and human-readable reports
- **Status:** complete

### Phase 5: 验收与交付
- [x] Run fresh tests, build/start checks, and key metric recomputation
- [x] Update `docs/progress.md`, architecture docs, decisions, and unresolved issues
- [x] Deliver concise usage, verification, SuperMap boundary, and next-stage guidance
- **Status:** complete

### Phase 6: v0.1 验收加固与发布
- [x] Preserve the verified baseline in a separate commit on `feat/rho-mvp-v0.1-hardening`
- [x] Add SuperMap evidence levels and file-level `verify-supermap` reporting without claiming dataset-level verification
- [x] Add model task creation, uniqueness checks, config snapshots, and default/comparison selection rationale
- [x] Add view configuration registration, audit JSONL, structured issue list, and expanded reports
- [x] Split portable CI tests from local real-data regression tests and add GitHub Actions
- [x] Run final release verification, push branch, create PR, and inspect CI
- **Status:** complete

## Key Questions
1. What project files and handover documents already exist in the repository?
2. Which local runtimes and tools are available on this Windows machine?
3. What exact MVP acceptance items are listed in `开发交接包/01_需求与范围/MVP功能清单.md`?
4. What is the safest initial architecture for local Windows operation, reliable CSV/JSON validation, testing, and future SuperMap adapter integration?
5. Which real baseline metrics and tolerance rules must regression tests enforce?

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Use `task_plan.md`, `findings.md`, and `progress.md` as persistent working memory | Long task requires durable progress tracking across many tool calls |
| Treat `../超图杯资料` as read-only and write all derived outputs inside `GeoModelingPlatform` | Required by master prompt and protects original evidence |
| Use Python CLI + file-backed registry + generated reports for the MVP | Matches installed environment, keeps validation/metrics testable, and avoids premature web/desktop UI complexity |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| None yet | 1 |  |
| Duplicate `model_id` in SuperMap config caused failed isosurface record to overwrite formal voxel record in a `model_id -> record` dict | 1 | Added `select_supermap_result_for_model()` to prefer formal succeeded openable non-empty results and used it in CLI/tests |
| Missing `export_model_list_markdown` import caused `run-all` to fail during report export | 1 | Added the missing report function import and reran the failing end-to-end test |
| `ModelTaskRegistry.list()` tried to parse `_selection.json` as a model task | 1 | Skipped underscore-prefixed registry metadata files and added a regression test |

## Notes
- Re-read this plan before major architecture or implementation decisions.
- Log all errors immediately and avoid repeating failed actions without changing approach.
