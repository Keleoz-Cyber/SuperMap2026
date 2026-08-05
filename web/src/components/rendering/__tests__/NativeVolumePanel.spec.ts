import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../../api/client'
import {
  createLegacyRhoRenderAsset,
  createResultRenderAsset,
  fetchLegacyRhoRenderAsset,
  fetchLegacyRhoRenderCapability,
  fetchResultRenderAsset,
  fetchResultRenderCapability,
  materializeResult,
} from '../../../api/client'
import type {
  DisplayTransform,
  RenderAssetRecord,
  RenderCapability,
} from '../../../api/types'
import NativeVolumePanel from '../NativeVolumePanel.vue'

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

const FAILED_ASSET: RenderAssetRecord = {
  ...ASSET,
  status: 'failed',
  netcdf_sha256: null,
  manifest_url: null,
  netcdf_url: null,
  error: { code: 'NETCDF_EXPORT_FAILED', message: 'NetCDF 写盘失败', details: {} },
}

function supportedCapability(): RenderCapability {
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

// frame stub：记录 props，暴露与真实组件同名的命令方法
let frameExposed: {
  applyRenderState: ReturnType<typeof vi.fn>
  setPointLayer: ReturnType<typeof vi.fn>
  resetView: ReturnType<typeof vi.fn>
}

const FrameStub = defineComponent({
  name: 'SuperMapVolumeFrame',
  props: {
    asset: { type: Object, default: null },
    displayTransform: { type: Object, required: true },
    initialState: { type: Object, required: true },
  },
  emits: ['ready', 'rendered', 'failed'],
  setup(_props, { expose }) {
    frameExposed = {
      applyRenderState: vi.fn().mockReturnValue(true),
      setPointLayer: vi.fn(),
      resetView: vi.fn(),
    }
    expose(frameExposed)
    return () => h('div', { 'data-test': 'volume-frame-stub' })
  },
})

interface FakeApi {
  fetchCapability: ReturnType<typeof vi.fn>
  fetchAsset: ReturnType<typeof vi.fn>
  createAsset: ReturnType<typeof vi.fn>
}

function makeApi(overrides: Partial<FakeApi> = {}): FakeApi {
  return {
    fetchCapability: vi.fn().mockResolvedValue(supportedCapability()),
    fetchAsset: vi
      .fn()
      .mockRejectedValue(new ApiError('RENDER_ASSET_NOT_FOUND', '该渲染源尚未创建渲染资产', 404)),
    createAsset: vi.fn().mockResolvedValue(ASSET),
    ...overrides,
  }
}

function mountPanel(api: FakeApi, auxPoints: typeof AUX_POINTS | null = null) {
  return mount(NativeVolumePanel, {
    props: { api, auxPoints },
    global: { stubs: { SuperMapVolumeFrame: FrameStub } },
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

beforeEach(() => {
  document.body.innerHTML = ''
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('NativeVolumePanel 能力与资产', () => {
  it('支持但未生成资产：显示生成按钮与三句真值标签，体积控件禁用', async () => {
    const api = makeApi()
    const wrapper = mountPanel(api)
    await flushPromises()

    expect(api.fetchCapability).toHaveBeenCalledTimes(1)
    const createBtn = wrapper.find('[data-test="create-asset"]')
    expect(createBtn.exists()).toBe(true)
    expect(createBtn.text()).toContain('生成 NetCDF 体渲染资产')

    const text = wrapper.text()
    expect(text).toContain('渲染器：SuperMap3D VoxelGridLayer3D')
    expect(text).toContain('坐标状态：显示锚点（非真实地理配准）')
    expect(text).toContain('辅助采样点：不参与连续体渲染')
    expect(text).toContain('display_anchor_only')

    for (const sel of ['[data-test="mode-volume"]', '[data-test="opacity-slider"]', '[data-test="reset-view"]']) {
      expect(wrapper.find(sel).attributes('disabled')).toBeDefined()
    }
  })

  it('生成资产：点击按钮调用 createAsset(false)，资产身份与坐标状态可见', async () => {
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

  it('unsupported capability：显示原因、INIT asset=null、绝不启用体积控件', async () => {
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

    // 即使 frame 误报 rendered，面板也绝不启用体积控件
    frame.vm.$emit('ready', { sdkVersion: '12.1.0', contextType: 2 })
    frame.vm.$emit('rendered', null)
    await flushPromises()
    expect(wrapper.find('[data-test="mode-volume"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-test="opacity-slider"]').attributes('disabled')).toBeDefined()
  })

  it('原生失败：显示错误且无任何 fallback 文案', async () => {
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
    // 失败不是成功：体积控件仍禁用
    expect(wrapper.find('[data-test="mode-volume"]').attributes('disabled')).toBeDefined()
  })
})

describe('NativeVolumePanel 控件', () => {
  it('控件 rendered 前禁用，rendered 后启用并发送命令', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await flushPromises()

    for (const sel of [
      '[data-test="mode-volume"]',
      '[data-test="mode-slice"]',
      '[data-test="mode-contour"]',
      '[data-test="opacity-slider"]',
      '[data-test="filter-apply"]',
      '[data-test="reset-view"]',
    ]) {
      expect(wrapper.find(sel).attributes('disabled')).toBeDefined()
    }

    await emitRendered(wrapper)

    for (const sel of ['[data-test="mode-slice"]', '[data-test="opacity-slider"]', '[data-test="reset-view"]']) {
      expect(wrapper.find(sel).attributes('disabled')).toBeUndefined()
    }

    await wrapper.find('[data-test="mode-slice"]').trigger('click')
    expect(frameExposed.applyRenderState).toHaveBeenCalledWith(
      expect.objectContaining({
        mode: 'slice',
        slice: { axis: 'z', index: 0, coordinate: 0, relativePosition: 0.5 },
      }),
    )

    const slider = wrapper.find('[data-test="opacity-slider"]')
    await slider.setValue('0.5')
    expect(frameExposed.applyRenderState).toHaveBeenCalledWith(
      expect.objectContaining({ opacity: 0.5 }),
    )

    await wrapper.find('[data-test="reset-view"]').trigger('click')
    expect(frameExposed.resetView).toHaveBeenCalledTimes(1)
  })

  it('滤波要求 min <= max：非法输入不发送命令并显示校验提示', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await flushPromises()
    await emitRendered(wrapper)

    await wrapper.find('[data-test="filter-min"]').setValue('10')
    await wrapper.find('[data-test="filter-max"]').setValue('2')
    await wrapper.find('[data-test="filter-apply"]').trigger('click')
    expect(frameExposed.applyRenderState).not.toHaveBeenCalled()
    expect(wrapper.find('[data-test="filter-error"]').exists()).toBe(true)

    await wrapper.find('[data-test="filter-max"]').setValue('20')
    await wrapper.find('[data-test="filter-apply"]').trigger('click')
    expect(frameExposed.applyRenderState).toHaveBeenCalledWith(
      expect.objectContaining({ filter: { min: 10, max: 20 } }),
    )
  })

  it('模式选项只有 体积/切片/等值线：体积绝不被名为「点」的显示模式隐藏', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await flushPromises()

    const modes = wrapper.findAll('[data-test^="mode-"]').map((b) => b.text())
    expect(modes).toHaveLength(3)
    expect(modes.join('|')).not.toContain('点')
    // 没有任何途径把体积显示模式切到「点」
    expect(wrapper.find('[data-test="mode-points"]').exists()).toBe(false)
  })

  it('辅助采样点默认关闭：frame 握手后发送 visible=false', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api, AUX_POINTS)
    await flushPromises()

    const toggle = wrapper.find('[data-test="aux-points-toggle"]')
    expect((toggle.element as HTMLInputElement).checked).toBe(false)

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

  it('点开关不改变体积 phase', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api, AUX_POINTS)
    await flushPromises()
    await emitRendered(wrapper)

    expect(wrapper.find('[data-test="volume-phase"]').text()).toContain('已渲染')

    await wrapper.find('[data-test="aux-points-toggle"]').setValue(true)
    await flushPromises()
    const lastCall = frameExposed.setPointLayer.mock.calls.at(-1)?.[0]
    expect(lastCall.visible).toBe(true)
    expect(wrapper.find('[data-test="volume-phase"]').text()).toContain('已渲染')

    await wrapper.find('[data-test="aux-points-toggle"]').setValue(false)
    await flushPromises()
    expect(frameExposed.setPointLayer.mock.calls.at(-1)?.[0].visible).toBe(false)
    expect(wrapper.find('[data-test="volume-phase"]').text()).toContain('已渲染')
  })

  it('光照与渐变透明度开关存在且标注为初始化固定启用（协议 v1 无运行时命令）', async () => {
    const api = makeApi({ fetchAsset: vi.fn().mockResolvedValue(ASSET) })
    const wrapper = mountPanel(api)
    await flushPromises()

    expect(wrapper.find('[data-test="lighting-toggle"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="gradient-opacity-toggle"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="style-note"]').text()).toContain('初始化')
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

    calls.length = 0
    await createLegacyRhoRenderAsset(true)
    expect(calls[0].url).toBe('/api/cases/resistivity/render-assets/netcdf')
    expect(calls[0].init?.method).toBe('POST')
  })

  it('状态/能力刷新一律 GET：绝不隐式 POST、绝不带请求体', async () => {
    const calls = stubFetchOk(ASSET)
    await fetchResultRenderAsset('r1')
    await fetchResultRenderCapability('r1')
    await fetchLegacyRhoRenderAsset()
    await fetchLegacyRhoRenderCapability()
    expect(calls.map((c) => c.url)).toEqual([
      '/api/results/r1/render-assets/netcdf',
      '/api/results/r1/render-capability',
      '/api/cases/resistivity/render-assets/netcdf',
      '/api/cases/resistivity/render-capability',
    ])
    for (const call of calls) {
      expect(call.init?.method ?? 'GET').toBe('GET')
      expect(call.init?.body).toBeUndefined()
    }
  })

  it('物化是显式 POST（结果元数据返回）', async () => {
    const calls = stubFetchOk({ result_id: 'r1' })
    await materializeResult('r1')
    expect(calls).toHaveLength(1)
    expect(calls[0].url).toBe('/api/results/r1/materialize')
    expect(calls[0].init?.method).toBe('POST')
  })
})
