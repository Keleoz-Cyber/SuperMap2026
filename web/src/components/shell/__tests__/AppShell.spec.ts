import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppShell from '../AppShell.vue'

describe('AppShell', () => {
  it('keeps custom-data and presentation actions available with accessible names', () => {
    const wrapper = mount(AppShell, {
      global: { stubs: { RouterView: true, RouterLink: { template: '<a><slot /></a>' } } },
    })
    expect(wrapper.get('[data-test="global-create-case"]').text()).toContain('导入数据')
    expect(wrapper.get('[data-test="presentation-mode-entry"]').attributes('aria-label')).toBe(
      '进入答辩模式',
    )
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

  it('presentation entry links to the presentation route', () => {
    const wrapper = mount(AppShell, {
      global: { stubs: { RouterView: true, RouterLink: { template: '<a><slot /></a>' } } },
    })
    const entry = wrapper.get('[data-test="presentation-mode-entry"]')
    expect(entry.attributes('aria-label')).toBe('进入答辩模式')
    expect(entry.attributes('aria-disabled')).toBeUndefined()
  })

  it('hides the global header and every edit/danger entry on the presentation route', async () => {
    const { createMemoryHistory, createRouter } = await import('vue-router')
    const stub = { template: '<div />' }
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'home', component: stub },
        { path: '/trash', name: 'trash', component: stub },
        { path: '/cases/new', name: 'case-create', component: stub },
        { path: '/presentation', name: 'presentation', component: stub },
      ],
    })
    await router.push('/presentation')
    const wrapper = mount(AppShell, {
      global: {
        plugins: [router],
        stubs: { RouterView: true, RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    await flushPromises()
    expect(wrapper.find('[data-test="app-global-header"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="global-create-case"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="presentation-mode-entry"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="shell-trash-link"]').exists()).toBe(false)

    await router.push('/')
    await flushPromises()
    expect(wrapper.find('[data-test="app-global-header"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="global-create-case"]').exists()).toBe(true)
  })
})
