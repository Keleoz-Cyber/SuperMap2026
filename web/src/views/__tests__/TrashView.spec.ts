import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type { TrashCaseSummary } from '../../api/types'
import * as client from '../../api/client'
import TrashView from '../TrashView.vue'

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    fetchTrashCases: vi.fn(),
    restoreCase: vi.fn(),
    purgeCase: vi.fn(),
  }
})

const T = '2026-08-01T00:00:00Z'

function makeEntry(id: string, name: string): TrashCaseSummary {
  return {
    case_id: id,
    name,
    trashed_at: T,
    counts: { datasets: 1, experiments: 2, results: 3 },
    can_restore: true,
    can_purge: true,
    reason: null,
  }
}

function makeTestRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/cases/new', name: 'case-create', component: { template: '<div />' } },
      { path: '/trash', name: 'trash', component: TrashView },
    ],
  })
}

async function mountView() {
  const router = makeTestRouter()
  await router.push('/trash')
  const wrapper = mount(TrashView, {
    global: { plugins: [router, ElementPlus] },
    attachTo: document.body,
  })
  await flushPromises()
  return { wrapper, router }
}

function setInputValue(input: HTMLInputElement, value: string) {
  input.value = value
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

describe('TrashView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    document.body.innerHTML = ''
    vi.mocked(client.fetchTrashCases).mockResolvedValue({ cases: [] })
    vi.mocked(client.restoreCase).mockResolvedValue({})
    vi.mocked(client.purgeCase).mockResolvedValue({})
  })

  it('空回收站只显示任务空态与返回/新建动作，不保留空表格', async () => {
    const { wrapper } = await mountView()

    expect(wrapper.get('[data-test="trash-empty"]').text()).toContain('没有待处理的案例')
    expect(wrapper.find('table').exists()).toBe(false)
    expect(wrapper.get('[data-test="trash-empty-home"]').attributes('href')).toBe('/')
    expect(wrapper.get('[data-test="trash-empty-create"]').attributes('href')).toBe('/cases/new')
    wrapper.unmount()
  })

  it('renders correct count of trashed cases', async () => {
    vi.mocked(client.fetchTrashCases).mockResolvedValue({
      cases: [
        makeEntry('c1', '案例A'),
        makeEntry('c2', '案例B'),
        makeEntry('c3', '案例C'),
      ],
    })
    const { wrapper } = await mountView()
    const rows = wrapper.findAll('[data-test="trash-row"]')
    expect(rows).toHaveLength(3)
    // Semantic table: one <table> with <thead> and <tbody>
    expect(wrapper.findAll('table').length).toBe(1)
    expect(wrapper.find('thead').exists()).toBe(true)
    expect(wrapper.find('tbody').exists()).toBe(true)
    expect(wrapper.findAll('[data-test="trash-mobile-item"]')).toHaveLength(3)
    wrapper.unmount()
  })

  it('restore calls restoreCase and refreshes the list', async () => {
    vi.mocked(client.fetchTrashCases).mockResolvedValueOnce({
      cases: [makeEntry('c1', '案例A'), makeEntry('c2', '案例B')],
    })
    vi.mocked(client.fetchTrashCases).mockResolvedValueOnce({
      cases: [makeEntry('c2', '案例B')],
    })
    const { wrapper } = await mountView()

    const restoreBtns = wrapper.findAll('[data-test="restore-case"]')
    expect(restoreBtns).toHaveLength(2)
    await restoreBtns[0].trigger('click')
    await flushPromises()

    expect(client.restoreCase).toHaveBeenCalledWith('c1')
    expect(client.fetchTrashCases).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('purge dialog exact-name gate works (button disabled until match)', async () => {
    vi.mocked(client.fetchTrashCases).mockResolvedValue({
      cases: [makeEntry('c1', '删除我')],
    })
    const { wrapper } = await mountView()

    await wrapper.find('[data-test="purge-case-open"]').trigger('click')
    await flushPromises()

    const confirmBtn = document.querySelector('[data-test="purge-confirm-btn"]') as HTMLButtonElement
    expect(confirmBtn).toBeTruthy()
    expect(confirmBtn.disabled).toBe(true)

    const input = document.querySelector('[data-test="purge-name-input"]') as HTMLInputElement
    setInputValue(input, '删除')
    await flushPromises()
    expect(confirmBtn.disabled).toBe(true)

    setInputValue(input, '删除我')
    await flushPromises()
    expect(confirmBtn.disabled).toBe(false)
    wrapper.unmount()
  })

  it('failed purge retains the row and dialog input', async () => {
    vi.mocked(client.fetchTrashCases).mockResolvedValue({
      cases: [makeEntry('c1', '不可删')],
    })
    vi.mocked(client.purgeCase).mockRejectedValue(
      new client.ApiError('PURGE_FAILED', '删除失败', 500),
    )
    const { wrapper } = await mountView()

    await wrapper.find('[data-test="purge-case-open"]').trigger('click')
    await flushPromises()

    const input = document.querySelector('[data-test="purge-name-input"]') as HTMLInputElement
    setInputValue(input, '不可删')
    await flushPromises()

    const confirmBtn = document.querySelector('[data-test="purge-confirm-btn"]') as HTMLButtonElement
    confirmBtn.click()
    await flushPromises()

    expect(wrapper.findAll('[data-test="trash-row"]')).toHaveLength(1)
    const inputAfter = document.querySelector('[data-test="purge-name-input"]') as HTMLInputElement
    expect(inputAfter).toBeTruthy()
    expect(inputAfter.value).toBe('不可删')
    wrapper.unmount()
  })
})
