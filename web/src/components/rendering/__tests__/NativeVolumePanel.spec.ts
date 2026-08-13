import { flushPromises, mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { defineComponent, h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import { ApiError } from '../../../api/client'
import {
  createRenderAssetSliceExport,
  createResultRenderAsset,
  fetchRenderAssetSliceAnalysis,
  fetchResultRenderAsset,
  fetchResultRenderCapability,
  materializeResult,
} from '../../../api/client'
import type {
  DisplayTransform,
  RenderAssetRecord,
  RenderCapability,
  RenderProfile,
  SliceAnalysisResponse,
  SliceAxis,
} from '../../../api/types'
import NativeVolumePanel from '../NativeVolumePanel.vue'
import VolumeRenderToolbar from '../VolumeRenderToolbar.vue'
import OrthogonalSliceControls from '../OrthogonalSliceControls.vue'
import SliceAnalysisPanel from '../SliceAnalysisPanel.vue'
import { PALETTES } from '../renderTransferFunctions'
import type { RenderStateV2 } from '../renderProtocol'
import { RESULT_ANALYSIS_MOCK_3D } from '../../../mocks/resultAnalysisMock'

// v0.7.0 第二批 Task 11：统一 NativeVolumePanel 集成。
// 面板 = 能力/资产生命周期 + 常驻工具栏（完整 v2 状态）+ 正交切片控件 +
// 剖面分析面板（目标驱动）。3D slice 状态只来自权威剖面响应；slice 模式
// 缺少 slice 载荷时绝不推送（app.js 硬要求）。

const TRANSFORM: DisplayTransform = {
  contract: 'wgs84_display_anchor_v1',
  origin_x: 0,
  origin_y: 0,
  anchor_longitude: 120,
  anchor_latitude: 30,
  anchor_height: 0,
  metres_per_degree_lon: 96486.3,
  metres_per_degree_lat: 110852.4,
}

const ASSET: RenderAssetRecord = {
  id: `nc-${'a'.repeat(32)}`,
  source_kind: 'candidate_result',
  source_id: 'r1',
  renderer: 'supermap_voxelgrid_netcdf',
  status: 'ready',
  grid_sha256: 'g'.repeat(64),
  netcdf_sha256: 'n'.repeat(64),
  manifest_url: `/api/render-assets/nc-${'a'.repeat(32)}/manifest`,
  netcdf_url: `/api/render-assets/nc-${'a'.repeat(32)}/volume.nc`,
  error: null,
}

const ASSET_B: RenderAssetRecord = {
  ...ASSET,
  id: `nc-${'b'.repeat(32)}`,
  manifest_url: `/api/render-assets/nc-${'b'.repeat(32)}/manifest`,
  netcdf_url: `/api/render-assets/nc-${'b'.repeat(32)}/volume.nc`,
}

const FAILED_ASSET: RenderAssetRecord = {
  ...ASSET,
  status: 'failed',
  netcdf_sha256: null,
  manifest_url: null,
  netcdf_url: null,
  error: { code: 'NETCDF_EXPORT_FAILED', message: 'NetCDF 写盘失败', details: {} },
}

// 候选成果默认：linear + viridis（Task 2 合同）
const CANDIDATE_PROFILE: RenderProfile = {
  property_name: 'Vx',
  unit: 'km/s',
  default_scale: 'linear',
  default_palette: 'viridis',
  log_available: true,
  value_range: [4.2, 5.8],
  filter_range: [4.2, 5.8],
  lighting: false,
  gradient_opacity: false,
  bounding_box: true,
  opacity: 1,
}

// 内置电阻率默认：log + native-spectrum（Task 2 合同）
const LEGACY_PROFILE: RenderProfile = {
  property_name: 'RHO',
  unit: 'unknown',
  default_scale: 'log',
  default_palette: 'native-spectrum',
  log_available: true,
  value_range: [1.4, 133.1],
  filter_range: [1.4, 133.1],
  lighting: false,
  gradient_opacity: false,
  bounding_box: true,
  opacity: 1,
}

function supportedCapability(profile: RenderProfile | null = CANDIDATE_PROFILE): RenderCapability {
  return {
    source_kind: 'candidate_result',
    source_id: 'r1',
    supported: true,
    reason_code: null,
    reason: null,
    dimension: '3d',
    grid_kind: 'regular',
    property_name: 'Vx',
    units: 'km/s',
    geolocation_status: 'display_anchor_only',
    display_transform: TRANSFORM,
    render_profile: profile,
  }
}

function unsupportedCapability(): RenderCapability {
  return {
    source_kind: 'candidate_result',
    source_id: 'r1',
    supported: false,
    reason_code: 'RENDER_REQUIRES_3D',
    reason: 'NetCDF 体渲染需要三维规则网格成果',
    dimension: '2d',
    grid_kind: null,
    property_name: 'rho',
    units: 'unknown',
    geolocation_status: 'display_anchor_only',
    display_transform: TRANSFORM,
    render_profile: null,
  }
}

const AUX_POINTS = {
  id: 'grid-samples' as const,
  role: 'auxiliary' as const,
  x: [0, 10, 20],
  y: [0, 10, 20],
  z: [0, -5, -10],
  values: [1.1, 2.2, 3.3],
  style: { color: '#22d3ee', pixelSize: 4 },
}

// 剖面分析夹具：x:2 / y:3 / z:4（z 默认中位索引 = floor((4-1)/2) = 1）
function makeSliceAnalysis(axis: SliceAxis, index: number): SliceAnalysisResponse {
  const axes = {
    x: { length: 2, coordinates: [0, 100], unit: 'm' },
    y: { length: 3, coordinates: [0, 10, 20], unit: 'm' },
    z: { length: 4, coordinates: [0, -800, -1600, -2400], unit: 'm' },
  }
  return {
    asset_identity: {
      asset_id: ASSET.id,
      source_kind: 'candidate_result',
      source_id: 'r1',
      grid_sha256: 'g'.repeat(64),
      netcdf_sha256: 'n'.repeat(64),
    },
    property: { name: 'Vx', unit: 'km/s' },
    axes,
    slice: {
      fixed_axis: axis,
      index,
      coordinate: axes[axis].coordinates[index],
      sdk_relative_position: index / (axes[axis].length - 1),
      row_axis: axis === 'z' ? 'y' : 'z',
      column_axis: 'x',
      row_coordinates: [0, 10, 20],
      column_coordinates: [0, 100],
      values: [
        [1, 101],
        [11, null],
        [21, 121],
      ],
      nodata_mask: [
        [false, false],
        [false, true],
        [false, false],
      ],
    },
    statistics: {
      total_count: 6,
      valid_count: 5,
      nodata_count: 1,
      min: 1,
      max: 121,
      mean: 51.2,
      std_population: 49.5,
      p10: 5,
      p50: 21,
      p90: 105,
      low_count: null,
      normal_count: null,
      high_count: null,
      low_ratio: null,
      normal_ratio: null,
      high_ratio: null,
      thresholds: null,
    },
    render_profile: null,
  }
}

// frame stub：记录 props，暴露与真实组件同名的命令方法
let frameExposed: {
  applyRenderState: ReturnType<typeof vi.fn>
  setPointLayer: ReturnType<typeof vi.fn>
  resetView: ReturnType<typeof vi.fn>
  setCameraPreset: ReturnType<typeof vi.fn>
  focusAnnotation: ReturnType<typeof vi.fn>
}

const FrameStub = defineComponent({
  name: 'SuperMapVolumeFrame',
  props: {
    asset: { type: Object, default: null },
    displayTransform: { type: Object, required: true },
    initialState: { type: Object, required: true },
  },
  emits: ['ready', 'rendered', 'failed', 'annotation-selected'],
  setup(_props, { expose }) {
    const instanceToken = crypto.randomUUID()
    frameExposed = {
      applyRenderState: vi.fn().mockReturnValue(true),
      setPointLayer: vi.fn(),
      resetView: vi.fn(),
      setCameraPreset: vi.fn(),
      focusAnnotation: vi.fn(),
    }
    expose(frameExposed)
    return () => h('div', { 'data-test': 'volume-frame-stub', 'data-instance-token': instanceToken })
  },
})

const HeatmapStub = {
  name: 'SliceHeatmap',
  template: '<div data-test="slice-heatmap-stub" />',
  methods: {
    capturePng: () => Promise.resolve(new Blob(['png'], { type: 'image/png' })),
  },
}

interface FakeApi {
  fetchCapability: ReturnType<typeof vi.fn>
  fetchAsset: ReturnType<typeof vi.fn>
  createAsset: ReturnType<typeof vi.fn>
  fetchSliceAnalysis: ReturnType<typeof vi.fn>
  createSliceExport: ReturnType<typeof vi.fn>
}

function makeApi(overrides: Partial<FakeApi> = {}): FakeApi {
  return {
    fetchCapability: vi.fn().mockResolvedValue(supportedCapability()),
    fetchAsset: vi
      .fn()
      .mockRejectedValue(new ApiError('RENDER_ASSET_NOT_FOUND', '该渲染源尚未创建渲染资产', 404)),
    createAsset: vi.fn().mockResolvedValue(ASSET),
    fetchSliceAnalysis: vi
      .fn()
      .mockImplementation((_id: string, axis: SliceAxis, index: number) =>
        Promise.resolve(makeSliceAnalysis(axis, index)),
      ),
    createSliceExport: vi.fn().mockResolvedValue({ id: 'exp-1' }),
    ...overrides,
  }
}

function mountPanel(
  api: FakeApi,
  auxPoints: typeof AUX_POINTS | null = null,
  extraProps: Record<string, unknown> = {},
) {
  return mount(NativeVolumePanel, {
    props: { api, auxPoints, ...extraProps },
    global: {
      plugins: [ElementPlus],
      stubs: { SuperMapVolumeFrame: FrameStub, SliceHeatmap: HeatmapStub },
    },
    attachTo: document.body,
  })
}

async function emitRendered(wrapper: ReturnType<typeof mount>) {
  const frame = wrapper.findComponent(FrameStub)
  frame.vm.$emit('ready', { sdkVersion: '12.1.0', contextType: 2 })
  frame.vm.$emit('rendered', {
    sourceKind: 'candidate_result',
    sourceId: 'r1',
    gridSha256: 'g'.repeat(64),
    netcdfSha256: 'n'.repeat(64),
  })
  await flushPromises()
}

function lastAppliedState(): RenderStateV2 {
  const calls = frameExposed.applyRenderState.mock.calls
  expect(calls.length).toBeGreaterThan(0)
  return calls.at(-1)![0] as RenderStateV2
}

beforeEach(() => {
  document.body.innerHTML = ''
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('NativeVolumePanel 能力与资产', () => {
  it('工具栏只允许纵向滚动，不产生底部横向滚动条', () => {
    const source = String(readFileSync('src/components/rendering/NativeVolumePanel.vue'))
    expect(source).toMatch(/\.tools-rail\s*\{[^}]*overflow-x:\s*hidden;/s)
  })

  it('presentation variant keeps a full-height scene geometry contract', async () => {
    const source = await import('../NativeVolumePanel.vue?raw')
    expect(source.default).toContain('.native-volume-panel.presentation .panel-body')
    expect(source.default).toContain('.native-volume-panel.presentation .scene-column')
    expect(source.default).toContain('.native-volume-panel.presentation :deep(.volume-frame)')
  })
  it('展示舞台只显示用户可理解的渲染状态，技术身份不占据主阅读层', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api, null, { variant: 'presentation' })
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('三维体渲染')
    expect(text).not.toContain('VoxelGridLayer3D')
    expect(text).not.toContain('display_anchor_only')
    expect(text).not.toContain('坐标契约')
    wrapper.unmount()
  })

  it('支持但未生成资产：显示生成按钮与三句真值标签，工具栏禁用', async () => {
    const api = makeApi()
    const wrapper = mountPanel(api)
    await flushPromises()

    expect(api.fetchCapability).toHaveBeenCalledTimes(1)
    const createBtn = wrapper.find('[data-test="create-asset"]')
    expect(createBtn.exists()).toBe(true)
    expect(createBtn.text()).toContain('准备体渲染数据')
    expect(createBtn.text()).not.toContain('NetCDF')

    const text = wrapper.text()
    expect(text).toContain('渲染器：SuperMap3D VoxelGridLayer3D')
    expect(text).toContain('坐标状态：显示锚点（非真实地理配准）')
    expect(text).toContain('辅助采样点：不参与连续体渲染')
    expect(text).toContain('display_anchor_only')

    expect(wrapper.findComponent(VolumeRenderToolbar).props('enabled')).toBe(false)
  })

  it('生成资产：点击按钮调用 createAsset(false)，资产身份与完整 v2 初始状态可见', async () => {
    const api = makeApi()
    const wrapper = mountPanel(api)
    await flushPromises()

    await wrapper.find('[data-test="create-asset"]').trigger('click')
    await flushPromises()

    expect(api.createAsset).toHaveBeenCalledWith(false)
    const identity = wrapper.find('[data-test="asset-identity"]')
    expect(identity.exists()).toBe(true)
    expect(identity.text()).toContain(ASSET.id)
    expect(identity.text()).toContain('supermap_voxelgrid_netcdf')
    expect(identity.text()).toContain('display_anchor_only')

    const frame = wrapper.findComponent(FrameStub)
    expect(frame.exists()).toBe(true)
    expect(frame.props('asset')).toEqual(ASSET)
    expect(frame.props('displayTransform')).toEqual(TRANSFORM)
    const initial = frame.props('initialState') as RenderStateV2
    expect(initial.revision).toBe(1)
    expect(initial.mode).toBe('volume')
    expect(initial.filter).toEqual({ min: 4.2, max: 5.8 })
    expect(initial.colorTransferFunction).toHaveLength(5)
    expect(initial.colorTransferFunction[0].color).toBe(PALETTES.viridis[0])
    expect(initial.lighting).toBe(false)
    expect(initial.gradientOpacity).toBe(false)
    expect(initial.boundingBox).toBe(true)
  })

  it('已有 ready 资产：状态刷新用 GET 恢复，直接挂载 frame', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await flushPromises()

    expect(api.fetchAsset).toHaveBeenCalledTimes(1)
    expect(api.createAsset).not.toHaveBeenCalled()
    expect(wrapper.find('[data-test="create-asset"]').exists()).toBe(false)
    expect(wrapper.findComponent(FrameStub).props('asset')).toEqual(ASSET)
  })

  it('展示面可隐藏 ready 调试动作与资产身份，但保留真实体渲染', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mount(NativeVolumePanel, {
      props: { api, showReadyDiagnostics: false },
      global: {
        plugins: [ElementPlus],
        stubs: { SuperMapVolumeFrame: FrameStub, SliceHeatmap: HeatmapStub },
      },
    })
    await flushPromises()

    expect(wrapper.find('[data-test="refresh-asset"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="asset-identity"]').exists()).toBe(false)
    expect(wrapper.findComponent(FrameStub).props('asset')).toEqual(ASSET)
  })

  it('failed 资产：显示持久化错误与重试动作，重试调用 createAsset(true)', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(FAILED_ASSET) })
    const wrapper = mountPanel(api)
    await flushPromises()

    const errorBox = wrapper.find('[data-test="asset-error"]')
    expect(errorBox.exists()).toBe(true)
    expect(errorBox.text()).toContain('NETCDF_EXPORT_FAILED')
    expect(wrapper.findComponent(FrameStub).exists()).toBe(false)

    api.createAsset.mockResolvedValue(ASSET)
    await wrapper.find('[data-test="retry-asset"]').trigger('click')
    await flushPromises()
    expect(api.createAsset).toHaveBeenCalledWith(true)
    expect(wrapper.findComponent(FrameStub).props('asset')).toEqual(ASSET)
  })

  it('unsupported capability：显示原因、INIT asset=null、绝不启用工具栏', async () => {
    const api = makeApi({ fetchCapability: vi.fn().mockResolvedValue(unsupportedCapability()) })
    const wrapper = mountPanel(api)
    await flushPromises()

    const reason = wrapper.find('[data-test="unsupported-reason"]')
    expect(reason.exists()).toBe(true)
    expect(reason.text()).toContain('RENDER_REQUIRES_3D')
    expect(reason.text()).toContain('NetCDF 体渲染需要三维规则网格')
    expect(wrapper.find('[data-test="create-asset"]').exists()).toBe(false)

    const frame = wrapper.findComponent(FrameStub)
    expect(frame.exists()).toBe(true)
    expect(frame.props('asset')).toBeNull()

    // 即使 frame 误报 rendered，面板也绝不启用工具栏
    frame.vm.$emit('ready', { sdkVersion: '12.1.0', contextType: 2 })
    frame.vm.$emit('rendered', null)
    await flushPromises()
    expect(wrapper.findComponent(VolumeRenderToolbar).props('enabled')).toBe(false)
  })

  it('原生失败：显示错误且无任何 fallback 文案，工具栏保持禁用', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await flushPromises()

    const frame = wrapper.findComponent(FrameStub)
    frame.vm.$emit('ready', { sdkVersion: '12.1.0', contextType: 2 })
    frame.vm.$emit('failed', { code: 'VOXEL_LAYER_LOAD_FAILED', message: '600 帧内 _frameState 未就绪' })
    await flushPromises()

    const errorBox = wrapper.find('[data-test="frame-error"]')
    expect(errorBox.exists()).toBe(true)
    expect(errorBox.text()).toContain('VOXEL_LAYER_LOAD_FAILED')
    expect(wrapper.text()).not.toMatch(/fallback|回退|降级|替代渲染|切换.*点/)
    expect(wrapper.findComponent(VolumeRenderToolbar).props('enabled')).toBe(false)
  })

  it('SDK 启动失败显示可理解的恢复说明，并可原位重启渲染帧', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await flushPromises()
    const firstFrame = wrapper.findComponent(FrameStub)
    const firstInstanceToken = firstFrame.get('[data-test="volume-frame-stub"]').attributes('data-instance-token')
    firstFrame.vm.$emit('failed', {
      code: 'FRAME_BOOT_SDK_MISSING',
      message: 'SuperMap3D global missing',
    })
    await flushPromises()

    const recovery = wrapper.get('[data-test="frame-recovery"]')
    expect(recovery.text()).toContain('三维引擎没有正确加载')
    expect(recovery.text()).toContain('重新加载三维场景')
    expect(recovery.text()).not.toContain('FRAME_BOOT_SDK_MISSING')
    await recovery.get('[data-test="reload-frame"]').trigger('click')
    await flushPromises()
    expect(wrapper.findComponent(FrameStub).get('[data-test="volume-frame-stub"]').attributes('data-instance-token')).not.toBe(firstInstanceToken)
  })

  it('刷新状态显示进行中与完成反馈', async () => {
    let resolveFetch!: (asset: RenderAssetRecord) => void
    const api = makeApi({
      fetchAsset: vi.fn()
        .mockResolvedValueOnce(ASSET)
        .mockImplementationOnce(() => new Promise<RenderAssetRecord>((resolve) => {
          resolveFetch = resolve
        })),
    })
    const wrapper = mountPanel(api, null, { showReadyDiagnostics: true, variant: 'workbench' })
    await flushPromises()
    expect(wrapper.get('[data-test="volume-status-bar"]').find('[data-test="refresh-asset"]').exists()).toBe(true)
    expect(wrapper.get('.scene-column').find(':scope > .asset-actions').exists()).toBe(false)
    await wrapper.get('[data-test="refresh-asset"]').trigger('click')
    expect(wrapper.get('[data-test="refresh-asset"]').text()).toContain('正在刷新')
    resolveFetch(ASSET)
    await flushPromises()
    expect(wrapper.get('[data-test="refresh-feedback"]').text()).toContain('状态已更新')
  })
})

describe('NativeVolumePanel profile 驱动初始状态', () => {
  it('候选成果 profile：linear + viridis，端点精确钉在值域上', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await flushPromises()

    const initial = wrapper.findComponent(FrameStub).props('initialState') as RenderStateV2
    expect(initial.filter).toEqual({ min: 4.2, max: 5.8 })
    expect(initial.colorTransferFunction[0]).toEqual({ value: 4.2, color: PALETTES.viridis[0] })
    expect(initial.colorTransferFunction[4]).toEqual({ value: 5.8, color: PALETTES.viridis[4] })
    // 线性中点
    expect(initial.colorTransferFunction[2].value).toBeCloseTo(5.0)
  })

  it('legacy profile：log + native-spectrum，节点几何间隔', async () => {
    const api = makeApi({
      fetchCapability: vi.fn().mockResolvedValue(supportedCapability(LEGACY_PROFILE)),
      fetchAsset: vi.fn().mockResolvedValue(ASSET),
    })
    const wrapper = mountPanel(api)
    await flushPromises()

    const initial = wrapper.findComponent(FrameStub).props('initialState') as RenderStateV2
    expect(initial.filter).toEqual({ min: 1.4, max: 133.1 })
    expect(initial.colorTransferFunction[0].color).toBe(PALETTES['native-spectrum'][0])
    expect(initial.colorTransferFunction[0].value).toBe(1.4)
    expect(initial.colorTransferFunction[4].value).toBe(133.1)
    // log 几何中点：sqrt(1.4 × 133.1)
    expect(initial.colorTransferFunction[2].value).toBeCloseTo(Math.sqrt(1.4 * 133.1))
  })
})

describe('NativeVolumePanel 控件与 revision', () => {
  it('rendered 后工具栏启用；每次变更推送完整状态且 revision 递增', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await flushPromises()

    expect(wrapper.findComponent(VolumeRenderToolbar).props('enabled')).toBe(false)
    await emitRendered(wrapper)
    expect(wrapper.findComponent(VolumeRenderToolbar).props('enabled')).toBe(true)

    // 不透明度变更：完整状态，revision=2（1 由 INIT 消费）
    const slider = wrapper.findComponent({ name: 'ElSlider' })
    ;(slider.vm as unknown as { $emit: (e: string, v: number) => void }).$emit(
      'update:modelValue',
      0.5,
    )
    await flushPromises()
    let state = lastAppliedState()
    expect(state.revision).toBe(2)
    expect(state.mode).toBe('volume')
    expect(state.opacity).toBe(0.5)
    expect(state.colorTransferFunction).toHaveLength(5)
    expect(state.lighting).toBe(false)

    // 滤波变更：revision=3
    await wrapper.find('[data-test="filter-min"]').setValue('4.5')
    await wrapper.find('[data-test="filter-max"]').setValue('5.5')
    await wrapper.find('[data-test="filter-apply"]').trigger('click')
    await flushPromises()
    state = lastAppliedState()
    expect(state.revision).toBe(3)
    expect(state.filter).toEqual({ min: 4.5, max: 5.5 })
    expect(state.opacity).toBe(0.5)
  })

  it('光照/渐变透明度可运行时切换，无「初始化固定」字样', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await flushPromises()
    await emitRendered(wrapper)

    expect(wrapper.text()).not.toContain('初始化固定')
    expect(wrapper.find('[data-test="lighting-toggle"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="gradient-opacity-toggle"]').exists()).toBe(true)

    // 默认关闭；用户手动打开后完整状态推送 true
    expect(
      (wrapper.findComponent(FrameStub).props('initialState') as RenderStateV2).lighting,
    ).toBe(false)
    await wrapper.find('[data-test="lighting-toggle"] input').setValue(true)
    await flushPromises()
    expect(lastAppliedState().lighting).toBe(true)

    await wrapper.find('[data-test="gradient-opacity-toggle"] input').setValue(true)
    await flushPromises()
    const state = lastAppliedState()
    expect(state.gradientOpacity).toBe(true)
    expect(state.lighting).toBe(true)
  })

  it('等值面输入只在 contour 模式显示；值进入状态，留空回落值域中点语义', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await flushPromises()
    await emitRendered(wrapper)

    expect(wrapper.find('[data-test="contour-value"]').exists()).toBe(false)

    await wrapper.find('[data-test="mode-contour"] input').setValue(true)
    await flushPromises()
    // contour 模式无 contourValue 时由子帧取值域中点
    let state = lastAppliedState()
    expect(state.mode).toBe('contour')
    expect(state.contourValue).toBeUndefined()

    const input = wrapper.find('[data-test="contour-value"]')
    expect(input.exists()).toBe(true)
    await input.setValue('5.1')
    await input.trigger('change')
    await flushPromises()
    state = lastAppliedState()
    expect(state.mode).toBe('contour')
    expect(state.contourValue).toBe(5.1)

    // 清空后回落中点语义（不带 contourValue）
    await input.setValue('')
    await input.trigger('change')
    await flushPromises()
    expect(lastAppliedState().contourValue).toBeUndefined()
  })

  it('模式选项只有 体积/切片/等值面：体积绝不被名为「点」的显示模式隐藏', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await flushPromises()

    const modes = ['mode-volume', 'mode-slice', 'mode-contour'].map((id) => {
      const el = wrapper.find(`[data-test="${id}"]`)
      expect(el.exists()).toBe(true)
      return el.text()
    })
    expect(modes).toEqual(['体积', '切片', '等值面'])
    expect(modes.join('|')).not.toContain('点')
    expect(wrapper.find('[data-test="mode-points"]').exists()).toBe(false)
  })

  it('辅助采样点默认关闭：frame 握手后发送 visible=false', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api, AUX_POINTS)
    await flushPromises()

    const toggle = wrapper.find('[data-test="aux-points-toggle"]')
    expect(toggle.classes()).toContain('el-checkbox')
    expect(toggle.attributes('aria-label')).toBe('显示辅助采样点')
    expect(toggle.find('input').exists()).toBe(true)
    expect((toggle.find('input').element as HTMLInputElement).checked).toBe(false)

    wrapper.findComponent(FrameStub).vm.$emit('ready', { sdkVersion: '12.1.0', contextType: 2 })
    await flushPromises()
    expect(frameExposed.setPointLayer).toHaveBeenCalledTimes(1)
    const payload = frameExposed.setPointLayer.mock.calls[0][0]
    expect(payload).toMatchObject({
      id: 'grid-samples',
      visible: false,
      role: 'auxiliary',
      coordinates: 'local',
    })
  })

  it('点开关不改变体积 phase；重置视角只发 reset-view', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api, AUX_POINTS)
    await flushPromises()
    await emitRendered(wrapper)

    expect(wrapper.find('[data-test="volume-phase"]').text()).toContain('已渲染')

    await wrapper.find('[data-test="aux-points-toggle"] input').setValue(true)
    await flushPromises()
    expect(frameExposed.setPointLayer.mock.calls.at(-1)?.[0].visible).toBe(true)
    expect(wrapper.find('[data-test="volume-phase"]').text()).toContain('已渲染')

    await wrapper.find('[data-test="reset-view"]').trigger('click')
    expect(frameExposed.resetView).toHaveBeenCalledTimes(1)
    // 重置视角不产生渲染状态推送
    expect(frameExposed.applyRenderState).not.toHaveBeenCalled()
  })
})

describe('NativeVolumePanel 切片集成', () => {
  it('apiKey 变化时清空旧身份并按新字段 API 重载，旧请求不得覆盖', async () => {
    let resolveOld: (value: RenderCapability) => void = () => {}
    const oldCapability = new Promise<RenderCapability>((resolve) => { resolveOld = resolve })
    const oldApi = makeApi({ fetchCapability: vi.fn(() => oldCapability) })
    const newAsset = { ...ASSET_B, source_id: 'r1::model_dispersion' }
    const newApi = makeApi({ fetchAsset: vi.fn().mockResolvedValue(newAsset) })
    const wrapper = mountPanel(oldApi, null, { apiKey: 'prediction' })

    await wrapper.setProps({ api: newApi, apiKey: 'model_dispersion' })
    await flushPromises()
    expect(newApi.fetchCapability).toHaveBeenCalledTimes(1)
    expect(newApi.fetchAsset).toHaveBeenCalledTimes(1)
    expect(wrapper.findComponent(FrameStub).props('asset')).toEqual(newAsset)

    resolveOld(supportedCapability())
    await flushPromises()
    expect(wrapper.findComponent(FrameStub).props('asset')).toEqual(newAsset)
    expect(wrapper.emitted('asset-identity')?.at(-1)?.[0]).toMatchObject({ assetId: newAsset.id })
    wrapper.unmount()
  })

  it('字段能力加载失败会结束切换状态，允许用户切回其他字段', async () => {
    const api = makeApi({
      fetchCapability: vi.fn().mockRejectedValue(
        new ApiError('ML_FIELD_NOT_AVAILABLE', '该成果不提供请求字段', 409),
      ),
    })
    const wrapper = mountPanel(api, null, { apiKey: 'model_dispersion' })
    await flushPromises()
    expect(wrapper.emitted('source-load-state')?.at(-1)?.[0]).toMatchObject({
      key: 'model_dispersion',
      loading: false,
      error: expect.stringContaining('ML_FIELD_NOT_AVAILABLE'),
    })
    wrapper.unmount()
  })

  it('字段切换后忽略旧资产的迟到切片响应', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api, null, { apiKey: 'prediction' })
    await flushPromises()
    await emitRendered(wrapper)
    await wrapper.find('[data-test="mode-slice"] input').setValue(true)
    await flushPromises()
    const before = wrapper.emitted('slice-analysis')?.length ?? 0

    const newAsset = { ...ASSET_B, source_id: 'r1::model_dispersion' }
    const nextApi = makeApi({ fetchAsset: vi.fn().mockResolvedValue(newAsset) })
    await wrapper.setProps({ api: nextApi, apiKey: 'model_dispersion' })
    await flushPromises()

    const stale = makeSliceAnalysis('z', 1)
    const exposed = wrapper.vm as unknown as { acceptSliceAnalysis: (response: SliceAnalysisResponse) => void }
    exposed.acceptSliceAnalysis(stale)
    await flushPromises()
    expect(wrapper.emitted('slice-analysis')?.length ?? 0).toBe(before)
    wrapper.unmount()
  })

  async function enterSliceMode(wrapper: ReturnType<typeof mount>) {
    await wrapper.find('[data-test="mode-slice"] input').setValue(true)
    await flushPromises()
  }

  it('进入切片：z/0 引导取轴元数据，目标转为 z 中位索引；3D slice 只来自权威响应', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await flushPromises()
    await emitRendered(wrapper)

    expect(wrapper.findComponent(OrthogonalSliceControls).exists()).toBe(false)
    expect(wrapper.findComponent(SliceAnalysisPanel).exists()).toBe(false)

    await enterSliceMode(wrapper)

    // 引导请求 z/0 + 中位索引 z/1 请求
    const calls = api.fetchSliceAnalysis.mock.calls.map((c: unknown[]) => [c[1], c[2]])
    expect(calls).toContainEqual(['z', 0])
    expect(calls).toContainEqual(['z', 1])
    expect(api.fetchSliceAnalysis.mock.calls[0][0]).toBe(ASSET.id)

    // 两个子组件出现，目标 = z 中位索引（floor((4-1)/2) = 1）
    expect(wrapper.findComponent(OrthogonalSliceControls).exists()).toBe(true)
    const analysis = wrapper.findComponent(SliceAnalysisPanel)
    expect(analysis.exists()).toBe(true)
    expect(analysis.props('target')).toEqual({ axis: 'z', index: 1 })
    expect(analysis.props('axesMeta')).toBeTruthy()
    expect(analysis.props('display')).toBe('controller')
    expect(wrapper.find('[data-test="slice-coordinate-label"]').exists()).toBe(false)

    // 3D slice 状态完全来自权威响应（coordinate / sdk_relative_position）
    const state = lastAppliedState()
    expect(state.mode).toBe('slice')
    expect(state.slice).toEqual({
      axis: 'z',
      index: 1,
      coordinate: -800,
      relativePosition: 1 / 3,
    })

    // 离开切片模式：两个子组件消失
    await wrapper.find('[data-test="mode-volume"] input').setValue(true)
    await flushPromises()
    expect(wrapper.findComponent(OrthogonalSliceControls).exists()).toBe(false)
    expect(wrapper.findComponent(SliceAnalysisPanel).exists()).toBe(false)
  })

  it('slice 模式切换瞬间不推送无 slice 载荷的状态', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await flushPromises()
    await emitRendered(wrapper)

    await wrapper.find('[data-test="mode-slice"] input').setValue(true)
    // 不等剖面链完成：此刻任何已推送状态都不得是缺 slice 载荷的 slice 模式
    for (const call of frameExposed.applyRenderState.mock.calls) {
      const state = call[0] as RenderStateV2
      if (state.mode === 'slice') expect(state.slice).toBeTruthy()
    }
    await flushPromises()
    // 最终状态：slice 载荷齐备
    expect(lastAppliedState().slice).toBeTruthy()
  })

  it('轴切换 commit 立即请求新剖面并更新 3D slice 状态', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await flushPromises()
    await emitRendered(wrapper)
    await enterSliceMode(wrapper)

    const controls = wrapper.findComponent(OrthogonalSliceControls)
    ;(controls.vm as unknown as { $emit: (e: string, v: unknown) => void }).$emit('commit', {
      axis: 'x',
      index: 1,
    })
    await flushPromises()

    expect(api.fetchSliceAnalysis).toHaveBeenCalledWith(ASSET.id, 'x', 1)
    const state = lastAppliedState()
    expect(state.mode).toBe('slice')
    expect(state.slice).toEqual({ axis: 'x', index: 1, coordinate: 100, relativePosition: 1 })
  })

  it('滑块 change 经 150ms 防抖更新目标', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await flushPromises()
    await emitRendered(wrapper)
    await enterSliceMode(wrapper)

    vi.useFakeTimers()
    try {
      const controls = wrapper.findComponent(OrthogonalSliceControls)
      const emitChange = (payload: unknown) =>
        (controls.vm as unknown as { $emit: (e: string, v: unknown) => void }).$emit(
          'change',
          payload,
        )
      const yCalls = () =>
        api.fetchSliceAnalysis.mock.calls.filter(
          (c: unknown[]) => c[1] === 'y' && c[2] === 2,
        ).length

      emitChange({ axis: 'y', index: 2, coordinate: 20 })
      vi.advanceTimersByTime(100)
      expect(yCalls()).toBe(0)
      vi.advanceTimersByTime(60)
      await flushPromises()
      expect(yCalls()).toBe(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('切换资产：剖面目标/轴元数据清空，渲染状态回 profile 默认，revision 重置', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await flushPromises()
    await emitRendered(wrapper)
    await enterSliceMode(wrapper)
    expect(wrapper.findComponent(SliceAnalysisPanel).exists()).toBe(true)

    // 资产身份切换（A → B）：刷新状态后一切切片上下文清空
    api.fetchAsset.mockResolvedValue(ASSET_B)
    await wrapper.find('[data-test="refresh-asset"]').trigger('click')
    await flushPromises()

    const frame = wrapper.findComponent(FrameStub)
    expect(frame.props('asset')).toEqual(ASSET_B)
    const initial = frame.props('initialState') as RenderStateV2
    expect(initial.revision).toBe(1)
    expect(initial.mode).toBe('volume')
    expect(wrapper.findComponent(SliceAnalysisPanel).exists()).toBe(false)
    expect(wrapper.findComponent(OrthogonalSliceControls).exists()).toBe(false)

    // 重新进入切片模式：对新资产重新引导
    await emitRendered(wrapper)
    await enterSliceMode(wrapper)
    expect(api.fetchSliceAnalysis).toHaveBeenCalledWith(ASSET_B.id, 'z', 0)
  })
})

describe('渲染资产 API 客户端（POST/GET 纪律）', () => {
  interface FetchCall {
    url: string
    init?: RequestInit
  }

  function stubFetchOk(body: unknown): FetchCall[] {
    const calls: FetchCall[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, init })
        return {
          ok: true,
          status: 200,
          json: async () => body,
        } as unknown as Response
      }),
    )
    return calls
  }

  it('资产创建一律 POST（retry_failed 进入请求体）', async () => {
    const calls = stubFetchOk(ASSET)
    await createResultRenderAsset('r1')
    await createResultRenderAsset('r1', true)
    expect(calls).toHaveLength(2)
    for (const call of calls) {
      expect(call.url).toBe('/api/results/r1/render-assets/netcdf')
      expect(call.init?.method).toBe('POST')
    }
    expect(JSON.parse(calls[0].init?.body as string)).toEqual({ retry_failed: false })
    expect(JSON.parse(calls[1].init?.body as string)).toEqual({ retry_failed: true })
  })

  it('状态/能力/剖面分析刷新一律 GET：绝不隐式 POST、绝不带请求体', async () => {
    const calls = stubFetchOk(ASSET)
    await fetchResultRenderAsset('r1')
    await fetchResultRenderCapability('r1')
    await fetchRenderAssetSliceAnalysis('nc-1', 'x', 3)
    expect(calls.map((c) => c.url)).toEqual([
      '/api/results/r1/render-assets/netcdf',
      '/api/results/r1/render-capability',
      '/api/render-assets/nc-1/slice-analysis?axis=x&index=3',
    ])
    for (const call of calls) {
      expect(call.init?.method ?? 'GET').toBe('GET')
      expect(call.init?.body).toBeUndefined()
    }
  })

  it('剖面导出是显式 multipart POST（axis/index/image 同名字段）', async () => {
    const calls = stubFetchOk({ id: 'exp-1' })
    const png = new Blob(['png'], { type: 'image/png' })
    await createRenderAssetSliceExport('nc-1', 'z', 1, png)
    expect(calls).toHaveLength(1)
    expect(calls[0].url).toBe('/api/render-assets/nc-1/slice-exports')
    expect(calls[0].init?.method).toBe('POST')
    const body = calls[0].init?.body
    expect(body).toBeInstanceOf(FormData)
    const form = body as FormData
    expect(form.get('axis')).toBe('z')
    expect(form.get('index')).toBe('1')
    expect(form.get('image')).toBeTruthy()
  })

  it('物化是显式 POST（结果元数据返回）', async () => {
    const calls = stubFetchOk({ result_id: 'r1' })
    await materializeResult('r1')
    expect(calls).toHaveLength(1)
    expect(calls[0].url).toBe('/api/results/r1/materialize')
    expect(calls[0].init?.method).toBe('POST')
  })
})

describe('NativeVolumePanel v0.9 图表—三维联动', () => {
  async function emitRenderedNow(wrapper: ReturnType<typeof mount>) {
    await flushPromises()
    const frame = wrapper.findComponent({ name: 'SuperMapVolumeFrame' })
    frame.vm.$emit('ready')
    frame.vm.$emit('rendered', {
      sourceKind: 'candidate_result',
      sourceId: 'r1',
      gridSha256: 'g'.repeat(64),
      netcdfSha256: 'n'.repeat(64),
    })
    await flushPromises()
  }

  it('sliceRequest 解析为最近坐标索引并驱动权威切片流程', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await emitRenderedNow(wrapper)

    // 进入 slice 模式（z 中位引导完成，axesMeta 就绪）
    await wrapper.find('[data-test="mode-slice"] input').setValue(true)
    await flushPromises()

    // 图表区间 [60,100] → 中点 80 → x 最近坐标 100（index 1）
    await wrapper.setProps({ sliceRequest: { axis: 'x', range: [60, 100], token: 1 } })
    await flushPromises()
    await flushPromises()

    const analysis = wrapper.findComponent(SliceAnalysisPanel)
    expect(analysis.props('target')).toEqual({ axis: 'x', index: 1 })
    wrapper.unmount()
  })

  it('区间越界时发出 slice-request-failed，绝不伪报定位成功', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await emitRenderedNow(wrapper)
    await wrapper.find('[data-test="mode-slice"] input').setValue(true)
    await flushPromises()

    await wrapper.setProps({ sliceRequest: { axis: 'x', range: [500, 600], token: 1 } })
    await flushPromises()

    const failed = wrapper.emitted('slice-request-failed')
    expect(failed).toBeTruthy()
    expect((failed?.[0] as Array<{ reason: string }>)[0].reason).toContain('超出数据范围')
    wrapper.unmount()
  })
})

describe('NativeVolumePanel v0.9 联动挂起解析', () => {
  it('volume 模式下 sliceRequest 先切模式挂起，轴元数据到达后解析为最近索引', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await flushPromises()
    const frame = wrapper.findComponent({ name: 'SuperMapVolumeFrame' })
    frame.vm.$emit('ready')
    frame.vm.$emit('rendered', {
      sourceKind: 'candidate_result',
      sourceId: 'r1',
      gridSha256: 'g'.repeat(64),
      netcdfSha256: 'n'.repeat(64),
    })
    await flushPromises()

    // 仍在 volume 模式（axesMeta 未加载）：请求 y 区间 [12, 20]（中点 16 → 最近 20，index 2）
    await wrapper.setProps({ sliceRequest: { axis: 'y', range: [12, 20], token: 1 } })
    await flushPromises()
    await flushPromises()
    await flushPromises()

    // 模式已切到 slice，且目标解析为 y/2（非 z 中位）
    const state = lastAppliedState()
    expect(state.mode).toBe('slice')
    const analysis = wrapper.findComponent(SliceAnalysisPanel)
    expect(analysis.exists()).toBe(true)
    expect(analysis.props('target')).toEqual({ axis: 'y', index: 2 })
    expect(wrapper.emitted('slice-request-failed')).toBeFalsy()
    wrapper.unmount()
  })
})

// v0.9.0 V6 Task 1：无 profile 降级路径的默认渲染状态合同
describe('NativeVolumePanel V6 默认渲染状态', () => {
  it('render_profile=null 降级路径：光照/渐变透明度默认关闭，包围盒默认开启', async () => {
    const api = makeApi({
      fetchCapability: vi.fn().mockResolvedValue({
        ...supportedCapability(null),
        render_profile: null,
      }),
      fetchAsset: vi.fn().mockResolvedValue(ASSET),
    })
    const wrapper = mountPanel(api)
    await flushPromises()
    const initial = wrapper.findComponent(FrameStub).props('initialState') as RenderStateV2
    expect(initial.lighting).toBe(false)
    expect(initial.gradientOpacity).toBe(false)
    expect(initial.boundingBox).toBe(true)
    wrapper.unmount()
  })
})

// v0.9.0 Task 9：成果异常标注、相机预设、组件聚焦与权威切片外发。
// 标注线协议由 components prop 映射（id=component-N、局部坐标、确定性色带）；
// 任何状态下组件身份变化立即重建标注，绝不跨成果残留。
describe('NativeVolumePanel v0.9 异常标注联动', () => {
  const COMPONENTS = RESULT_ANALYSIS_MOCK_3D.components_preview.rows

  function mountWithComponents(api: FakeApi, extraProps: Record<string, unknown> = {}) {
    return mount(NativeVolumePanel, {
      props: { api, components: COMPONENTS, ...extraProps },
      global: {
        plugins: [ElementPlus],
        stubs: { SuperMapVolumeFrame: FrameStub, SliceHeatmap: HeatmapStub },
      },
      attachTo: document.body,
    })
  }

  async function mountRenderedWithComponents(extraProps: Record<string, unknown> = {}) {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountWithComponents(api, extraProps)
    await flushPromises()
    await emitRendered(wrapper)
    return wrapper
  }

  it('components 映射为 INIT 初始状态标注：id/坐标/支持量/确定性颜色', async () => {
    const wrapper = await mountRenderedWithComponents()
    const frame = wrapper.findComponent(FrameStub)
    const initial = frame.props('initialState') as RenderStateV2
    expect(initial.annotations).toHaveLength(3)
    const [a, b] = initial.annotations!
    expect(a).toMatchObject({
      id: 'component-1',
      label: 'A',
      localPosition: [15, 15, 25],
      valueMax: 100,
      supportMeasure: 500,
      supportUnit: 'volume_coordinate_unit3',
      visible: true,
    })
    expect(a.bounds).toEqual([
      [10, 20],
      [10, 20],
      [20, 30],
    ])
    // 颜色按 rank 确定性分配且互不相同
    expect(a.color).toMatch(/^#[0-9a-fA-F]{6}$/)
    expect(b.color).not.toBe(a.color)
    // 初始无聚焦；场景辅助默认随状态携带
    expect(initial.focusedAnnotationId ?? null).toBeNull()
    expect(initial.sceneAids).toEqual({ axes: true, depthTicks: true })
    wrapper.unmount()
  })

  it('focusedComponentId prop 写入 focusedAnnotationId 并随状态推送', async () => {
    const wrapper = await mountRenderedWithComponents({ focusedComponentId: 2 })
    await flushPromises()
    // 挂载即聚焦：INIT 初始状态携带聚焦 id（无需等待状态推送）
    expect(
      (wrapper.findComponent(FrameStub).props('initialState') as RenderStateV2).focusedAnnotationId,
    ).toBe('component-2')
    // 清除聚焦：watch 推送完整状态
    await wrapper.setProps({ focusedComponentId: null })
    await flushPromises()
    expect(lastAppliedState().focusedAnnotationId ?? null).toBeNull()
    wrapper.unmount()
  })

  it('focusComponent 命令子帧聚焦相机；annotation-selected 反选组件', async () => {
    const wrapper = await mountRenderedWithComponents()
    const api = wrapper.vm as unknown as { focusComponent: (id: number) => void }
    api.focusComponent(2)
    expect(frameExposed.focusAnnotation).toHaveBeenCalledWith('component-2')

    const frame = wrapper.findComponent(FrameStub)
    frame.vm.$emit('annotation-selected', { annotationId: 'component-3' })
    await flushPromises()
    expect(wrapper.emitted('annotation-selected')).toEqual([[{ componentId: 3 }]])
    wrapper.unmount()
  })

  it('focusComponent 遇到当前渲染状态不存在的组件时保持场景可用', async () => {
    const wrapper = await mountRenderedWithComponents()
    const api = wrapper.vm as unknown as { focusComponent: (id: number) => void }
    api.focusComponent(99)
    expect(frameExposed.focusAnnotation).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('相机预设从工具栏命令子帧', async () => {
    const wrapper = await mountRenderedWithComponents()
    await wrapper.get('[data-test="camera-top-xy"]').trigger('click')
    expect(frameExposed.setCameraPreset).toHaveBeenCalledWith('top-xy')
    await wrapper.get('[data-test="camera-front-xz"]').trigger('click')
    expect(frameExposed.setCameraPreset).toHaveBeenCalledWith('front-xz')
    wrapper.unmount()
  })

  it('组件身份变化立即重建标注：旧 id 消失，聚焦清空', async () => {
    const wrapper = await mountRenderedWithComponents({ focusedComponentId: 2 })
    await flushPromises()
    await wrapper.setProps({ components: [COMPONENTS[0]] })
    await flushPromises()
    const state = lastAppliedState()
    expect(state.annotations).toHaveLength(1)
    expect(state.annotations![0].id).toBe('component-1')
    // 聚焦的 component-2 已不在列表：聚焦必须清空（协议硬校验）
    expect(state.focusedAnnotationId ?? null).toBeNull()
    // 组件清空：annotations 为空数组
    await wrapper.setProps({ components: null })
    await flushPromises()
    expect(lastAppliedState().annotations).toEqual([])
    wrapper.unmount()
  })

  it('权威剖面响应经 slice-analysis 事件外发（当前切片证据共用）', async () => {
    const wrapper = await mountRenderedWithComponents()
    await wrapper.get('[data-test="mode-slice"]').trigger('click')
    await flushPromises()
    await flushPromises()
    const emitted = wrapper.emitted('slice-analysis')
    expect(emitted).toBeTruthy()
    const response = emitted!.at(-1)![0] as SliceAnalysisResponse
    expect(response.slice.fixed_axis).toBe('z')
    expect(response.asset_identity.asset_id).toBe(ASSET.id)
    const controller = wrapper.findComponent(SliceAnalysisPanel)
    expect(controller.props('display')).toBe('controller')
    expect(wrapper.find('[data-test="slice-analysis"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="slice-analysis-controller"]').exists()).toBe(true)
    wrapper.unmount()
  })
})
