import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as client from '../../../api/client'
import type { AnalysisModuleResult, AnalysisSummaryResponse } from '../../../api/types'
import AnalysisCenterView from '../../../views/AnalysisCenterView.vue'
import analysisViewSource from '../../../views/AnalysisCenterView.vue?raw'
import SpatialFeaturePanel from '../SpatialFeaturePanel.vue'

// v0.8.0 第二批 Task 4：分析中心视图三态（加载中 / 成功 profile 徽标 /
// 类型化错误）。Task 5 扩展：A+B 壳布局、generic 降级可见性、profile 专属
// 模块 disabled 解释态、单位显示、导出命令、空间分箱选择 → 成果导航与
// 无物化成果非阻断提示、响应式媒体查询源断言（与 CaseWorkspaceView.spec 同
// 一 ?raw 模式；jsdom 无布局）。ECharts 在模块边界 mock（同 SliceHeatmap）。

const chartInstances: { dispose: ReturnType<typeof vi.fn> }[] = []

vi.mock('echarts/core', () => ({
  init: vi.fn(() => {
    const instance = {
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

vi.mock('../../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/client')>()
  return { ...actual, fetchAnalysisSummary: vi.fn() }
})

function summaryOf(profile: AnalysisSummaryResponse['analysis_profile']): AnalysisSummaryResponse {
  return {
    dataset_id: 'ds-1',
    case_id: 'case-1',
    analysis_profile: profile,
    profile_version: 1,
    variable: { name: 'Vx', unit: 'km/s' },
    quality: {
      row_count: 1911,
      valid_count: 1900,
      invalid_count: 11,
      duplicate_coordinate_count: 0,
      bounds: null,
    },
    statistics: {
      count: 1900,
      min: 1.2,
      max: 5.6,
      mean: 3.4,
      median: 3.3,
      std: 0.8,
      quantiles: { p05: 1.8, p25: 2.9, p50: 3.3, p75: 3.9, p95: 4.8 },
    },
    modules: [
      { module_id: 'distribution', status: 'ok', payload: {}, message: null },
      {
        module_id: 'velocity_trend',
        status: 'disabled',
        payload: {},
        message: '专属模块计算将在后续批次就位，本批仅提供能力声明',
      },
    ],
    provenance: {
      source_sha256: 'a'.repeat(64),
      dataset_version: 1,
      generated_at: '2026-08-09T00:00:00+00:00',
      calculation_version: 'analysis.v1',
    },
  }
}

function spatialModule(): AnalysisModuleResult {
  const bins = []
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

function comparisonModule(candidates: Record<string, unknown>[]): AnalysisModuleResult {
  return {
    module_id: 'model_comparison',
    status: 'ok',
    payload: { candidates },
    message: null,
  }
}

const MATERIALIZED_CANDIDATE = {
  result_id: 'cand-1',
  algorithm: 'ordinary_kriging',
  parameters: { variogram_model: 'spherical', neighbor_count: 16 },
  metrics: { rmse: 1.21, mae: 0.92, r2: 0.93, bias: 0.04 },
  materialized: true,
  formal_selection: true,
  result_url: '/results/cand-1',
}

// 完整 A+B 壳夹具：通用模块全部 ok + 微震专属 axis_trends disabled 骨架
function fullSummary(
  profile: AnalysisSummaryResponse['analysis_profile'],
  candidates: Record<string, unknown>[] = [MATERIALIZED_CANDIDATE],
): AnalysisSummaryResponse {
  const base = summaryOf(profile)
  const modules: AnalysisModuleResult[] = [
    { module_id: 'quality', status: 'ok', payload: {}, message: null },
    { module_id: 'statistics', status: 'ok', payload: {}, message: null },
    { module_id: 'distribution', status: 'ok', payload: { bin_count: 0, bins: [] }, message: null },
    spatialModule(),
    { module_id: 'profile_slices', status: 'ok', payload: { axes: [] }, message: null },
    comparisonModule(candidates),
  ]
  if (profile === 'microseismic_velocity') {
    modules.push({
      module_id: 'axis_trends',
      status: 'disabled',
      payload: {},
      message: '专属模块计算将在后续批次就位，本批仅提供能力声明',
    })
  }
  return { ...base, modules }
}

async function mountAnalysisCenter(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/datasets/:datasetId/analysis',
        name: 'analysis-center',
        component: AnalysisCenterView,
      },
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/cases/:caseId', name: 'case-workspace', component: { template: '<div />' } },
      { path: '/results/:resultId', name: 'result-workbench', component: { template: '<div />' } },
    ],
  })
  router.push(path)
  await router.isReady()
  const wrapper = mount(AnalysisCenterView, {
    global: {
      plugins: [router, ElementPlus],
    },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('AnalysisCenterView（三态）', () => {
  it('加载中显示加载状态，完成后隐藏', async () => {
    let resolveFetch: (value: AnalysisSummaryResponse) => void = () => {}
    vi.mocked(client.fetchAnalysisSummary).mockImplementation(
      () =>
        new Promise<AnalysisSummaryResponse>((resolve) => {
          resolveFetch = resolve
        }),
    )
    const { wrapper } = await mountAnalysisCenter('/datasets/ds-1/analysis')
    expect(wrapper.find('[data-test="analysis-loading"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="analysis-profile-badge"]').exists()).toBe(false)

    resolveFetch(summaryOf('microseismic_velocity'))
    await flushPromises()
    expect(wrapper.find('[data-test="analysis-loading"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('成功：显示案例身份与 profile 徽标', async () => {
    vi.mocked(client.fetchAnalysisSummary).mockResolvedValue(summaryOf('microseismic_velocity'))
    const { wrapper } = await mountAnalysisCenter('/datasets/ds-1/analysis')

    expect(client.fetchAnalysisSummary).toHaveBeenCalledWith('ds-1')
    const badge = wrapper.find('[data-test="analysis-profile-badge"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toContain('微震速度')
    expect(wrapper.text()).toContain('ds-1')
    expect(wrapper.text()).toContain('case-1')
    const variable = wrapper.find('[data-test="analysis-variable"]')
    expect(variable.text()).toContain('微震速度')
    expect(variable.text()).not.toContain('Vx')
    expect(variable.text()).toContain('km/s')
    expect(wrapper.find('[data-test="analysis-error"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('类型化错误：ApiError 显示错误码与消息，绝不渲染空徽标', async () => {
    const { ApiError } = await import('../../../api/client')
    vi.mocked(client.fetchAnalysisSummary).mockRejectedValue(
      new ApiError('DATASET_NOT_VALIDATED', '数据版本尚未通过验证，分析摘要不可用', 409),
    )
    const { wrapper } = await mountAnalysisCenter('/datasets/ds-1/analysis')

    const error = wrapper.find('[data-test="analysis-error"]')
    expect(error.exists()).toBe(true)
    expect(error.text()).toContain('DATASET_NOT_VALIDATED')
    expect(error.text()).toContain('数据版本尚未通过验证')
    expect(wrapper.find('[data-test="analysis-profile-badge"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="analysis-loading"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('summary 未就绪（加载中/加载失败）不渲染导出命令', async () => {
    let resolveFetch: (value: AnalysisSummaryResponse) => void = () => {}
    vi.mocked(client.fetchAnalysisSummary).mockImplementation(
      () =>
        new Promise<AnalysisSummaryResponse>((resolve) => {
          resolveFetch = resolve
        }),
    )
    const { wrapper } = await mountAnalysisCenter('/datasets/ds-1/analysis')
    expect(wrapper.find('[data-test="analysis-loading"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="analysis-export-panel"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="export-command-json"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="export-command-csv"]').exists()).toBe(false)

    resolveFetch(summaryOf('microseismic_velocity'))
    await flushPromises()
    expect(wrapper.find('[data-test="export-command-json"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="export-command-csv"]').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('AnalysisCenterView（A+B 壳）', () => {
  it('布局骨架：结论优先 / 分析视角 / 当前证据 / 方法折叠区', async () => {
    vi.mocked(client.fetchAnalysisSummary).mockResolvedValue(fullSummary('microseismic_velocity'))
    const { wrapper } = await mountAnalysisCenter('/datasets/ds-1/analysis')

    expect(wrapper.find('[data-test="analysis-header"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="analysis-conclusion"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="module-nav"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="primary-area"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="context-evidence"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="side-area"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="lower-area"]').exists()).toBe(true)
    // 默认主焦点为空间视图
    expect(wrapper.find('[data-test="spatial-feature-panel"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="model-comparison-panel"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('结论先说明数据与当前分析意义，并提供三维成果动作，技术身份不进入结论', async () => {
    vi.mocked(client.fetchAnalysisSummary).mockResolvedValue(fullSummary('resistivity'))
    const { wrapper, router } = await mountAnalysisCenter('/datasets/ds-1/analysis')

    const conclusion = wrapper.get('[data-test="analysis-conclusion"]')
    expect(conclusion.text()).toContain('电阻率')
    expect(conclusion.text()).toContain('有效样本')
    expect(conclusion.text()).not.toContain('ds-1')
    expect(conclusion.text()).not.toContain('analysis.v1')
    await conclusion.get('[data-test="analysis-open-result"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/results/cand-1')
    wrapper.unmount()
  })

  it('模型证据是独立分析视角，选择后才显示候选指标', async () => {
    vi.mocked(client.fetchAnalysisSummary).mockResolvedValue(fullSummary('microseismic_velocity'))
    const { wrapper } = await mountAnalysisCenter('/datasets/ds-1/analysis')

    expect(wrapper.find('[data-test="module-nav-item-model_comparison"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="model-comparison-panel"]').exists()).toBe(false)
    await wrapper.get('[data-test="module-nav-item-model_comparison"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="model-comparison-panel"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="context-evidence"]').text()).toContain('模型证据')
    wrapper.unmount()
  })

  it('generic 降级可见性：通用三维徽标，导航只含通用模块', async () => {
    vi.mocked(client.fetchAnalysisSummary).mockResolvedValue(fullSummary('generic_3d'))
    const { wrapper } = await mountAnalysisCenter('/datasets/ds-1/analysis')

    expect(wrapper.find('[data-test="analysis-profile-badge"]').text()).toContain('通用三维')
    const fallback = wrapper.get('[data-test="analysis-generic-fallback"]').text()
    expect(fallback).toContain('当前数据使用通用分析模板')
    expect(fallback).not.toContain('generic_3d')
    expect(fallback).not.toContain('CH4_content')
    expect(fallback).not.toContain('RHO')
    expect(wrapper.find('[data-test="module-nav-item-distribution"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="module-nav-item-spatial_extent"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="module-nav-item-axis_trends"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('profile 专属模块 disabled：导航标记不可用，选中后显示解释而非空图', async () => {
    vi.mocked(client.fetchAnalysisSummary).mockResolvedValue(fullSummary('microseismic_velocity'))
    const { wrapper } = await mountAnalysisCenter('/datasets/ds-1/analysis')

    const navItem = wrapper.find('[data-test="module-nav-item-axis_trends"]')
    expect(navItem.exists()).toBe(true)
    expect(navItem.text()).toContain('不可用')
    await navItem.trigger('click')
    await flushPromises()
    const disabled = wrapper.find('[data-test="module-disabled-state"]')
    expect(disabled.exists()).toBe(true)
    expect(disabled.text()).toContain('专属模块计算将在后续批次就位')
    // 不显示空图表
    expect(wrapper.find('[data-test="spatial-feature-panel"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="distribution-panel"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('单位显示：头部与方法区统计均带变量单位与样本数', async () => {
    vi.mocked(client.fetchAnalysisSummary).mockResolvedValue(fullSummary('microseismic_velocity'))
    const { wrapper } = await mountAnalysisCenter('/datasets/ds-1/analysis')

    expect(wrapper.find('[data-test="analysis-variable"]').text()).toContain('km/s')
    const numeric = wrapper.find('[data-test="numeric-summary"]')
    expect(numeric.text()).toContain('km/s')
    expect(numeric.text()).toContain('样本数')
    expect(numeric.text()).toContain('1,900')
    wrapper.unmount()
  })

  it('导出命令存在，底部渲染 provenance 溯源', async () => {
    vi.mocked(client.fetchAnalysisSummary).mockResolvedValue(fullSummary('microseismic_velocity'))
    const { wrapper } = await mountAnalysisCenter('/datasets/ds-1/analysis')

    expect(wrapper.find('[data-test="analysis-export-command"]').exists()).toBe(true)
    const prov = wrapper.find('[data-test="export-provenance"]')
    expect(prov.exists()).toBe(true)
    expect(prov.text()).toContain('analysis.v1')
    wrapper.unmount()
  })

  it('顶栏导出入口联动底部导出面板：点击后导出折叠项展开', async () => {
    vi.mocked(client.fetchAnalysisSummary).mockResolvedValue(fullSummary('microseismic_velocity'))
    const { wrapper } = await mountAnalysisCenter('/datasets/ds-1/analysis')

    const exportHeader = () =>
      wrapper
        .findAll('.el-collapse-item__header')
        .find((header) => header.text().includes('方法、导出与技术溯源'))
    expect(exportHeader()?.classes()).not.toContain('is-active')
    await wrapper.find('[data-test="analysis-export-command"]').trigger('click')
    await flushPromises()
    expect(exportHeader()?.classes()).toContain('is-active')
    expect(wrapper.find('[data-test="export-command-json"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="export-command-csv"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('空间分箱选择：有物化成果时导航到 /results/{id} 并带轴/区间/数据集查询参数', async () => {
    vi.mocked(client.fetchAnalysisSummary).mockResolvedValue(fullSummary('microseismic_velocity'))
    const { wrapper, router } = await mountAnalysisCenter('/datasets/ds-1/analysis')

    const panel = wrapper.findComponent(SpatialFeaturePanel)
    expect(panel.exists()).toBe(true)
    panel.vm.$emit('select', {
      axis: 'xy',
      x_range: [10, 20],
      y_range: [40, 60],
      dataset_id: 'ds-1',
      result_id: 'cand-1',
    })
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/results/cand-1')
    expect(router.currentRoute.value.query.axis).toBe('xy')
    expect(router.currentRoute.value.query.x_range).toBe('10..20')
    expect(router.currentRoute.value.query.y_range).toBe('40..60')
    expect(router.currentRoute.value.query.dataset).toBe('ds-1')
    wrapper.unmount()
  })

  it('空间分箱选择：无物化成果时显示非阻断解释，不导航', async () => {
    vi.mocked(client.fetchAnalysisSummary).mockResolvedValue(
      fullSummary('microseismic_velocity', []),
    )
    const { wrapper, router } = await mountAnalysisCenter('/datasets/ds-1/analysis')

    const panel = wrapper.findComponent(SpatialFeaturePanel)
    panel.vm.$emit('select', {
      axis: 'xy',
      x_range: [10, 20],
      y_range: [40, 60],
      dataset_id: 'ds-1',
    })
    await flushPromises()
    const hint = wrapper.find('[data-test="analysis-selection-hint"]')
    expect(hint.exists()).toBe(true)
    expect(hint.text()).toContain('物化成果')
    expect(router.currentRoute.value.path).toBe('/datasets/ds-1/analysis')
    wrapper.unmount()
  })

  it('模型对比行点击导航到成果页', async () => {
    vi.mocked(client.fetchAnalysisSummary).mockResolvedValue(fullSummary('microseismic_velocity'))
    const { wrapper, router } = await mountAnalysisCenter('/datasets/ds-1/analysis')

    await wrapper.get('[data-test="module-nav-item-model_comparison"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="model-candidate-row"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/results/cand-1')
    wrapper.unmount()
  })

  it('响应式结构：存在 <900px 与 <600px 媒体查询（jsdom 无布局，源断言）', () => {
    expect(analysisViewSource).toContain('@media (max-width: 900px)')
    expect(analysisViewSource).toContain('@media (max-width: 600px)')
  })
})


// ---------------------------------------------------------------------------
// v0.8.0 第三批 Task 8：瓦斯差异化导航——gas 模块标签补全，ok 但暂无面板
// 的专属模块不生成占位导航入口
// ---------------------------------------------------------------------------

function gasAnomalyModule(): AnalysisModuleResult {
  const bins = []
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
        region: count === 0 ? 'empty' : (row + col) % 2 === 0 ? 'high' : 'normal',
      })
    }
  }
  return {
    module_id: 'spatial_anomaly',
    status: 'ok',
    payload: {
      grid_size: 4,
      cell_count: 16,
      bounds: { x: [0, 40], y: [0, 80] },
      thresholds: {
        high: 3.2,
        low: 2.0,
        source: 'cell_mean_quantiles_p25_p75',
        method: '高值阈值=非空网格单元均值 p75、低值阈值=非空网格单元均值 p25',
      },
      non_empty_cell_count: 10,
      high_cell_count: 4,
      low_cell_count: 2,
      high_point_count: 6,
      low_point_count: 3,
      high_volume_ratio: 0.4,
      low_volume_ratio: 0.2,
      bins,
    },
    message: null,
  }
}

// 瓦斯完整壳夹具：通用模块 + spatial_anomaly/depth_slices/gradient ok（后两者
// ok 但暂无面板，不得生成占位导航入口）
function gasSummary(): AnalysisSummaryResponse {
  const base = summaryOf('gas_content')
  base.variable = { name: 'CH4_content', unit: 'ml/g' }
  const modules: AnalysisModuleResult[] = [
    { module_id: 'quality', status: 'ok', payload: {}, message: null },
    { module_id: 'statistics', status: 'ok', payload: {}, message: null },
    { module_id: 'distribution', status: 'ok', payload: { bin_count: 0, bins: [] }, message: null },
    gasAnomalyModule(),
    { module_id: 'profile_slices', status: 'ok', payload: { axes: [] }, message: null },
    comparisonModule([MATERIALIZED_CANDIDATE]),
    {
      module_id: 'depth_slices',
      status: 'ok',
      payload: {
        thresholds: {
          high: 18.9,
          low: 3.2,
          source: 'valid_value_quantiles_p25_p75',
          method: '高值阈值=有效值 p75、低值阈值=有效值 p25',
        },
        slice_count: 16,
        slices: [],
      },
      message: null,
    },
    {
      module_id: 'gradient',
      status: 'ok',
      payload: {
        grid_size: 16,
        pair_count: 480,
        excluded_pair_count: 452,
        count: 28,
        mean: 4.87,
        p95: 11.92,
        max: 17.35,
      },
      message: null,
    },
  ]
  return { ...base, modules }
}

describe('AnalysisCenterView（gas_content 差异化导航）', () => {
  it('gas 模块标签补全；ok 但暂无面板的专属模块无占位入口；无规范判断词', async () => {
    vi.mocked(client.fetchAnalysisSummary).mockResolvedValue(gasSummary())
    const { wrapper } = await mountAnalysisCenter('/datasets/ds-1/analysis')

    expect(wrapper.find('[data-test="analysis-profile-badge"]').text()).toContain('瓦斯含量')
    // gas 差异化模块标签
    expect(wrapper.find('[data-test="module-nav-item-distribution"]').text()).toContain('含量分布')
    expect(wrapper.find('[data-test="module-nav-item-spatial_anomaly"]').text()).toContain(
      '含量区域',
    )
    expect(wrapper.find('[data-test="module-nav-item-profile_slices"]').exists()).toBe(true)
    // ok 但暂无面板的专属模块（depth_slices/gradient）不生成占位导航入口
    expect(wrapper.find('[data-test="module-nav-item-depth_slices"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="module-nav-item-gradient"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('速度梯度')
    // 默认主焦点为 spatial_anomaly（gas 无 spatial_extent），面板为差异化标题
    expect(wrapper.find('[data-test="spatial-feature-panel"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('高/低含量区域')
    for (const term of ['危险', '安全', '爆炸', '突出']) {
      expect(wrapper.text()).not.toContain(term)
    }
    wrapper.unmount()
  })
})
