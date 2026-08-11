import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppShell from '../AppShell.vue'

describe('AppShell', () => {
  it('keeps custom-data action available; presentation entry is removed from the product', () => {
    const wrapper = mount(AppShell, {
      global: { stubs: { RouterView: true, RouterLink: { template: '<a><slot /></a>' } } },
    })
    expect(wrapper.get('[data-test="global-create-case"]').text()).toContain('导入数据')
    // v0.9.0 V6 Task 6：答辩模式入口完整退役
    expect(wrapper.find('[data-test="presentation-mode-entry"]').exists()).toBe(false)
    expect(wrapper.get('main').attributes('id')).toBe('main-content')
  })

  it('exposes a skip link targeting the main content', () => {
    const wrapper = mount(AppShell, {
      global: { stubs: { RouterView: true, RouterLink: { template: '<a><slot /></a>' } } },
    })
    const skip = wrapper.get('.skip-link')
    expect(skip.attributes('href')).toBe('#main-content')
  })

  it('renders brand, home navigation and trash entry through named routes', () => {
    const wrapper = mount(AppShell, {
      global: { stubs: { RouterView: true, RouterLink: { template: '<a><slot /></a>' } } },
    })
    expect(wrapper.get('[data-test="shell-brand"]').text()).toContain('GeoModelingPlatform')
    expect(wrapper.find('[data-test="shell-home-link"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="shell-trash-link"]').exists()).toBe(true)
  })

  it('legacy /presentation deep links redirect home via the catch-all route', async () => {
    // 路由合同在 web/src/router/index.ts：/presentation 不再注册，由末尾
    // catch-all 重定向首页；这里用同等 catch-all 验证旧深链行为
    const { createMemoryHistory, createRouter } = await import('vue-router')
    const stub = { template: '<div />' }
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'home', component: stub },
        { path: '/:pathMatch(.*)*', redirect: { name: 'home' } },
      ],
    })
    await router.push('/presentation')
    expect(router.currentRoute.value.name).toBe('home')
  })

  it('hides the global header on the result workbench route (V6 dedicated topbar)', async () => {
    const { createMemoryHistory, createRouter } = await import('vue-router')
    const stub = { template: '<div />' }
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'home', component: stub },
        { path: '/trash', name: 'trash', component: stub },
        { path: '/cases/new', name: 'case-create', component: stub },
        { path: '/results/:resultId', name: 'result-workbench', component: stub },
      ],
    })
    await router.push('/results/r1')
    const wrapper = mount(AppShell, {
      global: {
        plugins: [router],
        stubs: { RouterView: true, RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    await flushPromises()
    expect(wrapper.find('[data-test="app-global-header"]').exists()).toBe(false)

    await router.push('/')
    await flushPromises()
    expect(wrapper.find('[data-test="app-global-header"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="global-create-case"]').exists()).toBe(true)
  })
})
