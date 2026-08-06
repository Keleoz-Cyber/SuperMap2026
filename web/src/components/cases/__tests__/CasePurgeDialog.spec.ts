import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ElementPlus from 'element-plus'
import CasePurgeDialog from '../CasePurgeDialog.vue'

describe('CasePurgeDialog', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  function mountDialog(caseName = 'test-case') {
    return mount(CasePurgeDialog, {
      props: { visible: true, caseName },
      global: { plugins: [ElementPlus] },
      attachTo: document.body,
    })
  }

  function setInputValue(input: HTMLInputElement, value: string) {
    input.value = value
    input.dispatchEvent(new Event('input', { bubbles: true }))
  }

  it('confirm button is disabled until exact name match', async () => {
    mountDialog()
    await flushPromises()

    const confirmBtn = document.querySelector('[data-test="purge-confirm-btn"]') as HTMLButtonElement
    expect(confirmBtn).toBeTruthy()
    expect(confirmBtn.disabled).toBe(true)

    const input = document.querySelector('[data-test="purge-name-input"]') as HTMLInputElement
    setInputValue(input, 'test-cas')
    await flushPromises()
    expect(confirmBtn.disabled).toBe(true)

    setInputValue(input, 'test-case')
    await flushPromises()
    expect(confirmBtn.disabled).toBe(false)
  })

  it('confirm button is not auto-focused', async () => {
    mountDialog('focus-test')
    await flushPromises()

    const confirmBtn = document.querySelector('[data-test="purge-confirm-btn"]') as HTMLButtonElement
    expect(document.activeElement).not.toBe(confirmBtn)
  })

  it('emits confirm with name on click when name matches', async () => {
    const wrapper = mountDialog('delete-me')
    await flushPromises()

    const input = document.querySelector('[data-test="purge-name-input"]') as HTMLInputElement
    setInputValue(input, 'delete-me')
    await flushPromises()

    const confirmBtn = document.querySelector('[data-test="purge-confirm-btn"]') as HTMLButtonElement
    confirmBtn.click()
    await flushPromises()

    expect(wrapper.emitted('confirm')).toBeTruthy()
    expect(wrapper.emitted('confirm')![0]).toEqual(['delete-me'])
  })
})
