import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type {
  CandidatesResponse,
  CandidateRecord,
  DatasetVersionRecord,
  ExperimentRecord,
  RenderAssetRecord,
  RenderAssetStatus,
  RenderCapability,
  ResultMetadata,
  RunRecord,
  RunStatus,
} from '../../../api/types'
import * as client from '../../../api/client'
import ExperimentView from '../../../views/ExperimentView.vue'

vi.mock('../../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/client')>()
  return {
    ...actual,
    fetchExperiment: vi.fn(),
    fetchCaseDatasets: vi.fn(),
    fetchDataset: vi.fn(),
    fetchProfessionalConfirmation: vi.fn(),
    fetchProfessionalDiagnostics: vi.fn(),
    fetchMLCapability: vi.fn(),
    createExperiment: vi.fn(),
    startRun: vi.fn(),
    fetchRun: vi.fn(),
    cancelRun: vi.fn(),
    retryRun: vi.fn(),
    fetchCandidates: vi.fn(),
    fetchResult: vi.fn(),
    materializeResult: vi.fn(),
    fetchResultRenderCapability: vi.fn(),
    fetchResultRenderAsset: vi.fn(),
    createResultRenderAsset: vi.fn(),
  }
})

const T = '2026-07-23T00:00:00Z'

const DATASET: DatasetVersionRecord = {
  id: 'ds1',
  case_id: 'c1',
  version: 1,
  status: 'validated',
  profile: { dimension: '3d', original_filename: 'borehole.csv' },
  created_at: T,
}

const MICRO_DATASET: DatasetVersionRecord = {
  id: 'ds-micro',
  case_id: 'c1',
  version: 1,
  status: 'validated',
  profile: {
    dimension: '3d',
    original_filename: 'microseismic-dat',
    source_kind: 'microseismic_dat_bundle',
    mapping: { x: 'X_LOCAL_M', y: 'Y_LOCAL_M', z: 'Z_LOCAL_M', value: 'VX_KM_S' },
  },
  created_at: T,
}

const EXP: ExperimentRecord = {
  id: 'exp1',
  case_id: 'c1',
  name: '实验一',
  params: {
    case_id: 'c1',
    name: '实验一',
    algorithm: 'idw',
    dataset_version_id: 'ds1',
    search_mode: 'manual',
    parameters: { power: 2, neighbor_count: 8 },
    validation: { method: 'spatial_kfold', folds: 3, seed: 1, holdout_fraction: 0.2 },
    grid: null,
  },
  created_at: T,
  updated_at: T,
}

function makeRun(status: RunStatus, metrics: RunRecord['metrics'] = {}, id = 'run1'): RunRecord {
  return {
    id,
    experiment_id: 'exp1',
    status,
    error_code: status === 'interrupted' ? 'PROCESS_RESTARTED' : null,
    metrics,
    retry_of_run_id: null,
    created_at: T,
    updated_at: T,
    started_at: T,
    finished_at: null,
  }
}

function makeCandidate(
  id: string,
  status: 'succeeded' | 'failed',
  rmse: number | null,
  error: CandidateRecord['error'] = null,
): CandidateRecord {
  return {
    id,
    fingerprint: `fp-${id}`,
    status,
    parameters: { power: 2 },
    metrics:
      status === 'succeeded'
        ? { total_count: 100, common_valid_count: 96, candidate_valid_count: 96, candidate_nodata_count: 4, coverage: 0.92, mae: 1, rmse: rmse ?? 1, r2: 0.9, bias: 0.1 }
        : {},
    error,
  }
}

function makeCandidates(candidates: CandidateRecord[], latestRun: RunRecord | null): CandidatesResponse {
  return { experiment_id: 'exp1', candidates, public_metrics: { common_valid_count: 96 }, latest_run: latestRun }
}

// --------------------------------------------------------- v0.6.1 成果状态区夹具
const GRID_SHA = 'ab'.repeat(32)

const RESULT_META: ResultMetadata = {
  result_id: 'cand1',
  run_id: 'run1',
  experiment_id: 'exp1',
  dataset_version_id: 'ds1',
  algorithm: 'idw',
  parameters: { power: 2 },
  dimension: '3d',
  shape: [11, 11, 11],
  cell_count: 1331,
  bounds: [
    [-150, -60],
    [260, 580],
    [-800, -200],
  ],
  resolution: [9, 32, 60],
  value_range: [10, 60],
  nodata_count: 0,
  grid_sha256: GRID_SHA,
  source_sha256: GRID_SHA,
  standardized_sha256: GRID_SHA,
  fingerprint: 'fp-cand1',
  validation: null,
  created_at: T,
}

const CAPABILITY_OK: RenderCapability = {
  source_kind: 'candidate_result',
  source_id: 'cand1',
  supported: true,
  reason_code: null,
  reason: null,
  dimension: '3d',
  grid_kind: 'regular',
  property_name: '电阻率',
  units: 'unknown',
  geolocation_status: 'display_anchor_only',
  display_transform: null,
}

function makeAsset(status: RenderAssetStatus): RenderAssetRecord {
  return {
    id: 'nc-1',
    source_kind: 'candidate_result',
    source_id: 'cand1',
    renderer: 'supermap_voxelgrid_netcdf',
    status,
    grid_sha256: GRID_SHA,
    netcdf_sha256: status === 'ready' ? 'cd'.repeat(32) : null,
    manifest_url: status === 'ready' ? '/api/render-assets/nc-1/manifest' : null,
    netcdf_url: status === 'ready' ? '/api/render-assets/nc-1/volume.nc' : null,
    error:
      status === 'failed' ? { code: 'NETCDF_WRITE_FAILED', message: '资产写入失败', details: {} } : null,
  }
}

function notMaterialized(): client.ApiError {
  return new client.ApiError('RESULT_NOT_MATERIALIZED', '成果尚未生成', 404)
}

function assetNotFound(): client.ApiError {
  return new client.ApiError('RENDER_ASSET_NOT_FOUND', '该渲染源尚未创建渲染资产', 404)
}

function makeTestRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/cases/:caseId', name: 'case-workspace', component: { template: '<div />' } },
      { path: '/cases/:caseId/experiments/new', name: 'experiment-create', component: ExperimentView },
      { path: '/experiments/:experimentId', name: 'experiment-detail', component: ExperimentView },
      { path: '/results/:resultId', name: 'result-workbench', component: { template: '<div />' } },
    ],
  })
}

async function mountAt(path: string): Promise<{ wrapper: VueWrapper; router: Router }> {
  const router = makeTestRouter()
  await router.push(path)
  const wrapper = mount(ExperimentView, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers()
  // 成果状态区默认口径：未物化（404）+ 无渲染资产（404），各用例按需覆盖
  vi.mocked(client.fetchResult).mockRejectedValue(notMaterialized())
  vi.mocked(client.materializeResult).mockResolvedValue(RESULT_META)
  vi.mocked(client.fetchResultRenderCapability).mockResolvedValue(CAPABILITY_OK)
  vi.mocked(client.fetchResultRenderAsset).mockRejectedValue(assetNotFound())
  vi.mocked(client.createResultRenderAsset).mockResolvedValue(makeAsset('ready'))
  vi.mocked(client.fetchMLCapability).mockResolvedValue({
    dataset_id: 'ds1',
    level: 'supported',
    valid_sample_count: 240,
    spatial_group_count: 40,
    available_algorithms: ['random_forest_spatial', 'kriging_rf_residual'],
    confirmation_required: false,
    reason_code: null,
    message: '样本量和独立空间分组满足机器学习空间验证要求。',
    validation_requirement: 'spatial_cross_validation',
    dispersion_semantics: 'model_dispersion_reference',
  })
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('ExperimentView 创建模式', () => {
  it('主层说明数据用途但不暴露案例和数据 UUID', async () => {
    vi.mocked(client.fetchDataset).mockResolvedValue(DATASET)
    const { wrapper } = await mountAt('/cases/c1/experiments/new?dataset=ds1')

    const context = wrapper.get('[data-test="experiment-dataset-summary"]')
    expect(context.text()).toContain('已通过质量检查')
    expect(context.text()).not.toContain('ds1')
    expect(context.text()).not.toContain('c1')
    expect(wrapper.get('[data-test="experiment-technical-details"]').text()).toContain('ds1')
    wrapper.unmount()
  })

  it('manual IDW：提交后创建实验、启动运行并跳到详情路由轮询', async () => {
    vi.mocked(client.fetchDataset).mockResolvedValue(DATASET)
    vi.mocked(client.createExperiment).mockResolvedValue(EXP)
    vi.mocked(client.startRun).mockResolvedValue(makeRun('queued'))
    vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
    vi.mocked(client.fetchCandidates).mockResolvedValue(makeCandidates([], makeRun('queued')))
    vi.mocked(client.fetchRun).mockResolvedValue(makeRun('succeeded', { completed: 1, total: 1, failed: 0 }))

    const { wrapper, router } = await mountAt('/cases/c1/experiments/new?dataset=ds1')
    expect(wrapper.find('[data-test="param-editor"]').exists()).toBe(true)

    await wrapper.find('[data-test="exp-submit"]').trigger('click')
    await flushPromises()

    expect(client.createExperiment).toHaveBeenCalledTimes(1)
    const payload = vi.mocked(client.createExperiment).mock.calls[0][0]
    expect(payload).toMatchObject({
      case_id: 'c1',
      algorithm: 'idw',
      dataset_version_id: 'ds1',
      search_mode: 'manual',
      validation: { method: 'spatial_kfold', folds: 5, seed: 20260723, holdout_fraction: 0.2 },
    })
    expect(payload.parameters).toMatchObject({ power: 2, neighbor_count: 16 })
    expect(client.startRun).toHaveBeenCalledWith('exp1')
    expect(router.currentRoute.value.path).toBe('/experiments/exp1')
    wrapper.unmount()
  })

  it('manual Kriging：auto 变模式不携带 nugget/sill/range', async () => {
    vi.mocked(client.fetchDataset).mockResolvedValue(DATASET)
    vi.mocked(client.createExperiment).mockResolvedValue(EXP)
    vi.mocked(client.startRun).mockResolvedValue(makeRun('queued'))
    vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
    vi.mocked(client.fetchCandidates).mockResolvedValue(makeCandidates([], makeRun('queued')))
    vi.mocked(client.fetchRun).mockResolvedValue(makeRun('succeeded', { completed: 1, total: 1 }))

    const { wrapper } = await mountAt('/cases/c1/experiments/new?dataset=ds1')
    await wrapper.find('[data-test="algo-kriging"]').setValue(true)
    await wrapper.find('[data-test="exp-submit"]').trigger('click')
    await flushPromises()

    const payload = vi.mocked(client.createExperiment).mock.calls[0][0]
    expect(payload.algorithm).toBe('ordinary_kriging')
    expect(payload.parameters).toMatchObject({
      variogram_model: 'spherical',
      variogram_mode: 'auto',
      neighbor_count: 24,
    })
    expect(payload.parameters).not.toHaveProperty('nugget')
    expect(payload.parameters).not.toHaveProperty('sill')
    expect(payload.parameters).not.toHaveProperty('range')
    wrapper.unmount()
  })

  it('实验性 RF 将用户确认随实验请求提交', async () => {
    vi.mocked(client.fetchDataset).mockResolvedValue(DATASET)
    vi.mocked(client.fetchMLCapability).mockResolvedValue({
      dataset_id: 'ds1',
      level: 'experimental',
      valid_sample_count: 100,
      spatial_group_count: 20,
      available_algorithms: ['random_forest_spatial'],
      confirmation_required: true,
      reason_code: 'ML_EXPERIMENTAL_DATASET',
      message: '样本规模有限，仅建议将随机森林作为实验性对照。',
      validation_requirement: 'spatial_cross_validation',
      dispersion_semantics: 'model_dispersion_reference',
    })
    vi.mocked(client.createExperiment).mockResolvedValue(EXP)
    vi.mocked(client.startRun).mockResolvedValue(makeRun('queued'))
    vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
    vi.mocked(client.fetchCandidates).mockResolvedValue(makeCandidates([], makeRun('queued')))

    const { wrapper } = await mountAt('/cases/c1/experiments/new?dataset=ds1')
    await wrapper.get('[data-test="algo-random-forest"]').setValue(true)
    await wrapper.get('[data-test="ml-experimental-confirmation-input"]').setValue(true)
    await wrapper.get('[data-test="exp-submit"]').trigger('click')
    await flushPromises()

    expect(client.fetchMLCapability).toHaveBeenCalledWith('ds1')
    expect(vi.mocked(client.createExperiment).mock.calls[0][0]).toMatchObject({
      algorithm: 'random_forest_spatial',
      ml_experimental_confirmed: true,
    })
    wrapper.unmount()
  })

  it('grid 搜索：离散列表与可见组合数预览', async () => {
    vi.mocked(client.fetchDataset).mockResolvedValue(DATASET)
    vi.mocked(client.createExperiment).mockResolvedValue(EXP)
    vi.mocked(client.startRun).mockResolvedValue(makeRun('queued'))
    vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
    vi.mocked(client.fetchCandidates).mockResolvedValue(makeCandidates([], makeRun('queued')))
    vi.mocked(client.fetchRun).mockResolvedValue(makeRun('succeeded', { completed: 1, total: 1 }))

    const { wrapper } = await mountAt('/cases/c1/experiments/new?dataset=ds1')
    await wrapper.find('[data-test="mode-grid"]').setValue(true)
    await wrapper.find('[data-test="grid-power"]').setValue('1, 2')
    await wrapper.find('[data-test="grid-neighbors"]').setValue('8, 16')
    expect(wrapper.text()).toContain('4 个候选组合')

    await wrapper.find('[data-test="exp-submit"]').trigger('click')
    await flushPromises()
    const payload = vi.mocked(client.createExperiment).mock.calls[0][0]
    expect(payload.search_mode).toBe('grid')
    expect(payload.parameters).toMatchObject({ power: [1, 2], neighbor_count: [8, 16] })
    wrapper.unmount()
  })

  it('超过 30 组合显示警告但允许提交', async () => {
    vi.mocked(client.fetchDataset).mockResolvedValue(DATASET)
    const { wrapper } = await mountAt('/cases/c1/experiments/new?dataset=ds1')
    await wrapper.find('[data-test="mode-grid"]').setValue(true)
    await wrapper.find('[data-test="grid-power"]').setValue('1,1.5,2,2.5,3,3.5')
    await wrapper.find('[data-test="grid-neighbors"]').setValue('4,8,12,16,20,24')
    expect(wrapper.text()).toContain('36 个候选组合')
    expect(wrapper.find('[data-test="count-warning"]').exists()).toBe(true)
    expect((wrapper.find('[data-test="exp-submit"]').element as HTMLButtonElement).disabled).toBe(false)
    wrapper.unmount()
  })

  it('超过 50 组合硬阻断提交', async () => {
    vi.mocked(client.fetchDataset).mockResolvedValue(DATASET)
    const { wrapper } = await mountAt('/cases/c1/experiments/new?dataset=ds1')
    await wrapper.find('[data-test="mode-grid"]').setValue(true)
    await wrapper.find('[data-test="grid-power"]').setValue('1,1.5,2,2.5,3,3.5,4,4.5')
    await wrapper.find('[data-test="grid-neighbors"]').setValue('4,8,12,16,20,24,28,32')
    expect(wrapper.text()).toContain('64 个候选组合')
    expect(wrapper.find('[data-test="count-error"]').exists()).toBe(true)
    expect((wrapper.find('[data-test="exp-submit"]').element as HTMLButtonElement).disabled).toBe(true)
    wrapper.unmount()
  })

  it('无 dataset 查询时自动选择本案例已就绪数据集', async () => {
    vi.mocked(client.fetchCaseDatasets).mockResolvedValue({ datasets: [DATASET] })
    vi.mocked(client.fetchDataset).mockResolvedValue(DATASET)
    const { wrapper } = await mountAt('/cases/c1/experiments/new')
    expect(client.fetchCaseDatasets).toHaveBeenCalledWith('c1')
    expect(wrapper.text()).toContain('borehole.csv')
    expect(wrapper.find('[data-test="param-editor"]').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('ExperimentView 微震预设', () => {
  function mockMicroseismicCreate() {
    vi.mocked(client.fetchDataset).mockResolvedValue(MICRO_DATASET)
    vi.mocked(client.createExperiment).mockResolvedValue(EXP)
    vi.mocked(client.startRun).mockResolvedValue(makeRun('queued'))
    vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
    vi.mocked(client.fetchCandidates).mockResolvedValue(makeCandidates([], makeRun('queued')))
    vi.mocked(client.fetchRun).mockResolvedValue(makeRun('succeeded', { completed: 1, total: 1 }))
  }

  it('manual 模式显示 z_scale 字段（默认 1）与说明文案，并随 payload 提交', async () => {
    mockMicroseismicCreate()
    const { wrapper } = await mountAt('/cases/c1/experiments/new?dataset=ds-micro')

    const zScale = wrapper.find('[data-test="z-scale-manual"]')
    expect(zScale.exists()).toBe(true)
    expect((zScale.element as HTMLInputElement).value).toBe('1')
    expect(wrapper.find('[data-test="z-scale-hint"]').text()).toContain(
      '垂向距离缩放只改变实验中距离的计算方式；它本身不能说明地下介质存在方向性。',
    )

    await wrapper.find('[data-test="exp-submit"]').trigger('click')
    await flushPromises()
    const payload = vi.mocked(client.createExperiment).mock.calls[0][0]
    expect(payload.parameters).toMatchObject({ power: 2, neighbor_count: 16, z_scale: 1 })
    wrapper.unmount()
  })

  it('grid IDW 默认候选 3×4×3=36，z_scale 计入组合数与 payload', async () => {
    mockMicroseismicCreate()
    const { wrapper } = await mountAt('/cases/c1/experiments/new?dataset=ds-micro')
    await wrapper.find('[data-test="mode-grid"]').setValue(true)

    expect((wrapper.find('[data-test="grid-power"]').element as HTMLInputElement).value).toBe('1, 2, 3')
    expect((wrapper.find('[data-test="grid-neighbors"]').element as HTMLInputElement).value).toBe(
      '8, 16, 24, 32',
    )
    expect((wrapper.find('[data-test="grid-z-scale"]').element as HTMLInputElement).value).toBe(
      '0.5, 1, 2',
    )
    expect(wrapper.text()).toContain('36 个候选组合')

    await wrapper.find('[data-test="exp-submit"]').trigger('click')
    await flushPromises()
    const payload = vi.mocked(client.createExperiment).mock.calls[0][0]
    expect(payload.parameters).toMatchObject({
      power: [1, 2, 3],
      neighbor_count: [8, 16, 24, 32],
      z_scale: [0.5, 1, 2],
    })
    wrapper.unmount()
  })

  it('grid Kriging 默认候选 3×3×3=27', async () => {
    mockMicroseismicCreate()
    const { wrapper } = await mountAt('/cases/c1/experiments/new?dataset=ds-micro')
    await wrapper.find('[data-test="algo-kriging"]').setValue(true)
    await wrapper.find('[data-test="mode-grid"]').setValue(true)

    expect((wrapper.find('[data-test="grid-kriging-neighbors"]').element as HTMLInputElement).value).toBe(
      '12, 24, 36',
    )
    expect(wrapper.text()).toContain('27 个候选组合')

    await wrapper.find('[data-test="exp-submit"]').trigger('click')
    await flushPromises()
    const payload = vi.mocked(client.createExperiment).mock.calls[0][0]
    expect(payload.parameters).toMatchObject({
      variogram_model: ['spherical', 'exponential', 'gaussian'],
      neighbor_count: [12, 24, 36],
      z_scale: [0.5, 1, 2],
    })
    wrapper.unmount()
  })

  it('通用数据集不显示 z_scale 控件且默认体验不变', async () => {
    vi.mocked(client.fetchDataset).mockResolvedValue(DATASET)
    const { wrapper } = await mountAt('/cases/c1/experiments/new?dataset=ds1')
    expect(wrapper.find('[data-test="z-scale-manual"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="z-scale-hint"]').exists()).toBe(false)

    await wrapper.find('[data-test="mode-grid"]').setValue(true)
    expect(wrapper.find('[data-test="grid-z-scale"]').exists()).toBe(false)
    expect((wrapper.find('[data-test="grid-power"]').element as HTMLInputElement).value).toBe('2')
    expect((wrapper.find('[data-test="grid-neighbors"]').element as HTMLInputElement).value).toBe('8, 16')
    wrapper.unmount()
  })
})

describe('ExperimentView 详情模式', () => {
  it('queued→running→succeeded 每秒轮询并在终态停止', async () => {
    const succeededCandidate = makeCandidate('cand1', 'succeeded', 1.25)
    vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
    vi.mocked(client.fetchCandidates)
      .mockResolvedValueOnce(makeCandidates([], makeRun('queued')))
      .mockResolvedValue(makeCandidates([succeededCandidate], makeRun('succeeded', { completed: 1, total: 1 })))
    vi.mocked(client.fetchRun)
      .mockResolvedValueOnce(makeRun('running', { completed: 0, total: 1 }))
      .mockResolvedValue(makeRun('succeeded', { completed: 1, total: 1 }))

    const { wrapper } = await mountAt('/experiments/exp1')
    expect(wrapper.text()).toContain('排队中')
    expect(wrapper.text()).not.toContain('queued')

    await vi.advanceTimersByTimeAsync(1000)
    expect(client.fetchRun).toHaveBeenCalledWith('run1')
    expect(wrapper.text()).toContain('运行中')
    expect(wrapper.text()).not.toContain('running')

    await vi.advanceTimersByTimeAsync(1000)
    expect(wrapper.text()).toContain('验证完成')
    expect(wrapper.text()).not.toContain('succeeded')
    const callsAfterTerminal = vi.mocked(client.fetchRun).mock.calls.length
    // 终态后排行榜刷新且轮询停止
    expect(vi.mocked(client.fetchCandidates).mock.calls.length).toBeGreaterThanOrEqual(2)
    await vi.advanceTimersByTimeAsync(3000)
    expect(vi.mocked(client.fetchRun).mock.calls.length).toBe(callsAfterTerminal)
    wrapper.unmount()
  })

  it('部分候选失败：失败行保留在成功候选之下并显示错误码', async () => {
    const ok = makeCandidate('cand-ok', 'succeeded', 2.5)
    const bad = makeCandidate('cand-bad', 'failed', null, {
      code: 'VARIOGRAM_FIT_FAILED',
      message: '变异函数拟合失败',
    })
    vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
    vi.mocked(client.fetchCandidates).mockResolvedValue(
      makeCandidates([ok, bad], makeRun('succeeded', { completed: 1, total: 2, failed: 1 })),
    )

    const { wrapper } = await mountAt('/experiments/exp1')
    const rows = wrapper.findAll('[data-test="candidate-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('2.5')
    expect(rows[1].text()).toContain('VARIOGRAM_FIT_FAILED')
    wrapper.unmount()
  })

  it('运行中可以取消', async () => {
    vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
    vi.mocked(client.fetchCandidates).mockResolvedValue(
      makeCandidates([], makeRun('running', { completed: 0, total: 2 })),
    )
    vi.mocked(client.fetchRun).mockResolvedValue(makeRun('running', { completed: 0, total: 2 }))
    vi.mocked(client.cancelRun).mockResolvedValue(makeRun('canceled'))

    const { wrapper } = await mountAt('/experiments/exp1')
    await wrapper.find('[data-test="cancel-run"]').trigger('click')
    await flushPromises()
    expect(client.cancelRun).toHaveBeenCalledWith('run1')
    wrapper.unmount()
  })

  it('刷新后 interrupted 状态可见且可重试，重试后恢复轮询', async () => {
    vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
    vi.mocked(client.fetchCandidates).mockResolvedValue(makeCandidates([], makeRun('interrupted')))
    vi.mocked(client.retryRun).mockResolvedValue(makeRun('queued', {}, 'run2'))
    vi.mocked(client.fetchRun).mockResolvedValue(makeRun('succeeded', { completed: 1, total: 1 }, 'run2'))

    const { wrapper } = await mountAt('/experiments/exp1')
    expect(wrapper.text()).toContain('已中断')
    expect(wrapper.text()).not.toContain('interrupted')
    expect(wrapper.text()).toContain('PROCESS_RESTARTED')

    await wrapper.find('[data-test="retry-run"]').trigger('click')
    await flushPromises()
    expect(client.retryRun).toHaveBeenCalledWith('run1')

    await vi.advanceTimersByTimeAsync(1000)
    expect(client.fetchRun).toHaveBeenCalledWith('run2')
    wrapper.unmount()
  })

  it('排行榜默认按公共有效 RMSE 升序', async () => {
    const high = makeCandidate('cand-high', 'succeeded', 9.5)
    const low = makeCandidate('cand-low', 'succeeded', 1.25)
    vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
    vi.mocked(client.fetchCandidates).mockResolvedValue(
      makeCandidates([high, low], makeRun('succeeded', { completed: 2, total: 2 })),
    )

    const { wrapper } = await mountAt('/experiments/exp1')
    const rows = wrapper.findAll('[data-test="candidate-row"]')
    expect(rows[0].text()).toContain('1.25')
    expect(rows[1].text()).toContain('9.5')
    wrapper.unmount()
  })

  it('覆盖率与公共有效数可见', async () => {
    const ok = makeCandidate('cand-ok', 'succeeded', 2.0)
    vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
    vi.mocked(client.fetchCandidates).mockResolvedValue(
      makeCandidates([ok], makeRun('succeeded', { completed: 1, total: 1 })),
    )

    const { wrapper } = await mountAt('/experiments/exp1')
    expect(wrapper.text()).toContain('92.0%')
    expect(wrapper.text()).toContain('96')
    wrapper.unmount()
  })
})

describe('ExperimentView 成果状态区（v0.6.1）', () => {
  function mockSucceeded(candidates: CandidateRecord[]) {
    vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
    vi.mocked(client.fetchCandidates).mockResolvedValue(
      makeCandidates(candidates, {
        ...makeRun('succeeded', { completed: candidates.length, total: candidates.length }),
        finished_at: T,
      }),
    )
  }

  it('运行成功且有成功候选：运行状态区出现「查看成果」主按钮，单候选一键直达成果页', async () => {
    mockSucceeded([makeCandidate('cand1', 'succeeded', 1.25)])
    const { wrapper, router } = await mountAt('/experiments/exp1')

    const panel = wrapper.find('[data-test="result-status"]')
    expect(panel.exists()).toBe(true)
    const entry = wrapper.get('[data-test="view-result"]')
    expect(entry.text()).toContain('查看成果')
    await entry.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value).toMatchObject({ name: 'result-workbench', params: { resultId: 'cand1' } })
    wrapper.unmount()
  })

  it('四阶段分层使用用户语言，验证完成不被表述为已渲染', async () => {
    mockSucceeded([makeCandidate('cand1', 'succeeded', 1.25)])
    const { wrapper } = await mountAt('/experiments/exp1')

    expect(wrapper.get('[data-test="stage-validation"]').text()).toContain('验证完成')
    expect(wrapper.get('[data-test="stage-validation"]').text()).toContain(T)
    expect(wrapper.get('[data-test="stage-materialize"]').text()).toContain('等待生成')
    expect(wrapper.get('[data-test="stage-materialize"]').text()).not.toContain('物化')
    expect(wrapper.get('[data-test="stage-netcdf"]').text()).toContain('待')
    expect(wrapper.get('[data-test="stage-netcdf"]').text()).not.toContain('NetCDF')
    expect(wrapper.get('[data-test="stage-render"]').text()).toContain('成果工作台')
    const panelText = wrapper.get('[data-test="result-status"]').text()
    expect(panelText).not.toContain('已渲染')
    expect(panelText).not.toContain('体渲染完成')
    wrapper.unmount()
  })

  it('未物化候选：「生成规则网格」按钮触发 materialize，成功后翻转为已物化并出现 NetCDF 入口', async () => {
    mockSucceeded([makeCandidate('cand1', 'succeeded', 1.25)])
    const { wrapper } = await mountAt('/experiments/exp1')

    await wrapper.get('[data-test="materialize-result"]').trigger('click')
    await flushPromises()

    expect(client.materializeResult).toHaveBeenCalledWith('cand1')
    expect(wrapper.get('[data-test="stage-materialize"]').text()).toContain('三维网格已生成')
    expect(client.fetchResultRenderCapability).toHaveBeenCalledWith('cand1')
    expect(wrapper.find('[data-test="create-netcdf-asset"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('物化失败：错误码可见且可重试至成功', async () => {
    vi.mocked(client.materializeResult)
      .mockRejectedValueOnce(new client.ApiError('GRID_WRITE_FAILED', '磁盘不可写', 500))
      .mockResolvedValue(RESULT_META)
    mockSucceeded([makeCandidate('cand1', 'succeeded', 1.25)])
    const { wrapper } = await mountAt('/experiments/exp1')

    await wrapper.get('[data-test="materialize-result"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="materialize-error"]').text()).toContain('GRID_WRITE_FAILED')

    await wrapper.get('[data-test="materialize-retry"]').trigger('click')
    await flushPromises()
    expect(client.materializeResult).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[data-test="stage-materialize"]').text()).toContain('三维网格已生成')
    wrapper.unmount()
  })

  it('已物化且未生成资产：显示「生成 NetCDF 资产」；创建失败错误可见，再次点击重试后显示已生成', async () => {
    vi.mocked(client.fetchResult).mockResolvedValue(RESULT_META)
    vi.mocked(client.createResultRenderAsset)
      .mockRejectedValueOnce(new client.ApiError('NETCDF_WRITE_FAILED', '资产写入失败', 500))
      .mockResolvedValue(makeAsset('ready'))
    mockSucceeded([makeCandidate('cand1', 'succeeded', 1.25)])
    const { wrapper } = await mountAt('/experiments/exp1')

    expect(wrapper.get('[data-test="stage-netcdf"]').text()).toContain('未生成')
    await wrapper.get('[data-test="create-netcdf-asset"]').trigger('click')
    await flushPromises()
    expect(client.createResultRenderAsset).toHaveBeenCalledWith('cand1', false)
    expect(wrapper.get('[data-test="asset-error"]').text()).toContain('NETCDF_WRITE_FAILED')

    await wrapper.get('[data-test="create-netcdf-asset"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="stage-netcdf"]').text()).toContain('已生成')
    expect(wrapper.get('[data-test="stage-netcdf"]').text()).not.toContain('已渲染')
    wrapper.unmount()
  })

  it('资产 failed 记录：显示稳定错误码并以 retry_failed=true 重建', async () => {
    vi.mocked(client.fetchResult).mockResolvedValue(RESULT_META)
    vi.mocked(client.fetchResultRenderAsset).mockResolvedValue(makeAsset('failed'))
    mockSucceeded([makeCandidate('cand1', 'succeeded', 1.25)])
    const { wrapper } = await mountAt('/experiments/exp1')

    expect(wrapper.get('[data-test="stage-netcdf"]').text()).toContain('NETCDF_WRITE_FAILED')
    await wrapper.get('[data-test="retry-netcdf-asset"]').trigger('click')
    await flushPromises()
    expect(client.createResultRenderAsset).toHaveBeenCalledWith('cand1', true)
    expect(wrapper.get('[data-test="stage-netcdf"]').text()).toContain('已生成')
    wrapper.unmount()
  })

  it('资产 creating：轮询直至 ready 后显示已生成', async () => {
    vi.mocked(client.fetchResult).mockResolvedValue(RESULT_META)
    vi.mocked(client.fetchResultRenderAsset)
      .mockResolvedValueOnce(makeAsset('creating'))
      .mockResolvedValue(makeAsset('ready'))
    mockSucceeded([makeCandidate('cand1', 'succeeded', 1.25)])
    const { wrapper } = await mountAt('/experiments/exp1')

    expect(wrapper.get('[data-test="stage-netcdf"]').text()).toContain('创建中')
    await vi.advanceTimersByTimeAsync(2000)
    expect(vi.mocked(client.fetchResultRenderAsset).mock.calls.length).toBeGreaterThanOrEqual(2)
    expect(wrapper.get('[data-test="stage-netcdf"]').text()).toContain('已生成')
    wrapper.unmount()
  })

  it('能力不支持（如二维成果）：NetCDF 阶段显示不适用原因，不给生成入口', async () => {
    vi.mocked(client.fetchResult).mockResolvedValue(RESULT_META)
    vi.mocked(client.fetchResultRenderCapability).mockResolvedValue({
      ...CAPABILITY_OK,
      supported: false,
      reason_code: 'RENDER_REQUIRES_3D',
      reason: '原生体渲染要求三维成果网格',
    })
    mockSucceeded([makeCandidate('cand1', 'succeeded', 1.25)])
    const { wrapper } = await mountAt('/experiments/exp1')

    expect(wrapper.get('[data-test="stage-netcdf"]').text()).toContain('RENDER_REQUIRES_3D')
    expect(wrapper.find('[data-test="create-netcdf-asset"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('多候选实验：状态区以排行榜首名（公共 RMSE 最低成功候选）为准，排行榜「成果」链接保留', async () => {
    const high = makeCandidate('cand-high', 'succeeded', 9.5)
    const low = makeCandidate('cand-low', 'succeeded', 1.25)
    mockSucceeded([high, low])
    const { wrapper } = await mountAt('/experiments/exp1')

    expect(wrapper.get('[data-test="view-result"]').attributes('href')).toContain('/results/cand-low')
    expect(client.fetchResult).toHaveBeenCalledWith('cand-low')
    // 排行榜行内成果入口不受状态区影响
    expect(wrapper.findAll('[data-test="open-result"]')).toHaveLength(2)
    wrapper.unmount()
  })

  it('深链/刷新进入已完成实验：物化与 NetCDF 资产状态从服务端恢复', async () => {
    vi.mocked(client.fetchResult).mockResolvedValue(RESULT_META)
    vi.mocked(client.fetchResultRenderAsset).mockResolvedValue(makeAsset('ready'))
    mockSucceeded([makeCandidate('cand1', 'succeeded', 1.25)])
    // 直接以 URL 打开详情页（等价刷新/深链），状态区照常完成探测
    const { wrapper } = await mountAt('/experiments/exp1')

    expect(wrapper.get('[data-test="stage-materialize"]').text()).toContain('三维网格已生成')
    expect(wrapper.get('[data-test="stage-netcdf"]').text()).toContain('已生成')
    expect(wrapper.find('[data-test="materialize-result"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="stage-render"]').text()).toContain('成果工作台')
    wrapper.unmount()
  })

  it('运行未终态时不显示成果状态区', async () => {
    vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
    vi.mocked(client.fetchCandidates).mockResolvedValue(
      makeCandidates([], makeRun('running', { completed: 0, total: 1 })),
    )
    vi.mocked(client.fetchRun).mockResolvedValue(makeRun('running', { completed: 0, total: 1 }))
    const { wrapper } = await mountAt('/experiments/exp1')
    expect(wrapper.find('[data-test="result-status"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('运行成功但无成功候选时不显示成果状态区', async () => {
    const bad = makeCandidate('cand-bad', 'failed', null, { code: 'VARIOGRAM_FIT_FAILED', message: '拟合失败' })
    mockSucceeded([bad])
    const { wrapper } = await mountAt('/experiments/exp1')
    expect(wrapper.find('[data-test="result-status"]').exists()).toBe(false)
    expect(client.fetchResult).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})

describe('导航', () => {
  it('创建模式显示面包屑首页链接且点击不调用取消接口', async () => {
    vi.mocked(client.fetchDataset).mockResolvedValue(DATASET)
    const { wrapper, router } = await mountAt('/cases/c1/experiments/new?dataset=ds1')
    const crumbHome = wrapper.get('[data-test="crumb-home"]')
    await crumbHome.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('home')
    expect(client.cancelRun).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('详情模式显示面包屑首页与案例链接', async () => {
    vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
    vi.mocked(client.fetchCandidates).mockResolvedValue(
      makeCandidates([], makeRun('succeeded', { completed: 1, total: 1 })),
    )
    const { wrapper, router } = await mountAt('/experiments/exp1')
    expect(wrapper.get('[data-test="crumb-home"]').text()).toContain('首页')
    expect(wrapper.find('[data-test="crumb-case"]').exists()).toBe(true)
    await wrapper.get('[data-test="crumb-case"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('case-workspace')
    expect(router.currentRoute.value.params.caseId).toBe('c1')
    wrapper.unmount()
  })

  it('实验加载失败时仍能返回首页', async () => {
    vi.mocked(client.fetchExperiment).mockRejectedValue(new client.ApiError('EXPERIMENT_NOT_FOUND', '不存在', 404))
    vi.mocked(client.fetchCandidates).mockRejectedValue(new client.ApiError('EXPERIMENT_NOT_FOUND', '不存在', 404))
    const { wrapper, router } = await mountAt('/experiments/exp-missing')
    expect(wrapper.text()).toContain('加载失败')
    await wrapper.get('[data-test="crumb-home"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('home')
    wrapper.unmount()
  })
})
