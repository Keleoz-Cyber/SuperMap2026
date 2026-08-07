import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type {
  AnalysisJobRecord,
  AnisotropySuggestion,
  DatasetVersionRecord,
  DirectionalVariogramBin,
  ExperimentRecord,
  ProfessionalConfirmationRecord,
  ProfessionalConfirmationSummary,
  ProfessionalDiagnosisRecord,
  ProfessionalDiagnosticList,
  RunStatus,
  VariogramBin,
  VariogramEvidence,
} from '../../../api/types'
import * as client from '../../../api/client'
import ProfessionalDiagnosisView from '../../../views/ProfessionalDiagnosisView.vue'
import ExperimentView from '../../../views/ExperimentView.vue'

vi.mock('../../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/client')>()
  return {
    ...actual,
    fetchDataset: vi.fn(),
    fetchCaseDatasets: vi.fn(),
    fetchProfessionalDiagnostics: vi.fn(),
    fetchProfessionalConfirmation: vi.fn(),
    requestProfessionalDiagnosis: vi.fn(),
    fetchProfessionalDiagnosis: vi.fn(),
    fetchDiagnosisVariogram: vi.fn(),
    confirmProfessionalDiagnosis: vi.fn(),
    fetchAnalysisJob: vi.fn(),
    retryAnalysisJob: vi.fn(),
    createExperiment: vi.fn(),
    startRun: vi.fn(),
    fetchExperiment: vi.fn(),
    fetchRun: vi.fn(),
    fetchCandidates: vi.fn(),
  }
})

const T = '2026-07-26T00:00:00Z'

const DATASET: DatasetVersionRecord = {
  id: 'ds1',
  case_id: 'c1',
  version: 1,
  status: 'validated',
  profile: { dimension: '3d', original_filename: 'borehole.csv' },
  created_at: T,
}

const UNGATED_DATASET: DatasetVersionRecord = { ...DATASET, status: 'mapped' }

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

const OMNI_BINS: VariogramBin[] = [
  {
    bin_index: 0,
    lower_distance: 0,
    upper_distance: 10,
    center_distance: 5,
    mean_distance: 4.8,
    semivariance: 0.12,
    pair_count: 120,
    used_for_fit: true,
    exclusion_reason: null,
  },
  {
    bin_index: 1,
    lower_distance: 10,
    upper_distance: 20,
    center_distance: 15,
    mean_distance: 14.7,
    semivariance: 0.35,
    pair_count: 96,
    used_for_fit: true,
    exclusion_reason: null,
  },
  {
    bin_index: 2,
    lower_distance: 20,
    upper_distance: 30,
    center_distance: 25,
    mean_distance: 24.9,
    semivariance: 0.5,
    pair_count: 12,
    used_for_fit: false,
    exclusion_reason: 'insufficient_pairs',
  },
]

const DIRECTIONAL_BINS: DirectionalVariogramBin[] = [
  {
    direction_id: 'd000',
    azimuth_deg: 0,
    dip_deg: 0,
    azimuth_tolerance_deg: 15,
    dip_tolerance_deg: 15,
    bin_index: 0,
    lower_distance: 0,
    upper_distance: 10,
    center_distance: 5,
    mean_distance: 4.9,
    semivariance: 0.1,
    pair_count: 40,
    used_for_fit: true,
    exclusion_reason: null,
  },
  {
    direction_id: 'd000',
    azimuth_deg: 0,
    dip_deg: 0,
    azimuth_tolerance_deg: 15,
    dip_tolerance_deg: 15,
    bin_index: 1,
    lower_distance: 10,
    upper_distance: 20,
    center_distance: 15,
    mean_distance: 14.8,
    semivariance: 0.3,
    pair_count: 38,
    used_for_fit: true,
    exclusion_reason: null,
  },
  {
    direction_id: 'd001',
    azimuth_deg: 90,
    dip_deg: 0,
    azimuth_tolerance_deg: 15,
    dip_tolerance_deg: 15,
    bin_index: 0,
    lower_distance: 0,
    upper_distance: 10,
    center_distance: 5,
    mean_distance: 5.1,
    semivariance: 0.2,
    pair_count: 5,
    used_for_fit: false,
    exclusion_reason: 'insufficient_pairs',
  },
]

const SUGGESTION: AnisotropySuggestion = {
  candidates: [
    {
      status: 'diagnostic_suggestion',
      rank: 1,
      major_direction_id: 'd000',
      major_azimuth_deg: 0,
      major_dip_deg: 0,
      major_range: 60,
      secondary_direction_id: null,
      secondary_range: null,
      secondary_support_pairs: 0,
      vertical_direction_id: null,
      vertical_range: null,
      vertical_support_pairs: 0,
      major_minor_range_ratio: 1.8,
      major_vertical_range_ratio: null,
      used_direction_ids: ['d000'],
      used_bin_indices: [0, 1],
      used_pair_count: 78,
      warnings: ['single_supported_direction'],
    },
  ],
  compared_direction_ids: ['d000'],
  skipped_direction_ids: ['d001'],
  warnings: ['single_supported_direction'],
}

const EVIDENCE: VariogramEvidence = {
  diagnosis_id: 'diag1',
  omnidirectional: { total: 3, returned: 3, decimate: 1, rows: OMNI_BINS },
  directional: { total: 3, returned: 3, decimate: 1, rows: DIRECTIONAL_BINS },
  fitted_models: {
    models: [
      {
        model: 'spherical',
        nugget: 0.05,
        partial_sill: 0.6,
        sill: 0.65,
        range: 60,
        weighted_sse: 0.01,
        converged: true,
        parameter_origin: 'automatic_candidate',
        used_bin_indices: [0, 1],
        bounds: { range: [0, 100] },
        residuals: [0.0, 0.0],
      },
      {
        model: 'exponential',
        nugget: 0.04,
        partial_sill: 0.62,
        sill: 0.66,
        range: 55,
        weighted_sse: 0.02,
        converged: true,
        parameter_origin: 'automatic_candidate',
        used_bin_indices: [0, 1],
        bounds: { range: [0, 100] },
        residuals: [0.0, 0.0],
      },
      {
        model: 'gaussian',
        nugget: 0.06,
        partial_sill: 0.58,
        sill: 0.64,
        range: 50,
        weighted_sse: 0.03,
        converged: true,
        parameter_origin: 'automatic_candidate',
        used_bin_indices: [0, 1],
        bounds: { range: [0, 100] },
        residuals: [0.0, 0.0],
      },
    ],
    min_sse_model: 'spherical',
    parameter_origin: 'automatic_candidate',
  },
  anisotropy_candidates: SUGGESTION,
  sampling: {
    total_pair_count: 4950,
    used_pair_count: 2475,
    sampling_rate: 0.5,
    sampled: true,
    seed: 42,
  },
  downloads: {
    omnidirectional: '/api/professional-artifacts/diagnosis:diag1:omnidirectional/download',
    directional: '/api/professional-artifacts/diagnosis:diag1:directional/download',
    fitted_models: '/api/professional-artifacts/diagnosis:diag1:fitted_models/download',
    anisotropy_candidates: '/api/professional-artifacts/diagnosis:diag1:anisotropy_candidates/download',
  },
}

const DIAGNOSIS: ProfessionalDiagnosisRecord = {
  id: 'diag1',
  dataset_version_id: 'ds1',
  status: 'succeeded',
  fingerprint: 'fp-diag1',
  config: {
    variogram: {
      lag_count: 12,
      max_distance: null,
      min_pairs_per_bin: 30,
      max_pairs: 50000,
      directions: [],
    },
  },
  manifest: {
    version: 1,
    fingerprint: 'fp-diag1',
    artifacts: {
      metadata: { file: 'metadata.json', sha256: 'sha-meta', bytes: 100 },
      omnidirectional: { file: 'omnidirectional.csv', sha256: 'sha-omni', bytes: 200 },
      directional: { file: 'directional.csv', sha256: 'sha-dir', bytes: 300 },
      fitted_models: { file: 'fitted_models.json', sha256: 'sha-fitted', bytes: 400 },
      anisotropy_candidates: { file: 'anisotropy_candidates.json', sha256: 'sha-cand', bytes: 500 },
    },
    created_at: T,
    summary: {
      fitted_models: ['spherical', 'exponential', 'gaussian'],
      min_sse_model: 'spherical',
      omni_used_bin_count: 2,
      direction_count: 2,
      supported_direction_count: 1,
      skipped_direction_ids: ['d001'],
      candidate_ranks: [1],
      warnings: ['single_supported_direction'],
    },
  },
  error: null,
  created_at: T,
  updated_at: T,
  finished_at: T,
}

const CONFIRMATION: ProfessionalConfirmationRecord = {
  id: 'conf1',
  diagnostic_id: 'diag1',
  fingerprint: 'fp-conf1',
  note: '人工确认主方向',
  config: { model: 'spherical', parameter_strategy: 'automatic_candidate' },
  created_at: T,
}

const CONFIRMATION_SUMMARY: ProfessionalConfirmationSummary = {
  confirmation: { id: 'conf1', note: '人工确认主方向' },
  diagnosis_id: 'diag1',
  diagnosis_status: 'succeeded',
  dataset_id: 'ds1',
  case_id: 'c1',
  fingerprint: 'fp-conf1',
  config_summary: {},
}

function makeJob(
  status: RunStatus,
  id = 'job1',
  overrides: Partial<AnalysisJobRecord> = {},
): AnalysisJobRecord {
  return {
    id,
    job_kind: 'professional_diagnosis',
    subject_type: 'professional_diagnosis',
    subject_id: 'diag1',
    request_fingerprint: 'fp-diag1',
    status,
    retry_of_job_id: null,
    progress: { phase: 'empirical_variogram', completed_bins: 3, total_bins: 36 },
    error:
      status === 'failed'
        ? { code: 'VARIOGRAM_FIT_FAILED', message: '变异函数拟合失败' }
        : status === 'interrupted'
          ? { code: 'PROCESS_RESTARTED', message: '进程重启导致任务中断' }
          : null,
    created_at: T,
    updated_at: T,
    started_at: T,
    finished_at: null,
    ...overrides,
  }
}

function makeTestRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/cases/:caseId/experiments/new', name: 'experiment-create', component: ExperimentView },
      { path: '/experiments/:experimentId', name: 'experiment-detail', component: { template: '<div />' } },
      {
        path: '/datasets/:datasetId/professional-diagnosis',
        name: 'professional-diagnosis',
        component: ProfessionalDiagnosisView,
      },
    ],
  })
}

async function mountDiagnosis(path: string): Promise<{ wrapper: VueWrapper; router: Router }> {
  const router = makeTestRouter()
  await router.push(path)
  const wrapper = mount(ProfessionalDiagnosisView, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  return { wrapper, router }
}

async function mountExperiment(path: string): Promise<{ wrapper: VueWrapper; router: Router }> {
  const router = makeTestRouter()
  await router.push(path)
  const wrapper = mount(ExperimentView, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  return { wrapper, router }
}

/** 成功诊断链路：点击开始后任务 queued→running→succeeded，证据加载完成。 */
async function runToSuccess(wrapper: VueWrapper) {
  await wrapper.find('[data-test="start-diagnosis"]').trigger('click')
  await flushPromises()
  await vi.advanceTimersByTimeAsync(1000)
  await vi.advanceTimersByTimeAsync(1000)
  await flushPromises()
}

function mockHappyPath() {
  vi.mocked(client.fetchDataset).mockResolvedValue(DATASET)
  vi.mocked(client.requestProfessionalDiagnosis).mockResolvedValue({
    diagnosis_id: 'diag1',
    job_id: 'job1',
    status: 'queued',
    reused: false,
  })
  vi.mocked(client.fetchAnalysisJob)
    .mockResolvedValueOnce(makeJob('running'))
    .mockResolvedValue(makeJob('succeeded'))
  vi.mocked(client.fetchProfessionalDiagnosis).mockResolvedValue(DIAGNOSIS)
  vi.mocked(client.fetchDiagnosisVariogram).mockResolvedValue(EVIDENCE)
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers()
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('数据集入口与质量门禁', () => {
  it('数据集未过质量门禁：诊断页显示门禁提示且无开始按钮，导航保留', async () => {
    vi.mocked(client.fetchDataset).mockResolvedValue(UNGATED_DATASET)
    const { wrapper } = await mountDiagnosis('/datasets/ds1/professional-diagnosis?case=c1')
    expect(wrapper.find('[data-test="quality-gate-blocked"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="start-diagnosis"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="nav-home"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="nav-new-experiment"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('实验页在质量门禁通过后显示专业诊断入口并跳转到诊断路由', async () => {
    vi.mocked(client.fetchDataset).mockResolvedValue(DATASET)
    const { wrapper, router } = await mountExperiment('/cases/c1/experiments/new?dataset=ds1')
    const entry = wrapper.find('[data-test="professional-entry"]')
    expect(entry.exists()).toBe(true)
    await entry.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value).toMatchObject({
      name: 'professional-diagnosis',
      params: { datasetId: 'ds1' },
    })
    expect(router.currentRoute.value.query.case).toBe('c1')
    wrapper.unmount()
  })

  it('实验页在数据集未过质量门禁时不显示专业诊断入口', async () => {
    vi.mocked(client.fetchDataset).mockResolvedValue(UNGATED_DATASET)
    const { wrapper } = await mountExperiment('/cases/c1/experiments/new?dataset=ds1')
    expect(wrapper.find('[data-test="professional-entry"]').exists()).toBe(false)
    wrapper.unmount()
  })
})

describe('诊断运行与证据展示', () => {
  it('轮询至成功：点对模式、采样率与种子披露可见，诊断指纹可见', async () => {
    mockHappyPath()
    const { wrapper } = await mountDiagnosis('/datasets/ds1/professional-diagnosis?case=c1')
    await runToSuccess(wrapper)

    expect(client.requestProfessionalDiagnosis).toHaveBeenCalledTimes(1)
    const [datasetId, payload] = vi.mocked(client.requestProfessionalDiagnosis).mock.calls[0]
    expect(datasetId).toBe('ds1')
    expect(payload.variogram?.lag_count).toBe(12)
    expect(payload.variogram?.directions?.map((d) => d.azimuth_deg)).toContain(0)
    expect(payload.variogram?.directions?.map((d) => d.azimuth_deg)).toContain(90)

    expect(wrapper.find('[data-test="sampling-mode"]').text()).toContain('分层抽样')
    expect(wrapper.find('[data-test="sampling-rate"]').text()).toContain('50.0%')
    expect(wrapper.find('[data-test="sampling-pairs"]').text()).toContain('2475')
    expect(wrapper.find('[data-test="sampling-pairs"]').text()).toContain('4950')
    expect(wrapper.find('[data-test="sampling-seed"]').text()).toContain('42')
    expect(wrapper.find('[data-test="diagnosis-fingerprint"]').text()).toContain('fp-diag1')
    wrapper.unmount()
  })

  it('每个 bin 显示点对数，used_for_fit=false 的 bin 视觉区分并披露排除原因', async () => {
    mockHappyPath()
    const { wrapper } = await mountDiagnosis('/datasets/ds1/professional-diagnosis?case=c1')
    await runToSuccess(wrapper)

    const rows = wrapper.findAll('[data-test="omni-bin-row"]')
    expect(rows).toHaveLength(3)
    expect(rows[0].text()).toContain('120')
    expect(rows[1].text()).toContain('96')
    expect(rows[2].text()).toContain('12')
    expect(rows[2].classes()).toContain('excluded')
    expect(rows[2].text()).toContain('insufficient_pairs')
    wrapper.unmount()
  })

  it('点对支持不足的方向不可选，supported 方向可加入方向系列对比', async () => {
    mockHappyPath()
    const { wrapper } = await mountDiagnosis('/datasets/ds1/professional-diagnosis?case=c1')
    await runToSuccess(wrapper)

    const unsupported = wrapper.find('[data-test="direction-option-d001"]')
    expect(unsupported.exists()).toBe(true)
    expect((unsupported.element as HTMLInputElement).disabled).toBe(true)

    const supported = wrapper.find('[data-test="direction-option-d000"]')
    expect((supported.element as HTMLInputElement).disabled).toBe(false)
    await supported.setValue(true)
    expect(wrapper.find('[data-test="active-direction-d000"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('各向异性候选展示「诊断建议，需人工确认」标签与候选证据', async () => {
    mockHappyPath()
    const { wrapper } = await mountDiagnosis('/datasets/ds1/professional-diagnosis?case=c1')
    await runToSuccess(wrapper)

    expect(wrapper.find('[data-test="suggestion-label"]').text()).toContain('诊断建议，需人工确认')
    const candidate = wrapper.find('[data-test="candidate-evidence"]')
    expect(candidate.text()).toContain('1')
    expect(candidate.text()).toContain('1.8')
    expect(candidate.text()).toContain('78')
    expect(candidate.text()).toContain('single_supported_direction')
    wrapper.unmount()
  })
})

describe('模型选择语义', () => {
  it('变异函数模型无默认选中：占位提示选中且禁用，显式选择后才可确认', async () => {
    mockHappyPath()
    const { wrapper } = await mountDiagnosis('/datasets/ds1/professional-diagnosis?case=c1')
    await runToSuccess(wrapper)

    const select = wrapper.find('[data-test="confirm-model"]')
    expect(select.exists()).toBe(true)
    // 三个模型都不被默认选中：只有禁用的占位提示处于选中态
    const placeholder = select.find('option[disabled]')
    expect(placeholder.exists()).toBe(true)
    expect((placeholder.element as HTMLOptionElement).selected).toBe(true)
    // 只填 note 仍因未选模型而禁用；显式选择后放开
    await wrapper.find('[data-test="confirm-note"]').setValue('审阅拟合证据后确认')
    expect((wrapper.find('[data-test="confirm-submit"]').element as HTMLButtonElement).disabled).toBe(true)
    await select.setValue('exponential')
    expect((wrapper.find('[data-test="confirm-submit"]').element as HTMLButtonElement).disabled).toBe(false)
    wrapper.unmount()
  })

  it('SSE 最小按语义命名披露并附数值稳定警告，无「拟合最优」表述', async () => {
    mockHappyPath()
    const { wrapper } = await mountDiagnosis('/datasets/ds1/professional-diagnosis?case=c1')
    await runToSuccess(wrapper)

    expect(wrapper.find('[data-test="confirm-model"]').text()).toContain('变异函数拟合 SSE 最小')
    expect(wrapper.text()).not.toContain('拟合最优')
    const warning = wrapper.find('[data-test="model-sse-warning"]')
    expect(warning.exists()).toBe(true)
    expect(warning.text()).toContain('拟合 SSE 最小不代表空间验证更优或数值稳定，确认前请审阅拟合证据')
    wrapper.unmount()
  })
})

describe('不可变确认', () => {
  it('note 必填；提交创建新不可变确认快照并展示确认 ID 与指纹，表单不再出现', async () => {
    mockHappyPath()
    vi.mocked(client.confirmProfessionalDiagnosis).mockResolvedValue(CONFIRMATION)
    const { wrapper, router } = await mountDiagnosis('/datasets/ds1/professional-diagnosis?case=c1')
    await runToSuccess(wrapper)

    // note 为空：确认按钮不可用，且不会发出请求
    expect((wrapper.find('[data-test="confirm-submit"]').element as HTMLButtonElement).disabled).toBe(true)
    await wrapper.find('[data-test="confirm-note"]').setValue('人工确认主方向')
    // 模型无默认选中：只填 note 仍不可用，必须显式选择模型
    expect((wrapper.find('[data-test="confirm-submit"]').element as HTMLButtonElement).disabled).toBe(true)
    await wrapper.find('[data-test="confirm-model"]').setValue('spherical')
    expect((wrapper.find('[data-test="confirm-submit"]').element as HTMLButtonElement).disabled).toBe(false)

    await wrapper.find('[data-test="confirm-submit"]').trigger('click')
    await flushPromises()

    expect(client.confirmProfessionalDiagnosis).toHaveBeenCalledTimes(1)
    const [diagnosisId, payload] = vi.mocked(client.confirmProfessionalDiagnosis).mock.calls[0]
    expect(diagnosisId).toBe('diag1')
    expect(payload.note).toBe('人工确认主方向')
    expect(payload.model).toBe('spherical')
    expect(payload.parameter_strategy).toBe('automatic_candidate')
    expect(payload.fitted_models_sha256).toBe('sha-fitted')
    expect(payload.anisotropy.keep_isotropic).toBe(false)
    expect(payload.anisotropy.candidate_rank).toBe(1)
    expect(payload.anisotropy.anisotropy_candidates_sha256).toBe('sha-cand')
    expect(payload.anisotropy.azimuth_deg).toBe(0)
    expect(payload.anisotropy.major_minor_ratio).toBe(1.8)

    // 快照只读展示：确认 ID/指纹可见，编辑表单不再出现（确认只新建、永不编辑）
    expect(wrapper.find('[data-test="confirmation-id"]').text()).toContain('conf1')
    expect(wrapper.find('[data-test="confirmation-fingerprint"]').text()).toContain('fp-conf1')
    expect(wrapper.find('[data-test="confirm-submit"]').exists()).toBe(false)

    const goto = wrapper.find('[data-test="goto-experiment"]')
    expect(goto.exists()).toBe(true)
    await goto.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('experiment-create')
    expect(router.currentRoute.value.query.professional_confirmation).toBe('conf1')
    expect(router.currentRoute.value.query.dataset).toBe('ds1')
    wrapper.unmount()
  })

  it('保持各向同性：载荷不携带任何各向异性参数', async () => {
    mockHappyPath()
    vi.mocked(client.confirmProfessionalDiagnosis).mockResolvedValue(CONFIRMATION)
    const { wrapper } = await mountDiagnosis('/datasets/ds1/professional-diagnosis?case=c1')
    await runToSuccess(wrapper)

    await wrapper.find('[data-test="mode-isotropic"]').setValue(true)
    await wrapper.find('[data-test="confirm-model"]').setValue('spherical')
    await wrapper.find('[data-test="confirm-note"]').setValue('证据不足，保持各向同性')
    await wrapper.find('[data-test="confirm-submit"]').trigger('click')
    await flushPromises()

    const payload = vi.mocked(client.confirmProfessionalDiagnosis).mock.calls[0][1]
    expect(payload.anisotropy).toEqual({ keep_isotropic: true })
    wrapper.unmount()
  })

  it('手动字段校验：非法方位角禁止提交并显示校验提示', async () => {
    mockHappyPath()
    const { wrapper } = await mountDiagnosis('/datasets/ds1/professional-diagnosis?case=c1')
    await runToSuccess(wrapper)

    await wrapper.find('[data-test="manual-azimuth"]').setValue(200)
    await wrapper.find('[data-test="confirm-note"]').setValue('尝试非法方位角')
    expect(wrapper.find('[data-test="anisotropy-invalid"]').exists()).toBe(true)
    expect((wrapper.find('[data-test="confirm-submit"]').element as HTMLButtonElement).disabled).toBe(true)
    expect(client.confirmProfessionalDiagnosis).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})

describe('任务失败与重试', () => {
  it('失败任务显示结构化错误并保留导航；重试创建新任务并恢复轮询', async () => {
    vi.mocked(client.fetchDataset).mockResolvedValue(DATASET)
    vi.mocked(client.requestProfessionalDiagnosis).mockResolvedValue({
      diagnosis_id: 'diag1',
      job_id: 'job1',
      status: 'queued',
      reused: false,
    })
    vi.mocked(client.fetchAnalysisJob).mockImplementation(async (id: string) =>
      id === 'job1' ? makeJob('failed') : makeJob('succeeded', id, { retry_of_job_id: 'job1' }),
    )
    vi.mocked(client.retryAnalysisJob).mockResolvedValue(
      makeJob('queued', 'job2', { retry_of_job_id: 'job1' }),
    )
    vi.mocked(client.fetchProfessionalDiagnosis).mockResolvedValue(DIAGNOSIS)
    vi.mocked(client.fetchDiagnosisVariogram).mockResolvedValue(EVIDENCE)

    const { wrapper } = await mountDiagnosis('/datasets/ds1/professional-diagnosis?case=c1')
    await wrapper.find('[data-test="start-diagnosis"]').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()

    const jobError = wrapper.find('[data-test="job-error"]')
    expect(jobError.text()).toContain('VARIOGRAM_FIT_FAILED')
    expect(jobError.text()).toContain('变异函数拟合失败')
    expect(wrapper.find('[data-test="nav-home"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="nav-new-experiment"]').exists()).toBe(true)

    await wrapper.find('[data-test="retry-diagnosis"]').trigger('click')
    await flushPromises()
    expect(client.retryAnalysisJob).toHaveBeenCalledWith('job1')

    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(client.fetchAnalysisJob).toHaveBeenCalledWith('job2')
    expect(wrapper.find('[data-test="diagnosis-fingerprint"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('interrupted 任务保留导航、显示中断错误并可重试', async () => {
    vi.mocked(client.fetchDataset).mockResolvedValue(DATASET)
    vi.mocked(client.requestProfessionalDiagnosis).mockResolvedValue({
      diagnosis_id: 'diag1',
      job_id: 'job1',
      status: 'queued',
      reused: false,
    })
    vi.mocked(client.fetchAnalysisJob).mockResolvedValue(makeJob('interrupted'))

    const { wrapper } = await mountDiagnosis('/datasets/ds1/professional-diagnosis?case=c1')
    await wrapper.find('[data-test="start-diagnosis"]').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()

    expect(wrapper.find('[data-test="job-error"]').text()).toContain('PROCESS_RESTARTED')
    expect(wrapper.find('[data-test="nav-home"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="nav-new-experiment"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="retry-diagnosis"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('初始加载中保留首页与实验导航', async () => {
    vi.mocked(client.fetchDataset).mockReturnValue(new Promise(() => {}))
    const { wrapper } = await mountDiagnosis('/datasets/ds1/professional-diagnosis?case=c1')
    expect(wrapper.find('[data-test="nav-home"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="nav-new-experiment"]').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('诊断恢复（query.diagnosis）', () => {
  function makeDiagnosticList(
    diagnosis: ProfessionalDiagnosisRecord,
    job: AnalysisJobRecord | null,
  ): ProfessionalDiagnosticList {
    return {
      dataset_id: diagnosis.dataset_version_id,
      diagnostics: [{ diagnosis: diagnosis as unknown as Record<string, unknown>, job: job as unknown as Record<string, unknown> | null, url: `/datasets/${diagnosis.dataset_version_id}/professional-diagnosis?diagnosis=${diagnosis.id}`, latest_confirmation: null }],
    }
  }

  it('已成功的诊断：从 query.diagnosis 恢复后直接展示证据', async () => {
    vi.mocked(client.fetchDataset).mockResolvedValue(DATASET)
    vi.mocked(client.fetchProfessionalDiagnostics).mockResolvedValue(
      makeDiagnosticList(DIAGNOSIS, makeJob('succeeded')),
    )
    vi.mocked(client.fetchProfessionalDiagnosis).mockResolvedValue(DIAGNOSIS)
    vi.mocked(client.fetchDiagnosisVariogram).mockResolvedValue(EVIDENCE)

    const { wrapper } = await mountDiagnosis(
      '/datasets/ds1/professional-diagnosis?case=c1&diagnosis=diag1',
    )
    expect(client.fetchProfessionalDiagnostics).toHaveBeenCalledWith('ds1')
    expect(wrapper.find('[data-test="diagnosis-fingerprint"]').text()).toContain('fp-diag1')
    expect(wrapper.find('[data-test="diagnosis-config"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('运行中的诊断：从 query.diagnosis 恢复后继续轮询至成功', async () => {
    const runningDiagnosis: ProfessionalDiagnosisRecord = { ...DIAGNOSIS, status: 'running' }
    vi.mocked(client.fetchDataset).mockResolvedValue(DATASET)
    vi.mocked(client.fetchProfessionalDiagnostics).mockResolvedValue(
      makeDiagnosticList(runningDiagnosis, makeJob('running')),
    )
    vi.mocked(client.fetchAnalysisJob)
      .mockResolvedValueOnce(makeJob('running'))
      .mockResolvedValue(makeJob('succeeded'))
    vi.mocked(client.fetchProfessionalDiagnosis).mockResolvedValue(DIAGNOSIS)
    vi.mocked(client.fetchDiagnosisVariogram).mockResolvedValue(EVIDENCE)

    const { wrapper } = await mountDiagnosis(
      '/datasets/ds1/professional-diagnosis?case=c1&diagnosis=diag1',
    )
    expect(wrapper.find('[data-test="job-status"]').exists()).toBe(true)

    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()

    expect(wrapper.find('[data-test="diagnosis-fingerprint"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('数据集不匹配时显示错误', async () => {
    const foreignDiagnosis: ProfessionalDiagnosisRecord = {
      ...DIAGNOSIS,
      dataset_version_id: 'ds-other',
    }
    vi.mocked(client.fetchDataset).mockResolvedValue(DATASET)
    vi.mocked(client.fetchProfessionalDiagnostics).mockResolvedValue(
      makeDiagnosticList(foreignDiagnosis, makeJob('succeeded')),
    )

    const { wrapper } = await mountDiagnosis(
      '/datasets/ds1/professional-diagnosis?case=c1&diagnosis=diag1',
    )
    expect(wrapper.find('[data-test="quality-gate-blocked"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('DIAGNOSIS_DATASET_MISMATCH')
    wrapper.unmount()
  })
})

describe('ExperimentView 专业联动', () => {
  function mockExperimentCreate() {
    vi.mocked(client.fetchDataset).mockResolvedValue(DATASET)
    vi.mocked(client.fetchProfessionalConfirmation).mockResolvedValue(CONFIRMATION_SUMMARY)
    vi.mocked(client.createExperiment).mockResolvedValue(EXP)
    vi.mocked(client.startRun).mockResolvedValue({
      id: 'run1',
      experiment_id: 'exp1',
      status: 'queued',
      error_code: null,
      metrics: {},
      retry_of_run_id: null,
      created_at: T,
      updated_at: T,
      started_at: T,
      finished_at: null,
    })
    vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
    vi.mocked(client.fetchCandidates).mockResolvedValue({
      experiment_id: 'exp1',
      candidates: [],
      public_metrics: {},
      latest_run: null,
    })
  }

  it('Kriging 专业确认模式：算法锁定、确认快照可见，提交携带确认 ID 与邻域', async () => {
    mockExperimentCreate()
    const { wrapper } = await mountExperiment(
      '/cases/c1/experiments/new?dataset=ds1&professional_confirmation=conf1',
    )
    expect(client.fetchProfessionalConfirmation).toHaveBeenCalledWith('conf1')
    // 算法锁定为 ordinary_kriging
    expect((wrapper.find('[data-test="algo-idw"]').element as HTMLInputElement).disabled).toBe(true)
    expect((wrapper.find('[data-test="algo-kriging"]').element as HTMLInputElement).checked).toBe(true)
    // 确认快照始终可见
    expect(wrapper.find('[data-test="professional-confirmation"]').text()).toContain('conf1')
    expect(wrapper.find('[data-test="professional-confirmation"]').text()).toContain('fp-conf1')

    // v0.7.0: professional mode auto-enabled, neighborhood section visible
    await wrapper.find('[data-test="nb-radii"]').setValue('80, 40, 20')
    await wrapper.find('[data-test="exp-submit"]').trigger('click')
    await flushPromises()

    expect(client.createExperiment).toHaveBeenCalledTimes(1)
    const payload = vi.mocked(client.createExperiment).mock.calls[0][0]
    expect(payload.algorithm).toBe('ordinary_kriging')
    expect(payload.professional_confirmation_id).toBe('conf1')
    expect(payload.neighborhood).toMatchObject({
      radii: [80, 40, 20],
      min_neighbors: 3,
      max_neighbors: 24,
      sector_count: 4,
      max_per_sector: 8,
    })
    expect(payload.empirical_uncertainty).toMatchObject({
      min_neighbors: 3,
      max_neighbors: 24,
      power: 2,
    })
    wrapper.unmount()
  })

  it('专业确认模式自动启用：确认 ID 存在时邻域/经验不确定性自动包含', async () => {
    mockExperimentCreate()
    const { wrapper } = await mountExperiment(
      '/cases/c1/experiments/new?dataset=ds1&professional_confirmation=conf1',
    )
    // v0.7.0: no toggle - confirmation auto-enables professional mode
    expect(wrapper.find('[data-test="professional-neighborhood"]').exists()).toBe(true)
    await wrapper.find('[data-test="exp-submit"]').trigger('click')
    await flushPromises()

    const payload = vi.mocked(client.createExperiment).mock.calls[0][0]
    expect(payload.algorithm).toBe('ordinary_kriging')
    expect(payload.professional_confirmation_id).toBe('conf1')
    expect(payload).toHaveProperty('neighborhood')
    expect(payload).toHaveProperty('empirical_uncertainty')
    wrapper.unmount()
  })

  it('专业模式关闭：提交载荷不含任何专业字段（legacy 行为逐字不变）', async () => {
    mockExperimentCreate()
    const { wrapper } = await mountExperiment('/cases/c1/experiments/new?dataset=ds1')
    expect(wrapper.find('[data-test="professional-neighborhood"]').exists()).toBe(false)
    await wrapper.find('[data-test="exp-submit"]').trigger('click')
    await flushPromises()

    const payload = vi.mocked(client.createExperiment).mock.calls[0][0]
    expect(payload).not.toHaveProperty('professional_confirmation_id')
    expect(payload).not.toHaveProperty('neighborhood')
    expect(payload).not.toHaveProperty('empirical_uncertainty')
    wrapper.unmount()
  })

  it('无确认快照时普通 Kriging 可正常提交（不含专业参数）', async () => {
    mockExperimentCreate()
    const { wrapper } = await mountExperiment('/cases/c1/experiments/new?dataset=ds1')
    // v0.7.0: no toggle - without confirmation, professional section is hidden
    expect(wrapper.find('[data-test="professional-neighborhood"]').exists()).toBe(false)
    await wrapper.find('[data-test="algo-kriging"]').setValue(true)
    await wrapper.find('[data-test="exp-submit"]').trigger('click')
    await flushPromises()
    expect(client.createExperiment).toHaveBeenCalledTimes(1)
    const payload = vi.mocked(client.createExperiment).mock.calls[0][0]
    expect(payload.algorithm).toBe('ordinary_kriging')
    expect(payload).not.toHaveProperty('professional_confirmation_id')
    expect(payload).not.toHaveProperty('neighborhood')
    wrapper.unmount()
  })
})
