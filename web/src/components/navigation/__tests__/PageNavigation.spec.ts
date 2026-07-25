import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import PageNavigation from '../PageNavigation.vue'

function makeTestRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      {
        path: '/experiments/:experimentId',
        name: 'experiment-detail',
        component: { template: '<div />' },
      },
      {
        path: '/cases/:caseId/experiments/new',
        name: 'experiment-create',
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

describe('PageNavigation', () => {
  beforeEach(() => {})

  it('uses the named home route with a visible text button', async () => {
    const { wrapper, router } = await mountNav({ home: true })
    const button = wrapper.get('[data-test="nav-home"]')
    expect(button.text()).toContain('返回首页')
    expect(button.attributes('tabindex')).not.toBe('-1')
    await button.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('home')
  })

  it('routes to the owning experiment by id', async () => {
    const { wrapper, router } = await mountNav({ experimentId: 'exp-1' })
    const button = wrapper.get('[data-test="nav-experiment"]')
    expect(button.text()).toContain('返回实验')
    await button.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value).toMatchObject({
      name: 'experiment-detail',
      params: { experimentId: 'exp-1' },
    })
  })

  it('routes to a new experiment of the current case', async () => {
    const { wrapper, router } = await mountNav({ home: true, caseId: 'c-9', newExperiment: true })
    const button = wrapper.get('[data-test="nav-new-experiment"]')
    expect(button.text()).toContain('新建实验')
    await button.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value).toMatchObject({
      name: 'experiment-create',
      params: { caseId: 'c-9' },
    })
  })

  it('never uses history.back / router.back', async () => {
    const { wrapper, router } = await mountNav({ home: true, experimentId: 'exp-1' })
    const backSpy = vi.spyOn(router, 'back')
    await wrapper.get('[data-test="nav-home"]').trigger('click')
    await flushPromises()
    expect(backSpy).not.toHaveBeenCalled()
  })

  it('hides actions that are not requested', async () => {
    const { wrapper } = await mountNav({ home: true })
    expect(wrapper.find('[data-test="nav-experiment"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="nav-new-experiment"]').exists()).toBe(false)
  })
})
