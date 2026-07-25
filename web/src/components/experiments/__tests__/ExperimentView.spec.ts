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
        ? { n_total: 100, n_valid: 96, n_nodata: 4, coverage: 0.92, mae: 1, rmse: rmse ?? 1, r2: 0.9, bias: 0.1 }
        : {},
    error,
  }
}

function makeCandidates(candidates: CandidateRecord[], latestRun: RunRecord | null): CandidatesResponse {
  return { experiment_id: 'exp1', candidates, public_metrics: { n_valid: 96 }, latest_run: latestRun }
}

function makeTestRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
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
