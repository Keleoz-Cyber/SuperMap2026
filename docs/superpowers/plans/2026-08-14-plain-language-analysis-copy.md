# Plain-Language Analysis Copy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把系统中面向用户的分析文案改成自然、具体、可行动的中文，同时保持现有数值、规则和安全限制不变。

**Architecture:** 后端继续生成结构化研判字段，前端将这些字段组合成因属性而异的自然叙述卡。首页、分析中心和模型评估只改显示语言；计算合同和接口字段不变。

**Tech Stack:** Python 3.12、Pydantic、Vue 3、TypeScript、Vitest、Playwright、pytest

---

### Task 1: 后端专业研判文案

**Files:**
- Modify: `tests/test_geological_interpretation.py`
- Modify: `src/geomodeling/platform/geological_interpretation.py`

- [ ] **Step 1: 先把测试改成自然语言期望**

断言应覆盖“优先查看”“模型覆盖”“现场复核”等自然表述，并拒绝“网格支持体积”“探索性解释”“证据边界”。

- [ ] **Step 2: 运行测试确认旧文案失败**

Run: `python -m pytest tests/test_geological_interpretation.py -q`

Expected: 文案断言失败，数值和卡片数量断言仍通过。

- [ ] **Step 3: 改写规则文案**

保留 `DomainInterpretationCard` 字段和 `RULE_VERSION`；只改 `_component_summary()`、`_rule_copy()`、overview 和 limitation 文本。不同属性分别使用钻孔/水文、测线/岩性、通风/抽采等具体动作。

- [ ] **Step 4: 运行后端相关测试**

Run: `python -m pytest tests/test_geological_interpretation.py tests/test_result_analysis.py tests/test_result_analysis_api.py -q`

Expected: PASS。

### Task 2: 成果页自然叙述卡

**Files:**
- Modify: `web/src/components/results/__tests__/ResultInterpretationPanel.spec.ts`
- Modify: `web/src/components/results/ResultInterpretationPanel.vue`
- Modify: `web/src/components/results/__tests__/ResultAnalysisWorkbench.spec.ts`

- [ ] **Step 1: 写入失败的界面断言**

断言主卡显示连续叙述、具体动作和“注意”，且不出现固定栏目“事实 / 可能解释 / 潜在影响 / 建议核查”及“技术证据与模型口径”。

- [ ] **Step 2: 运行组件测试确认失败**

Run: `npm --prefix web run test:unit -- ResultInterpretationPanel.spec.ts ResultAnalysisWorkbench.spec.ts`

Expected: 旧栏目名导致 FAIL。

- [ ] **Step 3: 重组卡片显示**

正文将 `possible_interpretations` 与 `potential_impacts` 连成自然段；动作显示为卡片底部的“建议：……”；限制显示为“注意：……”。折叠区改名“计算说明”，可信度徽标 `exploratory` 改成“建议复核”。

- [ ] **Step 4: 运行组件测试**

Run: `npm --prefix web run test:unit -- ResultInterpretationPanel.spec.ts ResultAnalysisWorkbench.spec.ts`

Expected: PASS。

### Task 3: 其余分析页面去汇报腔

**Files:**
- Modify: `web/src/domain/findings.ts`
- Modify: `web/src/components/home/CommandCenterEvidence.vue`
- Modify: `web/src/views/AnalysisCenterView.vue`
- Modify: `web/src/components/analysis/SpatialFeaturePanel.vue`
- Modify: `web/src/views/ProfessionalAnalysisView.vue`
- Modify: `web/src/components/results/AIAssistedReview.vue`
- Modify: `web/src/views/__tests__/HomeView.spec.ts`
- Modify: `web/src/components/home/__tests__/CommandCenterEvidence.spec.ts`
- Modify: `web/src/components/analysis/__tests__/analysisPanels.spec.ts`
- Modify: `web/src/components/analysis/__tests__/AnalysisCenterView.spec.ts`
- Modify: `web/src/components/professional/__tests__/ProfessionalAnalysisView.spec.ts`
- Modify: `web/src/components/results/__tests__/AIAssistedReview.spec.ts`

- [ ] **Step 1: 更新可见文案断言**

首页用“高值/低值区域占比”，分析中心用“怎么算的”，模型评估用“在相同数据和分组方式下比较”，AI 区用“注意事项”；断言主阅读区不显示“口径”“证据边界”“探索性网格支持”。

- [ ] **Step 2: 运行相关测试确认失败**

Run: `npm --prefix web run test:unit -- analysisPanels.spec.ts AnalysisCenterView.spec.ts AIAssistedReview.spec.ts ProfessionalAnalysisView.spec.ts HomeView.spec.ts`

Expected: 旧文案断言或新禁词断言 FAIL。

- [ ] **Step 3: 改写用户可见字符串**

只替换展示字符串，不改 API 类型、统计公式和判定条件；必要技术词移入折叠区。

- [ ] **Step 4: 运行前端单元测试与构建**

Run: `npm --prefix web run test:unit`

Run: `npm --prefix web run type-check`

Run: `npm --prefix web run build`

Expected: 全部 PASS。

### Task 4: 实际页面核验

**Files:**
- Modify: `web/e2e/result-analysis.spec.ts`

- [ ] **Step 1: 更新成果页浏览器断言**

浏览器测试应看到“地质研判”“建议复核”“计算说明”，且主卡不出现四段式栏目。

- [ ] **Step 2: 运行成果页 E2E**

Run: `npm --prefix web run test:e2e -- result-analysis.spec.ts`

Expected: PASS。

- [ ] **Step 3: 重启 8000 并读取真实分析摘要**

使用 `GEOMODELING_DATA_DIR=var/demo_v041` 启动当前代码，确认 `/api/health` 为 `0.9.2`，微震官方成果返回专业研判卡，首页和成果页可以打开。

- [ ] **Step 4: 最终检查**

Run: `git diff --check`

Run: `rg -n "证据边界|探索性网格支持口径|技术证据与模型口径" web/src src/geomodeling/platform/geological_interpretation.py`

Expected: 用户可见区域无命中；内部注释或合同术语不纳入本次改写。
