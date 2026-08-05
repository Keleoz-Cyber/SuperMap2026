import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type {
  DatasetPoints,
  DisplayTransform,
  ExperimentRecord,
  FormalSelectionRecord,
  MicroseismicDerivation,
  MicroseismicPointLayer,
  RenderAssetRecord,
  RenderCapability,
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
    materializeResult: vi.fn(),
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
    fetchResultRenderCapability: vi.fn(),
    fetchResultRenderAsset: vi.fn(),
    createResultRenderAsset: vi.fn(),
  }
})

// ---------------------------------------------------------------------------
// SuperMapVolumeFrame stub：记录命令方法（setPointLayer 等），并渲染一个真实
// iframe 元素，让视图的协议监听器可以做 origin/source/protocol 三重校验。
// Cesium mock 已随 Field3D 一并移除：证据层断言全部落在桥接载荷上。
// ---------------------------------------------------------------------------

let frameExposed: {
  setMode: ReturnType<typeof vi.fn>
  setFilter: ReturnType<typeof vi.fn>
  setOpacity: ReturnType<typeof vi.fn>
  setPointLayer: ReturnType<typeof vi.fn>
  resetView: ReturnType<typeof vi.fn>
}

const FrameStub = defineComponent({
  name: 'SuperMapVolumeFrame',
  props: {
    asset: { type: Object, default: null },
    displayTransform: { type: Object, required: true },
  },
  emits: ['ready', 'rendered', 'failed'],
  setup(_props, { expose }) {
    frameExposed = {
      setMode: vi.fn(),
      setFilter: vi.fn(),
      setOpacity: vi.fn(),
      setPointLayer: vi.fn(),
      resetView: vi.fn(),
    }
    expose(frameExposed)
    return () =>
      h('div', { 'data-test': 'volume-frame-stub' }, [h('iframe', { 'data-test': 'frame-bridge-stub' })])
  },
})

// 模拟子帧握手：以 stub iframe 的 contentWindow 为 source 派发 FRAME_READY，
// 视图延迟一个任务后重发全部已加载证据层
async function simulateFrameHandshake(wrapper: ReturnType<typeof mount>) {
  const frame = wrapper.findComponent(FrameStub)
  frame.vm.$emit('ready', { sdkVersion: '12.1.0', contextType: 2 })
  const iframeEl = wrapper.find('[data-test="frame-bridge-stub"]')
  const source = (iframeEl.element as HTMLIFrameElement).contentWindow
  const event = new MessageEvent('message', {
    data: {
      protocol: 'gmp-supermap-volume/v1',
      type: 'FRAME_READY',
      requestId: 'req-stub',
      sdkVersion: '12.1.0',
      contextType: 2,
    },
    origin: window.location.origin,
    source,
  })
  if (event.source !== source) Object.defineProperty(event, 'source', { value: source })
  window.dispatchEvent(event)
  await new Promise((resolve) => setTimeout(resolve, 0))
  await flushPromises()
}

function pointLayerCalls(): Record<string, unknown>[] {
  return frameExposed.setPointLayer.mock.calls.map((call) => call[0] as Record<string, unknown>)
}

function lastLayerPayload(id: string): Record<string, unknown> | undefined {
  return pointLayerCalls()
    .filter((layer) => layer.id === id)
    .at(-1)
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

const CAPABILITY_3D: RenderCapability = {
  source_kind: 'candidate_result',
  source_id: 'r-micro',
  supported: true,
  reason_code: null,
  reason: null,
  dimension: '3d',
  grid_kind: 'regular',
  property_name: 'Vx',
  units: 'km/s',
  geolocation_status: 'display_anchor_only',
  display_transform: TRANSFORM,
}

const ASSET_READY: RenderAssetRecord = {
  id: `nc-${'a'.repeat(32)}`,
  source_kind: 'candidate_result',
  source_id: 'r-micro',
  renderer: 'supermap_voxelgrid_netcdf',
  status: 'ready',
  grid_sha256: 'cd'.repeat(32),
  netcdf_sha256: 'ef'.repeat(32),
  manifest_url: `/api/render-assets/nc-${'a'.repeat(32)}/manifest`,
  netcdf_url: `/api/render-assets/nc-${'a'.repeat(32)}/volume.nc`,
  error: null,
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
  vi.mocked(client.materializeResult).mockResolvedValue(META_3D)
  vi.mocked(client.fetchExperiment).mockResolvedValue(EXP_MICRO)
  vi.mocked(client.fetchResultPreview).mockResolvedValue(PREVIEW_3D)
  vi.mocked(client.fetchDatasetPoints).mockResolvedValue(DATASET_POINTS)
  vi.mocked(client.fetchFormalSelections).mockResolvedValue({ case_id: 'c1', selections: [] })
  vi.mocked(client.fetchResultRenderCapability).mockResolvedValue(CAPABILITY_3D)
  vi.mocked(client.fetchResultRenderAsset).mockResolvedValue(ASSET_READY)
  vi.mocked(client.createResultRenderAsset).mockResolvedValue(ASSET_READY)
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
      { path: '/results/:resultId/professional', name: 'professional-analysis', component: { template: '<div />' } },
    ],
  })
  await router.push('/results/r-micro')
  const wrapper = mount(ResultWorkbenchView, {
    global: { plugins: [router, ElementPlus], stubs: { SuperMapVolumeFrame: FrameStub } },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('微震证据图层', () => {
  it('通用成果不请求微震领域图层，也不显示图层控制组', async () => {
    const wrapper = await mountWorkbench('not_micro')
    // 派生元数据是唯一的 source_kind 探测手段；领域图层请求绝不发出
    expect(client.fetchMicroseismicDerivation).toHaveBeenCalledWith('ds-micro')
    expect(client.fetchMicroseismicDerivationPoints).not.toHaveBeenCalled()
    expect(wrapper.find('[data-test="evidence-layers"]').exists()).toBe(false)
    // 原生体渲染面板不受探测失败影响
    expect(wrapper.find('[data-test="native-volume-panel"]').exists()).toBe(true)
  })

  it('派生证据服务异常时静默降级，不阻塞成果工作台', async () => {
    const wrapper = await mountWorkbench('server_error')
    expect(client.fetchMicroseismicDerivationPoints).not.toHaveBeenCalled()
    expect(wrapper.find('[data-test="evidence-layers"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="native-volume-panel"]').exists()).toBe(true)
  })

  it('微震成果保留 aggregated/accepted/rejected 控件，默认只加载聚合节点层', async () => {
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
  })

  it('证据点层载荷按既有样式经桥接发送到 iframe', async () => {
    const wrapper = await mountWorkbench('micro')
    await simulateFrameHandshake(wrapper)

    // 握手后重发已加载层：聚合层默认可见，绿色样式
    expect(lastLayerPayload('aggregated')).toMatchObject({
      id: 'aggregated',
      visible: true,
      role: 'evidence',
      coordinates: 'local',
      x: AGGREGATED.x,
      y: AGGREGATED.y,
      z: AGGREGATED.z,
      style: { color: '#22c55e', pixelSize: 7 },
    })

    // 打开候选层：蓝色样式；关闭后以 visible=false 重发
    await wrapper.get('[data-test="layer-toggle-accepted"]').trigger('click')
    await flushPromises()
    expect(client.fetchMicroseismicDerivationPoints).toHaveBeenCalledWith('ds-micro', 'accepted')
    expect(lastLayerPayload('accepted')).toMatchObject({
      id: 'accepted',
      visible: true,
      role: 'evidence',
      coordinates: 'local',
      x: ACCEPTED.x,
      y: ACCEPTED.y,
      z: ACCEPTED.z,
      style: { color: '#38bdf8', pixelSize: 4 },
    })

    await wrapper.get('[data-test="layer-toggle-accepted"]').trigger('click')
    await flushPromises()
    expect(lastLayerPayload('accepted')).toMatchObject({ id: 'accepted', visible: false })

    // 再开不重复请求：图层数据驻留内存，只经桥接更新可见性
    await wrapper.get('[data-test="layer-toggle-accepted"]').trigger('click')
    await flushPromises()
    expect(client.fetchMicroseismicDerivationPoints).toHaveBeenCalledTimes(2)
    expect(lastLayerPayload('accepted')).toMatchObject({ id: 'accepted', visible: true })

    // 剔除层：既有红色填充 + 浅色描边样式逐字保留
    await wrapper.get('[data-test="layer-toggle-rejected"]').trigger('click')
    await flushPromises()
    expect(client.fetchMicroseismicDerivationPoints).toHaveBeenCalledWith('ds-micro', 'rejected')
    expect(lastLayerPayload('rejected')).toMatchObject({
      id: 'rejected',
      visible: true,
      role: 'evidence',
      coordinates: 'local',
      x: REJECTED.x,
      y: REJECTED.y,
      z: REJECTED.z,
      style: { color: '#ef4444', pixelSize: 6, outlineColor: '#f8fafc', outlineWidth: 2 },
    })
  })

  it('剔除层不改变网格值域、渲染成功态或正式选择', async () => {
    const wrapper = await mountWorkbench('micro')
    await simulateFrameHandshake(wrapper)
    // 体积已渲染
    const frame = wrapper.findComponent(FrameStub)
    frame.vm.$emit('rendered', {
      sourceKind: 'candidate_result',
      sourceId: 'r-micro',
      gridSha256: 'cd'.repeat(32),
      netcdfSha256: 'ef'.repeat(32),
    })
    await flushPromises()
    expect(wrapper.get('[data-test="volume-phase"]').text()).toContain('已渲染')
    const headerBefore = wrapper.get('.page-sub').text()

    await wrapper.get('[data-test="layer-toggle-rejected"]').trigger('click')
    await flushPromises()

    // 值域与渲染成功态保持成果本身口径：证据层绝不触碰过滤器/身份/成功态
    expect(wrapper.get('.page-sub').text()).toBe(headerBefore)
    expect(wrapper.get('.page-sub').text()).toContain('1.4 ~ 133.1')
    expect(wrapper.get('[data-test="volume-phase"]').text()).toContain('已渲染')

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

  it('原生渲染失败保持可见，点控件仍标注为辅助/证据', async () => {
    const wrapper = await mountWorkbench('micro')
    const frame = wrapper.findComponent(FrameStub)
    frame.vm.$emit('ready', { sdkVersion: '12.1.0', contextType: 2 })
    frame.vm.$emit('failed', { code: 'VOXEL_LAYER_LOAD_FAILED', message: '600 帧内 _frameState 未就绪' })
    await flushPromises()

    // 失败显式可见，绝不切换到任何替代渲染
    expect(wrapper.get('[data-test="frame-error"]').text()).toContain('VOXEL_LAYER_LOAD_FAILED')
    expect(wrapper.get('[data-test="volume-phase"]').text()).toContain('原生渲染失败')
    expect(wrapper.text()).not.toMatch(/fallback|回退|降级为点|替代渲染/)

    // 点控件仍明确标注为证据/辅助：不伪装成体渲染
    expect(wrapper.get('[data-test="evidence-layers"]').text()).toContain('微震证据图层')
    expect(wrapper.get('[data-test="layer-toggle-aggregated"]').text()).toContain('1,911 个唯一建模节点')
    expect(wrapper.get('[data-test="layer-toggle-rejected"]').text()).toContain('80 条3σ剔除诊断')
    expect(wrapper.get('[data-test="truth-labels"]').text()).toContain('辅助采样点：不参与连续体渲染')
  })
})
