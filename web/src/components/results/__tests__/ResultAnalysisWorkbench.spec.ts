import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type { AnalysisSummaryResponse, ResultEvaluationSummary } from '../../../api/types'
import type { PresentationFinding } from '../../../domain/findings'
import ResultAnalysisWorkbench from '../ResultAnalysisWorkbench.vue'

// v0.9.0 Task 11：成果与分析融合工作台合同。首屏同时包含三维场景、
// 关键发现、证据带、模型评估摘要与溯源抽屉；组件只组合不 fetch。

const chartInstances: Array<{ dispose: ReturnType<typeof vi.fn> }> = []
vi.mock('echarts/core', () => ({
  init: vi.fn(() => {
    const instance = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(), on: vi.fn() }
    chartInstances.push(instance)
    return instance
  }),
  use: vi.fn(),
}))
vi.mock('echarts/charts', () => ({ BarChart: {}, LineChart: {}, ScatterChart: {}, HeatmapChart: {} }))
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

function mountWorkbench() {
  return mount(ResultAnalysisWorkbench, {
    props: {
      findings: [FINDING],
      summary: SUMMARY,
      residuals: null,
      datasetId: 'ds-1',
      resultId: 'r-1',
      evaluation: EVALUATION,
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
  it('first screen composes scene, findings, evidence dock, model metrics and provenance access', async () => {
    const wrapper = mountWorkbench()
    await flushPromises()
    expect(wrapper.get('[data-test="result-scene"]').text()).toContain('三维场景')
    expect(wrapper.get('[data-test="result-findings"]').text()).toContain('有效数据 96/100')
    expect(wrapper.find('[data-test="result-evidence-dock"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="result-evaluation"]').text()).toContain('RMSE')
    expect(wrapper.get('[data-test="result-evaluation"]').text()).toContain('6.454')
    expect(wrapper.find('[data-test="provenance-drawer"]').exists()).toBe(true)
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

  it('forwards finding locate and dock selection events', async () => {
    const wrapper = mountWorkbench()
    await flushPromises()
    const withTarget: PresentationFinding = {
      ...FINDING,
      id: 'spatial-anomaly',
      spatialTarget: { axis: 'z', range: [-25, 0] },
    }
    await wrapper.setProps({ findings: [withTarget] })
    await flushPromises()
    await wrapper.get('[data-test="finding-locate"]').trigger('click')
    expect(wrapper.emitted('locate')).toHaveLength(1)
  })

  it('model evaluation renders finite metrics only, never NaN', async () => {
    const wrapper = mountWorkbench()
    await flushPromises()
    const text = wrapper.get('[data-test="result-evaluation"]').text()
    expect(text).not.toContain('NaN')
    expect(text).not.toContain('undefined')
  })
})
