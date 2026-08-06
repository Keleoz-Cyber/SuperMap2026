import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as client from '../../api/client'
import type {
  CandidateCatalog,
  ComparisonCandidateSummary,
  MultiCandidateComparison,
} from '../../api/types'
import CandidateComparisonView from '../CandidateComparisonView.vue'

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    fetchComparisonCandidates: vi.fn(),
    compareCandidates: vi.fn(),
  }
})

function makeCandidate(
  id: string,
  experimentId: string,
  algorithm: string,
  selectable = true,
  metrics?: { rmse: number | null; mae: number | null; r2: number | null; bias: number | null },
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
        makeCandidate('r-5', 'exp-2', 'idw', true, { rmse: 0.14, mae: 0.09, r2: 0.91, bias: 0.02 }),
        makeCandidate('r-6', 'exp-2', 'idw', true, { rmse: 0.16, mae: 0.11, r2: 0.89, bias: 0.04 }),
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
        path: '/results/:resultId/professional',
        name: 'professional-analysis',
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
  })

  it('candidates are grouped by experiment in the catalog table', async () => {
    const { wrapper } = await mountView()
    expect(wrapper.find('[data-test="candidate-comparison-view"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('实验 A')
    expect(wrapper.text()).toContain('实验 B')
    expect(wrapper.text()).toContain('同一数据版本')
    expect(wrapper.text()).not.toContain('跨案例排行榜')
    expect(wrapper.text()).toContain('dsi_like')
    wrapper.unmount()
  })

  it('checkbox selection enforces 2 minimum / 4 maximum limit', async () => {
    const { wrapper } = await mountView()

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

  it('exactly two selected enables deep comparison; three/four disables it', async () => {
    const { wrapper, router } = await mountView()

    expect(wrapper.find('[data-test="deep-compare-btn"]').attributes('disabled')).toBeDefined()

    await check(wrapper, 0)
    await check(wrapper, 1)
    expect(wrapper.find('[data-test="deep-compare-btn"]').attributes('disabled')).toBeUndefined()

    await check(wrapper, 3)
    expect(wrapper.find('[data-test="deep-compare-btn"]').attributes('disabled')).toBeDefined()

    await check(wrapper, 4)
    expect(wrapper.find('[data-test="deep-compare-btn"]').attributes('disabled')).toBeDefined()

    await uncheck(wrapper, 3)
    await uncheck(wrapper, 4)
    expect(wrapper.find('[data-test="deep-compare-btn"]').attributes('disabled')).toBeUndefined()

    await wrapper.find('[data-test="deep-compare-btn"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('professional-analysis')
    expect(router.currentRoute.value.params.resultId).toBe('r-1')
    wrapper.unmount()
  })
})
