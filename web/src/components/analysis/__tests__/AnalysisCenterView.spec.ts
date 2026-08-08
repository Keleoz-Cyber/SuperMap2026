import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as client from '../../../api/client'
import type { AnalysisSummaryResponse } from '../../../api/types'
import AnalysisCenterView from '../../../views/AnalysisCenterView.vue'

// v0.8.0 第二批 Task 4：分析中心占位视图三态（加载中 / 成功 profile 徽标 /
// 类型化错误）。完整 A+B 壳与模块降级测试属 Task 5，在本文件上扩展。

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

describe('AnalysisCenterView（占位）', () => {
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
    expect(variable.text()).toContain('Vx')
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
})
