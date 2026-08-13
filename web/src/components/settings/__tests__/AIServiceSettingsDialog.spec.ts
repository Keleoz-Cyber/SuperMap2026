import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as client from '../../../api/client'
import AIServiceSettingsDialog from '../AIServiceSettingsDialog.vue'

vi.mock('../../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/client')>()
  return {
    ...actual,
    fetchAISettings: vi.fn(),
    saveAISettings: vi.fn(),
    testAISettings: vi.fn(),
    clearAISettings: vi.fn(),
  }
})

const EMPTY = {
  configured: false,
  source: 'none' as const,
  editable: true,
  storage_available: true,
  base_url: 'https://api.deepseek.com',
  model: 'deepseek-v4-flash',
  timeout_sec: 90,
  max_tokens: 4096,
}

function mountDialog() {
  return mount(AIServiceSettingsDialog, {
    props: { modelValue: true },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(client.fetchAISettings).mockResolvedValue(EMPTY)
})

describe('AIServiceSettingsDialog', () => {
  it('loads redacted status and never renders an existing key', async () => {
    vi.mocked(client.fetchAISettings).mockResolvedValue({ ...EMPTY, configured: true, source: 'windows_credential' })
    const wrapper = mountDialog()
    await flushPromises()
    expect(wrapper.get('[data-test="ai-settings-status"]').text()).toContain('已安全保存')
    expect((wrapper.get('[data-test="ai-settings-key"]').element as HTMLInputElement).value).toBe('')
    expect(wrapper.text()).not.toContain('sk-')
  })

  it('tests the entered key without saving it', async () => {
    vi.mocked(client.testAISettings).mockResolvedValue({ ok: true, code: 'DEEPSEEK_AVAILABLE', message: '连接成功' })
    const wrapper = mountDialog()
    await flushPromises()
    await wrapper.get('[data-test="ai-settings-key"]').setValue('sk-temporary')
    await wrapper.get('[data-test="ai-settings-test"]').trigger('click')
    await flushPromises()
    expect(client.testAISettings).toHaveBeenCalledWith(expect.objectContaining({ api_key: 'sk-temporary' }))
    expect(client.saveAISettings).not.toHaveBeenCalled()
    expect(wrapper.get('[data-test="ai-settings-feedback"]').text()).toContain('连接成功')
  })

  it('saves configuration then clears key field and refreshes status', async () => {
    vi.mocked(client.saveAISettings).mockResolvedValue({ ...EMPTY, configured: true, source: 'windows_credential' })
    const wrapper = mountDialog()
    await flushPromises()
    await wrapper.get('[data-test="ai-settings-key"]').setValue('sk-save-me')
    await wrapper.get('[data-test="ai-settings-save"]').trigger('click')
    await flushPromises()
    expect(client.saveAISettings).toHaveBeenCalledWith(expect.objectContaining({ api_key: 'sk-save-me' }))
    expect((wrapper.get('[data-test="ai-settings-key"]').element as HTMLInputElement).value).toBe('')
    expect(wrapper.get('[data-test="ai-settings-status"]').text()).toContain('已安全保存')
  })

  it('environment managed status disables save and clear', async () => {
    vi.mocked(client.fetchAISettings).mockResolvedValue({ ...EMPTY, configured: true, source: 'environment', editable: false })
    const wrapper = mountDialog()
    await flushPromises()
    expect(wrapper.get('[data-test="ai-settings-status"]').text()).toContain('环境变量')
    expect(wrapper.get('[data-test="ai-settings-save"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="ai-settings-clear"]').attributes('disabled')).toBeDefined()
  })
})
