import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type { AnalysisSummaryResponse, ResidualEvidence } from '../../../api/types'
import EvidenceDock from '../EvidenceDock.vue'

// v0.9.0 Task 10：混合证据坞合同。环图只吃可加总的部分-整体口径；
// 瓦斯文案恒为探索性；所有图表选择事件携带 dataset/result 身份。

const chartInstances: Array<{ setOption: ReturnType<typeof vi.fn>; dispose: ReturnType<typeof vi.fn>; resize: ReturnType<typeof vi.fn>; on: ReturnType<typeof vi.fn> }> = []

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

function summaryOf(overrides: Partial<AnalysisSummaryResponse> = {}): AnalysisSummaryResponse {
  return {
    dataset_id: 'ds-1',
    case_id: 'gas',
    analysis_profile: 'gas_content',
    profile_version: 1,
    variable: { name: 'CH4_content', unit: 'ml/g' },
    quality: {
      row_count: 100,
      valid_count: 96,
      invalid_count: 4,
      duplicate_coordinate_count: 0,
      bounds: { x: [0, 1], y: [0, 1], z: [0, 1] },
    },
    statistics: null,
    modules: [
      {
        module_id: 'distribution',
        status: 'ok',
        message: null,
        payload: { bins: [{ lower: 0, upper: 10, count: 96 }] },
      },
      {
        module_id: 'model_comparison',
        status: 'ok',
        message: null,
        payload: {
          candidates: [
            {
              result_id: 'r-1',
              algorithm: 'ordinary_kriging',
              parameters: {},
              metrics: { rmse: 8.3, mae: 6.5 },
              materialized: true,
              formal_selection: true,
              result_url: '/results/r-1',
            },
          ],
        },
      },
      {
        module_id: 'profile_slices',
        status: 'ok',
        message: null,
        payload: {
          axes: [
            {
              axis: 'z',
              bins: [
                { lower: 120, upper: 130, count: 10, mean: 5.2, median: 5.0 },
                { lower: 130, upper: 140, count: 12, mean: 7.8, median: 7.5 },
              ],
            },
          ],
        },
      },
    ],
    provenance: {
      source_sha256: 'abc',
      dataset_version: 1,
      generated_at: '2026-08-10T00:00:00+00:00',
      calculation_version: 'analysis.v1',
    },
    ...overrides,
  }
}

const RESIDUALS: ResidualEvidence = {
  result_id: 'r-1',
  total: 2,
  returned: 2,
  decimate: 1,
  source_row: [0, 1],
  fold_index: [0, 0],
  x: [0, 1],
  y: [0, 1],
  z: [120, 130],
  observed: [5.0, 8.0],
  predicted: [5.2, 7.6],
  residual: [-0.2, 0.4],
  absolute_error: [0.2, 0.4],
  squared_error: [0.04, 0.16],
  is_nodata: [false, false],
  download_url: '/api/results/r-1/residuals.csv',
}

function mountDock(summary: AnalysisSummaryResponse | null, residuals: ResidualEvidence | null = null) {
  return mount(EvidenceDock, {
    props: { summary, residuals, datasetId: 'ds-1', resultId: 'r-1' },
    global: { plugins: [ElementPlus] },
  })
}

beforeEach(() => {
  chartInstances.length = 0
})

describe('EvidenceDock', () => {
  it('donut input must sum to the declared total, otherwise nodata', async () => {
    const ok = mountDock(summaryOf())
    await flushPromises()
    expect(ok.find('[data-test="quality-donut"]').exists()).toBe(true)

    const broken = summaryOf()
    broken.quality = { ...broken.quality, row_count: 99, valid_count: 96, invalid_count: 4 }
    const bad = mountDock(broken)
    await flushPromises()
    expect(bad.find('[data-test="quality-donut"]').exists()).toBe(false)
    expect(bad.text()).toContain('质量计数不一致')
  })

  it('continuous distribution never routes into the donut', async () => {
    const wrapper = mountDock(summaryOf())
    await flushPromises()
    // 分布走柱状图（ECharts 实例），不是环图
    await wrapper.get('[data-test="dock-tab-distribution"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="dock-distribution-chart"]').exists()).toBe(true)
    expect(chartInstances.length).toBeGreaterThan(0)
  })

  it('gas labels stay exploratory and free of hazard/reserve wording', async () => {
    const wrapper = mountDock(summaryOf())
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('探索性')
    expect(text).not.toMatch(/危险|安全比例|储量/)
  })

  it('chart selections emit dataset/result identity', async () => {
    const wrapper = mountDock(summaryOf())
    await flushPromises()
    await wrapper.get('[data-test="dock-tab-trends"]').trigger('click')
    await flushPromises()
    const chart = chartInstances.at(-1)!
    const handler = chart.on.mock.calls.find((c) => c[0] === 'click')?.[1]
    expect(handler).toBeDefined()
    handler({ dataIndex: 1, seriesIndex: 0 })
    const events = wrapper.emitted('select')
    expect(events).toBeTruthy()
    const selection = (events?.[0] as Array<Record<string, unknown>>)[0]
    expect(selection.axis).toBe('z')
    expect(selection.dataset_id).toBe('ds-1')
    expect(selection.result_id).toBe('r-1')
    expect(selection.range).toEqual([130, 140])
  })

  it('disposes every ECharts instance on unmount', async () => {
    const wrapper = mountDock(summaryOf(), RESIDUALS)
    await flushPromises()
    await wrapper.get('[data-test="dock-tab-distribution"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="dock-tab-residuals"]').trigger('click')
    await flushPromises()
    const created = chartInstances.length
    expect(created).toBeGreaterThan(0)
    wrapper.unmount()
    for (const instance of chartInstances) {
      expect(instance.dispose).toHaveBeenCalled()
    }
  })

  it('malformed module payloads render typed nodata, never an empty canvas', async () => {
    const broken = summaryOf({
      modules: [
        { module_id: 'distribution', status: 'ok', message: null, payload: { bins: 'bad' } },
      ],
    })
    const wrapper = mountDock(broken)
    await flushPromises()
    await wrapper.get('[data-test="dock-tab-distribution"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-state="nodata"]').exists()).toBe(true)
  })
})
