import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as client from '../../api/client'
import type {
  CandidateCatalog,
  ComparisonCandidateSummary,
  MultiCandidateComparison,
  ResultMetadata,
} from '../../api/types'
import CandidateComparisonView from '../CandidateComparisonView.vue'

// v0.9.0：比较图在模块边界 mock echarts（jsdom 无 canvas 上下文；
// 与 analysisPanels.spec.ts 同一模式）
vi.mock('echarts/core', () => ({
  init: vi.fn(() => ({
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
    on: vi.fn(),
  })),
  use: vi.fn(),
}))
vi.mock('echarts/charts', () => ({ BarChart: {} }))
vi.mock('echarts/components', () => ({
  GridComponent: {},
  TooltipComponent: {},
  LegendComponent: {},
}))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    fetchComparisonCandidates: vi.fn(),
    compareCandidates: vi.fn(),
    fetchResult: vi.fn(),
  }
})

function makeCandidate(
  id: string,
  experimentId: string,
  algorithm: string,
  selectable = true,
  metrics?: { rmse: number | null; mae: number | null; r2: number | null; bias: number | null },
  fingerprint?: string,
): ComparisonCandidateSummary {
  return {
    candidate_result_id: id,
    experiment_id: experimentId,
    run_id: `run-${id}`,
    algorithm,
    parameters: { power: 2, range: 800 },
    selectable,
    metrics: metrics ?? { rmse: 0.1, mae: 0.05, r2: 0.95, bias: 0.01 },
    result_url: `/results/${id}`,
    configuration_fingerprint: fingerprint ?? `fp-${id}`,
  }
}

const CATALOG: CandidateCatalog = {
  dataset_id: 'ds-1',
  groups: [
    {
      experiment_id: 'exp-1',
      experiment_name: '实验 A',
      candidates: [
        makeCandidate('r-1', 'exp-1', 'idw', true, { rmse: 0.12, mae: 0.08, r2: 0.93, bias: 0.02 }),
        makeCandidate('r-2', 'exp-1', 'ordinary_kriging', true, { rmse: 0.08, mae: 0.04, r2: 0.97, bias: -0.01 }),
        makeCandidate('r-3', 'exp-1', 'ordinary_kriging', false, { rmse: null, mae: null, r2: null, bias: null }),
      ],
    },
    {
      experiment_id: 'exp-2',
      experiment_name: '实验 B',
      candidates: [
        makeCandidate('r-4', 'exp-2', 'dsi_like', true, { rmse: 0.15, mae: 0.10, r2: 0.90, bias: 0.03 }),
        makeCandidate('r-5', 'exp-2', 'idw', true, { rmse: 0.14, mae: 0.09, r2: 0.91, bias: 0.02 }, 'fp-dup'),
        makeCandidate('r-6', 'exp-2', 'idw', true, { rmse: 0.16, mae: 0.11, r2: 0.89, bias: 0.04 }, 'fp-dup'),
      ],
    },
  ],
}

const COMPARABLE: MultiCandidateComparison = {
  candidate_result_ids: ['r-1', 'r-2', 'r-4'],
  dataset_version_id: 'ds-1',
  comparable: true,
  mismatches: [],
  candidates: [
    makeCandidate('r-1', 'exp-1', 'idw', true, { rmse: 0.12, mae: 0.08, r2: 0.93, bias: 0.02 }),
    makeCandidate('r-2', 'exp-1', 'ordinary_kriging', true, { rmse: 0.08, mae: 0.04, r2: 0.97, bias: -0.01 }),
    makeCandidate('r-4', 'exp-2', 'dsi_like', true, { rmse: 0.15, mae: 0.10, r2: 0.90, bias: 0.03 }),
  ],
  ranking: ['r-2', 'r-1', 'r-4'],
  comparison_fingerprint: 'fp-comparable',
}

const INCOMPARABLE: MultiCandidateComparison = {
  candidate_result_ids: ['r-1', 'r-4'],
  dataset_version_id: 'ds-1',
  comparable: false,
  mismatches: ['validation_contract', 'grid_resolution'],
  candidates: [
    makeCandidate('r-1', 'exp-1', 'idw', true, { rmse: 0.12, mae: 0.08, r2: 0.93, bias: 0.02 }),
    makeCandidate('r-4', 'exp-2', 'dsi_like', true, { rmse: 0.15, mae: 0.10, r2: 0.90, bias: 0.03 }),
  ],
  ranking: null,
  comparison_fingerprint: 'fp-incomparable',
}

const T = '2026-07-26T00:00:00Z'

function makeResultMeta(id: string, enhanced: boolean): ResultMetadata {
  return {
    result_id: id,
    run_id: `run-${id}`,
    experiment_id: 'exp-1',
    dataset_version_id: 'ds-1',
    algorithm: 'idw',
    parameters: { power: 2 },
    dimension: '2d',
    shape: [11, 11],
    cell_count: 121,
    bounds: [[0, 100], [0, 100]],
    resolution: [10, 10],
    value_range: [10, 60],
    nodata_count: 0,
    grid_sha256: 'ab'.repeat(32),
    source_sha256: 'ab'.repeat(32),
    standardized_sha256: 'ab'.repeat(32),
    fingerprint: `fp-${id}`,
    validation: { folds: 3 },
    created_at: T,
    evaluation_summary: {
      common_valid_count: 96,
      candidate_valid_count: 96,
      candidate_nodata_count: 4,
      total_count: 100,
      coverage: 0.96,
      rmse: 1.2,
      mae: 0.9,
      r2: 0.94,
      bias: 0.05,
      enhanced_evidence_available: enhanced,
    },
  }
}

async function mountView(): Promise<{ wrapper: ReturnType<typeof mount>; router: Router }> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      {
        path: '/datasets/:datasetId/candidate-comparison',
        name: 'candidate-comparison',
        component: CandidateComparisonView,
      },
      {
        path: '/results/:resultId',
        name: 'result-workbench',
        component: { template: '<div />' },
      },
      {
        path: '/results/:resultId/evaluation',
        name: 'model-evaluation',
        component: { template: '<div />' },
      },
      {
        path: '/cases/:caseId/experiments/new',
        name: 'experiment-create',
        component: { template: '<div />' },
      },
    ],
  })
  await router.push('/datasets/ds-1/candidate-comparison')
  await router.isReady()
  const wrapper = mount(CandidateComparisonView, {
    global: { plugins: [router, ElementPlus] },
    attachTo: document.body,
  })
  await flushPromises()
  return { wrapper, router }
}

function checkboxes(wrapper: ReturnType<typeof mount>) {
  return wrapper.findAll('[data-test="candidate-checkbox"]')
}

function isDisabled(wrapper: ReturnType<typeof mount>, index: number): boolean {
  const cbs = checkboxes(wrapper)
  return cbs[index].find('input').attributes('disabled') !== undefined
}

async function check(wrapper: ReturnType<typeof mount>, index: number) {
  const cbs = checkboxes(wrapper)
  await cbs[index].find('input').setValue(true)
  await flushPromises()
}

async function uncheck(wrapper: ReturnType<typeof mount>, index: number) {
  const cbs = checkboxes(wrapper)
  await cbs[index].find('input').setValue(false)
  await flushPromises()
}

describe('CandidateComparisonView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    document.body.innerHTML = ''
    vi.mocked(client.fetchComparisonCandidates).mockResolvedValue(CATALOG)
    vi.mocked(client.compareCandidates).mockResolvedValue(COMPARABLE)
    vi.mocked(client.fetchResult).mockImplementation(async (id: string) =>
      makeResultMeta(id, true),
    )
  })

  it('标题为「模型比较」且使用可读算法标签', async () => {
    const { wrapper } = await mountView()
    expect(wrapper.find('h1').text()).toBe('模型比较')
    expect(wrapper.text()).toContain('同一数据版本和验证口径下比较候选成果')
    expect(wrapper.text()).toContain('IDW（反距离加权）')
    expect(wrapper.text()).toContain('普通克里金')
    expect(wrapper.text()).toContain('DSI-like 离散平滑插值')
    expect(wrapper.text()).not.toContain('dsi_like')
    wrapper.unmount()
  })

  it('参数列使用可读标签而非原始键', async () => {
    const { wrapper } = await mountView()
    expect(wrapper.text()).toContain('幂参数')
    expect(wrapper.text()).not.toContain('power=2')
    wrapper.unmount()
  })

  it('默认选择 RMSE 最低的两个不同配置候选，并说明仍需校验兼容性', async () => {
    const { wrapper } = await mountView()
    const selected = checkboxes(wrapper).filter((item) =>
      (item.find('input').element as HTMLInputElement).checked,
    )

    expect(selected).toHaveLength(2)
    expect(wrapper.get('[data-test="comparison-start-summary"]').text()).toContain('已为你选择')
    expect(wrapper.get('[data-test="comparison-start-summary"]').text()).toContain('兼容性')
    expect(wrapper.find('[data-test="compare-btn"]').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('数据版本 UUID 不出现在主标题区，只保留于技术详情', async () => {
    const { wrapper } = await mountView()
    const header = wrapper.get('[data-test="page-context-header"]')
    expect(header.get('h1').text()).not.toContain('ds-1')
    expect(header.get('.page-context__subtitle').text()).not.toContain('ds-1')
    expect(wrapper.get('[data-test="comparison-technical-details"]').text()).toContain('ds-1')
    wrapper.unmount()
  })

  it('比较完成后先展示推荐结论、指标差异和主要参数差异', async () => {
    const { wrapper } = await mountView()
    await wrapper.get('[data-test="compare-btn"]').trigger('click')
    await flushPromises()

    const summary = wrapper.get('[data-test="comparison-summary"]')
    expect(summary.text()).toContain('普通克里金')
    expect(summary.text()).toContain('RMSE')
    expect(summary.text()).toContain('主要参数差异')
    expect(summary.text()).not.toContain('r-2')
    wrapper.unmount()
  })

  it('单候选状态不显示空比较表，并引导创建参数网格实验', async () => {
    vi.mocked(client.fetchComparisonCandidates).mockResolvedValue({
      dataset_id: 'ds-1',
      groups: [{
        experiment_id: 'exp-1',
        experiment_name: '实验 A',
        candidates: [makeCandidate('r-only', 'exp-1', 'idw')],
      }],
    })
    const { wrapper, router } = await mountView()

    expect(wrapper.find('[data-test="candidate-table"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="single-candidate-state"]').text()).toContain('参数网格')
    await wrapper.get('[data-test="create-grid-experiment"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('experiment-create')
    expect(router.currentRoute.value.query.dataset).toBe('ds-1')
    wrapper.unmount()
  })

  it('checkbox selection enforces 2 minimum / 4 maximum limit', async () => {
    const { wrapper } = await mountView()

    await uncheck(wrapper, 0)
    await uncheck(wrapper, 1)
    expect(wrapper.find('[data-test="compare-btn"]').attributes('disabled')).toBeDefined()

    await check(wrapper, 0)
    expect(wrapper.find('[data-test="compare-btn"]').attributes('disabled')).toBeDefined()

    await check(wrapper, 1)
    expect(wrapper.find('[data-test="compare-btn"]').attributes('disabled')).toBeUndefined()

    await check(wrapper, 3)
    await check(wrapper, 4)
    expect(wrapper.find('[data-test="compare-btn"]').attributes('disabled')).toBeUndefined()

    expect(isDisabled(wrapper, 5)).toBe(true)

    await uncheck(wrapper, 4)
    expect(isDisabled(wrapper, 5)).toBe(false)
    wrapper.unmount()
  })

  it('failed/unverifiable candidates have disabled checkboxes', async () => {
    const { wrapper } = await mountView()
    expect(isDisabled(wrapper, 2)).toBe(true)
    expect(isDisabled(wrapper, 0)).toBe(false)
    expect(isDisabled(wrapper, 3)).toBe(false)
    wrapper.unmount()
  })

  it('comparable response shows deterministic ranks with 最佳 badge on rank 1', async () => {
    const { wrapper } = await mountView()

    await check(wrapper, 0)
    await check(wrapper, 1)
    await check(wrapper, 3)

    await wrapper.find('[data-test="compare-btn"]').trigger('click')
    await flushPromises()

    expect(client.compareCandidates).toHaveBeenCalledWith(['r-1', 'r-2', 'r-4'])

    const ranking = wrapper.find('[data-test="ranking-result"]')
    expect(ranking.exists()).toBe(true)

    const rows = wrapper.findAll('[data-test^="ranking-row-"]')
    expect(rows).toHaveLength(3)
    expect(rows[0].text()).toContain('r-2')
    expect(rows[0].text()).toContain('最佳')
    expect(rows[1].text()).toContain('r-1')
    expect(rows[1].text()).not.toContain('最佳')
    expect(rows[2].text()).toContain('r-4')

    expect(wrapper.find('[data-test="mismatch-list"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('incompatible response shows mismatch fields with no 最佳 badge', async () => {
    vi.mocked(client.compareCandidates).mockResolvedValue(INCOMPARABLE)
    const { wrapper } = await mountView()

    await uncheck(wrapper, 1)
    await check(wrapper, 0)
    await check(wrapper, 3)

    await wrapper.find('[data-test="compare-btn"]').trigger('click')
    await flushPromises()

    expect(client.compareCandidates).toHaveBeenCalledWith(['r-1', 'r-4'])

    const mismatch = wrapper.find('[data-test="mismatch-list"]')
    expect(mismatch.exists()).toBe(true)
    expect(mismatch.text()).toContain('validation_contract')
    expect(mismatch.text()).toContain('grid_resolution')

    expect(wrapper.find('[data-test="ranking-result"]').exists()).toBe(false)
    expect(wrapper.find('.best-badge').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('最佳')
    wrapper.unmount()
  })

  it('初始无 deep-compare-btn；可比排名且恰好 2 选时显示查看详细差异', async () => {
    const { wrapper, router } = await mountView()

    expect(wrapper.find('[data-test="deep-compare-btn"]').exists()).toBe(false)

    await check(wrapper, 0)
    await check(wrapper, 1)

    await wrapper.find('[data-test="compare-btn"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="deep-compare-btn"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="deep-compare-btn"]').text()).toContain('查看详细差异')

    await wrapper.find('[data-test="deep-compare-btn"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('model-evaluation')
    expect(router.currentRoute.value.params.resultId).toBe('r-1')
    expect(router.currentRoute.value.query.compareWith).toBe('r-2')
    wrapper.unmount()
  })

  it('3 个选中不显示查看详细差异', async () => {
    const { wrapper } = await mountView()

    await check(wrapper, 0)
    await check(wrapper, 1)
    await check(wrapper, 3)

    await wrapper.find('[data-test="compare-btn"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="deep-compare-btn"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('enhanced_evidence_available=false 时不显示查看详细差异', async () => {
    vi.mocked(client.fetchResult).mockImplementation(async (id: string) =>
      makeResultMeta(id, false),
    )
    const { wrapper } = await mountView()

    await check(wrapper, 0)
    await check(wrapper, 1)

    await wrapper.find('[data-test="compare-btn"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="deep-compare-btn"]').exists()).toBe(false)
    wrapper.unmount()
  })
})

describe('重复配置分组', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    document.body.innerHTML = ''
    vi.mocked(client.fetchComparisonCandidates).mockResolvedValue(CATALOG)
    vi.mocked(client.compareCandidates).mockResolvedValue(COMPARABLE)
    vi.mocked(client.fetchResult).mockImplementation(async (id: string) =>
      makeResultMeta(id, true),
    )
  })

  it('相同 fingerprint 显示「相同配置，第 N 次运行」', async () => {
    const { wrapper } = await mountView()
    expect(wrapper.find('[data-test="dup-badge-r-5"]').text()).toContain('相同配置，第 1 次运行')
    expect(wrapper.find('[data-test="dup-badge-r-6"]').text()).toContain('相同配置，第 2 次运行')
    expect(wrapper.find('[data-test="dup-badge-r-1"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('选中同组一个后，另一个被禁用', async () => {
    const { wrapper } = await mountView()

    expect(isDisabled(wrapper, 4)).toBe(false)
    expect(isDisabled(wrapper, 5)).toBe(false)

    await check(wrapper, 4)
    expect(isDisabled(wrapper, 5)).toBe(true)

    await uncheck(wrapper, 4)
    expect(isDisabled(wrapper, 5)).toBe(false)
    wrapper.unmount()
  })
})

describe('stale-response protection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    document.body.innerHTML = ''
  })

  it('dataset A -> B：A 后解析不覆盖 B 的目录', async () => {
    const catalogA: CandidateCatalog = {
      dataset_id: 'ds-A',
      groups: [
        {
          experiment_id: 'exp-A',
          experiment_name: '实验 A',
          candidates: [makeCandidate('r-A', 'exp-A', 'idw')],
        },
      ],
    }
    const catalogB: CandidateCatalog = {
      dataset_id: 'ds-B',
      groups: [
        {
          experiment_id: 'exp-B',
          experiment_name: '实验 B',
          candidates: [makeCandidate('r-B', 'exp-B', 'idw')],
        },
      ],
    }

    let resolveA: (v: CandidateCatalog) => void = () => {}
    const promiseA = new Promise<CandidateCatalog>((resolve) => {
      resolveA = resolve
    })
    vi.mocked(client.fetchComparisonCandidates).mockImplementation(async (id: string) => {
      if (id === 'ds-A') return promiseA
      return catalogB
    })

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'home', component: { template: '<div />' } },
        {
          path: '/datasets/:datasetId/candidate-comparison',
          name: 'candidate-comparison',
          component: CandidateComparisonView,
        },
      ],
    })
    await router.push('/datasets/ds-A/candidate-comparison')
    await router.isReady()
    const wrapper = mount(CandidateComparisonView, {
      global: { plugins: [router, ElementPlus] },
      attachTo: document.body,
    })
    await flushPromises()

    await router.push('/datasets/ds-B/candidate-comparison')
    await flushPromises()

    resolveA(catalogA)
    await flushPromises()

    expect(wrapper.text()).toContain('实验 B')
    expect(wrapper.text()).not.toContain('实验 A')
    wrapper.unmount()
  })
})
