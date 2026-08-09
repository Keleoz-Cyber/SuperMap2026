import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import ElementPlus from 'element-plus'
import PresentationOverlay from '../PresentationOverlay.vue'
import { resetPresentationStore, usePresentationStore } from '../../../stores/presentation'

describe('PresentationOverlay', () => {
  beforeEach(() => {
    resetPresentationStore()
  })

  it('renders chapter title, position and navigation controls with accessible names', () => {
    const store = usePresentationStore()
    store.enter()
    const wrapper = mount(PresentationOverlay, { global: { plugins: [ElementPlus] } })
    expect(wrapper.get('[data-test="presentation-title"]').text()).toContain('平台能力总览')
    expect(wrapper.get('[data-test="presentation-position"]').text()).toContain('1 / 6')
    expect(wrapper.get('[data-test="presentation-exit"]').attributes('aria-label')).toBe('退出答辩模式')
    expect(wrapper.get('[data-test="presentation-prev"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-test="presentation-next"]').exists()).toBe(true)
  })

  it('emits navigation intents through the store-backed controls', async () => {
    const store = usePresentationStore()
    store.enter()
    const wrapper = mount(PresentationOverlay, { global: { plugins: [ElementPlus] } })
    await wrapper.get('[data-test="presentation-next"]').trigger('click')
    expect(store.currentId.value).toBe('resistivity')
    await wrapper.get('[data-test="presentation-prev"]').trigger('click')
    expect(store.currentId.value).toBe('overview')
    await wrapper.get('[data-test="presentation-exit"]').trigger('click')
    expect(store.active.value).toBe(false)
  })

  it('chapter dots allow direct selection', async () => {
    const store = usePresentationStore()
    store.enter()
    const wrapper = mount(PresentationOverlay, { global: { plugins: [ElementPlus] } })
    await wrapper.get('[data-test="presentation-chapter-gas"]').trigger('click')
    await flushPromises()
    expect(store.currentId.value).toBe('gas')
  })
})
