import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type {
  CandidatesResponse,
  CandidateRecord,
  DatasetVersionRecord,
  ExperimentRecord,
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
    createExperiment: vi.fn(),
    startRun: vi.fn(),
    fetchRun: vi.fn(),
    cancelRun: vi.fn(),
    retryRun: vi.fn(),
    fetchCandidates: vi.fn(),
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

function makeTestRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/cases/:caseId/experiments/new', name: 'experiment-create', component: ExperimentView },
      { path: '/experiments/:experimentId', name: 'experiment-detail', component: ExperimentView },
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
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('ExperimentView 创建模式', () => {
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
      '距离计算使用 Z × z_scale；它是实验参数，不是已确认地质各向异性。',
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
    expect(wrapper.text()).toContain('queued')

    await vi.advanceTimersByTimeAsync(1000)
    expect(client.fetchRun).toHaveBeenCalledWith('run1')
    expect(wrapper.text()).toContain('running')

    await vi.advanceTimersByTimeAsync(1000)
    expect(wrapper.text()).toContain('succeeded')
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
    expect(wrapper.text()).toContain('interrupted')
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

describe('导航', () => {
  it('创建模式显示 nav-home 且点击不调用取消接口', async () => {
    vi.mocked(client.fetchDataset).mockResolvedValue(DATASET)
    const { wrapper, router } = await mountAt('/cases/c1/experiments/new?dataset=ds1')
    const navHome = wrapper.get('[data-test="nav-home"]')
    await navHome.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('home')
    expect(client.cancelRun).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('详情模式显示 nav-home 与 nav-new-experiment', async () => {
    vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
    vi.mocked(client.fetchCandidates).mockResolvedValue(
      makeCandidates([], makeRun('succeeded', { completed: 1, total: 1 })),
    )
    const { wrapper, router } = await mountAt('/experiments/exp1')
    expect(wrapper.get('[data-test="nav-home"]').text()).toContain('返回首页')
    const navNew = wrapper.get('[data-test="nav-new-experiment"]')
    await navNew.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value).toMatchObject({
      name: 'experiment-create',
      params: { caseId: 'c1' },
    })
    wrapper.unmount()
  })

  it('实验加载失败时仍能返回首页', async () => {
    vi.mocked(client.fetchExperiment).mockRejectedValue(new client.ApiError('EXPERIMENT_NOT_FOUND', '不存在', 404))
    vi.mocked(client.fetchCandidates).mockRejectedValue(new client.ApiError('EXPERIMENT_NOT_FOUND', '不存在', 404))
    const { wrapper, router } = await mountAt('/experiments/exp-missing')
    expect(wrapper.text()).toContain('加载失败')
    await wrapper.get('[data-test="nav-home"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('home')
    wrapper.unmount()
  })
})
