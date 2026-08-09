import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ComparisonCandidateSummary } from '../../../api/types'
import MetricComparisonChart from '../MetricComparisonChart.vue'

// v0.9.0 Task 9：模型比较证据图。分组柱状 RMSE/MAE 与独立标度 R²/Bias；
// 不兼容/重复指纹/有效指标不足时绝不渲染排名图。

const chartInstances: Array<{ setOption: ReturnType<typeof vi.fn>; dispose: ReturnType<typeof vi.fn>; resize: ReturnType<typeof vi.fn>; on: ReturnType<typeof vi.fn> }> = []

vi.mock('echarts/core', () => ({
  init: vi.fn(() => {
    const instance = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(), on: vi.fn() }
    chartInstances.push(instance)
    return instance
  }),
  use: vi.fn(),
}))
vi.mock('echarts/charts', () => ({ BarChart: {} }))
vi.mock('echarts/components', () => ({
  GridComponent: {},
  TooltipComponent: {},
  LegendComponent: {},
}))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

function candidateOf(
  id: string,
  overrides: Partial<ComparisonCandidateSummary> = {},
): ComparisonCandidateSummary {
  return {
    candidate_result_id: id,
    experiment_id: 'exp-1',
    run_id: 'run-1',
    algorithm: 'ordinary_kriging',
    parameters: { variogram_model: 'exponential', neighbor_count: 24 },
    selectable: true,
    metrics: { rmse: 6.45, mae: 3.25, r2: 0.92, bias: -0.09 },
    result_url: `/results/${id}`,
    configuration_fingerprint: `fp-${id}`,
    ...overrides,
  }
}

beforeEach(() => {
  chartInstances.length = 0
})

describe('MetricComparisonChart', () => {
  it('renders grouped RMSE/MAE bars and a separate R²/Bias scale for compatible candidates', async () => {
    const wrapper = mount(MetricComparisonChart, {
      props: {
        candidates: [
          candidateOf('r1'),
          candidateOf('r2', { algorithm: 'idw', metrics: { rmse: 9.1, mae: 5.2, r2: 0.81, bias: 0.2 } }),
        ],
        comparable: true,
      },
    })
    await flushPromises()
    expect(chartInstances).toHaveLength(1)
    const option = chartInstances[0].setOption.mock.calls[0][0]
    // 双 y 轴：误差轴与 R²/Bias 轴分离
    expect(option.yAxis).toHaveLength(2)
    const series = option.series as Array<{ name: string; yAxisIndex: number }>
    const byName = Object.fromEntries(series.map((s) => [s.name, s.yAxisIndex]))
    expect(byName['RMSE']).toBe(0)
    expect(byName['MAE']).toBe(0)
    expect(byName['R²']).toBe(1)
    expect(byName['Bias']).toBe(1)
    expect(wrapper.find('[data-test="metric-comparison-chart"]').exists()).toBe(true)
    wrapper.unmount()
    expect(chartInstances[0].dispose).toHaveBeenCalled()
  })

  it('renders no ranking chart when candidates are incompatible', () => {
    const wrapper = mount(MetricComparisonChart, {
      props: { candidates: [candidateOf('r1'), candidateOf('r2')], comparable: false },
    })
    expect(wrapper.find('[data-test="metric-comparison-chart"]').exists()).toBe(false)
    expect(chartInstances).toHaveLength(0)
  })

  it('renders no ranking chart for duplicate configuration fingerprints', () => {
    const wrapper = mount(MetricComparisonChart, {
      props: {
        candidates: [candidateOf('r1'), candidateOf('r2', { configuration_fingerprint: 'fp-r1' })],
        comparable: true,
      },
    })
    expect(wrapper.find('[data-test="metric-comparison-chart"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="metric-chart-skip"]').text()).toContain('相同配置')
    expect(chartInstances).toHaveLength(0)
  })

  it('renders no ranking chart when fewer than two candidates have finite error metrics', () => {
    const wrapper = mount(MetricComparisonChart, {
      props: {
        candidates: [
          candidateOf('r1'),
          candidateOf('r2', { metrics: { rmse: null, mae: null, r2: null, bias: null } }),
        ],
        comparable: true,
      },
    })
    expect(wrapper.find('[data-test="metric-comparison-chart"]').exists()).toBe(false)
    expect(chartInstances).toHaveLength(0)
  })
})
