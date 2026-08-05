import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type {
  DatasetPoints,
  ExperimentRecord,
  FormalSelectionRecord,
  RenderCapability,
  ResultMetadata,
  ResultPreview,
} from '../../../api/types'
import * as client from '../../../api/client'
import ResultWorkbenchView from '../../../views/ResultWorkbenchView.vue'
import router from '../../../router'

// v0.7.0 Task 8：成果工作台不再假定 microseismic_dat_bundle 派生证据——
// DAT 派生端点与证据图层退出产品面；通用网格采样辅助点保留。

vi.mock('../../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/client')>()
  return {
    ...actual,
    fetchResult: vi.fn(),
    materializeResult: vi.fn(),
    fetchResultPreview: vi.fn(),
    fetchResultSlice: vi.fn(),
    fetchExperiment: vi.fn(),
    fetchFormalSelections: vi.fn(),
    selectFormal: vi.fn(),
    createExport: vi.fn(),
    createPublication: vi.fn(),
    fetchDatasetPoints: vi.fn(),
    fetchResultRenderCapability: vi.fn(),
    fetchResultRenderAsset: vi.fn(),
    createResultRenderAsset: vi.fn(),
  }
})

const CAPABILITY: RenderCapability = {
  supported: true,
  reason_code: null,
  reason: null,
  source_kind: 'candidate_result',
  source_id: 'r1',
  dimension: '3d',
  grid_kind: 'regular',
  property_name: 'Vx',
  units: 'km/s',
  geolocation_status: 'display_anchor_only',
  display_transform: { contract: 'wgs84_display_anchor_v1' } as never,
}

function makeMetadata(): ResultMetadata {
  return {
    result_id: 'r1',
    case_id: 'c-micro',
    experiment_id: 'e1',
    run_id: 'run1',
    dataset_version_id: 'ds-micro',
    algorithm: 'ordinary_kriging',
    fingerprint: 'f'.repeat(64),
    dimension: '3d',
    shape: [4, 4, 4],
    value_range: [1.5, 3.2],
    grid_sha256: 'a'.repeat(64),
    created_at: '2026-08-05T00:00:00+00:00',
  } as unknown as ResultMetadata
}

function mountWorkbench() {
  vi.mocked(client.materializeResult).mockResolvedValue(makeMetadata())
  vi.mocked(client.fetchExperiment).mockResolvedValue({
    id: 'e1',
    case_id: 'c-micro',
    name: 'exp',
    status: 'succeeded',
    params: { dataset_version_id: 'ds-micro' },
    created_at: '',
    updated_at: '',
  } as unknown as ExperimentRecord)
  vi.mocked(client.fetchDatasetPoints).mockResolvedValue({
    x: [0, 1],
    y: [0, 1],
    z: [0, 1],
    values: [2.1, 2.2],
  } as unknown as DatasetPoints)
  vi.mocked(client.fetchResultPreview).mockResolvedValue({
    x: [0, 1],
    y: [0, 1],
    z: [0, 1],
    values: [2.1, 2.2],
    is_nodata: [false, false],
  } as unknown as ResultPreview)
  vi.mocked(client.fetchFormalSelections).mockResolvedValue({
    case_id: 'c-micro',
    selections: [] as FormalSelectionRecord[],
  })
  vi.mocked(client.fetchResultRenderCapability).mockResolvedValue(CAPABILITY)
  vi.mocked(client.fetchResultRenderAsset).mockRejectedValue(
    new client.ApiError('RENDER_ASSET_NOT_FOUND', '渲染资产尚未创建', 404),
  )
  const testRouter = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/results/:resultId', name: 'result-workbench', component: ResultWorkbenchView },
    ],
  })
  return testRouter.push('/results/r1').then(() => {
    const wrapper = mount(ResultWorkbenchView, {
      global: { plugins: [testRouter, ElementPlus] },
    })
    return flushPromises().then(() => wrapper)
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ResultWorkbenchView v0.7.0（DAT 证据层退出）', () => {
  it('has no microseismic import route registered', () => {
    expect(router.resolve('/cases/builtin-microseismic-vx-1911/microseismic/import').matched).toHaveLength(0)
  })

  it('client exposes no DAT derivation calls', () => {
    expect('fetchMicroseismicDerivation' in client).toBe(false)
    expect('fetchMicroseismicDerivationPoints' in client).toBe(false)
    expect('importMicroseismic' in client).toBe(false)
  })

  it('microseismic-source result shows no evidence layers, keeps generic grid samples', async () => {
    const wrapper = await mountWorkbench()
    // 不再出现 DAT 证据图层控制组
    expect(wrapper.find('[data-test="evidence-layers"]').exists()).toBe(false)
    // 通用辅助网格采样点仍以 aux-points 提供给 NativeVolumePanel
    const panel = wrapper.findComponent({ name: 'NativeVolumePanel' })
    expect(panel.exists()).toBe(true)
    const aux = panel.props('auxPoints') as { id: string; role: string } | null
    expect(aux?.id).toBe('grid-samples')
    expect(aux?.role).toBe('auxiliary')
  })
})
