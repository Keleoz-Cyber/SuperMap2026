import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type {
  CaseDatasetsResponse,
  MicroseismicDerivation,
  MicroseismicImportResponse,
  PublishStatus,
  QualityReport,
} from '../../../api/types'
import * as client from '../../../api/client'
import MicroseismicImportView from '../../../views/MicroseismicImportView.vue'
import CaseCreateView from '../../../views/CaseCreateView.vue'
import HomeView from '../../../views/HomeView.vue'

vi.mock('../../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/client')>()
  return {
    ...actual,
    createCase: vi.fn(),
    uploadDataset: vi.fn(),
    fetchCaseDatasets: vi.fn(),
    fetchDataset: vi.fn(),
    fetchCases: vi.fn(),
    fetchRhoPublishStatus: vi.fn(),
    importMicroseismic: vi.fn(),
    fetchMicroseismicDerivation: vi.fn(),
    fetchMicroseismicDerivationPoints: vi.fn(),
    validateDataset: vi.fn(),
    confirmWarnings: vi.fn(),
  }
})

const SHA = 'ab'.repeat(32)

// 夹具计数与真实口径（2006/1925 等）刻意不同，证明前端展示来自响应而非硬编码
const LAYER_COUNTS = {
  source_records: 45,
  finite_records: 44,
  invalid_records: 1,
  rejected_3sigma: 3,
  accepted_modeling: 41,
  aggregated_nodes: 40,
}

const AGGREGATION = {
  conflict_group_count: 2,
  conflict_row_count: 4,
  collapsed_row_count: 2,
  max_value_range: 0.12,
}

const GOLDEN = {
  passed: true,
  checks: [
    { name: 'accepted_count', passed: true, expected: 41, actual: 41 },
    { name: 'rejected_count', passed: true, expected: 3, actual: 3 },
    { name: 'modeling_node_count', passed: true, expected: 40, actual: 40 },
  ],
}

const MAPPING = {
  dimension: '3d' as const,
  x: 'X_LOCAL_M',
  y: 'Y_LOCAL_M',
  z: 'Z_LOCAL_M',
  value: 'VX_KM_S',
  value_name: 'Vx',
  value_unit: 'km/s',
  coordinate_kind: 'local_linear' as const,
}

const SOURCE_FILES = Array.from({ length: 22 }, (_, i) => ({
  file_name: `W${i + 1}.dat`,
  sha256: SHA,
  point_id: `W${i + 1}`,
  line_id: i < 9 ? 'L1' : i < 18 ? 'L2' : 'L3',
  source_record_count: 2,
}))

const IMPORT_RESPONSE: MicroseismicImportResponse = {
  id: 'ds-micro-1',
  case_id: 'c1',
  version: 1,
  status: 'mapped',
  created_at: '2026-07-25T00:00:00Z',
  profile: {
    source_kind: 'microseismic_dat_bundle',
    dimension: '3d',
    mapping: MAPPING,
    rule_version: 'microseismic-v0.5-fixture',
    adapter_version: '0.5.0',
    aggregation_method: 'arithmetic_mean_exact_xyz',
    golden: GOLDEN,
    layer_counts: LAYER_COUNTS,
    aggregation: AGGREGATION,
    source_files: SOURCE_FILES,
    derivation_report: 'derived/derivation_report.json',
    modeling_provenance: 'derived/modeling_provenance.parquet',
    row_count: 40,
    valid_row_count: 40,
    invalid_row_count: 0,
    standardized_sha256: SHA,
  },
}

const DERIVATION: MicroseismicDerivation = {
  dataset_id: 'ds-micro-1',
  case_id: 'c1',
  status: 'mapped',
  source_kind: 'microseismic_dat_bundle',
  rule_version: 'microseismic-v0.5-fixture',
  adapter_version: '0.5.0',
  aggregation_method: 'arithmetic_mean_exact_xyz',
  layer_counts: LAYER_COUNTS,
  line_counts: { L1: 19, L2: 18, L3: 8 },
  three_sigma: {
    threshold: 3,
    ddof: 1,
    depth_mean: 120.5,
    depth_std: 30.25,
    vx_mean: 0.52,
    vx_std: 0.04,
  },
  aggregation: AGGREGATION,
  coordinates: {
    coord_type: 'local_engineering_m',
    depth_rule: 'depth_m = WL/2(km) × 1000',
    z_rule: 'z_local_m = -depth_m',
    vx_unit: 'km/s',
    absolute_crs: 'unavailable',
  },
  golden: GOLDEN,
  validation_passed: true,
  downstream_gates: {
    geometry_blocked: false,
    cleaning_blocked: false,
    interpolation_blocked: false,
  },
  source_files: SOURCE_FILES,
  artifacts: {
    accepted_modeling: { file: 'accepted_modeling_41.csv', rows: 41, sha256: SHA },
    aggregated_nodes: { file: 'aggregated_nodes_40.csv', rows: 40, sha256: SHA },
  },
}

const MICRO_DATASET_RECORD = {
  id: 'ds-micro-1',
  case_id: 'c1',
  version: 1,
  status: 'mapped' as const,
  profile: { source_kind: 'microseismic_dat_bundle', mapping: MAPPING },
  created_at: '2026-07-25T00:00:00Z',
}

function makeQuality(status: QualityReport['status']): QualityReport {
  const issues =
    status === 'passed'
      ? []
      : status === 'blocked'
        ? [{ code: 'MISSING_NUMERIC', kind: 'blocker' as const, message: '必填字段无法解析', details: {} }]
        : [{ code: 'SPARSE_POINTS', kind: 'warning' as const, message: '点稀疏', details: {} }]
  return {
    status,
    checks: [],
    issues,
    statistics: {
      ranges: { x: [0, 10], y: [0, 10], z: [-9, 0], value: [1, 99] },
      unique_coordinate_count: 40,
      duplicate_count: 0,
      conflict_count: 0,
    },
    valid_row_count: 40,
    invalid_row_count: 0,
    row_count: 40,
    source_sha256: SHA,
    standardized_sha256: SHA,
    confirmed: status === 'passed',
    confirmed_issue_codes: [],
  }
}

function makeTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: HomeView },
      { path: '/cases/new', name: 'case-create', component: CaseCreateView },
      {
        path: '/cases/:caseId/microseismic/import',
        name: 'microseismic-import',
        component: MicroseismicImportView,
      },
      {
        path: '/cases/:caseId/experiments/new',
        name: 'experiment-create',
        component: { template: '<div />' },
      },
    ],
  })
}

async function mountImportView(startPath = '/cases/c1/microseismic/import') {
  const router = makeTestRouter()
  await router.push(startPath)
  const wrapper = mount(MicroseismicImportView, {
    global: { plugins: [router, ElementPlus] },
  })
  await flushPromises()
  return { wrapper, router }
}

function datFiles(count: number): File[] {
  return Array.from(
    { length: count },
    (_, i) => new File(['0.060000 0.500000'], `W${i + 1}.dat`, { type: 'application/octet-stream' }),
  )
}

async function selectFiles(wrapper: ReturnType<typeof mount>, testId: string, files: File[]) {
  const input = wrapper.find(`[data-test="${testId}"]`)
  Object.defineProperty(input.element, 'files', { value: files, configurable: true })
  await input.trigger('change')
}

/** 走完导入成功 → 派生确认 → 质量校验的完整流程，停在第 4 步。 */
async function reachQualityStep(quality: QualityReport) {
  vi.mocked(client.importMicroseismic).mockResolvedValue(IMPORT_RESPONSE)
  vi.mocked(client.fetchMicroseismicDerivation).mockResolvedValue(DERIVATION)
  vi.mocked(client.validateDataset).mockResolvedValue(quality)
  const { wrapper, router } = await mountImportView()
  await selectFiles(wrapper, 'micro-dat-files', datFiles(22))
  await wrapper.find('[data-test="micro-import-submit"]').trigger('click')
  await flushPromises()
  await wrapper.find('[data-test="micro-continue-derivation"]').trigger('click')
  await flushPromises()
  await wrapper.find('[data-test="micro-continue-modeling"]').trigger('click')
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(client.fetchCaseDatasets).mockResolvedValue({ datasets: [] })
  vi.mocked(client.fetchCases).mockResolvedValue({ cases: [] })
  vi.mocked(client.fetchRhoPublishStatus).mockResolvedValue({
    iserver_available: false,
  } as unknown as PublishStatus)
})

describe('MicroseismicImportView · 选择原始数据', () => {
  it('少于 22 个 DAT 时禁止提交', async () => {
    const { wrapper } = await mountImportView()
    expect(wrapper.find('[data-test="micro-dat-files"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="micro-dat-folder"]').exists()).toBe(true)

    await selectFiles(wrapper, 'micro-dat-files', datFiles(21))
    expect(wrapper.text()).toContain('21')
    let submit = wrapper.find('[data-test="micro-import-submit"]')
    expect((submit.element as HTMLButtonElement).disabled).toBe(true)

    await selectFiles(wrapper, 'micro-dat-files', datFiles(22))
    submit = wrapper.find('[data-test="micro-import-submit"]')
    expect((submit.element as HTMLButtonElement).disabled).toBe(false)
  })

  it('重复 basename 显示错误且禁止提交', async () => {
    const { wrapper } = await mountImportView()
    const files = datFiles(22)
    files[21] = new File(['x'], 'W1.dat') // 与 W1.dat 重名
    await selectFiles(wrapper, 'micro-dat-files', files)

    const dupError = wrapper.find('[data-test="micro-dup-error"]')
    expect(dupError.exists()).toBe(true)
    expect(dupError.text()).toContain('W1.dat')
    const submit = wrapper.find('[data-test="micro-import-submit"]')
    expect((submit.element as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('MicroseismicImportView · 导入与派生', () => {
  it('导入成功展示五层计数与黄金状态', async () => {
    vi.mocked(client.importMicroseismic).mockResolvedValue(IMPORT_RESPONSE)
    vi.mocked(client.fetchMicroseismicDerivation).mockResolvedValue(DERIVATION)
    const { wrapper } = await mountImportView()
    await selectFiles(wrapper, 'micro-dat-files', datFiles(22))
    await wrapper.find('[data-test="micro-import-submit"]').trigger('click')
    await flushPromises()

    expect(client.importMicroseismic).toHaveBeenCalledTimes(1)
    const [caseId, files] = vi.mocked(client.importMicroseismic).mock.calls[0]
    expect(caseId).toBe('c1')
    expect(files).toHaveLength(22)
    expect(client.fetchMicroseismicDerivation).toHaveBeenCalledWith('ds-micro-1')

    // 第 2 步：原始数据核验（来源清单）
    expect(wrapper.find('[data-test="source-manifest"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="source-manifest"]').text()).toContain('W1.dat')

    // 第 3 步：派生结果确认
    await wrapper.find('[data-test="micro-continue-derivation"]').trigger('click')
    await flushPromises()
    const layerCounts = wrapper.find('[data-test="layer-counts"]')
    expect(layerCounts.exists()).toBe(true)
    const text = layerCounts.text()
    expect(text).toContain('源记录')
    expect(text).toContain('有限记录')
    expect(text).toContain('3σ剔除')
    expect(text).toContain('黄金候选')
    expect(text).toContain('唯一建模节点')
    expect(text).toContain('45')
    expect(text).toContain('44')
    expect(text).toContain('41')
    expect(text).toContain('40')
    expect(wrapper.find('[data-test="golden-status"]').text()).toContain('通过')
    expect(wrapper.find('[data-test="golden-checks"]').text()).toContain('accepted_count')
    // 只读自动映射
    const mapping = wrapper.find('[data-test="auto-mapping"]')
    expect(mapping.text()).toContain('X_LOCAL_M')
    expect(mapping.text()).toContain('VX_KM_S')
  })

  it('导入被服务端阻断时显示失败检查，且无继续按钮', async () => {
    vi.mocked(client.importMicroseismic).mockRejectedValue(
      new client.ApiError('MICROSEISMIC_DERIVATION_FAILED', '派生合同未通过', 422, {
        failed_checks: [{ name: 'source_record_counts_per_line', evidence: 'expected 19 got 20' }],
      }),
    )
    const { wrapper } = await mountImportView()
    await selectFiles(wrapper, 'micro-dat-files', datFiles(22))
    await wrapper.find('[data-test="micro-import-submit"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="import-error"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('MICROSEISMIC_DERIVATION_FAILED')
    expect(wrapper.text()).toContain('source_record_counts_per_line')
    expect(wrapper.find('[data-test="micro-continue-derivation"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="enter-modeling"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="nav-home"]').exists()).toBe(true)
  })
})

describe('MicroseismicImportView · 质量门禁与建模入口', () => {
  it('质量校验阻断时不出现进入建模', async () => {
    const { wrapper } = await reachQualityStep(makeQuality('blocked'))
    expect(client.validateDataset).toHaveBeenCalledWith('ds-micro-1')
    expect(wrapper.text()).toContain('MISSING_NUMERIC')
    expect(wrapper.find('[data-test="enter-modeling"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('进入建模')
  })

  it('质量校验通过后路由到实验创建并携带返回的数据集 ID', async () => {
    const { wrapper, router } = await reachQualityStep(makeQuality('passed'))
    const enter = wrapper.find('[data-test="enter-modeling"]')
    expect(enter.exists()).toBe(true)
    expect((enter.element as HTMLButtonElement).disabled).toBe(false)
    await enter.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/cases/c1/experiments/new')
    expect(router.currentRoute.value.query.dataset).toBe('ds-micro-1')
  })

  it('警告须整体确认后才能进入建模', async () => {
    const warnings = makeQuality('warnings')
    const { wrapper } = await reachQualityStep(warnings)
    const enter = wrapper.find('[data-test="enter-modeling"]')
    expect(enter.exists()).toBe(true)
    expect((enter.element as HTMLButtonElement).disabled).toBe(true)

    vi.mocked(client.confirmWarnings).mockResolvedValue({
      ...warnings,
      confirmed: true,
      confirmed_issue_codes: ['SPARSE_POINTS'],
    })
    await wrapper.find('[data-test="confirm-warnings"]').trigger('click')
    await flushPromises()
    expect(client.confirmWarnings).toHaveBeenCalledWith('ds-micro-1', ['SPARSE_POINTS'])
    expect((wrapper.find('[data-test="enter-modeling"]').element as HTMLButtonElement).disabled).toBe(false)
  })
})

describe('MicroseismicImportView · 状态恢复与导航', () => {
  it('加载中状态存在 nav-home', async () => {
    vi.mocked(client.fetchCaseDatasets).mockReturnValue(new Promise<CaseDatasetsResponse>(() => {}))
    const router = makeTestRouter()
    await router.push('/cases/c1/microseismic/import')
    const wrapper = mount(MicroseismicImportView, { global: { plugins: [router, ElementPlus] } })
    expect(wrapper.find('[data-test="nav-home"]').exists()).toBe(true)
  })

  it('加载失败状态存在 nav-home', async () => {
    vi.mocked(client.fetchCaseDatasets).mockRejectedValue(new client.ApiError('CASE_NOT_FOUND', '案例不存在', 404))
    const { wrapper, router } = await mountImportView()
    expect(wrapper.text()).toContain('CASE_NOT_FOUND')
    const navHome = wrapper.find('[data-test="nav-home"]')
    expect(navHome.exists()).toBe(true)
    await navHome.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('home')
  })

  it('案例下已有微震数据集时直接恢复到派生确认步骤', async () => {
    vi.mocked(client.fetchCaseDatasets).mockResolvedValue({ datasets: [MICRO_DATASET_RECORD] })
    vi.mocked(client.fetchMicroseismicDerivation).mockResolvedValue(DERIVATION)
    const { wrapper } = await mountImportView()
    expect(client.importMicroseismic).not.toHaveBeenCalled()
    expect(client.fetchMicroseismicDerivation).toHaveBeenCalledWith('ds-micro-1')
    expect(wrapper.find('[data-test="layer-counts"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="golden-status"]').text()).toContain('通过')
  })

  it('路由带 dataset 参数时恢复对应数据集的派生确认', async () => {
    vi.mocked(client.fetchDataset).mockResolvedValue(MICRO_DATASET_RECORD)
    vi.mocked(client.fetchMicroseismicDerivation).mockResolvedValue(DERIVATION)
    const { wrapper } = await mountImportView('/cases/c1/microseismic/import?dataset=ds-micro-1')
    expect(client.fetchDataset).toHaveBeenCalledWith('ds-micro-1')
    expect(wrapper.find('[data-test="layer-counts"]').exists()).toBe(true)
  })
})

describe('CaseCreateView · microseismic preset', () => {
  it('preset=microseismic 只需要案例名称，创建后路由到导入页', async () => {
    vi.mocked(client.createCase).mockResolvedValue({
      id: 'c9',
      name: '微震案例',
      case_type: 'microseismic',
      config: {},
      created_at: '2026-07-25T00:00:00Z',
      updated_at: '2026-07-25T00:00:00Z',
    })
    const router = makeTestRouter()
    await router.push('/cases/new?preset=microseismic')
    const wrapper = mount(CaseCreateView, { global: { plugins: [router, ElementPlus] } })
    await flushPromises()

    expect(wrapper.find('[data-test="case-file"]').exists()).toBe(false)
    let submit = wrapper.find('[data-test="case-submit"]')
    expect((submit.element as HTMLButtonElement).disabled).toBe(true)

    await wrapper.find('[data-test="case-name"]').setValue('微震案例')
    submit = wrapper.find('[data-test="case-submit"]')
    expect((submit.element as HTMLButtonElement).disabled).toBe(false)
    await submit.trigger('click')
    await flushPromises()

    expect(client.createCase).toHaveBeenCalledWith('微震案例', 'microseismic')
    expect(client.uploadDataset).not.toHaveBeenCalled()
    expect(router.currentRoute.value.path).toBe('/cases/c9/microseismic/import')
  })
})
