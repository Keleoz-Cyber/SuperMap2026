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

const chartInstances: Array<{
  dispose: ReturnType<typeof vi.fn>
  setOption: ReturnType<typeof vi.fn>
}> = []
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
    global: {
      plugins: [ElementPlus],
      stubs: {
        SliceHeatmap: {
          template: '<div data-test="slice-heatmap-stub" />',
          methods: {
            capturePng: () => Promise.resolve(new Blob(['png'], { type: 'image/png' })),
          },
        },
      },
    },
    attachTo: document.body,
  })
}

describe('ResultGridEvidence（V6 四标签）', () => {
  it('机器学习成果在模型可信度中展示基线比较证据', async () => {
    const analysis = structuredClone(RESULT_ANALYSIS_MOCK_3D)
    analysis.model_evidence.algorithm = 'random_forest_spatial'
    analysis.machine_learning = {
      algorithm: 'random_forest_spatial',
      comparison_status: 'comparable',
      comparison_reason_code: null,
      baseline: {
        result_id: 'kriging-1',
        algorithm: 'ordinary_kriging',
        rmse: 6.5,
        mae: 4.2,
        r2: 0.91,
        bias: 0.08,
        common_valid_count: 1722,
        fold_assignments_sha256: 'a'.repeat(64),
      },
      metric_change: {
        rmse_absolute: 0.2,
        rmse_percent: 3.077,
        mae_absolute: 0.1,
        mae_percent: 2.381,
      },
      improved_over_kriging: false,
      available_fields: ['prediction', 'model_dispersion'],
      dispersion_semantics: 'model_dispersion_reference',
      limitations: ['模型离散度仅作参考，不是严格置信区间。'],
      technical_details: {
        feature_version: 'spatial_features.v1',
        sklearn_version: '1.7.2',
        validation_method: 'spatial_kfold',
        common_valid_count: 1722,
        fold_assignments_sha256: 'a'.repeat(64),
      },
    }
    const wrapper = mountEvidence({ analysis })
    await wrapper.get('[data-test="ge-tab-model"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="ml-model-evidence"]').text()).toContain('未优于普通克里金')
    expect(wrapper.get('[data-test="ge-pane-model"]').text()).toContain('随机森林空间预测')
  })

  it('只渲染四个一级标签', async () => {
    const wrapper = mountEvidence()
    await flushPromises()
    const tabs = wrapper.findAll('[data-test^="ge-tab-"]')
    expect(tabs.map((t) => t.text())).toEqual(['成果概览', '切片分析', '模型可信度', '数据与导出'])
  })

  it('成果组成环图不绘制外侧标签和重复图例，避免窄卡片内遮挡', async () => {
    const before = chartInstances.length
    const wrapper = mountEvidence()
    await flushPromises()
    const composition = chartInstances[before]
    const option = composition.setOption.mock.calls.at(-1)?.[0] as {
      legend?: { show?: boolean }
      series?: Array<{ label?: { show?: boolean }; labelLine?: { show?: boolean } }>
    }
    expect(option.legend?.show).toBe(false)
    expect(option.series?.[0]?.label?.show).toBe(false)
    expect(option.series?.[0]?.labelLine?.show).toBe(false)
    wrapper.unmount()
  })

  it('综合分析：组成环图 + 深度趋势图 + 层段表（成果网格口径）', async () => {
    const wrapper = mountEvidence()
    await flushPromises()
    const pane = wrapper.get('[data-test="ge-pane-overview"]')
    expect(wrapper.get('[data-test="ge-scope-badge"]').text()).toContain('成果网格')
    expect(wrapper.find('[data-test="ge-composition-chart"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="ge-depth-chart"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="ge-depth-chart-scroll"]').exists()).toBe(true)
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
    expect(wrapper.get('[data-test="ge-pane-slices"]').classes()).toContain('no-current-slice')
    await wrapper.setProps({ currentSlice: SLICE_ANALYSIS_MOCK })
    await flushPromises()
    const pane = wrapper.get('[data-test="ge-pane-slices"]')
    expect(pane.classes()).not.toContain('no-current-slice')
    expect(pane.text()).toContain('有效 11')
    expect(pane.text()).toContain('27.3%')
    expect(wrapper.find('[data-test="ge-slice-heatmap"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="ge-components-chart"]').exists()).toBe(true)
    expect(pane.text()).toContain('标准差')
    await wrapper.get('[data-test="ge-component-1"]').trigger('click')
    expect(wrapper.emitted('focus-component')).toEqual([[1]])
  })

  it('切片分析从唯一热力图生成 PNG 并调用注入的导出动作', async () => {
    const exportSlice = vi.fn().mockResolvedValue(undefined)
    const wrapper = mountEvidence({ currentSlice: SLICE_ANALYSIS_MOCK, exportSlice })
    await wrapper.get('[data-test="ge-tab-slices"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="ge-export-slice"]').trigger('click')
    await flushPromises()
    expect(exportSlice).toHaveBeenCalledWith(expect.any(Blob))
  })

  it('成果摘要不可用时仍独立展示权威切片、统计和导出', async () => {
    const exportSlice = vi.fn().mockResolvedValue(undefined)
    const wrapper = mountEvidence({
      analysis: null,
      currentSlice: SLICE_ANALYSIS_MOCK,
      exportSlice,
      activeTab: 'slices',
    })
    await flushPromises()
    const pane = wrapper.get('[data-test="ge-pane-slices"]')
    expect(wrapper.find('[data-test="ge-slice-heatmap"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="ge-slice-statistics"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="ge-export-slice"]').exists()).toBe(true)
    expect(pane.text()).toContain('成果异常区域分析暂不可用')
    expect(wrapper.find('[data-test="ge-empty"]').exists()).toBe(false)
  })

  it('模型证据：后端指标 + 残差类型化空态', async () => {
    const wrapper = mountEvidence()
    await flushPromises()
    await wrapper.get('[data-test="ge-tab-model"]').trigger('click')
    await flushPromises()
    const pane = wrapper.get('[data-test="ge-pane-model"]')
    expect(pane.text()).toContain('普通克里金')
    expect(pane.text()).not.toContain('ordinary_kriging')
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

  it('四类证据使用各自布局，切换标签后不继承上一页的内部滚动位置', async () => {
    const wrapper = mountEvidence()
    await flushPromises()

    const overview = wrapper.get('[data-test="ge-pane-overview"]')
    expect(overview.classes()).toContain('layout-overview')
    ;(overview.element as HTMLElement).scrollTop = 160

    await wrapper.get('[data-test="ge-tab-slices"]').trigger('click')
    await flushPromises()
    const slices = wrapper.get('[data-test="ge-pane-slices"]')
    expect(slices.classes()).toContain('layout-slices')
    expect(slices.element).not.toBe(overview.element)
    expect((slices.element as HTMLElement).scrollTop).toBe(0)

    await wrapper.get('[data-test="ge-tab-model"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="ge-pane-model"]').classes()).toContain('layout-model')

    await wrapper.get('[data-test="ge-tab-provenance"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="ge-pane-provenance"]').classes()).toContain('layout-provenance')
  })

  it('数据溯源默认只展示摘要，输入样本详细分析按需展开', async () => {
    const wrapper = mountEvidence({
      datasetFindings: [
        {
          id: 'quality',
          title: '数据质量',
          statement: '有效数据 96/100',
          evidence: ['重复坐标 0'],
          source: { datasetId: 'ds-1', sourceSha256: 'abc', calculationVersion: 'analysis.v1' },
          confidence: 'verified',
          limitations: [],
        },
      ],
    })
    await wrapper.get('[data-test="ge-tab-provenance"]').trigger('click')
    await flushPromises()

    const details = wrapper.get('[data-test="ge-input-details"]')
    expect(details.attributes('open')).toBeUndefined()
    expect(details.get('summary').text()).toContain('查看输入样本详细分析')
    expect(wrapper.get('[data-test="ge-input-summary"]').text()).toContain('96')
    expect(wrapper.get('[data-test="ge-input-summary"]').find('[data-test="ge-input-details"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="ge-input-analysis"]').classes()).toContain('input-analysis-card')
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
