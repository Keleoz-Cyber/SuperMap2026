import { flushPromises, mount } from '@vue/test-utils'
import { createWebHashHistory, createRouter, type Router } from 'vue-router'
import { describe, expect, it } from 'vitest'
import ElementPlus from 'element-plus'
import PageNavigation from '../PageNavigation.vue'

function makeTestRouter(): Router {
  return createRouter({
    history: createWebHashHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/cases/:caseId', name: 'case-workspace', component: { template: '<div />' } },
      {
        path: '/experiments/:experimentId',
        name: 'experiment-detail',
        component: { template: '<div />' },
      },
      {
        path: '/results/:resultId',
        name: 'result-workbench',
        component: { template: '<div />' },
      },
    ],
  })
}

async function mountNav(props: Record<string, unknown>) {
  const router = makeTestRouter()
  await router.push('/')
  const wrapper = mount(PageNavigation, {
    props,
    global: { plugins: [router, ElementPlus] },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('PageNavigation breadcrumbs', () => {
  it('renders RouterLink hrefs for home, case, experiment, and result', async () => {
    const { wrapper } = await mountNav({
      caseId: 'c1',
      caseName: '案例 A',
      experimentId: 'e1',
      resultId: 'r1',
      currentLabel: '模型评估',
    })
    expect(wrapper.get('[data-test="crumb-home"]').attributes('href')).toBe('#/')
    expect(wrapper.get('[data-test="crumb-case"]').attributes('href')).toBe('#/cases/c1')
    expect(wrapper.get('[data-test="crumb-experiment"]').attributes('href')).toBe('#/experiments/e1')
    expect(wrapper.get('[data-test="crumb-result"]').attributes('href')).toBe('#/results/r1')
  })

  it('marks the current label with aria-current="page"', async () => {
    const { wrapper } = await mountNav({ currentLabel: '回收站' })
    const current = wrapper.get('.crumb-current')
    expect(current.attributes('aria-current')).toBe('page')
    expect(current.text()).toBe('回收站')
  })

  it('renders dataset crumb as text-only (no href)', async () => {
    const { wrapper } = await mountNav({ caseId: 'c1', datasetId: 'ds1', currentLabel: '空间结构分析' })
    const datasetCrumb = wrapper.get('[data-test="crumb-dataset"]')
    expect(datasetCrumb.find('a').exists()).toBe(false)
    expect(datasetCrumb.text()).toContain('数据版本')
  })

  it('renders only home when no identities are provided', async () => {
    const { wrapper } = await mountNav({})
    expect(wrapper.find('[data-test="crumb-home"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="crumb-case"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="crumb-experiment"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="crumb-result"]').exists()).toBe(false)
  })

  it('uses caseName when provided, falls back to generic label', async () => {
    const { wrapper: w1 } = await mountNav({ caseId: 'c1', caseName: '我的案例' })
    expect(w1.get('[data-test="crumb-case"]').text()).toBe('我的案例')

    const { wrapper: w2 } = await mountNav({ caseId: 'c1' })
    expect(w2.get('[data-test="crumb-case"]').text()).toBe('案例')
  })

  it('navigates home when crumb-home is clicked', async () => {
    const { wrapper, router } = await mountNav({ caseId: 'c1', currentLabel: '工作台' })
    await wrapper.get('[data-test="crumb-home"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('home')
  })

  it('navigates to case workspace when crumb-case is clicked', async () => {
    const { wrapper, router } = await mountNav({ caseId: 'c1', currentLabel: '工作台' })
    await wrapper.get('[data-test="crumb-case"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('case-workspace')
    expect(router.currentRoute.value.params.caseId).toBe('c1')
  })
})
