# Two-Speed CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 普通提交只运行 3–5 分钟快速门，`v*` 标签和手工触发运行现有完整 CI。

**Architecture:** 保留单一 `.github/workflows/ci.yml` 和三个既有 job 身份。`portable-tests` 始终创建并按 `FULL_CI` 选择快速或全量 Python 命令；两个浏览器 job 仅在完整模式创建。

**Tech Stack:** GitHub Actions YAML、PowerShell、pytest、Vitest、Playwright。

---

### Task 1: 固定双速合同

**Files:**
- Create: `tests/test_two_speed_ci_contract.py`
- Modify: `tests/test_v05_ci_contract.py`
- Modify: `tests/test_v06_ci_contract.py`

- [ ] 写入测试，断言 `v*`/手工为完整模式、普通事件为快速模式，快速测试命令存在，发布三个 job 和完整命令保留。
- [ ] 运行 `python -m pytest tests/test_two_speed_ci_contract.py tests/test_v05_ci_contract.py tests/test_v06_ci_contract.py -q`，确认旧 YAML 红灯。

### Task 2: 实现双速工作流

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] 添加 push branches/tags、`FULL_CI` 表达式、快速/全量 Python 条件步骤，以及两个浏览器 job 的完整门条件。
- [ ] 运行 Task 1 测试，确认全部通过。
- [ ] 运行所有 CI 合同测试和 `git diff --check`。

### Task 3: 提交和实测 GitHub 快速门

**Files:**
- Modify: `docs/superpowers/plans/2026-08-14-two-speed-ci.md`

- [ ] 提交并推送 `main`。
- [ ] 读取新 GitHub run，确认仅 `portable-tests` 创建、执行快速 Python 步骤且总耗时明显低于原 18–20 分钟。
