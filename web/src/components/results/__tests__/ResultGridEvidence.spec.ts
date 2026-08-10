import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type { AnalysisSummaryResponse } from '../../../api/types'
import ResultGridEvidence from '../ResultGridEvidence.vue'
import {
  RESULT_ANALYSIS_MOCK_2D,
  RESULT_ANALYSIS_MOCK_3D,
  SLICE_ANALYSIS_MOCK,
} from '../../../mocks/resultAnalysisMock'

// v0.9.0 Task 6：成果网格证据带合同。七个标签页（成果组成/深度趋势/组件比较/
// 当前切片/模型与残差/输入样本/溯源）全部标注数据来源（成果网格 vs 输入样本）；
// ECharts 实例卸载即 dispose，绝不泄漏；畸形/缺失载荷显示类型化空态。

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

const DATASET_SUMMARY: AnalysisSummaryResponse = {
  dataset_id: 'ds-1',
  case_id: 'c-1',
  analysis_profile: 'resistivity',
  profile_version: 1,
  variable: { name: 'RHO', unit: 'Ω·m' },
  quality: { row_count: 100, valid_count: 96, invalid_count: 4, duplicate_coordinate_count: 0, bounds: null },
  statistics: null,
  modules: [],
  provenance: {
    source_sha256: 'abc',
    dataset_version: 1,
    generated_at: '2026-08-10T00:00:00+00:00',
    calculation_version: 'analysis.v1',
  },
}

function mountEvidence(props: Record<string, unknown> = {}) {
  return mount(ResultGridEvidence, {
    props: {
      analysis: RESULT_ANALYSIS_MOCK_3D,
      currentSlice: null,
      datasetSummary: DATASET_SUMMARY,
      residuals: null,
      resultId: 'r-3d-normal',
      ...props,
    },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
}

describe('ResultGridEvidence', () => {
  it('renders composition tab with donut chart and result-grid label from backend buckets', async () => {
    const wrapper = mountEvidence()
    await flushPromises()
    expect(wrapper.find('[data-test="ge-tab-composition"]').exists()).toBe(true)
    const pane = wrapper.get('[data-test="ge-pane-composition"]')
    expect(pane.text()).toContain('成果网格')
    expect(pane.text()).toContain('体元节点占比')
    // 桶数字逐字来自 DTO
    expect(pane.text()).toContain('15')
    expect(pane.text()).toContain('30')
    // ECharts 环形图宿主存在
    expect(wrapper.find('[data-test="ge-composition-chart"]').exists()).toBe(true)
  })

  it('depth tab shows bins chart and table; 2D shows typed not-applicable state', async () => {
    const wrapper = mountEvidence()
    await flushPromises()
    await wrapper.get('[data-test="ge-tab-depth"]').trigger('click')
    await flushPromises()
    const pane = wrapper.get('[data-test="ge-pane-depth"]')
    expect(wrapper.find('[data-test="ge-depth-chart"]').exists()).toBe(true)
    expect(pane.text()).toContain('20–30')
    expect(pane.text()).toContain('33.3%')
    // 层段点击 → focus-depth-bin 联动事件
    await wrapper.get('[data-test="ge-depth-bin-2"]').trigger('click')
    expect(wrapper.emitted('focus-depth-bin')).toEqual([[2]])

    const wrapper2d = mountEvidence({ analysis: RESULT_ANALYSIS_MOCK_2D })
    await flushPromises()
    await wrapper2d.get('[data-test="ge-tab-depth"]').trigger('click')
    await flushPromises()
    expect(wrapper2d.get('[data-test="ge-pane-depth"]').text()).toContain('深度分层不适用')
  })

  it('components tab compares support measure and peak values from backend rows', async () => {
    const wrapper = mountEvidence()
    await flushPromises()
    await wrapper.get('[data-test="ge-tab-components"]').trigger('click')
    await flushPromises()
    const pane = wrapper.get('[data-test="ge-pane-components"]')
    expect(wrapper.find('[data-test="ge-components-chart"]').exists()).toBe(true)
    expect(pane.text()).toContain('网格支持体积估计')
    // 组件行点击 → focus-component
    await wrapper.get('[data-test="ge-component-1"]').trigger('click')
    expect(wrapper.emitted('focus-component')).toEqual([[1]])
  })

  it('slice tab shows typed empty then authoritative statistics and heatmap', async () => {
    const wrapper = mountEvidence()
    await flushPromises()
    await wrapper.get('[data-test="ge-tab-slice"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="ge-pane-slice"]').text()).toContain('进入切片模式')
    await wrapper.setProps({ currentSlice: SLICE_ANALYSIS_MOCK })
    await flushPromises()
    const pane = wrapper.get('[data-test="ge-pane-slice"]')
    expect(pane.text()).toContain('有效 11')
    expect(pane.text()).toContain('27.3%')
    expect(wrapper.find('[data-test="ge-slice-heatmap"]').exists()).toBe(true)
  })

  it('model tab renders backend metrics and typed residual empty state', async () => {
    const wrapper = mountEvidence()
    await flushPromises()
    await wrapper.get('[data-test="ge-tab-model"]').trigger('click')
    await flushPromises()
    const pane = wrapper.get('[data-test="ge-pane-model"]')
    expect(pane.text()).toContain('ordinary_kriging')
    expect(pane.text()).toContain('5.2')
    expect(pane.text()).toContain('暂无残差证据')
    expect(pane.text()).not.toContain('NaN')
  })

  it('input tab keeps dataset-level evidence under explicit input-sample label', async () => {
    const wrapper = mountEvidence()
    await flushPromises()
    await wrapper.get('[data-test="ge-tab-input"]').trigger('click')
    await flushPromises()
    const pane = wrapper.get('[data-test="ge-pane-input"]')
    expect(pane.text()).toContain('输入样本')
    expect(pane.text()).toContain('96')
  })

  it('provenance tab shows grid hash, calculation version and threshold method', async () => {
    const wrapper = mountEvidence()
    await flushPromises()
    await wrapper.get('[data-test="ge-tab-provenance"]').trigger('click')
    await flushPromises()
    const pane = wrapper.get('[data-test="ge-pane-provenance"]')
    expect(pane.text()).toContain('result_analysis.v1')
    expect(pane.text()).toContain('numpy_linear_p25_p75')
    expect(pane.text()).toContain('a64charhex')
  })

  it('disposes every chart instance on unmount', async () => {
    const before = chartInstances.length
    const wrapper = mountEvidence({ currentSlice: SLICE_ANALYSIS_MOCK })
    await flushPromises()
    await wrapper.get('[data-test="ge-tab-depth"]').trigger('click')
    await wrapper.get('[data-test="ge-tab-components"]').trigger('click')
    await wrapper.get('[data-test="ge-tab-slice"]').trigger('click')
    await flushPromises()
    const created = chartInstances.slice(before)
    expect(created.length).toBeGreaterThan(0)
    wrapper.unmount()
    expect(created.filter((c) => c.dispose.mock.calls.length > 0).length).toBe(created.length)
  })
})
