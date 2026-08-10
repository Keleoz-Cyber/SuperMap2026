import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type { AnalysisSummaryResponse, ResultEvaluationSummary } from '../../../api/types'
import type { PresentationFinding } from '../../../domain/findings'
import ResultAnalysisWorkbench from '../ResultAnalysisWorkbench.vue'
import { RESULT_ANALYSIS_MOCK_3D, SLICE_ANALYSIS_MOCK } from '../../../mocks/resultAnalysisMock'

// v0.9.0 Task 9：成果与分析融合工作台合同（成果级分析版）。首屏同时包含
// 三维场景、成果级规则研判、成果网格证据带、模型评估摘要与溯源抽屉；
// 组件只组合不 fetch；数据集级证据只出现在「输入样本」标签下。

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
      evaluation: EVALUATION,
      analysis: RESULT_ANALYSIS_MOCK_3D,
      currentSlice: null,
      ...props,
    },
    slots: {
      scene: '<div data-test="slot-scene">三维场景</div>',
      evaluation: '<div data-test="slot-selection">正式选择面板</div>',
      provenance: '<div data-test="slot-export">导出与发布</div>',
    },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
}

describe('ResultAnalysisWorkbench', () => {
  it('first screen composes scene, result interpretation, evidence dock, model metrics and provenance', async () => {
    const wrapper = mountWorkbench()
    await flushPromises()
    expect(wrapper.get('[data-test="result-scene"]').text()).toContain('三维场景')
    // 成果级研判：后端发现与 A/B/C 组件
    expect(wrapper.get('[data-test="result-interpretation"]').text()).toContain('最大高值连通区为 A 区')
    expect(wrapper.find('[data-test="component-1"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="result-evidence-dock"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="result-grid-evidence"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="result-evaluation"]').text()).toContain('RMSE')
    expect(wrapper.get('[data-test="result-evaluation"]').text()).toContain('6.454')
    expect(wrapper.find('[data-test="provenance-drawer"]').exists()).toBe(true)
  })

  it('dataset-level findings live only under the input-sample dock tab', async () => {
    const wrapper = mountWorkbench()
    await flushPromises()
    // 输入样本证据明确标注，不混入成果级研判区
    expect(wrapper.get('[data-test="result-interpretation"]').text()).not.toContain('有效数据 96/100')
    await wrapper.get('[data-test="ge-tab-input"]').trigger('click')
    await flushPromises()
    const pane = wrapper.get('[data-test="ge-pane-input"]')
    expect(pane.text()).toContain('输入样本')
    expect(pane.text()).toContain('有效数据 96/100')
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

  it('provenance drawer expands to reveal export/provenance slot content', async () => {
    const wrapper = mountWorkbench()
    await flushPromises()
    expect(wrapper.find('.provenance-body').isVisible()).toBe(false)
    await wrapper.get('[data-test="provenance-toggle"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('.provenance-body').isVisible()).toBe(true)
    expect(wrapper.find('[data-test="slot-export"]').exists()).toBe(true)
  })

  it('model evaluation renders finite metrics only, never NaN', async () => {
    const wrapper = mountWorkbench()
    await flushPromises()
    const text = wrapper.get('[data-test="result-evaluation"]').text()
    expect(text).not.toContain('NaN')
    expect(text).not.toContain('undefined')
  })
})
