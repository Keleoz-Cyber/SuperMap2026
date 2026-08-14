import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type { AnalysisSummaryResponse, ResultEvaluationSummary } from '../../../api/types'
import type { PresentationFinding } from '../../../domain/findings'
import ResultAnalysisWorkbench from '../ResultAnalysisWorkbench.vue'
import { RESULT_ANALYSIS_MOCK_3D, SLICE_ANALYSIS_MOCK } from '../../../mocks/resultAnalysisMock'

// v0.9.0 V6：成果工作台一屏布局合同。三栏主舞台（工具/场景/研判）+
// 四标签证据窗；组合器不 fetch；调试身份只在数据溯源出现。

const chartInstances: Array<{ dispose: ReturnType<typeof vi.fn> }> = []
vi.mock('echarts/core', () => ({
  init: vi.fn(() => {
    const instance = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(), on: vi.fn() }
    chartInstances.push(instance)
    return instance
  }),
  use: vi.fn(),
}))
vi.mock('echarts/charts', () => ({ BarChart: {}, LineChart: {}, PieChart: {}, ScatterChart: {}, HeatmapChart: {} }))
vi.mock('echarts/components', () => ({
  GridComponent: {},
  TooltipComponent: {},
  LegendComponent: {},
  VisualMapComponent: {},
}))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

// AI 辅助面板桩：只保留 evidence ref 联动出口
const AIStub = {
  name: 'AIAssistedReview',
  emits: ['focus-evidence'],
  template:
    '<div data-test="ai-stub">' +
    '<button data-test="ai-stub-ref-component" @click="$emit(\'focus-evidence\', \'component-1\')" />' +
    '<button data-test="ai-stub-ref-depth" @click="$emit(\'focus-evidence\', \'depth_bin-2\')" />' +
    '<button data-test="ai-stub-ref-slice" @click="$emit(\'focus-evidence\', \'current_slice\')" />' +
    '</div>',
}

const FINDING: PresentationFinding = {
  id: 'quality',
  title: '数据质量',
  statement: '有效数据 96/100（96%）',
  evidence: ['重复坐标 0'],
  source: { datasetId: 'ds-1', sourceSha256: 'abc', calculationVersion: 'analysis.v1' },
  confidence: 'verified',
  limitations: ['质量口径来自数据版本质量报告'],
}

const SUMMARY: AnalysisSummaryResponse = {
  dataset_id: 'ds-1',
  case_id: 'c-1',
  analysis_profile: 'resistivity',
  profile_version: 1,
  variable: { name: 'RHO', unit: 'Ω·m' },
  quality: {
    row_count: 100,
    valid_count: 96,
    invalid_count: 4,
    duplicate_coordinate_count: 0,
    bounds: null,
  },
  statistics: null,
  modules: [],
  provenance: {
    source_sha256: 'abc',
    dataset_version: 1,
    generated_at: '2026-08-10T00:00:00+00:00',
    calculation_version: 'analysis.v1',
  },
}

const EVALUATION: ResultEvaluationSummary = {
  common_valid_count: 17547,
  candidate_valid_count: 17547,
  candidate_nodata_count: 0,
  total_count: 17547,
  coverage: 1,
  rmse: 6.454476,
  mae: 3.251899,
  r2: 0.923093,
  bias: -0.095026,
  enhanced_evidence_available: false,
}

function mountWorkbench(props: Record<string, unknown> = {}) {
  return mount(ResultAnalysisWorkbench, {
    props: {
      findings: [FINDING],
      summary: SUMMARY,
      residuals: null,
      datasetId: 'ds-1',
      resultId: 'r-1',
      analysis: RESULT_ANALYSIS_MOCK_3D,
      currentSlice: null,
      ...props,
    },
    slots: {
      scene: '<div data-test="slot-scene">三维场景</div>',
      evaluation: '<div data-test="slot-selection">正式选择面板</div>',
      provenance: '<div data-test="slot-export">导出与发布</div>',
    },
    global: { plugins: [ElementPlus], stubs: { AIAssistedReview: AIStub } },
    attachTo: document.body,
  })
}
void EVALUATION

describe('ResultAnalysisWorkbench（V6 一屏布局）', () => {
  it('main stage composes scene slot and analysis side; dock shows four tabs', async () => {
    const wrapper = mountWorkbench()
    await flushPromises()
    expect(wrapper.find('[data-test="v6-main-stage"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="result-scene"]').text()).toContain('三维场景')
    expect(wrapper.find('[data-test="result-analysis-side"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="result-interpretation"]').text()).toContain('最大高值连通区为 A 区')
    expect(wrapper.find('[data-test="result-evidence-dock"]').exists()).toBe(true)
    const tabs = wrapper.findAll('[data-test^="ge-tab-"]')
    expect(tabs.map((t) => t.text())).toEqual(['成果概览', '切片分析', '模型可信度', '数据与导出'])
  })

  it('uses geological judgement label and exposes a dedicated judgement focus mode', async () => {
    const analysis = structuredClone(RESULT_ANALYSIS_MOCK_3D) as typeof RESULT_ANALYSIS_MOCK_3D & {
      domain_interpretation: Record<string, unknown>
    }
    analysis.domain_interpretation = {
      rule_version: 'geological_interpretation.v1',
      profile: 'resistivity',
      panel_label: '地质研判',
      narrative_label: '地下电性结构',
      status: 'exploratory',
      overview: '低阻异常解释',
      cards: [],
      global_limitations: [],
    }
    const wrapper = mountWorkbench({ analysis })
    await flushPromises()

    expect(wrapper.get('[data-test="side-tab-rules"]').text()).toBe('地质研判')
    await wrapper.get('[data-test="workbench-focus-judgement"]').trigger('click')
    expect(wrapper.get('[data-test="result-analysis-workbench"]').classes()).toContain('focus-judgement')
    expect(wrapper.find('[data-test="result-analysis-side"]').exists()).toBe(true)
  })

  it('expands and collapses the evidence dock without remounting the scene', async () => {
    const wrapper = mountWorkbench()
    await flushPromises()
    const sceneElement = wrapper.get('[data-test="slot-scene"]').element
    const dock = wrapper.get('[data-test="result-evidence-dock"]')
    const toggle = wrapper.get('[data-test="evidence-dock-toggle"]')

    expect(dock.classes()).not.toContain('expanded')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(toggle.text()).toBe('展开分析')
    expect(dock.classes()).toContain('dock-overview')

    await toggle.trigger('click')
    expect(dock.classes()).toContain('expanded')
    expect(dock.classes()).toContain('is-transitioning')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(toggle.text()).toBe('收起分析')
    expect(wrapper.get('[data-test="slot-scene"]').element).toBe(sceneElement)

    await toggle.trigger('click')
    expect(dock.classes()).not.toContain('expanded')
    expect(toggle.attributes('aria-expanded')).toBe('false')

    await wrapper.get('[data-test="ge-tab-provenance"]').trigger('click')
    await flushPromises()
    expect(dock.classes()).toContain('dock-provenance')
    expect(dock.classes()).not.toContain('dock-overview')
  })

  it('场景 / 控制 / 分析切换只改变焦点，不重新挂载三维场景', async () => {
    const wrapper = mountWorkbench()
    await flushPromises()
    const sceneElement = wrapper.get('[data-test="slot-scene"]').element

    expect(wrapper.get('[data-test="workbench-focus-all"]').attributes('aria-pressed')).toBe('true')
    await wrapper.get('[data-test="workbench-focus-scene"]').trigger('click')
    expect(wrapper.get('[data-test="result-analysis-workbench"]').classes()).toContain('focus-scene')
    expect(wrapper.get('[data-test="slot-scene"]').element).toBe(sceneElement)

    await wrapper.get('[data-test="workbench-focus-controls"]').trigger('click')
    expect(wrapper.get('[data-test="result-analysis-workbench"]').classes()).toContain('focus-controls')
    expect(wrapper.get('[data-test="slot-scene"]').element).toBe(sceneElement)

    await wrapper.get('[data-test="workbench-focus-analysis"]').trigger('click')
    expect(wrapper.get('[data-test="result-analysis-workbench"]').classes()).toContain('focus-analysis')
    expect(wrapper.get('[data-test="slot-scene"]').element).toBe(sceneElement)
  })

  it('分析聚焦已占满内容区，不显示没有可见效果的展开按钮', async () => {
    const wrapper = mountWorkbench()
    await wrapper.get('[data-test="workbench-focus-analysis"]').trigger('click')
    expect(wrapper.find('[data-test="evidence-dock-toggle"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="result-evidence-dock"]').classes()).toContain('analysis-focus')
    await wrapper.get('[data-test="ge-tab-provenance"]').trigger('click')
    expect(wrapper.get('[data-test="ge-input-details"]').attributes('open')).toBeDefined()

    await wrapper.get('[data-test="workbench-focus-all"]').trigger('click')
    expect(wrapper.get('[data-test="ge-input-details"]').attributes('open')).toBeUndefined()
  })

  it('dataset-level findings live only under the provenance input-sample cell', async () => {
    const wrapper = mountWorkbench()
    await flushPromises()
    expect(wrapper.get('[data-test="result-interpretation"]').text()).not.toContain('有效数据 96/100')
    await wrapper.get('[data-test="ge-tab-provenance"]').trigger('click')
    await flushPromises()
    const pane = wrapper.get('[data-test="ge-pane-provenance"]')
    expect(pane.text()).toContain('输入样本')
    expect(pane.text()).toContain('有效数据 96/100')
    // 导出/发布内容迁入数据溯源标签
    expect(pane.find('[data-test="slot-export"]').exists()).toBe(true)
  })

  it('forwards component and depth-bin focus events from interpretation and dock', async () => {
    const wrapper = mountWorkbench()
    await flushPromises()
    await wrapper.get('[data-test="component-2"]').trigger('click')
    expect(wrapper.emitted('focus-component')).toEqual([[2]])
    await wrapper.get('[data-test="finding-locate-finding-dominant-depth"]').trigger('click')
    expect(wrapper.emitted('focus-depth-bin')).toEqual([[2]])
  })

  it('shows current-slice evidence shared with the 3D slice state', async () => {
    const wrapper = mountWorkbench({ currentSlice: SLICE_ANALYSIS_MOCK })
    await flushPromises()
    const slice = wrapper.get('[data-test="interpretation-slice"]')
    expect(slice.text()).toContain('Z')
    expect(slice.text()).toContain('-400')
    expect(slice.text()).toContain('有效 11')
  })

  it('analysis error shows typed state without stale numbers', async () => {
    const wrapper = mountWorkbench({
      analysis: null,
      analysisError: 'RESULT_NOT_MATERIALIZED：成果未物化',
    })
    await flushPromises()
    expect(wrapper.get('[data-test="interpretation-error"]').text()).toContain('RESULT_NOT_MATERIALIZED')
    expect(wrapper.find('[data-test="component-1"]').exists()).toBe(false)
  })

  it('evaluation slot renders formal selection inside analysis side', async () => {
    const wrapper = mountWorkbench()
    await flushPromises()
    expect(wrapper.get('[data-test="result-evaluation"]').find('[data-test="slot-selection"]').exists()).toBe(true)
  })

  it('rule/AI tab switch keeps rule analysis default; AI evidence refs link components, depth bins and dock tabs', async () => {
    const wrapper = mountWorkbench()
    await flushPromises()
    expect(wrapper.find('[data-test="result-interpretation"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="ai-stub"]').exists()).toBe(false)
    await wrapper.get('[data-test="side-tab-ai"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="result-interpretation"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="ai-stub"]').exists()).toBe(true)
    await wrapper.get('[data-test="ai-stub-ref-component"]').trigger('click')
    expect(wrapper.emitted('focus-component')).toEqual([[1]])
    await wrapper.get('[data-test="ai-stub-ref-depth"]').trigger('click')
    expect(wrapper.emitted('focus-depth-bin')).toEqual([[2]])
    await wrapper.get('[data-test="ai-stub-ref-slice"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="ge-pane-slices"]').exists()).toBe(true)
  })
})
