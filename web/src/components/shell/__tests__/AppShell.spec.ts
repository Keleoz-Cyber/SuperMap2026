import { mount } from '@vue/test-utils'
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

  it('keeps the presentation action disabled until the mode ships', () => {
    const wrapper = mount(AppShell, {
      global: { stubs: { RouterView: true, RouterLink: { template: '<a><slot /></a>' } } },
    })
    expect(
      wrapper.get('[data-test="presentation-mode-entry"]').attributes('aria-disabled'),
    ).toBe('true')
  })
})
