import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as client from '../../api/client'
import type { CaseSummary } from '../../api/types'
import HomeView from '../HomeView.vue'

// v0.6.1：首页上传案例卡的主打成果入口（featured_result）组件级回归。

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    fetchCases: vi.fn(),
    fetchRhoPublishStatus: vi.fn(),
  }
})

const BENCH_CASE: CaseSummary = {
  case_id: 'case-bench-32',
  title: '体积基准 32³',
  status: 'active',
  source_kind: 'upload',
  case_type: 'generic',
  created_at: '2026-08-01T00:00:00+00:00',
  featured_result: {
    result_id: 'cand-bench-32',
    url: '/results/cand-bench-32',
    materialized: true,
  },
  links: { detail: '/api/cases/case-bench-32', publish_status: null },
}

const PLAIN_UPLOAD_CASE: CaseSummary = {
  case_id: 'case-plain',
  title: '普通上传案例',
  status: 'active',
  source_kind: 'upload',
  case_type: 'generic',
  created_at: '2026-08-01T00:00:00+00:00',
  featured_result: null,
  links: { detail: '/api/cases/case-plain', publish_status: null },
}

async function mountHome(cases: CaseSummary[]) {
  vi.mocked(client.fetchCases).mockResolvedValue({ cases })
  vi.mocked(client.fetchRhoPublishStatus).mockRejectedValue(new Error('iServer offline'))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: HomeView },
      { path: '/results/:resultId', name: 'result-workbench', component: { template: '<div />' } },
      {
        path: '/cases/:caseId/experiments/new',
        name: 'experiment-create',
        component: { template: '<div />' },
      },
      { path: '/cases/new', name: 'case-create', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  const wrapper = mount(HomeView, {
    global: { plugins: [router, ElementPlus] },
    attachTo: document.body,
  })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  document.body.innerHTML = ''
  vi.clearAllMocks()
})

describe('HomeView featured_result 入口', () => {
  it('有 featured_result 的上传卡：主入口直达成果页，新建实验为次操作', async () => {
    const { wrapper, router } = await mountHome([BENCH_CASE])

    const primary = wrapper.find('[data-test="open-featured-result"]')
    expect(primary.exists()).toBe(true)
    expect(primary.text()).toContain('查看体渲染成果')
    // 次级操作保留且不与主入口混淆
    const secondary = wrapper.find('[data-test="new-experiment"]')
    expect(secondary.exists()).toBe(true)
    expect(secondary.text()).toContain('新建实验')
    // 不再显示「进入调参实验室」主按钮
    expect(wrapper.text()).not.toContain('进入调参实验室')

    // 主入口导航到 featured_result.url，且不触发卡片点击的实验创建导航
    await primary.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/results/cand-bench-32')
  })

  it('新建实验次操作仍进入实验创建页', async () => {
    const { wrapper, router } = await mountHome([BENCH_CASE])

    await wrapper.find('[data-test="new-experiment"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/cases/case-bench-32/experiments/new')
  })

  it('无 featured_result 的上传卡：保持「进入调参实验室」原入口', async () => {
    const { wrapper, router } = await mountHome([PLAIN_UPLOAD_CASE])

    expect(wrapper.find('[data-test="open-featured-result"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="new-experiment"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('进入调参实验室')

    // 卡片点击行为不变：进入调参实验室
    await wrapper.find('.case-card').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/cases/case-plain/experiments/new')
  })
})
