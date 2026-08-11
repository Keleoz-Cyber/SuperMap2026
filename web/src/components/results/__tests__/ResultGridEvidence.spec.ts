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

// v0.9.0 V6：成果证据窗合同（四个一级标签）。
// 综合分析/切片与异常/模型证据/数据溯源；七类证据全部保留只归组；
// 每个面板标注成果网格/输入样本口径；ECharts 实例卸载即 dispose。

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

describe('ResultGridEvidence（V6 四标签）', () => {
  it('只渲染四个一级标签', async () => {
    const wrapper = mountEvidence()
    await flushPromises()
    const tabs = wrapper.findAll('[data-test^="ge-tab-"]')
    expect(tabs.map((t) => t.text())).toEqual(['综合分析', '切片与异常', '模型证据', '数据溯源'])
  })

  it('综合分析：组成环图 + 深度趋势图 + 层段表（成果网格口径）', async () => {
    const wrapper = mountEvidence()
    await flushPromises()
    const pane = wrapper.get('[data-test="ge-pane-overview"]')
    expect(pane.text()).toContain('成果网格')
    expect(wrapper.find('[data-test="ge-composition-chart"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="ge-depth-chart"]').exists()).toBe(true)
    expect(pane.text()).toContain('15')
    expect(pane.text()).toContain('33.3%')
    await wrapper.get('[data-test="ge-depth-bin-2"]').trigger('click')
    expect(wrapper.emitted('focus-depth-bin')).toEqual([[2]])
  })

  it('综合分析：2D 成果深度分层类型化不适用', async () => {
    const wrapper = mountEvidence({ analysis: RESULT_ANALYSIS_MOCK_2D })
    await flushPromises()
    expect(wrapper.get('[data-test="ge-pane-overview"]').text()).toContain('深度分层不适用')
  })

  it('切片与异常：类型化空态 → 权威切片统计与热力图 + 连通区比较', async () => {
    const wrapper = mountEvidence()
    await flushPromises()
    await wrapper.get('[data-test="ge-tab-slices"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="ge-pane-slices"]').text()).toContain('进入切片模式')
    await wrapper.setProps({ currentSlice: SLICE_ANALYSIS_MOCK })
    await flushPromises()
    const pane = wrapper.get('[data-test="ge-pane-slices"]')
    expect(pane.text()).toContain('有效 11')
    expect(pane.text()).toContain('27.3%')
    expect(wrapper.find('[data-test="ge-slice-heatmap"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="ge-components-chart"]').exists()).toBe(true)
    await wrapper.get('[data-test="ge-component-1"]').trigger('click')
    expect(wrapper.emitted('focus-component')).toEqual([[1]])
  })

  it('模型证据：后端指标 + 残差类型化空态', async () => {
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

  it('数据溯源：输入样本标注 + 成果身份 + 资产身份', async () => {
    const wrapper = mountEvidence({
      assetIdentity: {
        assetId: 'nc-abc123',
        renderer: 'supermap_voxelgrid_netcdf',
        status: 'ready',
        gridSha256: 'a64charhexhash00000000000000000000000000000000000000000000000000',
        netcdfSha256: 'f64charhexhash00000000000000000000000000000000000000000000000000',
        geolocationStatus: 'display_anchor_only',
      },
    })
    await flushPromises()
    await wrapper.get('[data-test="ge-tab-provenance"]').trigger('click')
    await flushPromises()
    const pane = wrapper.get('[data-test="ge-pane-provenance"]')
    expect(pane.text()).toContain('输入样本')
    expect(pane.text()).toContain('96')
    expect(pane.text()).toContain('result_analysis.v1')
    expect(pane.text()).toContain('numpy_linear_p25_p75')
    expect(pane.text()).toContain('a64charhex')
    expect(pane.text()).toContain('nc-abc123')
    expect(pane.text()).toContain('display_anchor_only')
  })

  it('disposes every chart instance on unmount', async () => {
    const before = chartInstances.length
    const wrapper = mountEvidence({ currentSlice: SLICE_ANALYSIS_MOCK })
    await flushPromises()
    await wrapper.get('[data-test="ge-tab-slices"]').trigger('click')
    await wrapper.get('[data-test="ge-tab-model"]').trigger('click')
    await wrapper.get('[data-test="ge-tab-overview"]').trigger('click')
    await flushPromises()
    const created = chartInstances.slice(before)
    expect(created.length).toBeGreaterThan(0)
    wrapper.unmount()
    expect(created.filter((c) => c.dispose.mock.calls.length > 0).length).toBe(created.length)
  })
})
