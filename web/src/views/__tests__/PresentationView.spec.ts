import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as client from '../../api/client'
import PresentationView from '../PresentationView.vue'
import { resetPresentationStore, usePresentationStore } from '../../stores/presentation'

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    fetchHealth: vi.fn(),
    fetchCases: vi.fn(),
    fetchCaseWorkspace: vi.fn(),
    fetchAnalysisSummary: vi.fn(),
  }
})

async function mountPresentation() {
  vi.mocked(client.fetchHealth).mockResolvedValue({
    status: 'ok',
    version: '0.9.0',
    time: '2026-08-10T00:00:00+00:00',
  })
  vi.mocked(client.fetchCases).mockResolvedValue({ cases: [] })
  const stub = { template: '<div />' }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: stub },
      { path: '/presentation', name: 'presentation', component: PresentationView },
    ],
  })
  await router.push('/presentation')
  const wrapper = mount(PresentationView, {
    global: { plugins: [router, ElementPlus] },
    attachTo: document.body,
  })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  document.body.innerHTML = ''
  vi.clearAllMocks()
  resetPresentationStore()
})

describe('PresentationView', () => {
  it('ArrowRight/ArrowLeft navigate chapters within bounds', async () => {
    const store = usePresentationStore()
    const { wrapper } = await mountPresentation()
    expect(store.currentId.value).toBe('overview')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
    expect(store.currentId.value).toBe('resistivity')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))
    expect(store.currentId.value).toBe('overview')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))
    expect(store.currentId.value).toBe('overview')
    wrapper.unmount()
  })

  it('Escape exits presentation mode and returns home', async () => {
    const store = usePresentationStore()
    const { wrapper, router } = await mountPresentation()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(store.active.value).toBe(false)
    expect(router.currentRoute.value.path).toBe('/')
    wrapper.unmount()
  })

  it('missing official case chapter shows explicit degradation, never a black screen', async () => {
    const store = usePresentationStore()
    const { wrapper } = await mountPresentation()
    store.goTo('resistivity')
    await flushPromises()
    const chapter = wrapper.get('[data-test="chapter-resistivity"]')
    expect(chapter.find('[data-state="degraded"]').exists()).toBe(true)
    expect(chapter.text()).toContain('跳过')
    wrapper.unmount()
  })

  it('overview chapter renders the real capability chain', async () => {
    const { wrapper } = await mountPresentation()
    const overview = wrapper.get('[data-test="chapter-overview"]')
    expect(overview.text()).toContain('数据接入')
    expect(overview.text()).toContain('三维成果')
    wrapper.unmount()
  })
})
