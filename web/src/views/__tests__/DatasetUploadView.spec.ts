import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as client from '../../api/client'
import type { DatasetVersionRecord } from '../../api/types'
import DatasetUploadView from '../DatasetUploadView.vue'

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return { ...actual, uploadDataset: vi.fn() }
})

function makeDataset(overrides: Partial<DatasetVersionRecord> = {}): DatasetVersionRecord {
  return {
    id: 'ds-1',
    case_id: 'case-1',
    version: 1,
    status: 'uploaded',
    profile: {},
    created_at: '2026-08-07T00:00:00+00:00',
    ...overrides,
  }
}

async function mountView(caseId = 'case-1') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/cases/:caseId/datasets/new',
        name: 'dataset-upload',
        component: DatasetUploadView,
      },
      {
        path: '/cases/:caseId/datasets/:datasetId/prepare',
        name: 'dataset-prepare',
        component: { template: '<div />' },
      },
      { path: '/cases/:caseId', name: 'case-workspace', component: { template: '<div />' } },
    ],
  })
  await router.push(`/cases/${caseId}/datasets/new`)
  await router.isReady()
  const wrapper = mount(DatasetUploadView, {
    global: { plugins: [router, ElementPlus] },
  })
  return { wrapper, router }
}

function setFile(wrapper: VueWrapper, filename = 'test.csv') {
  const file = new File(['x,y,z,value\n1,2,3,4'], filename, { type: 'text/csv' })
  const input = wrapper.find('[data-test="dataset-file"]').element as HTMLInputElement
  Object.defineProperty(input, 'files', {
    value: [file],
    writable: false,
    configurable: true,
  })
}

describe('DatasetUploadView', () => {
  it('uses the shared three-step workbench and explains that it adds a new version', async () => {
    const { wrapper } = await mountView('case-7')

    expect(wrapper.get('[data-test="intake-mode-title"]').text()).toContain('新增数据版本')
    expect(wrapper.findAll('[data-test^="intake-step-"]')).toHaveLength(3)
    expect(wrapper.text()).toContain('不会覆盖既有数据与成果')

    setFile(wrapper, 'resistivity.csv')
    await wrapper.find('[data-test="dataset-file"]').trigger('change')
    expect(wrapper.get('[data-test="selected-file-summary"]').text()).toContain('resistivity.csv')
  })

  it('upload succeeds and navigates to prepare page', async () => {
    vi.mocked(client.uploadDataset).mockResolvedValue(makeDataset({ id: 'ds-42' }))
    const { wrapper, router } = await mountView('case-7')

    setFile(wrapper)
    await wrapper.find('[data-test="dataset-file"]').trigger('change')
    await wrapper.find('[data-test="dataset-submit"]').trigger('click')
    await flushPromises()

    expect(client.uploadDataset).toHaveBeenCalledWith('case-7', expect.any(File))
    expect(router.currentRoute.value.name).toBe('dataset-prepare')
    expect(router.currentRoute.value.params.caseId).toBe('case-7')
    expect(router.currentRoute.value.params.datasetId).toBe('ds-42')
  })

  it('upload failure shows error', async () => {
    vi.mocked(client.uploadDataset).mockRejectedValue(
      new client.ApiError('UPLOAD_TOO_LARGE', '文件超出大小限制', 413),
    )
    const { wrapper } = await mountView('case-1')

    setFile(wrapper)
    await wrapper.find('[data-test="dataset-file"]').trigger('change')
    await wrapper.find('[data-test="dataset-submit"]').trigger('click')
    await flushPromises()

    const err = wrapper.find('[data-test="upload-error"]')
    expect(err.exists()).toBe(true)
    expect(err.text()).toContain('文件超出大小限制')
  })
})
