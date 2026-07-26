import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type {
  DatasetPoints,
  ExperimentRecord,
  FormalSelectionRecord,
  MicroseismicDerivation,
  MicroseismicPointLayer,
  ResultMetadata,
  ResultPreview,
} from '../../../api/types'
import * as client from '../../../api/client'
import ResultWorkbenchView from '../../../views/ResultWorkbenchView.vue'

vi.mock('../../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/client')>()
  return {
    ...actual,
    fetchResult: vi.fn(),
    fetchResultPreview: vi.fn(),
    fetchResultSlice: vi.fn(),
    fetchExperiment: vi.fn(),
    fetchFormalSelections: vi.fn(),
    selectFormal: vi.fn(),
    createExport: vi.fn(),
    createPublication: vi.fn(),
    fetchDatasetPoints: vi.fn(),
    fetchMicroseismicDerivation: vi.fn(),
    fetchMicroseismicDerivationPoints: vi.fn(),
  }
})

// ---------------------------------------------------------------------------
// 最小 Cesium mock：只覆盖 Field3D 实际使用的 API 面。
// PointPrimitiveCollection 记录 add/removeAll，用于断言渲染集合计数；
// 图层可见性必须走 removeAll + 内存重建（v0.3.1 实证结论），断言即基于此。
// ---------------------------------------------------------------------------

interface AddedPoint {
  position: unknown
  pixelSize: number
  outlineWidth?: number
  outlineColor?: unknown
  [key: string]: unknown
}

class MockPointPrimitiveCollection {
  length = 0
  items: AddedPoint[] = []

  add(options: AddedPoint): AddedPoint {
    this.items.push(options)
    this.length += 1
    return options
  }

  removeAll(): void {
    this.items = []
    this.length = 0
  }
}

const createdCollections: MockPointPrimitiveCollection[] = []

class MockViewer {
  imageryLayers = { removeAll: vi.fn() }

  scene = {
    mode: 0,
    skyBox: { show: true },
    skyAtmosphere: { show: true },
    sun: { show: true },
    moon: { show: true },
    backgroundColor: null as unknown,
    globe: { baseColor: null as unknown },
    camera: { setView: vi.fn() },
    primitives: {
      add: (collection: MockPointPrimitiveCollection) => {
        createdCollections.push(collection)
        return collection
      },
    },
  }

  isDestroyed(): boolean {
    return false
  }

  destroy(): void {
    // no-op
  }
}

class MockCartographic {
  constructor(
    public longitude: number,
    public latitude: number,
    public height: number,
  ) {}
}

class MockCartesian3 {
  constructor(
    public x: number,
    public y: number,
    public z: number,
  ) {}
}

const CesiumMock = {
  Viewer: MockViewer,
  SceneMode: { COLUMBUS_VIEW: 1 },
  PointPrimitiveCollection: MockPointPrimitiveCollection,
  Color: {
    fromCssColorString: (css: string) => ({ css }),
    fromHsl: (h: number, s: number, l: number, a: number) => ({ h, s, l, a }),
    BLACK: { css: '#000000' },
  },
  Ellipsoid: {
    WGS84: {
      cartographicToCartesian: (c: MockCartographic) => ({
        lon: c.longitude,
        lat: c.latitude,
        h: c.height,
      }),
    },
  },
  Cartographic: MockCartographic,
  Cartesian3: MockCartesian3,
  Math: { toRadians: (deg: number) => (deg * 3.141592653589793) / 180 },
}

function totalRendered(): number {
  return createdCollections.reduce((sum, c) => sum + c.length, 0)
}

function addedItems(): AddedPoint[] {
  return createdCollections.flatMap((c) => c.items)
}

// ---------------------------------------------------------------------------
// 夹具：微震计数使用真实值 1,911 / 1,925 / 80（通用夹具点集缩小，total 保持真实）
// ---------------------------------------------------------------------------

const T = '2026-07-25T00:00:00Z'

const META_3D: ResultMetadata = {
  result_id: 'r-micro',
  run_id: 'run1',
  experiment_id: 'exp1',
  dataset_version_id: 'ds-micro',
  algorithm: 'idw',
  parameters: { power: 2, neighbor_count: 8, z_scale: 1 },
  dimension: '3d',
  shape: [11, 11, 11],
  cell_count: 1331,
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
  fingerprint: 'fp-micro',
  validation: { folds: 3 },
  created_at: T,
}

const EXP_MICRO: ExperimentRecord = {
  id: 'exp1',
  case_id: 'c1',
  name: '微震实验',
  params: {
    case_id: 'c1',
    name: '微震实验',
    algorithm: 'idw',
    dataset_version_id: 'ds-micro',
    search_mode: 'manual',
    parameters: { power: 2 },
    validation: { method: 'spatial_kfold', folds: 3, seed: 1, holdout_fraction: 0.2 },
    grid: null,
  },
  created_at: T,
  updated_at: T,
}

const PREVIEW_3D: ResultPreview = {
  result_id: 'r-micro',
  dimension: '3d',
  original_cell_count: 1331,
  served_cell_count: 1331,
  stride: 1,
  x: [-150, -141],
  y: [260, 292],
  z: [-800, -740],
  values: [10, 20],
  is_nodata: [false, false],
  value_range: [10, 20],
}

const DATASET_POINTS: DatasetPoints = {
  dataset_id: 'ds-micro',
  dimension: '3d',
  count: 3,
  served: 3,
  decimate: 1,
  x: [-150, -141, -132],
  y: [260, 292, 324],
  z: [-800, -740, -680],
  values: [10, 50, 60],
  value_range: [10, 60],
  value_name: 'Vx',
  source_sha256: 'ab'.repeat(32),
}

const DERIVATION: MicroseismicDerivation = {
  dataset_id: 'ds-micro',
  case_id: 'c1',
  status: 'validated',
  source_kind: 'microseismic_dat_bundle',
  rule_version: 'v0.5',
  adapter_version: 'microseismic_dat_v05',
  aggregation_method: 'exact_xyz',
  layer_counts: {
    source_records: 2006,
    finite_records: 2005,
    invalid_records: 1,
    rejected_3sigma: 80,
    accepted_modeling: 1925,
    aggregated_nodes: 1911,
  },
  line_counts: { L1: 1000, L2: 1006 },
  three_sigma: {
    threshold: 3,
    ddof: 1,
    depth_mean: -520,
    depth_std: 120,
    vx_mean: 5.5,
    vx_std: 0.4,
  },
  aggregation: {
    conflict_group_count: 13,
    conflict_row_count: 27,
    collapsed_row_count: 14,
    max_value_range: 0.05,
  },
  coordinates: {
    coord_type: 'local_linear',
    depth_rule: 'depth_positive_down',
    z_rule: 'z_negative_elevation',
    vx_unit: 'km/s',
    absolute_crs: 'none',
  },
  golden: { passed: true, checks: [] },
  validation_passed: true,
  downstream_gates: {
    geometry_blocked: false,
    cleaning_blocked: false,
    interpolation_blocked: false,
  },
  source_files: [],
  artifacts: {},
}

const AGGREGATED: MicroseismicPointLayer = {
  dataset_id: 'ds-micro',
  layer: 'aggregated',
  total: 1911,
  returned: 2,
  decimate: 1,
  x: [-100, -90],
  y: [300, 320],
  z: [-500, -520],
  vx: [5.5, 5.6],
  sample_count: [2, 1],
  source_sample_ids: [['L1P1', 'L1P2'], ['L2P1']],
  vx_min: [5.4, 5.6],
  vx_max: [5.6, 5.6],
  vx_std: [0.1, null],
}

const ACCEPTED: MicroseismicPointLayer = {
  dataset_id: 'ds-micro',
  layer: 'accepted',
  total: 1925,
  returned: 3,
  decimate: 1,
  x: [-100, -95, -90],
  y: [300, 310, 320],
  z: [-500, -510, -520],
  vx: [5.5, 5.55, 5.6],
  sample_id: ['L1P1', 'L1P2', 'L2P1'],
}

const REJECTED: MicroseismicPointLayer = {
  dataset_id: 'ds-micro',
  layer: 'rejected',
  total: 80,
  returned: 1,
  decimate: 1,
  x: [-80],
  y: [330],
  z: [-530],
  vx: [9.9],
  sample_id: ['L9P9'],
  filter_reason: ['depth_3sigma'],
  depth_zscore: [3.2],
  vx_zscore: [1.1],
}

const SELECTION: FormalSelectionRecord = {
  id: 'sel1',
  case_id: 'c1',
  candidate_result_id: 'r-micro',
  selected_by: 'tester',
  note: '公共验证 RMSE 最低',
  created_at: T,
}

type DerivationBehavior = 'micro' | 'not_micro' | 'server_error'

async function mountWorkbench(behavior: DerivationBehavior) {
  vi.mocked(client.fetchResult).mockResolvedValue(META_3D)
  vi.mocked(client.fetchExperiment).mockResolvedValue(EXP_MICRO)
  vi.mocked(client.fetchResultPreview).mockResolvedValue(PREVIEW_3D)
  vi.mocked(client.fetchDatasetPoints).mockResolvedValue(DATASET_POINTS)
  vi.mocked(client.fetchFormalSelections).mockResolvedValue({ case_id: 'c1', selections: [] })
  if (behavior === 'micro') {
    vi.mocked(client.fetchMicroseismicDerivation).mockResolvedValue(DERIVATION)
  } else if (behavior === 'not_micro') {
    vi.mocked(client.fetchMicroseismicDerivation).mockRejectedValue(
      new client.ApiError('DATASET_NOT_MICROSEISMIC', '数据集不是微震 DAT 导入，没有派生证据', 409),
    )
  } else {
    vi.mocked(client.fetchMicroseismicDerivation).mockRejectedValue(
      new client.ApiError('HTTP_500', '服务异常', 500),
    )
  }
  vi.mocked(client.fetchMicroseismicDerivationPoints).mockImplementation(
    (_datasetId: string, layer: string) => {
      if (layer === 'aggregated') return Promise.resolve(AGGREGATED)
      if (layer === 'accepted') return Promise.resolve(ACCEPTED)
      return Promise.resolve(REJECTED)
    },
  )
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/experiments/:experimentId', name: 'experiment-detail', component: { template: '<div />' } },
      { path: '/results/:resultId', name: 'result-workbench', component: ResultWorkbenchView },
    ],
  })
  await router.push('/results/r-micro')
  const wrapper = mount(ResultWorkbenchView, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  createdCollections.length = 0
  ;(window as unknown as { Cesium: unknown }).Cesium = CesiumMock
})

describe('微震证据图层', () => {
  it('通用成果不请求微震领域图层，也不显示图层控制组', async () => {
    const wrapper = await mountWorkbench('not_micro')
    // 派生元数据是唯一的 source_kind 探测手段；领域图层请求绝不发出
    expect(client.fetchMicroseismicDerivation).toHaveBeenCalledWith('ds-micro')
    expect(client.fetchMicroseismicDerivationPoints).not.toHaveBeenCalled()
    expect(wrapper.find('[data-test="evidence-layers"]').exists()).toBe(false)
    // 主点云不受探测失败影响
    expect(wrapper.find('[data-test="field-3d"]').exists()).toBe(true)
    expect(totalRendered()).toBe(2)
  })

  it('派生证据服务异常时静默降级，不阻塞成果工作台', async () => {
    const wrapper = await mountWorkbench('server_error')
    expect(client.fetchMicroseismicDerivationPoints).not.toHaveBeenCalled()
    expect(wrapper.find('[data-test="evidence-layers"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="preview-count"]').text()).toContain('1331 / 1331')
    expect(totalRendered()).toBe(2)
  })

  it('微震成果默认只加载聚合节点层，候选与剔除层默认关', async () => {
    const wrapper = await mountWorkbench('micro')
    expect(client.fetchMicroseismicDerivation).toHaveBeenCalledWith('ds-micro')
    expect(client.fetchMicroseismicDerivationPoints).toHaveBeenCalledTimes(1)
    expect(client.fetchMicroseismicDerivationPoints).toHaveBeenCalledWith('ds-micro', 'aggregated')

    const controls = wrapper.get('[data-test="evidence-layers"]')
    const aggregated = controls.get('[data-test="layer-toggle-aggregated"]')
    const accepted = controls.get('[data-test="layer-toggle-accepted"]')
    const rejected = controls.get('[data-test="layer-toggle-rejected"]')
    expect(aggregated.text()).toContain('[on]')
    expect(aggregated.text()).toContain('1,911 个唯一建模节点')
    expect(accepted.text()).toContain('[off]')
    expect(accepted.text()).toContain('1,925 条3σ候选来源')
    expect(rejected.text()).toContain('[off]')
    expect(rejected.text()).toContain('80 条3σ剔除诊断')

    // 渲染集合 = 主点云 2 有效单元 + 聚合层 2 点
    expect(totalRendered()).toBe(4)
  })

  it('开关图层改变渲染集合计数，剔除层用描边符号区分', async () => {
    const wrapper = await mountWorkbench('micro')
    expect(totalRendered()).toBe(4)

    await wrapper.get('[data-test="layer-toggle-accepted"]').trigger('click')
    await flushPromises()
    expect(client.fetchMicroseismicDerivationPoints).toHaveBeenCalledWith('ds-micro', 'accepted')
    expect(totalRendered()).toBe(7)

    await wrapper.get('[data-test="layer-toggle-accepted"]').trigger('click')
    await flushPromises()
    expect(totalRendered()).toBe(4)

    // 再开不重复请求：图层数据驻留内存，可见性只靠 removeAll + 重建
    await wrapper.get('[data-test="layer-toggle-accepted"]').trigger('click')
    await flushPromises()
    expect(client.fetchMicroseismicDerivationPoints).toHaveBeenCalledTimes(2)
    expect(totalRendered()).toBe(7)

    await wrapper.get('[data-test="layer-toggle-rejected"]').trigger('click')
    await flushPromises()
    expect(client.fetchMicroseismicDerivationPoints).toHaveBeenCalledWith('ds-micro', 'rejected')
    expect(totalRendered()).toBe(8)

    const outlined = addedItems().filter((item) => (item.outlineWidth ?? 0) > 0)
    expect(outlined.length).toBeGreaterThan(0)
  })

  it('剔除层不改变网格值域、预览计数、指标或正式选择', async () => {
    const wrapper = await mountWorkbench('micro')
    const headerBefore = wrapper.get('.page-sub').text()
    const previewBefore = wrapper.get('[data-test="preview-count"]').text()

    await wrapper.get('[data-test="layer-toggle-rejected"]').trigger('click')
    await flushPromises()
    expect(totalRendered()).toBe(5)

    // 值域与完整场计数保持成果本身口径
    expect(wrapper.get('.page-sub').text()).toBe(headerBefore)
    expect(wrapper.get('.page-sub').text()).toContain('1.4 ~ 133.1')
    expect(wrapper.get('[data-test="preview-count"]').text()).toBe(previewBefore)

    // 正式选择流程不受剔除点影响
    vi.mocked(client.selectFormal).mockResolvedValue(SELECTION)
    vi.mocked(client.fetchFormalSelections).mockResolvedValue({ case_id: 'c1', selections: [SELECTION] })
    await wrapper.find('[data-test="selection-note"]').setValue('公共验证 RMSE 最低')
    await wrapper.find('[data-test="selection-submit"]').trigger('click')
    await flushPromises()
    expect(client.selectFormal).toHaveBeenCalledWith('r-micro', '公共验证 RMSE 最低', undefined)
    expect(wrapper.text()).toContain('公共验证 RMSE 最低')

    // 剔除层开启后值域仍然不变
    expect(wrapper.get('.page-sub').text()).toContain('1.4 ~ 133.1')
  })
})
