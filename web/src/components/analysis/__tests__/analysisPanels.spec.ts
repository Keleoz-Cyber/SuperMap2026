import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type {
  AnalysisModuleResult,
  AnalysisProvenance,
  AnalysisSummaryResponse,
  AnalysisVariable,
  NumericSummary,
  ProfileSliceBin,
  QualitySummary,
  SpatialBin,
} from '../../../api/types'

// v0.8.0 第二批 Task 5：分析中心模块面板组件测试（模块边界 mock echarts，
// 与 SliceHeatmap.spec.ts 同一模式）。覆盖：质量/统计数字与单位、ECharts
// 直方图与空间热力图（含 dispose）、类型化 selection 事件、模型对比表
// （空候选解释态 + 行点击导航）、剖面轴切换、导出占位 provenance。

const chartInstances: FakeChart[] = []

interface FakeChart {
  setOption: ReturnType<typeof vi.fn>
  resize: ReturnType<typeof vi.fn>
  dispose: ReturnType<typeof vi.fn>
  on: ReturnType<typeof vi.fn>
}

vi.mock('echarts/core', () => ({
  init: vi.fn(() => {
    const instance: FakeChart = {
      setOption: vi.fn(),
      resize: vi.fn(),
      dispose: vi.fn(),
      on: vi.fn(),
    }
    chartInstances.push(instance)
    return instance
  }),
  use: vi.fn(),
}))
vi.mock('echarts/charts', () => ({ BarChart: {}, HeatmapChart: {}, LineChart: {} }))
vi.mock('echarts/components', () => ({
  GridComponent: {},
  TooltipComponent: {},
  VisualMapComponent: {},
  LegendComponent: {},
}))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

import AnalysisHeader from '../AnalysisHeader.vue'
import QualitySummaryPanel from '../QualitySummaryPanel.vue'
import DistributionPanel from '../DistributionPanel.vue'
import SpatialFeaturePanel from '../SpatialFeaturePanel.vue'
import ModelComparisonPanel from '../ModelComparisonPanel.vue'
import ProfileAnalysisPanel from '../ProfileAnalysisPanel.vue'
import AnalysisExportPanel from '../AnalysisExportPanel.vue'

const variable: AnalysisVariable = { name: 'Vx', unit: 'km/s' }

const quality: QualitySummary = {
  row_count: 1911,
  valid_count: 1900,
  invalid_count: 11,
  duplicate_coordinate_count: 2,
  bounds: { x: [0, 120], y: [0, 440], z: [0, 813.4] },
}

const statistics: NumericSummary = {
  count: 1900,
  min: 1.2,
  max: 5.6,
  mean: 3.4,
  median: 3.3,
  std: 0.8,
  quantiles: { p05: 1.8, p25: 2.9, p50: 3.3, p75: 3.9, p95: 4.8 },
}

const provenance: AnalysisProvenance = {
  source_sha256: 'a'.repeat(64),
  dataset_version: 3,
  generated_at: '2026-08-09T00:00:00+00:00',
  calculation_version: 'analysis.v1',
}

function distributionModule(): AnalysisModuleResult {
  const width = (5.6 - 1.2) / 32
  const bins = Array.from({ length: 32 }, (_, i) => ({
    lower: 1.2 + i * width,
    upper: 1.2 + (i + 1) * width,
    count: (i % 4) + 1,
  }))
  return {
    module_id: 'distribution',
    status: 'ok',
    payload: { bin_count: 32, bins },
    message: null,
  }
}

function spatialModule(): AnalysisModuleResult {
  const bins: SpatialBin[] = []
  for (let row = 0; row < 4; row += 1) {
    for (let col = 0; col < 4; col += 1) {
      const count = (row * 4 + col) % 3
      bins.push({
        x_lower: col * 10,
        x_upper: (col + 1) * 10,
        y_lower: row * 20,
        y_upper: (row + 1) * 20,
        count,
        mean: count ? 2 + (row * 4 + col) * 0.1 : null,
      })
    }
  }
  return {
    module_id: 'spatial_extent',
    status: 'ok',
    payload: { grid_size: 4, cell_count: 16, bounds: { x: [0, 40], y: [0, 80] }, bins },
    message: null,
  }
}

function axisBins(offset: number): ProfileSliceBin[] {
  return [0, 1, 2, 3].map((i) => ({
    lower: offset + i * 5,
    upper: offset + (i + 1) * 5,
    count: 10 + i,
    mean: 2 + i * 0.5,
    median: 2.1 + i * 0.5,
  }))
}

function profileModule(): AnalysisModuleResult {
  return {
    module_id: 'profile_slices',
    status: 'ok',
    payload: {
      axes: [
        { axis: 'x', bins: axisBins(0) },
        { axis: 'y', bins: axisBins(100) },
        { axis: 'z', bins: axisBins(200) },
      ],
    },
    message: null,
  }
}

function comparisonModule(candidates?: Record<string, unknown>[]): AnalysisModuleResult {
  return {
    module_id: 'model_comparison',
    status: 'ok',
    payload: {
      candidates: candidates ?? [
        {
          result_id: 'cand-1',
          algorithm: 'ordinary_kriging',
          parameters: { variogram_model: 'spherical', neighbor_count: 16 },
          metrics: { rmse: 1.21, mae: 0.92, r2: 0.93, bias: 0.04 },
          materialized: true,
          formal_selection: true,
          result_url: '/results/cand-1',
        },
        {
          result_id: 'cand-2',
          algorithm: 'idw',
          parameters: { power: 2, neighbor_count: 8 },
          metrics: { rmse: 2.4, mae: 1.6, r2: 0.88, bias: -0.1 },
          materialized: false,
          formal_selection: false,
          result_url: '/results/cand-2',
        },
      ],
    },
    message: null,
  }
}

function disabledModule(moduleId: string): AnalysisModuleResult {
  return {
    module_id: moduleId,
    status: 'disabled',
    payload: {},
    message: '专属模块计算将在后续批次就位，本批仅提供能力声明',
  }
}

function summaryOf(
  profile: AnalysisSummaryResponse['analysis_profile'],
  modules: AnalysisModuleResult[],
): AnalysisSummaryResponse {
  return {
    dataset_id: 'ds-1',
    case_id: 'case-1',
    analysis_profile: profile,
    profile_version: 1,
    variable,
    quality,
    statistics,
    modules,
    provenance,
  }
}

function lastOption(): Record<string, any> {
  const chart = chartInstances[chartInstances.length - 1]
  const calls = chart.setOption.mock.calls
  return calls[calls.length - 1][0]
}

function clickHandler(): (params: Record<string, unknown>) => void {
  const chart = chartInstances[chartInstances.length - 1]
  const call = chart.on.mock.calls.find(([name]) => name === 'click')
  expect(call).toBeTruthy()
  return call![1] as (params: Record<string, unknown>) => void
}

beforeEach(() => {
  chartInstances.length = 0
})

describe('AnalysisHeader', () => {
  it('呈现案例身份、数据版本、变量/单位、坐标类型与质量徽标', () => {
    const wrapper = mount(AnalysisHeader, {
      props: { summary: summaryOf('microseismic_velocity', []) },
      global: { plugins: [ElementPlus] },
    })
    const header = wrapper.find('[data-test="analysis-header"]')
    expect(header.exists()).toBe(true)
    expect(wrapper.find('[data-test="analysis-profile-badge"]').text()).toContain('微震速度')
    expect(wrapper.text()).toContain('case-1')
    expect(wrapper.text()).toContain('ds-1')
    expect(wrapper.text()).toContain('v3')
    const variableLine = wrapper.find('[data-test="analysis-variable"]')
    expect(variableLine.text()).toContain('Vx')
    expect(variableLine.text()).toContain('km/s')
    expect(wrapper.find('[data-test="analysis-coord-type"]').text()).toContain('三维')
    const badge = wrapper.find('[data-test="analysis-quality-badge"]')
    expect(badge.text()).toContain('11')
    expect(badge.text()).toContain('无效')
    wrapper.unmount()
  })

  it('全部有效时质量徽标为成功态；导出命令存在且点击发出 export 事件', async () => {
    const summary = summaryOf('generic_3d', [])
    summary.quality = { ...quality, invalid_count: 0 }
    const wrapper = mount(AnalysisHeader, {
      props: { summary },
      global: { plugins: [ElementPlus] },
    })
    expect(wrapper.find('[data-test="analysis-quality-badge"]').text()).toContain('全部有效')
    expect(wrapper.find('[data-test="analysis-profile-badge"]').text()).toContain('通用三维')
    const command = wrapper.find('[data-test="analysis-export-command"]')
    expect(command.exists()).toBe(true)
    await command.trigger('click')
    expect(wrapper.emitted('export')).toBeTruthy()
    wrapper.unmount()
  })
})

describe('QualitySummaryPanel', () => {
  it('行/有效/无效/重复坐标计数、三轴 bounds、含分位数的统计（全部带单位与样本数）', () => {
    const wrapper = mount(QualitySummaryPanel, {
      props: { quality, statistics, variable },
      global: { plugins: [ElementPlus] },
    })
    const rows = wrapper.find('[data-test="quality-rows"]')
    expect(rows.text()).toContain('1,911')
    expect(rows.text()).toContain('1,900')
    expect(rows.text()).toContain('11')
    expect(rows.text()).toContain('重复坐标')
    const bounds = wrapper.find('[data-test="quality-bounds"]')
    expect(bounds.text()).toContain('X')
    expect(bounds.text()).toContain('120')
    expect(bounds.text()).toContain('440')
    expect(bounds.text()).toContain('813.4')
    const numeric = wrapper.find('[data-test="numeric-summary"]')
    expect(numeric.text()).toContain('样本数')
    expect(numeric.text()).toContain('1,900')
    expect(numeric.text()).toContain('3.4')
    expect(numeric.text()).toContain('km/s')
    const quantiles = wrapper.find('[data-test="numeric-quantiles"]')
    expect(quantiles.text()).toContain('p05')
    expect(quantiles.text()).toContain('1.8')
    expect(quantiles.text()).toContain('p95')
    expect(quantiles.text()).toContain('4.8')
    wrapper.unmount()
  })

  it('statistics 为 null 时显示解释而非空表格', () => {
    const wrapper = mount(QualitySummaryPanel, {
      props: { quality, statistics: null, variable },
      global: { plugins: [ElementPlus] },
    })
    expect(wrapper.find('[data-test="numeric-summary"]').text()).toContain('不可用')
    wrapper.unmount()
  })
})

describe('DistributionPanel', () => {
  it('32 分箱直方图：轴带单位、样本数与可访问文本摘要', async () => {
    const wrapper = mount(DistributionPanel, {
      props: { module: distributionModule(), variable, profile: 'microseismic_velocity' },
      global: { plugins: [ElementPlus] },
      attachTo: document.body,
    })
    await flushPromises()
    expect(chartInstances).toHaveLength(1)
    const option = lastOption()
    expect(option.series[0].type).toBe('bar')
    expect(option.series[0].data).toHaveLength(32)
    expect(option.xAxis.name).toContain('km/s')
    const summaryText = wrapper.find('[data-test="distribution-summary"]')
    expect(summaryText.text()).toContain('样本数')
    expect(summaryText.text()).toContain('32')
    expect(summaryText.text()).toContain('km/s')
    // 计数守恒：样本数 = 分箱计数之和
    const total = distributionModule().payload.bins as { count: number }[]
    const expected = total.reduce((acc, b) => acc + b.count, 0)
    expect(summaryText.text()).toContain(String(expected))
    wrapper.unmount()
  })

  it('disabled 模块显示解释性空状态，不初始化图表', () => {
    const wrapper = mount(DistributionPanel, {
      props: { module: disabledModule('distribution'), variable, profile: 'generic_3d' },
      global: { plugins: [ElementPlus] },
    })
    const empty = wrapper.find('[data-test="distribution-empty"]')
    expect(empty.exists()).toBe(true)
    expect(empty.text()).toContain('专属模块计算将在后续批次就位')
    expect(chartInstances).toHaveLength(0)
    wrapper.unmount()
  })

  it('ok 但无分箱数据显示解释性空状态', () => {
    const module: AnalysisModuleResult = {
      module_id: 'distribution',
      status: 'ok',
      payload: { bin_count: 0, bins: [] },
      message: null,
    }
    const wrapper = mount(DistributionPanel, {
      props: { module, variable, profile: 'generic_3d' },
      global: { plugins: [ElementPlus] },
    })
    expect(wrapper.find('[data-test="distribution-empty"]').exists()).toBe(true)
    expect(chartInstances).toHaveLength(0)
    wrapper.unmount()
  })

  it('电阻率 profile 显示对数尺度说明（log 专属展示属后续任务）', async () => {
    const wrapper = mount(DistributionPanel, {
      props: { module: distributionModule(), variable, profile: 'resistivity' },
      global: { plugins: [ElementPlus] },
      attachTo: document.body,
    })
    await flushPromises()
    const note = wrapper.find('[data-test="distribution-log-note"]')
    expect(note.exists()).toBe(true)
    expect(note.text()).toContain('对数')
    // 本批仍渲染原始分箱
    expect(chartInstances).toHaveLength(1)
    wrapper.unmount()
  })

  it('卸载时 dispose ECharts 实例', async () => {
    const wrapper = mount(DistributionPanel, {
      props: { module: distributionModule(), variable, profile: 'microseismic_velocity' },
      global: { plugins: [ElementPlus] },
      attachTo: document.body,
    })
    await flushPromises()
    expect(chartInstances).toHaveLength(1)
    wrapper.unmount()
    expect(chartInstances[0].dispose).toHaveBeenCalled()
  })
})

describe('SpatialFeaturePanel', () => {
  it('XY 网格热力图：默认计数度量，tooltip 带坐标范围与单位', async () => {
    const wrapper = mount(SpatialFeaturePanel, {
      props: { module: spatialModule(), variable, datasetId: 'ds-1', resultId: 'cand-1' },
      global: { plugins: [ElementPlus] },
      attachTo: document.body,
    })
    await flushPromises()
    expect(chartInstances).toHaveLength(1)
    const option = lastOption()
    expect(option.series[0].type).toBe('heatmap')
    expect(option.series[0].data).toHaveLength(16)
    // 默认计数度量：visualMap 值域来自 count（夹具最大 2）
    expect(option.visualMap.max).toBe(2)
    // bin 10（col=2,row=2）：X 20–30 · Y 40–60，count=1，mean=3
    const tooltip = option.tooltip.formatter({ data: [2, 2, 1], dataIndex: 10 })
    expect(tooltip).toContain('20')
    expect(tooltip).toContain('30')
    expect(tooltip).toContain('40')
    expect(tooltip).toContain('60')
    expect(tooltip).toContain('km/s')
    const summaryText = wrapper.find('[data-test="spatial-summary"]')
    expect(summaryText.text()).toContain('样本')
    wrapper.unmount()
  })

  it('count/mean 度量切换改变系列数据', async () => {
    const wrapper = mount(SpatialFeaturePanel, {
      props: { module: spatialModule(), variable, datasetId: 'ds-1' },
      global: { plugins: [ElementPlus] },
      attachTo: document.body,
    })
    await flushPromises()
    const countOption = lastOption()
    // bin 5：count=2，mean=2.5
    expect(countOption.series[0].data[5][2]).toBe(2)
    await wrapper.find('[data-test="metric-mean"]').setValue(true)
    await flushPromises()
    const meanOption = lastOption()
    expect(meanOption.series[0].data[5][2]).toBe(2.5)
    wrapper.unmount()
  })

  it('点击分箱发出类型化 selection 事件（axis/x_range/y_range/dataset_id/result_id）', async () => {
    const wrapper = mount(SpatialFeaturePanel, {
      props: { module: spatialModule(), variable, datasetId: 'ds-1', resultId: 'cand-1' },
      global: { plugins: [ElementPlus] },
      attachTo: document.body,
    })
    await flushPromises()
    clickHandler()({ data: [1, 2, 2], dataIndex: 9 })
    const events = wrapper.emitted('select')
    expect(events).toBeTruthy()
    expect(events![0][0]).toEqual({
      axis: 'xy',
      x_range: [10, 20],
      y_range: [40, 60],
      dataset_id: 'ds-1',
      result_id: 'cand-1',
    })
    wrapper.unmount()
  })

  it('无物化成果时 selection 不带 result_id', async () => {
    const wrapper = mount(SpatialFeaturePanel, {
      props: { module: spatialModule(), variable, datasetId: 'ds-1' },
      global: { plugins: [ElementPlus] },
      attachTo: document.body,
    })
    await flushPromises()
    clickHandler()({ data: [1, 2, 2], dataIndex: 9 })
    const selection = wrapper.emitted('select')![0][0] as Record<string, unknown>
    expect(selection.dataset_id).toBe('ds-1')
    expect(selection.result_id).toBeUndefined()
    wrapper.unmount()
  })

  it('disabled 模块显示解释性空状态；卸载 dispose', async () => {
    const disabled = mount(SpatialFeaturePanel, {
      props: { module: disabledModule('spatial_anomaly'), variable, datasetId: 'ds-1' },
      global: { plugins: [ElementPlus] },
    })
    expect(disabled.find('[data-test="spatial-empty"]').text()).toContain(
      '专属模块计算将在后续批次就位',
    )
    expect(chartInstances).toHaveLength(0)
    disabled.unmount()

    const wrapper = mount(SpatialFeaturePanel, {
      props: { module: spatialModule(), variable, datasetId: 'ds-1' },
      global: { plugins: [ElementPlus] },
      attachTo: document.body,
    })
    await flushPromises()
    expect(chartInstances).toHaveLength(1)
    wrapper.unmount()
    expect(chartInstances[0].dispose).toHaveBeenCalled()
  })
})

describe('ModelComparisonPanel', () => {
  function mountWithRouter(module: AnalysisModuleResult) {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div />' } },
        { path: '/results/:resultId', name: 'result-workbench', component: { template: '<div />' } },
      ],
    })
    const pushSpy = vi.spyOn(router, 'push')
    const wrapper = mount(ModelComparisonPanel, {
      props: { module },
      global: { plugins: [router, ElementPlus] },
    })
    return { wrapper, pushSpy }
  }

  it('候选表格：算法中文标签、参数摘要、RMSE/MAE/R²/Bias、物化与正式选择徽标', () => {
    const { wrapper } = mountWithRouter(comparisonModule())
    const rows = wrapper.findAll('[data-test="model-candidate-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('普通克里金')
    expect(rows[0].text()).toContain('变异函数')
    expect(rows[0].text()).toContain('球状')
    expect(rows[0].text()).toContain('1.21')
    expect(rows[0].text()).toContain('0.92')
    expect(rows[0].text()).toContain('0.93')
    expect(rows[0].text()).toContain('0.04')
    expect(rows[0].find('[data-test="badge-materialized"]').exists()).toBe(true)
    expect(rows[0].find('[data-test="badge-formal"]').exists()).toBe(true)
    expect(rows[1].text()).toContain('IDW')
    expect(rows[1].text()).toContain('幂参数')
    expect(rows[1].find('[data-test="badge-materialized"]').exists()).toBe(false)
    expect(rows[1].find('[data-test="badge-formal"]').exists()).toBe(false)
    // 表头包含指标单位语义
    expect(wrapper.text()).toContain('RMSE')
    expect(wrapper.text()).toContain('MAE')
    expect(wrapper.text()).toContain('R²')
    wrapper.unmount()
  })

  it('点击候选行导航到 /results/{result_id}', async () => {
    const { wrapper, pushSpy } = mountWithRouter(comparisonModule())
    await wrapper.findAll('[data-test="model-candidate-row"]')[0].trigger('click')
    expect(pushSpy).toHaveBeenCalledWith({ path: '/results/cand-1' })
    wrapper.unmount()
  })

  it('无候选时显示解释性空状态', () => {
    const { wrapper } = mountWithRouter(comparisonModule([]))
    const empty = wrapper.find('[data-test="model-comparison-empty"]')
    expect(empty.exists()).toBe(true)
    expect(empty.text()).toContain('尚无')
    expect(wrapper.findAll('[data-test="model-candidate-row"]')).toHaveLength(0)
    wrapper.unmount()
  })
})

describe('ProfileAnalysisPanel', () => {
  it('三轴剖面：默认首轴，分段控件切换轴后图表数据变化', async () => {
    const wrapper = mount(ProfileAnalysisPanel, {
      props: { module: profileModule(), variable, datasetId: 'ds-1' },
      global: { plugins: [ElementPlus] },
      attachTo: document.body,
    })
    await flushPromises()
    expect(chartInstances).toHaveLength(1)
    const xOption = lastOption()
    expect(xOption.series[0].data).toHaveLength(4)
    expect(wrapper.find('[data-test="profile-summary"]').text()).toContain('X')
    await wrapper.find('[data-test="axis-y"]').setValue(true)
    await flushPromises()
    const yOption = lastOption()
    // Y 轴分箱 lower 从 100 起
    expect(JSON.stringify(yOption.xAxis.data)).toContain('100')
    expect(wrapper.find('[data-test="profile-summary"]').text()).toContain('Y')
    wrapper.unmount()
  })

  it('点击剖面分箱发出类型化 selection（axis/range/dataset_id）', async () => {
    const wrapper = mount(ProfileAnalysisPanel, {
      props: { module: profileModule(), variable, datasetId: 'ds-1', resultId: 'cand-1' },
      global: { plugins: [ElementPlus] },
      attachTo: document.body,
    })
    await flushPromises()
    clickHandler()({ data: [1, 11], dataIndex: 1 })
    const events = wrapper.emitted('select')
    expect(events).toBeTruthy()
    expect(events![0][0]).toEqual({
      axis: 'x',
      range: [5, 10],
      dataset_id: 'ds-1',
      result_id: 'cand-1',
    })
    wrapper.unmount()
  })

  it('disabled 模块解释态；卸载 dispose', async () => {
    const disabled = mount(ProfileAnalysisPanel, {
      props: { module: disabledModule('profile_slices'), variable, datasetId: 'ds-1' },
      global: { plugins: [ElementPlus] },
    })
    expect(disabled.find('[data-test="profile-empty"]').exists()).toBe(true)
    expect(chartInstances).toHaveLength(0)
    disabled.unmount()

    const wrapper = mount(ProfileAnalysisPanel, {
      props: { module: profileModule(), variable, datasetId: 'ds-1' },
      global: { plugins: [ElementPlus] },
      attachTo: document.body,
    })
    await flushPromises()
    expect(chartInstances).toHaveLength(1)
    wrapper.unmount()
    expect(chartInstances[0].dispose).toHaveBeenCalled()
  })
})

describe('AnalysisExportPanel', () => {
  it('渲染 provenance 溯源信息，导出为占位结构（后续任务接线）', () => {
    const wrapper = mount(AnalysisExportPanel, {
      props: { provenance, datasetId: 'ds-1', profile: 'microseismic_velocity' },
      global: { plugins: [ElementPlus] },
    })
    const prov = wrapper.find('[data-test="export-provenance"]')
    expect(prov.exists()).toBe(true)
    expect(prov.text()).toContain('aaaa')
    expect(prov.text()).toContain('v3')
    expect(prov.text()).toContain('2026-08-09')
    expect(prov.text()).toContain('analysis.v1')
    // 占位导出命令存在但不可用
    expect(wrapper.find('[data-test="export-command-json"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="export-command-csv"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="export-placeholder-hint"]').exists()).toBe(true)
    wrapper.unmount()
  })
})
