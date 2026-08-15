# Geological Interpretation Workbench Implementation Plan


**Goal:** 将电阻率、微震速度和瓦斯成果的高低异常转换为可定位、可追溯、带专业边界的地质研判卡，并保持通用数据安全降级。

**Architecture:** 扩展既有成果分析摘要而不新增计费或写接口。后端从同一成果网格提取高/低值连通区，经独立版本化规则模块生成 `domain_interpretation`；前端只渲染合同并将卡片空间目标与现有三维标注协议联动。

**Tech Stack:** Python 3.12、Pydantic、NumPy、FastAPI、Vue 3、TypeScript、Vitest、Playwright、SuperMap 三维渲染协议。

---

## 文件结构

- 创建 `src/geomodeling/platform/geological_interpretation.py`：领域识别、规则库和解释卡生成。
- 修改 `src/geomodeling/platform/result_analysis_contracts.py`：高低组件及领域解释 DTO。
- 修改 `src/geomodeling/platform/result_analysis.py`：低值连通区提取与解释装配。
- 修改 `web/src/api/types.ts`：与后端逐字段一致的前端合同。
- 修改 `web/src/components/results/ResultInterpretationPanel.vue`：地质研判总览、卡片、证据和边界。
- 修改 `web/src/components/results/ResultAnalysisWorkbench.vue`：领域化标签与窄屏研判工作区。
- 修改 `web/src/views/ResultWorkbenchView.vue`、`web/src/components/rendering/NativeVolumePanel.vue`：高低异常三维双向联动。
- 修改 `web/src/mocks/platformDemo.ts`：官方案例合同 Mock。
- 新增/修改对应 Python、Vitest、Playwright 测试。

### Task 1：严格合同与规则库

**Files:**
- Create: `src/geomodeling/platform/geological_interpretation.py`
- Modify: `src/geomodeling/platform/result_analysis_contracts.py`
- Test: `tests/test_geological_interpretation.py`

- [ ] **Step 1: 写失败测试**

```python
def test_resistivity_low_component_is_exploratory_and_bounded():
    result = build_domain_interpretation(
        variable_name="RHO", variable_unit="Ω·m",
        high_components=high_components, low_components=low_components,
    )
    assert result.profile == "resistivity"
    assert result.cards[0].direction == "low"
    assert result.cards[0].confidence == "exploratory"
    assert "不能直接认定" in "".join(result.cards[0].limitations)
```

- [ ] **Step 2: 确认失败**

Run: `python -m pytest tests/test_geological_interpretation.py -q`

Expected: FAIL because the module and DTO do not exist.

- [ ] **Step 3: 最小实现**

实现 `resolve_domain_profile()` 和 `build_domain_interpretation()`；规则只接受精确变量/单位组合，输出 `rule_version="geological_interpretation.v1"`、`exploratory` 可信等级、专业解释、影响、建议和禁止声明边界。`generic_3d` 返回 `not_applicable` 且无专业卡。

- [ ] **Step 4: 运行规则测试**

Run: `python -m pytest tests/test_geological_interpretation.py -q`

Expected: PASS for resistivity, microseismic velocity, gas and generic fallback.

### Task 2：高低异常提取与成果摘要

**Files:**
- Modify: `src/geomodeling/platform/result_analysis.py`
- Modify: `src/geomodeling/platform/result_analysis_contracts.py`
- Modify: `src/geomodeling/api/routes/result_analysis.py`
- Test: `tests/test_result_analysis.py`
- Test: `tests/test_result_analysis_api.py`

- [ ] **Step 1: 写失败测试**

```python
summary = analyze_result_grid(
    grid,
    result_id="result-rho",
    grid_sha256="a" * 64,
    variable_name="RHO",
    variable_unit="Ω·m",
)
assert summary.components_preview.rows[0].direction == "high"
assert summary.low_components_preview.rows[0].direction == "low"
assert {row.component_id for row in summary.components_preview.rows}.isdisjoint(
    {row.component_id for row in summary.low_components_preview.rows}
)
assert summary.domain_interpretation.profile == "resistivity"
```

- [ ] **Step 2: 确认失败**

Run: `python -m pytest tests/test_result_analysis.py tests/test_result_analysis_api.py -q`

Expected: FAIL on missing low preview and interpretation fields.

- [ ] **Step 3: 实现双向提取**

复用 `extract_anomalies`，分别以 `direction="high", threshold=p75` 与 `direction="low", threshold=p25` 运行。高值 ID 保持 `1..N`，低值 ID 使用 `1_000_000 + original_id`；低值标签使用 `低-A`。缓存键继续绑定成果哈希和参数，摘要计算版本升级为 `result_analysis.v2`，产品版本不变。

- [ ] **Step 4: 装配解释并通过测试**

Run: `python -m pytest tests/test_geological_interpretation.py tests/test_result_analysis.py tests/test_result_analysis_api.py -q`

Expected: PASS; old high-component ordering and values remain unchanged.

### Task 3：地质研判面板

**Files:**
- Modify: `web/src/api/types.ts`
- Modify: `web/src/components/results/ResultInterpretationPanel.vue`
- Test: `web/src/components/results/__tests__/ResultInterpretationPanel.spec.ts`

- [ ] **Step 1: 写失败组件测试**

```ts
expect(wrapper.get('[data-test="domain-overview"]').text()).toContain('低阻异常')
expect(wrapper.get('[data-test="domain-card-low-1000001"]').text()).toContain('可能解释')
expect(wrapper.text()).toContain('建议核查')
await wrapper.get('[data-test="domain-locate-1000001"]').trigger('click')
expect(wrapper.emitted('focus-component')).toEqual([[1000001]])
```

- [ ] **Step 2: 确认失败**

Run: `npm --prefix web run test:unit -- ResultInterpretationPanel.spec.ts`

Expected: FAIL because the domain sections are absent.

- [ ] **Step 3: 实现面板**

以 `domain_interpretation` 为唯一专业文案来源。顶部显示总体结论，卡片使用 `事实 / 可能解释 / 潜在影响 / 建议核查 / 证据边界` 五段；默认折叠详情，定位按钮发射现有 `focus-component`。原有成果概览、切片和模型内容收纳进“技术证据”折叠区。

- [ ] **Step 4: 通过组件和类型检查**

Run: `npm --prefix web run test:unit -- ResultInterpretationPanel.spec.ts && npm --prefix web run type-check`

Expected: PASS and no TypeScript errors.

### Task 4：三维双向联动与响应式工作区

**Files:**
- Modify: `web/src/views/ResultWorkbenchView.vue`
- Modify: `web/src/components/results/ResultAnalysisWorkbench.vue`
- Modify: `web/src/components/rendering/NativeVolumePanel.vue`
- Test: `web/src/components/results/__tests__/ResultAnalysisWorkbench.spec.ts`
- Test: `web/src/components/results/__tests__/ResultWorkbench.spec.ts`
- Test: `web/e2e/v090-responsive.spec.ts`

- [ ] **Step 1: 写失败测试**

```ts
expect(wrapper.get('[data-test="side-tab-rules"]').text()).toBe('地质研判')
await wrapper.get('[data-test="workbench-focus-judgement"]').trigger('click')
expect(wrapper.get('[data-test="result-analysis-side"]').isVisible()).toBe(true)
```

Playwright 在 1280×720 和 1366×768 下验证无横向溢出，点击“研判”后右栏可见，点击低值异常卡后对应三维标注获得聚焦状态。

- [ ] **Step 2: 确认失败**

Run: `npm --prefix web run test:unit -- ResultAnalysisWorkbench.spec.ts ResultWorkbench.spec.ts`

Expected: FAIL on missing judgement mode and low annotations.

- [ ] **Step 3: 实现联动与布局**

合并高低组件传入 `NativeVolumePanel`，低值使用冷色、高值使用属性强调色。增加 `judgement` 聚焦模式；小于 1440 px 时提供 `场景 / 控制 / 研判 / 分析`，不并排挤压场景。三维标注反选继续经全局唯一 component ID 回填卡片。

- [ ] **Step 4: 通过前端测试**

Run: `npm --prefix web run test:unit && npm --prefix web run type-check && npm --prefix web run build`

Expected: all unit tests pass, type check and production build exit 0.

### Task 5：Mock、浏览器验收与文档

**Files:**
- Modify: `web/src/mocks/platformDemo.ts`
- Modify: `web/e2e/result-analysis.spec.ts`
- Modify: `web/e2e/v090-responsive.spec.ts`
- Modify: `README.md`
- Modify: `docs/project-guide.md`

- [ ] **Step 1: 更新三个官方 Mock**

为电阻率、微震速度和瓦斯结果摘要提供 `low_components_preview` 与 `domain_interpretation`；通用夹具提供 `not_applicable` 空卡，所有 Mock 与后端 DTO 逐字段一致。

- [ ] **Step 2: 浏览器验收**

Run: `npm --prefix web run test:e2e -- result-analysis.spec.ts v090-responsive.spec.ts`

Expected: all target tests pass at 1920×1080, 1366×768 and 1280×720.

- [ ] **Step 3: 全量回归**

Run: `python -m pytest -q tests/`

Run: `npm --prefix web run test:unit`

Run: `npm --prefix web run type-check`

Run: `npm --prefix web run build`

Expected: all commands exit 0; no product version file changes.

- [ ] **Step 4: 文档与提交**

记录地质解释规则、探索性边界、AI 角色和响应式入口。运行 `git diff --check` 与版本文件差异检查后提交，不创建标签或 Release。
