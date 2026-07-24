import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type { DatasetVersionRecord, InspectionResult, QualityReport } from '../../../api/types'
import * as client from '../../../api/client'
import DatasetWizardView from '../../../views/DatasetWizardView.vue'
import CaseCreateView from '../../../views/CaseCreateView.vue'

vi.mock('../../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/client')>()
  return {
    ...actual,
    createCase: vi.fn(),
    uploadDataset: vi.fn(),
    fetchDataset: vi.fn(),
    fetchInspection: vi.fn(),
    postMapping: vi.fn(),
    validateDataset: vi.fn(),
    fetchQuality: vi.fn(),
    confirmWarnings: vi.fn(),
  }
})

const SHA = 'ab'.repeat(32)

function makeDataset(status: DatasetVersionRecord['status']): DatasetVersionRecord {
  return {
    id: 'ds1',
    case_id: 'c1',
    version: 1,
    status,
    source_path: 'var/geomodeling/uploads/c1/ds1/data.csv',
    standardized_path: status === 'uploaded' ? null : 'var/geomodeling/datasets/c1/ds1.parquet',
    profile: {
      original_filename: 'borehole.csv',
      suffix: 'csv',
      size_bytes: 2048,
      source_sha256: SHA,
      dimension: '3d',
    },
    created_at: '2026-07-23T00:00:00Z',
  }
}

const INSPECTION: InspectionResult = {
  dataset_id: 'ds1',
  case_id: 'c1',
  suffix: 'csv',
  sheet: 'Sheet1',
  columns: [
    { name: 'Easting', inferred_type: 'numeric' },
    { name: 'Northing', inferred_type: 'numeric' },
    { name: 'Depth', inferred_type: 'numeric' },
    { name: 'Rho', inferred_type: 'numeric' },
    { name: 'Note', inferred_type: 'text' },
  ],
  preview_rows: [{ Easting: 1, Northing: 2, Depth: -3, Rho: 4, Note: 'a' }],
  row_count: 6,
  candidate_mapping: { x: 'Easting', y: 'Northing', z: 'Depth', value: 'Rho' },
  limits: { max_upload_bytes: 52428800, max_upload_rows: 500000 },
  profile: { original_filename: 'borehole.csv', size_bytes: 2048, source_sha256: SHA },
}

function makeQuality(status: QualityReport['status']): QualityReport {
  const issues =
    status === 'ready'
      ? []
      : status === 'blocked'
        ? [{ code: 'MISSING_NUMERIC', kind: 'blocker' as const, message: '必填字段无法解析', details: {} }]
        : [
            { code: 'DUPLICATE_ROWS', kind: 'warning' as const, message: '存在重复行', details: {} },
            { code: 'SPARSE_POINTS', kind: 'warning' as const, message: '点稀疏', details: {} },
          ]
  return {
    status,
    checks: [],
    issues,
    statistics: {
      ranges: { x: [0, 10], y: [0, 10], z: [-9, 0], value: [1, 99] },
      unique_coordinate_count: 5,
      duplicate_count: status === 'warnings' ? 1 : 0,
      conflict_count: 0,
    },
    valid_row_count: 5,
    invalid_row_count: 1,
    row_count: 6,
    source_sha256: SHA,
    standardized_sha256: SHA,
    confirmed: status === 'ready',
    confirmed_issue_codes: [],
  }
}

function makeTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/cases/new', name: 'case-create', component: CaseCreateView },
      {
        path: '/cases/:caseId/datasets/:datasetId/prepare',
        name: 'dataset-prepare',
        component: DatasetWizardView,
      },
      {
        path: '/cases/:caseId/experiments/new',
        name: 'experiment-create',
        component: { template: '<div />' },
      },
    ],
  })
}

async function mountWizard(
  dataset: DatasetVersionRecord,
  quality: QualityReport | null,
  startPath = '/cases/c1/datasets/ds1/prepare',
) {
  vi.mocked(client.fetchDataset).mockResolvedValue(dataset)
  vi.mocked(client.fetchInspection).mockResolvedValue(INSPECTION)
  if (quality) {
    vi.mocked(client.fetchQuality).mockResolvedValue(quality)
  } else {
    vi.mocked(client.fetchQuality).mockRejectedValue(new client.ApiError('QUALITY_NOT_EVALUATED', '尚未执行', 404))
  }
  const router = makeTestRouter()
  await router.push(startPath)
  const wrapper = mount(DatasetWizardView, {
    global: { plugins: [router, ElementPlus] },
  })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('DatasetWizardView', () => {
  it('renders file step with original name, size, hash and preview', async () => {
    const { wrapper } = await mountWizard(makeDataset('uploaded'), null)
    const text = wrapper.text()
    expect(text).toContain('borehole.csv')
    expect(text).toContain('2048')
    expect(text).toContain(SHA.slice(0, 12))
    expect(text).toContain('Easting')
    expect(wrapper.find('[data-test="step-file"]').exists()).toBe(true)
  })

  it('toggles z column select by 2D/3D dimension choice', async () => {
    const { wrapper } = await mountWizard(makeDataset('uploaded'), null)
    const zBefore = wrapper.find('[data-test="mapping-z"]')
    // 候选映射带 z，默认应为 3d
    expect((wrapper.find('[data-test="dimension-3d"]').element as HTMLInputElement).checked).toBe(true)
    expect(zBefore.exists()).toBe(true)

    await wrapper.find('[data-test="dimension-2d"]').setValue(true)
    expect(wrapper.find('[data-test="mapping-z"]').exists()).toBe(false)

    await wrapper.find('[data-test="dimension-3d"]').setValue(true)
    expect(wrapper.find('[data-test="mapping-z"]').exists()).toBe(true)
  })

  it('submits field mapping and shows numeric conversion outcome', async () => {
    const mapped = makeDataset('mapped')
    mapped.profile = { ...mapped.profile, valid_row_count: 5, invalid_row_count: 1, row_count: 6 }
    vi.mocked(client.postMapping).mockResolvedValue(mapped)
    const quality = makeQuality('ready')
    vi.mocked(client.validateDataset).mockResolvedValue(quality)

    const { wrapper } = await mountWizard(makeDataset('uploaded'), null)
    await wrapper.find('[data-test="mapping-value-name"]').setValue('电阻率')
    await wrapper.find('[data-test="mapping-submit"]').trigger('click')
    await flushPromises()

    expect(client.postMapping).toHaveBeenCalledTimes(1)
    const [dsId, payload] = vi.mocked(client.postMapping).mock.calls[0]
    expect(dsId).toBe('ds1')
    expect(payload).toMatchObject({
      dimension: '3d',
      x: 'Easting',
      y: 'Northing',
      z: 'Depth',
      value: 'Rho',
      value_name: '电阻率',
      coordinate_kind: 'local_linear',
    })
    // 映射后自动执行质量校验并展示数值转换结果
    expect(client.validateDataset).toHaveBeenCalledWith('ds1')
    const text = wrapper.text()
    expect(text).toContain('5')
    expect(text).toContain('1')
  })

  it('keeps start disabled while quality is blocked', async () => {
    const { wrapper } = await mountWizard(makeDataset('blocked'), makeQuality('blocked'))
    const text = wrapper.text()
    expect(text).toContain('MISSING_NUMERIC')
    const start = wrapper.find('[data-test="start-experiment"]')
    expect(start.exists()).toBe(true)
    expect((start.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('requires exact warning confirmation before start is enabled', async () => {
    const warnings = makeQuality('warnings')
    const { wrapper } = await mountWizard(makeDataset('validated'), warnings)
    const start = wrapper.find('[data-test="start-experiment"]')
    expect((start.element as HTMLButtonElement).disabled).toBe(true)

    vi.mocked(client.confirmWarnings).mockResolvedValue({
      ...warnings,
      confirmed: true,
      confirmed_issue_codes: ['DUPLICATE_ROWS', 'SPARSE_POINTS'],
    })
    await wrapper.find('[data-test="confirm-warnings"]').trigger('click')
    await flushPromises()

    expect(client.confirmWarnings).toHaveBeenCalledWith('ds1', ['DUPLICATE_ROWS', 'SPARSE_POINTS'])
    expect((wrapper.find('[data-test="start-experiment"]').element as HTMLButtonElement).disabled).toBe(false)
  })

  it('restores ready state from the server after reload', async () => {
    const { wrapper } = await mountWizard(makeDataset('validated'), makeQuality('ready'))
    expect(client.fetchQuality).toHaveBeenCalledWith('ds1')
    expect(wrapper.find('[data-test="step-quality"]').exists()).toBe(true)
    const start = wrapper.find('[data-test="start-experiment"]')
    expect((start.element as HTMLButtonElement).disabled).toBe(false)
  })

  it('navigates to experiment creation when quality is ready', async () => {
    const { wrapper, router } = await mountWizard(makeDataset('validated'), makeQuality('ready'))
    await wrapper.find('[data-test="start-experiment"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/cases/c1/experiments/new')
    expect(router.currentRoute.value.query.dataset).toBe('ds1')
  })
})

describe('CaseCreateView', () => {
  it('creates the case, uploads the file and navigates to the wizard', async () => {
    vi.mocked(client.createCase).mockResolvedValue({
      id: 'c9',
      name: '新案例',
      case_type: 'generic',
      config: {},
      created_at: '2026-07-23T00:00:00Z',
      updated_at: '2026-07-23T00:00:00Z',
    })
    vi.mocked(client.uploadDataset).mockResolvedValue(makeDataset('uploaded'))

    const router = makeTestRouter()
    await router.push('/cases/new')
    const wrapper = mount(CaseCreateView, { global: { plugins: [router, ElementPlus] } })
    await flushPromises()

    await wrapper.find('[data-test="case-name"]').setValue('新案例')
    const file = new File(['x,y,z,v\n1,2,3,4\n'], 'borehole.csv', { type: 'text/csv' })
    const input = wrapper.find('[data-test="case-file"]')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await wrapper.find('[data-test="case-submit"]').trigger('click')
    await flushPromises()

    expect(client.createCase).toHaveBeenCalledWith('新案例', 'generic')
    expect(client.uploadDataset).toHaveBeenCalledTimes(1)
    expect(vi.mocked(client.uploadDataset).mock.calls[0][0]).toBe('c9')
    expect(router.currentRoute.value.path).toBe('/cases/c9/datasets/ds1/prepare')
  })
})
