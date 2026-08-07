import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type {
  AnalysisJobRecord,
  AnomalyExtractionRecord,
  CandidateComparisonResult,
  CandidatesResponse,
  ExperimentRecord,
  FoldEvidence,
  ProfessionalResultEvidence,
  ResidualEvidence,
  ResultMetadata,
  ResultPreview,
  UncertaintyPreview,
} from '../../../api/types'
import * as client from '../../../api/client'
import ProfessionalAnalysisView from '../../../views/ProfessionalAnalysisView.vue'
import ResultWorkbenchView from '../../../views/ResultWorkbenchView.vue'

vi.mock('../../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/client')>()
  return {
    ...actual,
    fetchResult: vi.fn(),
    materializeResult: vi.fn(),
    fetchExperiment: vi.fn(),
    fetchCandidates: vi.fn(),
    fetchResultPreview: vi.fn(),
    fetchResultSlice: vi.fn(),
    fetchDatasetPoints: vi.fn(),
    fetchFormalSelections: vi.fn(),
    selectFormal: vi.fn(),
    createExport: vi.fn(),
    createPublication: vi.fn(),
    fetchProfessionalResult: vi.fn(),
    fetchResultFolds: vi.fn(),
    fetchResultResiduals: vi.fn(),
    fetchResultUncertainty: vi.fn(),
    requestAnomalyExtraction: vi.fn(),
    fetchAnomalyExtraction: vi.fn(),
    fetchAnalysisJob: vi.fn(),
    createProfessionalComparison: vi.fn(),
  }
})

const T = '2026-07-26T00:00:00Z'
const FP = 'ab'.repeat(32)

const META_R1: ResultMetadata = {
  result_id: 'r1',
  run_id: 'run1',
  experiment_id: 'exp1',
  dataset_version_id: 'ds1',
  algorithm: 'ordinary_kriging',
  parameters: { variogram_model: 'spherical' },
  dimension: '2d',
  shape: [11, 11],
  cell_count: 121,
  bounds: [
    [0, 100],
    [0, 100],
  ],
  resolution: [10, 10],
  value_range: [50, 200],
  nodata_count: 1,
  grid_sha256: FP,
  source_sha256: FP,
  standardized_sha256: FP,
  fingerprint: 'fp-r1',
  validation: { method: 'spatial_kfold', folds: 2 },
  created_at: T,
  professional_analysis_supported: true,
}

const META_R2: ResultMetadata = { ...META_R1, result_id: 'r2', algorithm: 'idw', fingerprint: 'fp-r2' }

const EXP: ExperimentRecord = {
  id: 'exp1',
  case_id: 'c1',
  name: '实验一',
  params: {
    case_id: 'c1',
    name: '实验一',
    algorithm: 'ordinary_kriging',
    dataset_version_id: 'ds1',
    search_mode: 'grid',
    parameters: {},
    validation: { method: 'spatial_kfold', folds: 2, seed: 1, holdout_fraction: 0.2 },
    grid: null,
  },
  created_at: T,
  updated_at: T,
}

const CANDIDATES: CandidatesResponse = {
  experiment_id: 'exp1',
  candidates: [
    { id: 'r1', fingerprint: 'fp-r1', status: 'succeeded', parameters: {}, metrics: { rmse: 1.2 }, error: null },
    { id: 'r2', fingerprint: 'fp-r2', status: 'succeeded', parameters: {}, metrics: { rmse: 1.5 }, error: null },
    {
      id: 'r3',
      fingerprint: 'fp-r3',
      status: 'failed',
      parameters: {},
      metrics: {},
      error: { code: 'RUN_FAILED', message: '失败' },
    },
  ],
  public_metrics: {},
  latest_run: null,
}

const PROF_KRIGING: ProfessionalResultEvidence = {
  result_id: 'r1',
  available: true,
  algorithm: 'ordinary_kriging',
  confirmation_id: 'conf1',
  capabilities: {
    algorithm: 'ordinary_kriging',
    empirical_variogram: 'supported',
    model_anisotropy: 'supported',
    empirical_error_scale: 'supported',
    native_kriging_std: 'supported',
    anomaly_extraction: 'supported',
    candidate_comparison: 'supported',
    notes: {},
  },
  parameter_provenance: {
    validation: {
      origin: 'automatic_candidate',
      scope: 'fold_training_subsets',
      evidence: 'prediction_diagnostics.json',
    },
    final: {
      origin: 'final_full_data_fit',
      scope: 'all_valid_rows',
      variogram: { model: 'spherical', nugget: 0.05, sill: 0.65, range: 60 },
    },
  },
  manifest: {
    version: 1,
    fingerprint: 'mf-r1',
    artifacts: {
      fold_assignments: { file: 'fold_assignments.parquet', sha256: 'sha-fold', bytes: 100 },
    },
    created_at: T,
  },
}

const PROF_IDW: ProfessionalResultEvidence = {
  ...PROF_KRIGING,
  result_id: 'r2',
  algorithm: 'idw',
  confirmation_id: null,
  capabilities: {
    algorithm: 'idw',
    empirical_variogram: 'not_applicable',
    model_anisotropy: 'not_applicable',
    empirical_error_scale: 'supported',
    native_kriging_std: 'not_applicable',
    anomaly_extraction: 'supported',
    candidate_comparison: 'supported',
    notes: {},
  },
  parameter_provenance: {
    validation: { origin: 'fold_training_subsets', scope: 'fold_training_subsets' },
    final: { origin: 'final_full_data_fit', scope: 'all_valid_rows' },
  },
}

const PROF_LEGACY: ProfessionalResultEvidence = {
  result_id: 'r9',
  available: false,
  reason: 'LEGACY_RESULT_NOT_COMPUTED',
  algorithm: 'idw',
}

const FOLDS_R1: FoldEvidence = {
  result_id: 'r1',
  fold_count: 2,
  leakage_detected: false,
  folds: [
    {
      fold_index: 0,
      training_count: 30,
      validation_count: 2,
      validation_groups: [3, 7],
      group_count: 2,
      leakage_detected: false,
      metrics: { rmse: 1.1, valid_count: 2 },
    },
    {
      fold_index: 1,
      training_count: 28,
      validation_count: 3,
      validation_groups: [1, 5, 9],
      group_count: 3,
      leakage_detected: false,
      metrics: { rmse: 1.4, valid_count: 3 },
    },
  ],
  download_url: '/api/professional-artifacts/result:r1:fold_assignments/download',
}

const FOLDS_LEAKED: FoldEvidence = {
  ...FOLDS_R1,
  leakage_detected: true,
  folds: FOLDS_R1.folds.map((fold, index) =>
    index === 1 ? { ...fold, leakage_detected: true } : fold,
  ),
}

// 5 条 OOF 行：fold 0 两条、fold 1 三条；折切换必须改变验证残差点集
const RESIDUALS_R1: ResidualEvidence = {
  result_id: 'r1',
  total: 5,
  returned: 5,
  decimate: 1,
  source_row: [0, 1, 2, 3, 4],
  fold_index: [0, 0, 1, 1, 1],
  x: [0, 10, 20, 30, 40],
  y: [0, 10, 20, 30, 40],
  z: [null, null, null, null, null],
  observed: [10, 20, 30, 40, 50],
  predicted: [11, 19, 31, 38, 52],
  residual: [-1, 1, -1, 2, -2],
  absolute_error: [1, 1, 1, 2, 2],
  squared_error: [1, 1, 1, 4, 4],
  is_nodata: [false, false, false, false, false],
  download_url: '/api/professional-artifacts/result:r1:out_of_fold_predictions/download',
}

// 值预览：一个 NoData 高值节点（300）——阈值 100 高值方向下只有 150/200 两个合格节点
const PREVIEW_R1: ResultPreview = {
  result_id: 'r1',
  dimension: '2d',
  original_cell_count: 4,
  served_cell_count: 4,
  stride: 1,
  x: [0, 10, 20, 30],
  y: [0, 10, 20, 30],
  z: null,
  values: [50, 150, 200, 300],
  is_nodata: [false, false, false, true],
  value_range: [50, 300],
}

const UNC_EMPIRICAL: UncertaintyPreview = {
  result_id: 'r1',
  layer: 'empirical_error',
  dimension: '2d',
  original_cell_count: 4,
  served_cell_count: 4,
  stride: 1,
  x: [0, 10, 20, 30],
  y: [0, 10, 20, 30],
  z: null,
  values: [1, 2, 3, 4],
  is_nodata: [false, false, false, false],
  value_range: [1, 4],
}

const UNC_KRIGING: UncertaintyPreview = {
  result_id: 'r1',
  layer: 'kriging_std',
  dimension: '2d',
  original_cell_count: 4,
  served_cell_count: 4,
  stride: 1,
  x: [0, 10, 20, 30],
  y: [0, 10, 20, 30],
  z: null,
  values: [0.1, 0.2, 0.3, 0.4],
  is_nodata: [false, false, false, false],
  value_range: [0.1, 0.4],
}

const EXTRACTION_JOB: AnalysisJobRecord = {
  id: 'job-ext1',
  job_kind: 'anomaly_extraction',
  subject_type: 'anomaly_extraction',
  subject_id: 'ext1',
  request_fingerprint: 'fp-ext1',
  status: 'succeeded',
  retry_of_job_id: null,
  progress: {},
  error: null,
  created_at: T,
  updated_at: T,
  started_at: T,
  finished_at: T,
}

const EXTRACTION: AnomalyExtractionRecord = {
  id: 'ext1',
  candidate_result_id: 'r1',
  status: 'succeeded',
  fingerprint: 'fp-ext1',
  config: { direction: 'high', threshold: 100, empirical_error_max: 5, kriging_std_max: 8 },
  manifest: {
    version: 1,
    fingerprint: 'mf-ext1',
    artifacts: { components: { file: 'components.csv', sha256: 'sha-comp', bytes: 50 } },
    created_at: T,
  },
  error: null,
  components: {
    total: 1,
    returned: 1,
    rows: [
      {
        component_id: 1,
        support_node_count: 2,
        support_measure: 200,
        support_unit: 'area_coordinate_unit2',
        // 包围盒覆盖预览点 (10,10)/(20,20)/(30,30)；其中 (30,30) 是 NoData，不得进入高亮
        bounds: [
          [5, 35],
          [5, 35],
        ],
        centroid: [15, 15],
        value_min: 150,
        value_max: 200,
        value_mean: 175,
        touches_grid_boundary: false,
        empirical_error_scale_min: 1,
        empirical_error_scale_max: 2,
        empirical_error_scale_mean: 1.5,
        kriging_std_min: 3,
        kriging_std_max: 4,
        kriging_std_mean: 3.5,
      },
    ],
  },
  created_at: T,
}

const COMPATIBLE: CandidateComparisonResult = {
  first_result_id: 'r1',
  second_result_id: 'r2',
  compatible: true,
  mismatches: [],
  common_valid_count: 40,
  metric_deltas: { rmse: -0.3, mae: -0.2 },
  grid_difference_available: true,
  grid_difference: { common_valid_count: 121, mean: 0.05, max_abs: 1.2 },
  comparison_fingerprint: FP,
}

const INCOMPATIBLE: CandidateComparisonResult = {
  first_result_id: 'r1',
  second_result_id: 'r2',
  compatible: false,
  mismatches: ['dataset_version_id', 'validation_fingerprint'],
  common_valid_count: null,
  metric_deltas: null,
  grid_difference_available: false,
  grid_difference: null,
  comparison_fingerprint: 'cd'.repeat(32),
}

function makeTestRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/experiments/:experimentId', name: 'experiment-detail', component: { template: '<div />' } },
      { path: '/results/:resultId', name: 'result-workbench', component: ResultWorkbenchView },
      {
        path: '/results/:resultId/professional',
        name: 'professional-analysis',
        component: ProfessionalAnalysisView,
      },
    ],
  })
}

async function mountAnalysis(path = '/results/r1/professional') {
  const router = makeTestRouter()
  await router.push(path)
  const wrapper = mount(ProfessionalAnalysisView, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  return { wrapper, router }
}

function mockKrigingPath() {
  vi.mocked(client.fetchResult).mockImplementation(async (id: string) =>
    id === 'r2' ? META_R2 : META_R1,
  )
  vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
  vi.mocked(client.fetchCandidates).mockResolvedValue(CANDIDATES)
  vi.mocked(client.fetchProfessionalResult).mockImplementation(async (id: string) =>
    id === 'r2' ? PROF_IDW : PROF_KRIGING,
  )
  vi.mocked(client.fetchResultFolds).mockImplementation(async (id: string) => ({
    ...FOLDS_R1,
    result_id: id,
  }))
  vi.mocked(client.fetchResultResiduals).mockImplementation(async (id: string) => ({
    ...RESIDUALS_R1,
    result_id: id,
  }))
  vi.mocked(client.fetchResultPreview).mockImplementation(async (id: string) => ({
    ...PREVIEW_R1,
    result_id: id,
  }))
  vi.mocked(client.fetchResultUncertainty).mockImplementation(
    async (id: string, kind: string) => ({
      ...(kind === 'kriging_std' ? UNC_KRIGING : UNC_EMPIRICAL),
      result_id: id,
      layer: kind,
    }),
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers()
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('单候选联动与参数快照', () => {
  it('切换候选后所有面板请求同一 result ID；失败候选不进入选择器', async () => {
    mockKrigingPath()
    const { wrapper } = await mountAnalysis()

    // 初始加载：全部以 r1 请求
    expect(client.fetchProfessionalResult).toHaveBeenCalledWith('r1')
    expect(client.fetchResultFolds).toHaveBeenCalledWith('r1')
    expect(client.fetchResultResiduals).toHaveBeenCalledWith('r1')
    expect(client.fetchResultPreview).toHaveBeenCalledWith('r1')

    // 失败候选 r3 不进入候选切换器
    expect(wrapper.find('[data-test="candidate-option-r3"]').exists()).toBe(false)
    const option = wrapper.find('[data-test="candidate-option-r2"]')
    expect(option.exists()).toBe(true)
    await option.trigger('click')
    await flushPromises()

    // 切换后：专业证据/折分/残差/预览全部以 r2 重新请求
    expect(client.fetchProfessionalResult).toHaveBeenCalledWith('r2')
    expect(client.fetchResultFolds).toHaveBeenCalledWith('r2')
    expect(client.fetchResultResiduals).toHaveBeenCalledWith('r2')
    expect(client.fetchResultPreview).toHaveBeenCalledWith('r2')
    expect(wrapper.find('[data-test="selected-candidate-id"]').text()).toContain('r2')

    // 不确定性面板同样跟随新候选
    await wrapper.find('[data-test="layer-tab-empirical"]').trigger('click')
    await flushPromises()
    expect(client.fetchResultUncertainty).toHaveBeenCalledWith('r2', 'empirical_error')
    wrapper.unmount()
  })

  it('参数快照展示算法、能力、参数出处与确认身份', async () => {
    mockKrigingPath()
    const { wrapper } = await mountAnalysis()

    expect(wrapper.find('[data-test="summary-algorithm"]').text()).toContain('ordinary_kriging')
    expect(wrapper.find('[data-test="summary-confirmation"]').text()).toContain('conf1')
    expect(wrapper.find('[data-test="capability-native-kriging-std"]').text()).toContain('supported')
    expect(wrapper.find('[data-test="param-origin-validation"]').text()).toContain(
      'automatic_candidate',
    )
    expect(wrapper.find('[data-test="param-origin-final"]').text()).toContain('final_full_data_fit')
    wrapper.unmount()
  })

  it('legacy 成果显示不可用原因并保留导航，不渲染分析面板', async () => {
    vi.mocked(client.fetchResult).mockResolvedValue({ ...META_R1, result_id: 'r9' })
    vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
    vi.mocked(client.fetchCandidates).mockResolvedValue(CANDIDATES)
    vi.mocked(client.fetchProfessionalResult).mockResolvedValue(PROF_LEGACY)

    const { wrapper } = await mountAnalysis('/results/r9/professional')
    expect(wrapper.find('[data-test="legacy-unavailable"]').text()).toContain(
      'LEGACY_RESULT_NOT_COMPUTED',
    )
    expect(wrapper.find('[data-test="fold-inspector"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="nav-home"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="nav-experiment"]').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('FoldInspector 折分检查', () => {
  it('折切换改变训练/验证计数与验证残差点集，泄漏徽标可见', async () => {
    mockKrigingPath()
    const { wrapper } = await mountAnalysis()

    // 默认选中 fold 0
    expect(wrapper.find('[data-test="fold-training-count"]').text()).toContain('30')
    expect(wrapper.find('[data-test="fold-validation-count"]').text()).toContain('2')
    expect(wrapper.find('[data-test="fold-rmse"]').text()).toContain('1.1')
    expect(wrapper.find('[data-test="validation-point-count"]').text()).toContain('2')
    expect(wrapper.find('[data-test="context-point-count"]').text()).toContain('3')
    expect(wrapper.find('[data-test="leakage-badge"]').text()).toContain('未检测到泄漏')

    await wrapper.find('[data-test="fold-tab-1"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="fold-training-count"]').text()).toContain('28')
    expect(wrapper.find('[data-test="fold-validation-count"]').text()).toContain('3')
    expect(wrapper.find('[data-test="fold-rmse"]').text()).toContain('1.4')
    expect(wrapper.find('[data-test="fold-group-count"]').text()).toContain('3')
    expect(wrapper.find('[data-test="validation-point-count"]').text()).toContain('3')
    expect(wrapper.find('[data-test="context-point-count"]').text()).toContain('2')
    wrapper.unmount()
  })

  it('泄漏检查失败阻断分析视图并显示失败态，导航保留', async () => {
    mockKrigingPath()
    vi.mocked(client.fetchResultFolds).mockResolvedValue(FOLDS_LEAKED)
    const { wrapper } = await mountAnalysis()

    expect(wrapper.find('[data-test="leakage-blocked"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="fold-inspector"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="uncertainty-panel"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="anomaly-panel"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="nav-home"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="nav-experiment"]').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('UncertaintyPanel 不确定性图层', () => {
  it('IDW 显示经验误差尺度与「Kriging standard deviation not applicable」，绝不请求 kriging_std', async () => {
    mockKrigingPath()
    const { wrapper } = await mountAnalysis()
    await wrapper.find('[data-test="candidate-option-r2"]').trigger('click')
    await flushPromises()

    // IDW 候选：经验误差层可切换
    await wrapper.find('[data-test="layer-tab-empirical"]').trigger('click')
    await flushPromises()
    expect(client.fetchResultUncertainty).toHaveBeenCalledWith('r2', 'empirical_error')
    expect(wrapper.find('[data-test="layer-value-range"]').text()).toContain('1')
    expect(wrapper.find('[data-test="layer-value-range"]').text()).toContain('4')

    // Kriging 标准差不适用：类型化提示，且绝不发起 kriging_std 请求
    await wrapper.find('[data-test="layer-tab-kriging-std"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="kriging-std-na"]').text()).toContain(
      'Kriging standard deviation not applicable',
    )
    expect(client.fetchResultUncertainty).not.toHaveBeenCalledWith('r2', 'kriging_std')
    expect(client.fetchResultUncertainty).not.toHaveBeenCalledWith('r1', 'kriging_std')
    wrapper.unmount()
  })

  it('Kriging 可切换 值/经验误差/Kriging 标准差 三图层，各自独立图例与值域标题', async () => {
    mockKrigingPath()
    const { wrapper } = await mountAnalysis()

    // 默认值图层
    expect(wrapper.find('[data-test="layer-title"]').text()).toContain('预测值')
    expect(wrapper.find('[data-test="layer-value-range"]').text()).toContain('50')
    expect(wrapper.find('[data-test="layer-value-range"]').text()).toContain('300')

    await wrapper.find('[data-test="layer-tab-empirical"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="layer-title"]').text()).toContain('经验误差尺度')
    expect(wrapper.find('[data-test="layer-value-range"]').text()).toContain('1')
    expect(wrapper.find('[data-test="layer-value-range"]').text()).toContain('4')
    expect(client.fetchResultUncertainty).toHaveBeenCalledWith('r1', 'empirical_error')

    await wrapper.find('[data-test="layer-tab-kriging-std"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="layer-title"]').text()).toContain('Kriging 标准差')
    expect(wrapper.find('[data-test="layer-value-range"]').text()).toContain('0.1')
    expect(wrapper.find('[data-test="layer-value-range"]').text()).toContain('0.4')
    expect(client.fetchResultUncertainty).toHaveBeenCalledWith('r1', 'kriging_std')

    // 切回值图层：值域标题恢复
    await wrapper.find('[data-test="layer-tab-value"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="layer-title"]').text()).toContain('预测值')
    expect(wrapper.find('[data-test="layer-value-range"]').text()).toContain('50')
    wrapper.unmount()
  })
})

describe('AnomalyPanel 异常提取', () => {
  async function saveAnomaly(wrapper: VueWrapper) {
    await wrapper.find('[data-test="anomaly-threshold"]').setValue(100)
    await wrapper.find('[data-test="anomaly-empirical-max"]').setValue(5)
    await wrapper.find('[data-test="anomaly-kriging-max"]').setValue(8)
    await wrapper.find('[data-test="anomaly-save"]').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
  }

  it('阈值预览排除 NoData 节点；保存发送阈值与不确定性门槛并轮询任务', async () => {
    mockKrigingPath()
    vi.mocked(client.requestAnomalyExtraction).mockResolvedValue({
      extraction_id: 'ext1',
      job_id: 'job-ext1',
      status: 'pending',
      reused: false,
    })
    vi.mocked(client.fetchAnalysisJob).mockResolvedValue(EXTRACTION_JOB)
    vi.mocked(client.fetchAnomalyExtraction).mockResolvedValue(EXTRACTION)

    const { wrapper } = await mountAnalysis()
    // 阈值 100 高值方向：NoData 节点（值 300）不进入预览计数
    await wrapper.find('[data-test="anomaly-threshold"]').setValue(100)
    await flushPromises()
    expect(wrapper.find('[data-test="anomaly-preview-count"]').text()).toContain('2')

    await saveAnomaly(wrapper)
    expect(client.requestAnomalyExtraction).toHaveBeenCalledTimes(1)
    const [resultId, payload] = vi.mocked(client.requestAnomalyExtraction).mock.calls[0]
    expect(resultId).toBe('r1')
    expect(payload).toMatchObject({
      direction: 'high',
      threshold: 100,
      empirical_error_max: 5,
      kriging_std_max: 8,
    })
    expect(client.fetchAnalysisJob).toHaveBeenCalledWith('job-ext1')
    expect(client.fetchAnomalyExtraction).toHaveBeenCalledWith('ext1')
    wrapper.unmount()
  })

  it('保存后展示提取身份与连通区表；NoData 节点不进入高亮集合', async () => {
    mockKrigingPath()
    vi.mocked(client.requestAnomalyExtraction).mockResolvedValue({
      extraction_id: 'ext1',
      job_id: null,
      status: 'succeeded',
      reused: true,
    })
    vi.mocked(client.fetchAnomalyExtraction).mockResolvedValue(EXTRACTION)

    const { wrapper } = await mountAnalysis()
    await saveAnomaly(wrapper)

    expect(wrapper.find('[data-test="extraction-identity"]').text()).toContain('ext1')
    expect(wrapper.find('[data-test="extraction-fingerprint"]').text()).toContain('fp-ext1')
    const rows = wrapper.findAll('[data-test="component-row"]')
    expect(rows).toHaveLength(1)
    expect(rows[0].text()).toContain('1')
    expect(rows[0].text()).toContain('2') // support_node_count
    // 高亮：包围盒内 3 个预览点中 NoData (30,30) 被排除
    expect(wrapper.find('[data-test="highlight-count"]').text()).toContain('2')
    wrapper.unmount()
  })
})

describe('CandidateComparison 双候选比较', () => {
  it('兼容比较显示成对公共指标差与场差摘要', async () => {
    mockKrigingPath()
    vi.mocked(client.createProfessionalComparison).mockResolvedValue(COMPATIBLE)
    const { wrapper } = await mountAnalysis()

    await wrapper.find('[data-test="comparison-second-r2"]').trigger('click')
    await wrapper.find('[data-test="comparison-run"]').trigger('click')
    await flushPromises()

    expect(client.createProfessionalComparison).toHaveBeenCalledWith('r1', 'r2')
    expect(wrapper.find('[data-test="comparison-compatible"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="common-valid-count"]').text()).toContain('40')
    const deltas = wrapper.findAll('[data-test="metric-delta-row"]')
    expect(deltas.length).toBe(2)
    expect(wrapper.text()).toContain('rmse')
    expect(wrapper.text()).toContain('-0.3')
    expect(wrapper.find('[data-test="grid-difference"]').text()).toContain('121')
    expect(wrapper.find('[data-test="grid-difference"]').text()).toContain('1.2')
    wrapper.unmount()
  })

  it('不兼容比较显示原因且禁止显示指标差', async () => {
    mockKrigingPath()
    vi.mocked(client.createProfessionalComparison).mockResolvedValue(INCOMPATIBLE)
    const { wrapper } = await mountAnalysis()

    await wrapper.find('[data-test="comparison-second-r2"]').trigger('click')
    await wrapper.find('[data-test="comparison-run"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="comparison-incompatible"]').exists()).toBe(true)
    const reasons = wrapper.find('[data-test="mismatch-reasons"]')
    expect(reasons.text()).toContain('dataset_version_id')
    expect(reasons.text()).toContain('validation_fingerprint')
    expect(wrapper.find('[data-test="metric-delta-row"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="common-valid-count"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="grid-difference"]').exists()).toBe(false)
    wrapper.unmount()
  })
})

describe('只读性与导航契约', () => {
  it('任何开关都不修改正式选择或结果指标（无相关写请求）', async () => {
    mockKrigingPath()
    vi.mocked(client.createProfessionalComparison).mockResolvedValue(COMPATIBLE)
    vi.mocked(client.requestAnomalyExtraction).mockResolvedValue({
      extraction_id: 'ext1',
      job_id: null,
      status: 'succeeded',
      reused: true,
    })
    vi.mocked(client.fetchAnomalyExtraction).mockResolvedValue(EXTRACTION)

    const { wrapper } = await mountAnalysis()
    // 全量交互：切换候选、切换图层、切换折、保存异常、运行比较
    await wrapper.find('[data-test="candidate-option-r2"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="candidate-option-r1"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="layer-tab-empirical"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="layer-tab-kriging-std"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="fold-tab-1"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="anomaly-threshold"]').setValue(100)
    await wrapper.find('[data-test="anomaly-save"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="comparison-second-r2"]').trigger('click')
    await wrapper.find('[data-test="comparison-run"]').trigger('click')
    await flushPromises()

    expect(client.selectFormal).not.toHaveBeenCalled()
    expect(client.createExport).not.toHaveBeenCalled()
    expect(client.createPublication).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('加载失败保留返回首页/实验导航', async () => {
    vi.mocked(client.fetchResult).mockRejectedValue(new client.ApiError('RESULT_NOT_FOUND', '成果不存在', 404))
    const { wrapper } = await mountAnalysis()
    expect(wrapper.find('[data-test="nav-home"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="load-error"]').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('ResultWorkbenchView 专业分析入口', () => {
  it('成果工作台显示专业分析链接并跳转，现有切片行为不变', async () => {
    // v0.6.1：成果工作台挂载时显式物化（POST），不再走 fetchResult
    vi.mocked(client.materializeResult).mockResolvedValue(META_R1)
    vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
    vi.mocked(client.fetchDatasetPoints).mockResolvedValue({
      dataset_id: 'ds1',
      dimension: '2d',
      count: 0,
      served: 0,
      decimate: 1,
      x: [],
      y: [],
      z: null,
      values: [],
      value_range: null,
      value_name: null,
      source_sha256: null,
    })
    vi.mocked(client.fetchFormalSelections).mockResolvedValue({ case_id: 'c1', selections: [] })

    const router = makeTestRouter()
    await router.push('/results/r1')
    const wrapper = mount(ResultWorkbenchView, { global: { plugins: [router, ElementPlus] } })
    await flushPromises()

    // 现有行为不变：2D 成果仍显示切片面板
    expect(wrapper.find('[data-test="slice-panel"]').exists()).toBe(true)
    const entry = wrapper.find('[data-test="professional-entry"]')
    expect(entry.exists()).toBe(true)
    await entry.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value).toMatchObject({
      name: 'professional-analysis',
      params: { resultId: 'r1' },
    })
    wrapper.unmount()
  })
})
