import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as client from '../../../api/client'
import FormalSelectionPanel from '../FormalSelectionPanel.vue'

// v0.7.0 审查修复（Blocker 前端面）：read_only 官方案例由后端
// selection_allowed 显式给出，前端据此隐藏可写选择控件（不硬编码案例 ID）。

vi.mock('../../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/client')>()
  return { ...actual, fetchFormalSelections: vi.fn(), selectFormal: vi.fn() }
})

function mockSelections(selectionAllowed: boolean) {
  vi.mocked(client.fetchFormalSelections).mockResolvedValue({
    case_id: 'c1',
    selection_allowed: selectionAllowed,
    selections: [
      {
        id: 'sel-1',
        case_id: 'c1',
        candidate_result_id: 'cand-1',
        selected_by: 'preset-seed',
        note: '官方普通克里金基线',
        created_at: '2026-08-05T00:00:00+00:00',
      },
    ],
  })
}

describe('FormalSelectionPanel read_only 防护', () => {
  it('selection_allowed=false：隐藏可写表单，显示只读说明，绝不可提交', async () => {
    mockSelections(false)
    const wrapper = mount(FormalSelectionPanel, {
      props: { resultId: 'cand-1', caseId: 'c1' },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    expect(wrapper.find('[data-test="selection-submit"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="selection-note"]').exists()).toBe(false)
    const notice = wrapper.find('[data-test="selection-readonly"]')
    expect(notice.exists()).toBe(true)
    expect(notice.text()).toContain('只读')
    // 既有官方选择列表仍只读展示
    expect(wrapper.find('[data-test="selection-item"]').exists()).toBe(true)
    expect(client.selectFormal).not.toHaveBeenCalled()
  })

  it('能力请求失败：保持隐藏写控件（能力未知不默认可写）', async () => {
    vi.mocked(client.fetchFormalSelections).mockRejectedValue(new Error('network down'))
    const wrapper = mount(FormalSelectionPanel, {
      props: { resultId: 'cand-1', caseId: 'c1' },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    expect(wrapper.find('[data-test="selection-submit"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="selection-note"]').exists()).toBe(false)
    expect(client.selectFormal).not.toHaveBeenCalled()
  })

  it('selection_allowed=true：保留可写表单（普通案例不回归）', async () => {
    mockSelections(true)
    const wrapper = mount(FormalSelectionPanel, {
      props: { resultId: 'cand-1', caseId: 'c1' },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    expect(wrapper.find('[data-test="selection-submit"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="selection-readonly"]').exists()).toBe(false)
  })
})
