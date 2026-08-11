import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as client from '../../../api/client'
import ResultWorkbenchView from '../../../views/ResultWorkbenchView.vue'
import { RESULT_ANALYSIS_MOCK_3D } from '../../../mocks/resultAnalysisMock'
import type {
  DatasetPoints,
  DisplayTransform,
  ExperimentRecord,
  PlatformCaseRecord,
  RenderCapability,
  ResultMetadata,
} from '../../../api/types'

// v0.9.0 V6 Task 3/4：成果工作台一屏结构合同。
// 钉死 V6 四层（成果顶栏 → 摘要条 → 三栏主舞台 → 四标签证据窗）与稳定
// 测试钩子；旧面包屑/页面头/调试身份块不得出现在主舞台。

vi.mock('../../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/client')>()
  return {
    ...actual,
    materializeResult: vi.fn(),
    fetchExperiment: vi.fn(),
    fetchCase: vi.fn(),
    fetchCases: vi.fn(),
    fetchDatasetPoints: vi.fn(),
    fetchResultPreview: vi.fn(),
    fetchResultAnalysisSummary: vi.fn(),
    fetchResultRenderCapability: vi.fn(),
    fetchResultRenderAsset: vi.fn(),
  }
})

vi.mock('echarts/core', () => ({
  init: vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(), on: vi.fn() })),
  use: vi.fn(),
}))
vi.mock('echarts/charts', () => ({ BarChart: {}, LineChart: {}, PieChart: {}, ScatterChart: {}, HeatmapChart: {} }))
vi.mock('echarts/components', () => ({
  GridComponent: {},
  TooltipComponent: {},
  LegendComponent: {},
  VisualMapComponent: {},
}))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

const T = '2026-07-23T00:00:00Z'

const META_3D: ResultMetadata = {
  result_id: 'r1',
  run_id: 'run1',
  experiment_id: 'exp1',
  dataset_version_id: 'ds1',
  algorithm: 'ordinary_kriging',
  parameters: {},
  dimension: '3d',
  shape: [7, 23, 42],
  cell_count: 6762,
  bounds: [
    [-150, -60],
    [260, 580],
    [-800, -200],
  ],
  resolution: [9, 32, 60],
  value_range: [1.4, 133.1],
  nodata_count: 0,
  grid_sha256: 'cd'.repeat(32),
  source_sha256: 'ab'.repeat(32),
  standardized_sha256: 'ab'.repeat(32),
  fingerprint: 'fp1',
  validation: { folds: 5 },
  created_at: T,
  evaluation_summary: {
    common_valid_count: 1481,
    candidate_valid_count: 1481,
    candidate_nodata_count: 0,
    total_count: 1481,
    coverage: 1,
    rmse: 6.45,
    mae: 3.25,
    r2: 0.923,
    bias: -0.09,
    enhanced_evidence_available: false,
  },
}

const EXP: ExperimentRecord = {
  id: 'exp1',
  case_id: 'resistivity',
  name: '电阻率实验',
  params: {
    case_id: 'resistivity',
    name: '电阻率实验',
    algorithm: 'ordinary_kriging',
    dataset_version_id: 'ds1',
    search_mode: 'manual',
    parameters: {},
    validation: { method: 'spatial_kfold', folds: 5, seed: 1, holdout_fraction: 0.2 },
    grid: null,
  },
  created_at: T,
  updated_at: T,
}

const CASE: PlatformCaseRecord = {
  id: 'resistivity',
  name: '地下电阻率',
  case_type: 'generic',
  config: {},
  created_at: T,
  updated_at: T,
}

const TRANSFORM: DisplayTransform = {
  contract: 'wgs84_display_anchor_v1',
  origin_x: -150,
  origin_y: 260,
  anchor_longitude: 120,
  anchor_latitude: 30,
  anchor_height: 0,
  metres_per_degree_lon: 96486.3,
  metres_per_degree_lat: 110852.4,
}

const CAPABILITY: RenderCapability = {
  source_kind: 'candidate_result',
  source_id: 'r1',
  supported: true,
  reason_code: null,
  reason: null,
  dimension: '3d',
  grid_kind: 'regular',
  property_name: 'RHO',
  units: 'unknown',
  geolocation_status: 'display_anchor_only',
  display_transform: TRANSFORM,
  render_profile: null,
}

const POINTS: DatasetPoints = {
  dataset_id: 'ds1',
  dimension: '3d',
  count: 3,
  served: 3,
  decimate: 1,
  x: [-150, -141, -132],
  y: [260, 292, 324],
  z: [-800, -700, -600],
  values: [10, 50, 60],
  value_range: [10, 60],
  value_name: '电阻率',
  source_sha256: 'ab'.repeat(32),
}

async function mountV6() {
  vi.mocked(client.materializeResult).mockResolvedValue(META_3D)
  vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
  vi.mocked(client.fetchCase).mockResolvedValue(CASE)
  vi.mocked(client.fetchCases).mockResolvedValue({ cases: [{ case_id: 'resistivity', title: '地下电阻率', status: 'active', links: { detail: '/cases/resistivity', publish_status: null } }] })
  vi.mocked(client.fetchDatasetPoints).mockResolvedValue(POINTS)
  vi.mocked(client.fetchResultPreview).mockResolvedValue({
    result_id: 'r1',
    dimension: '3d',
    original_cell_count: 6762,
    served_cell_count: 2,
    stride: 1,
    x: [-150, -141],
    y: [260, 292],
    z: [-800, -740],
    values: [10, 20],
    is_nodata: [false, false],
    value_range: [10, 20],
  })
  vi.mocked(client.fetchResultAnalysisSummary).mockResolvedValue(RESULT_ANALYSIS_MOCK_3D)
  vi.mocked(client.fetchResultRenderCapability).mockResolvedValue(CAPABILITY)
  vi.mocked(client.fetchResultRenderAsset).mockRejectedValue(
    new client.ApiError('RENDER_ASSET_NOT_FOUND', '尚未创建', 404),
  )
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/cases/:caseId', name: 'case-workspace', component: { template: '<div />' } },
      { path: '/experiments/:experimentId', name: 'experiment-detail', component: { template: '<div />' } },
      { path: '/datasets/:datasetId/candidate-comparison', name: 'candidate-comparison', component: { template: '<div />' } },
      { path: '/results/:resultId', name: 'result-workbench', component: ResultWorkbenchView },
      { path: '/results/:resultId/evaluation', name: 'model-evaluation', component: { template: '<div />' } },
    ],
  })
  await router.push('/results/r1')
  const wrapper = mount(ResultWorkbenchView, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('V6 成果工作台结构合同', () => {
  it('四层结构钩子齐备；旧面包屑与调试身份块消失', async () => {
    const { wrapper } = await mountV6()
    expect(wrapper.find('[data-test="v6-result-topbar"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="v6-result-summary"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="v6-main-stage"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="tools-rail"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="result-scene"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="result-analysis-side"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="result-evidence-dock"]').exists()).toBe(true)
    // 旧通用页面元素不得出现
    expect(wrapper.find('[data-test="page-navigation"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="asset-identity"]').exists()).toBe(false)
  })

  it('证据窗只使用四个一级标签', async () => {
    const { wrapper } = await mountV6()
    const tabs = wrapper.findAll('[data-test^="ge-tab-"]')
    expect(tabs.map((t) => t.text())).toEqual(['综合分析', '切片与异常', '模型证据', '数据溯源'])
  })

  it('V6 顶栏：品牌、五段导航、案例选择、导出报告主动作', async () => {
    const { wrapper } = await mountV6()
    const topbar = wrapper.get('[data-test="v6-result-topbar"]')
    expect(topbar.text()).toContain('GeoModelingPlatform')
    expect(topbar.find('[data-test="v6-nav-home"]').exists()).toBe(true)
    expect(topbar.find('[data-test="v6-nav-ingest"]').exists()).toBe(true)
    expect(topbar.find('[data-test="v6-nav-experiment"]').exists()).toBe(true)
    expect(topbar.find('[data-test="v6-nav-compare"]').exists()).toBe(true)
    expect(topbar.find('[data-test="v6-nav-result"]').exists()).toBe(true)
    // 案例选择显示真实案例名；导出报告是唯一主动作
    expect(topbar.get('[data-test="v6-case-select"]').text()).toContain('地下电阻率')
    expect(topbar.find('[data-test="v6-export-report"]').exists()).toBe(true)
    // 答辩模式/回收站/服务版本不得挤占成果页顶栏
    expect(topbar.find('[data-test="presentation-mode-entry"]').exists()).toBe(false)
    expect(topbar.find('[data-test="shell-trash-link"]').exists()).toBe(false)
    expect(topbar.find('[data-test="shell-service-status"]').exists()).toBe(false)
  })

  it('摘要条：左侧成果身份，右侧判断指标；无指纹长串与完整哈希', async () => {
    const { wrapper } = await mountV6()
    const summary = wrapper.get('[data-test="v6-result-summary"]')
    expect(summary.text()).toContain('地下电阻率')
    expect(summary.text()).toContain('普通克里金')
    expect(summary.text()).toContain('7 × 23 × 42')
    expect(summary.text()).toContain('local_linear')
    expect(summary.text()).toContain('R² 0.923')
    expect(summary.text()).toContain('1,481')
    expect(summary.text()).not.toContain('cdcdcdcd')
    expect(summary.text()).not.toContain('fp1')
  })
})
