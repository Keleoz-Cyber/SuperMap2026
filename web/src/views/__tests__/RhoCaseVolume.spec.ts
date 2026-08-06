import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as client from '../../api/client'
import { ApiError } from '../../api/client'
import type {
  DisplayTransform,
  LegacyRenderSourceRegistration,
  PublishStatus,
  RenderAssetRecord,
  RenderCapability,
  RhoCaseDetail,
  RhoPoints,
} from '../../api/types'
import RhoCaseView from '../RhoCaseView.vue'

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    fetchRhoCase: vi.fn(),
    fetchRhoPublishStatus: vi.fn(),
    fetchRhoPoints: vi.fn(),
    fetchLegacyRhoRenderCapability: vi.fn(),
    fetchLegacyRhoRenderAsset: vi.fn(),
    createLegacyRhoRenderAsset: vi.fn(),
    importLegacyRhoRenderSource: vi.fn(),
  }
})

const TRANSFORM: DisplayTransform = {
  contract: 'wgs84_display_anchor_v1',
  origin_x: -160,
  origin_y: 220,
  anchor_longitude: 120,
  anchor_latitude: 30,
  anchor_height: 0,
  metres_per_degree_lon: 96486.3,
  metres_per_degree_lat: 110852.4,
}

const RHO_DETAIL: RhoCaseDetail = {
  case_id: 'resistivity',
  title: '地下电阻率',
  coordinate: { type: 'local', epsg: null, note: '局部工程坐标 · EPSG 未确认 · Z 向下为负' },
  datasets: [],
  validation_split: { spatial_column_overlap: 0, seed: 'test-seed' },
  metric_expectations: { common_valid: 100, common_nodata: 0, coverage_rate: 1 },
  models: [],
  baseline_comparison: null,
  metric_source: 'test',
  supermap: { version: '12.1.0', datasource_alias: 'rho', dataset_api: '', results: [] },
  views: [],
  issues: [],
}

const RHO_POINTS: RhoPoints = {
  case_id: 'resistivity',
  source: 'csv',
  source_label: 'rho_measurements.csv',
  sha256: 'ab'.repeat(32),
  decimate: 40,
  count: 1000,
  served: 3,
  value_field: 'rho',
  unit_note: 'Ω·m',
  x: [-150, -100, -60],
  y: [260, 400, 580],
  z: [-100, -200, -300],
  values: [10, 50, 120],
  value_range: [10, 120],
  x_range: [-150, -60],
  y_range: [260, 580],
  z_range: [-300, -100],
}

function makePublishStatus(volumeAvailable: boolean): PublishStatus {
  return {
    case_id: 'resistivity',
    result_id: 'RHO_KRIG_FINAL_20M_40',
    iserver_available: true,
    iserver: {
      base_url: 'http://localhost:8090/iserver',
      reachable: true,
      http_status: 200,
      services: [],
    },
    service_checks: [
      {
        name: 'realspace',
        service_type: 'REST3D',
        url: 'http://localhost:8090/iserver/services/3D-WorkSpace/rest/realspace',
        reachable: true,
        http_status: 200,
        detail: {
          scene_names: ['RHO_三维全值域'],
          layers: [{ name: 'RHO@rho', layer3DType: 'ImageFileLayer', visible: true }],
        },
        error: null,
      },
    ],
    evidence_chain: { result_id: 'RHO_KRIG_FINAL_20M_40', states: [] },
    failed_results: [],
    planned_services: {
      data: 'http://localhost:8090/iserver/services/data-rho/rest/data',
      map: 'http://localhost:8090/iserver/services/map-rho/rest/maps/rho',
      realspace: 'http://localhost:8090/iserver/services/3D-WorkSpace/rest/realspace',
      scene_name: 'RHO_三维全值域',
      volume: {
        url: 'http://localhost:8090/iserver/services/3D-WorkSpace/rest/realspace/datas/rho',
        service_name: 'rho-volume',
        scene_name: 'RHO_三维全值域',
        available: volumeAvailable,
        layers: [],
        note: volumeAvailable ? 'S3M 缓存已发布且可访问' : 'S3M 缓存未发布',
      },
    },
  }
}

function supportedCapability(): RenderCapability {
  return {
    source_kind: 'builtin_legacy',
    source_id: 'resistivity',
    supported: true,
    reason_code: null,
    reason: null,
    dimension: '3d',
    grid_kind: 'regular',
    property_name: 'rho',
    units: 'Ω·m',
    geolocation_status: 'display_anchor_only',
    display_transform: TRANSFORM,
  }
}

function missingGridCapability(transform: DisplayTransform | null): RenderCapability {
  return {
    source_kind: 'builtin_legacy',
    source_id: 'resistivity',
    supported: false,
    reason_code: 'LEGACY_RENDER_SOURCE_NOT_REGISTERED',
    reason: '内置电阻率案例尚未登记可审计的规则三维网格',
    dimension: null,
    grid_kind: null,
    property_name: 'rho',
    units: 'Ω·m',
    geolocation_status: 'display_anchor_only',
    display_transform: transform,
  }
}

const LEGACY_ASSET: RenderAssetRecord = {
  id: `nc-${'a'.repeat(32)}`,
  source_kind: 'builtin_legacy',
  source_id: 'resistivity',
  renderer: 'supermap_voxelgrid_netcdf',
  status: 'ready',
  grid_sha256: 'g'.repeat(64),
  netcdf_sha256: 'n'.repeat(64),
  manifest_url: `/api/render-assets/nc-${'a'.repeat(32)}/manifest`,
  netcdf_url: `/api/render-assets/nc-${'a'.repeat(32)}/volume.nc`,
  error: null,
}

const LEGACY_FAILED_ASSET: RenderAssetRecord = {
  ...LEGACY_ASSET,
  status: 'failed',
  netcdf_sha256: null,
  manifest_url: null,
  netcdf_url: null,
  error: { code: 'NETCDF_EXPORT_FAILED', message: 'NetCDF 写盘失败', details: {} },
}

// 导入登记身份（导入端点响应）：artifact_dir 为相对工件目录身份，绝无绝对路径
const REGISTRATION: LegacyRenderSourceRegistration = {
  source_kind: 'builtin_legacy',
  source_id: 'resistivity',
  grid_sha256: 'g'.repeat(64),
  property_name: 'RHO',
  units: 'unknown',
  shape: [3, 4, 5],
  artifact_dir: `builtin_legacy/resistivity/${'g'.repeat(64)}`,
  import_source_sha256: 'i'.repeat(64),
}

async function chooseImportFile(wrapper: { find: (selector: string) => any }): Promise<File> {
  const file = new File(['X,Y,Z,RHO\n0,0,0,1\n'], 'grid.csv', { type: 'text/csv' })
  const input = wrapper.find('[data-test="legacy-import-file"]')
  expect(input.exists()).toBe(true)
  Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
  await input.trigger('change')
  return file
}

// frame stub：与 NativeVolumePanel.spec 同一约定（v2 协议），记录 props 并暴露同名命令方法
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

async function mountView(options: {
  capability: RenderCapability
  asset?: RenderAssetRecord | null
  volumeAvailable?: boolean
}) {
  vi.mocked(client.fetchRhoCase).mockResolvedValue(RHO_DETAIL)
  vi.mocked(client.fetchRhoPublishStatus).mockResolvedValue(
    makePublishStatus(options.volumeAvailable ?? false),
  )
  vi.mocked(client.fetchRhoPoints).mockResolvedValue(RHO_POINTS)
  vi.mocked(client.fetchLegacyRhoRenderCapability).mockResolvedValue(options.capability)
  if (options.asset) {
    vi.mocked(client.fetchLegacyRhoRenderAsset).mockResolvedValue(options.asset)
  } else {
    vi.mocked(client.fetchLegacyRhoRenderAsset).mockRejectedValue(
      new ApiError('RENDER_ASSET_NOT_FOUND', '该渲染源尚未创建渲染资产', 404),
    )
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/case/resistivity', name: 'rho-case', component: RhoCaseView },
    ],
  })
  await router.push('/case/resistivity')
  const wrapper = mount(RhoCaseView, {
    global: { plugins: [router, ElementPlus], stubs: { SuperMapVolumeFrame: FrameStub } },
    attachTo: document.body,
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  document.body.innerHTML = ''
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('RhoCaseView legacy 体渲染能力真值', () => {
  it('已登记网格：显式创建按钮 -> 原生 iframe，测点握手后作为 legacy-measurements 辅助层发送', async () => {
    vi.mocked(client.createLegacyRhoRenderAsset).mockResolvedValue(LEGACY_ASSET)
    const wrapper = await mountView({ capability: supportedCapability() })

    // 能力支持 + 无资产：只有显式创建按钮，绝不自动 POST
    const createBtn = wrapper.find('[data-test="create-asset"]')
    expect(createBtn.exists()).toBe(true)
    expect(client.createLegacyRhoRenderAsset).not.toHaveBeenCalled()

    await createBtn.trigger('click')
    await flushPromises()
    expect(client.createLegacyRhoRenderAsset).toHaveBeenCalledWith(false)

    // 原生 iframe：ready 资产 + 只读 display_transform
    const frame = wrapper.findComponent(FrameStub)
    expect(frame.exists()).toBe(true)
    expect(frame.props('asset')).toEqual(LEGACY_ASSET)
    expect(frame.props('displayTransform')).toEqual(TRANSFORM)

    // 握手后测点作为 legacy-measurements 辅助层发送（默认关，局部坐标）
    frame.vm.$emit('ready', { sdkVersion: '12.1.0', contextType: 2 })
    await flushPromises()
    expect(frameExposed.setPointLayer).toHaveBeenCalled()
    const payload = frameExposed.setPointLayer.mock.calls[0][0]
    expect(payload).toMatchObject({
      id: 'legacy-measurements',
      visible: false,
      role: 'auxiliary',
      coordinates: 'local',
      x: RHO_POINTS.x,
      y: RHO_POINTS.y,
      z: RHO_POINTS.z,
      values: RHO_POINTS.values,
    })

    frame.vm.$emit('rendered', {
      sourceKind: 'builtin_legacy',
      sourceId: 'resistivity',
      gridSha256: 'g'.repeat(64),
      netcdfSha256: 'n'.repeat(64),
    })
    await flushPromises()
    expect(wrapper.find('[data-test="volume-phase"]').text()).toContain('已渲染')
    expect(wrapper.find('[data-test="legacy-aux-notice"]').exists()).toBe(false)
  })

  it('未登记网格：点云专用 iframe + 测点辅助层 + LEGACY_RENDER_SOURCE_NOT_REGISTERED，状态永不为 rendered', async () => {
    const wrapper = await mountView({ capability: missingGridCapability(TRANSFORM) })

    // 稳定原因码 + 显式分离的辅助视图说明
    const reason = wrapper.find('[data-test="unsupported-reason"]')
    expect(reason.exists()).toBe(true)
    expect(reason.text()).toContain('LEGACY_RENDER_SOURCE_NOT_REGISTERED')
    const notice = wrapper.find('[data-test="legacy-aux-notice"]')
    expect(notice.exists()).toBe(true)
    expect(notice.text()).toContain('当前案例尚未登记可审计的规则三维网格，因此不支持 NetCDF 体渲染。')
    expect(notice.text()).toContain('测点仅用于数据分布检查，不是体渲染。')

    // 无创建按钮；点云专用 iframe 以 asset=null 挂载
    expect(wrapper.find('[data-test="create-asset"]').exists()).toBe(false)
    const frame = wrapper.findComponent(FrameStub)
    expect(frame.exists()).toBe(true)
    expect(frame.props('asset')).toBeNull()
    expect(frame.props('displayTransform')).toEqual(TRANSFORM)

    // 握手后仍发送测点辅助层
    frame.vm.$emit('ready', { sdkVersion: '12.1.0', contextType: 2 })
    await flushPromises()
    expect(frameExposed.setPointLayer).toHaveBeenCalled()
    expect(frameExposed.setPointLayer.mock.calls[0][0].id).toBe('legacy-measurements')

    // 即使子帧因点像素误报 rendered，原生体积状态保持 unsupported，控件绝不可用
    frame.vm.$emit('rendered', null)
    await flushPromises()
    expect(wrapper.find('[data-test="volume-phase"]').text()).toContain('不支持体渲染')
    expect(wrapper.find('[data-test="mode-volume"]').classes()).toContain('is-disabled')
  })

  it('原生创建失败：显示稳定错误，无任何 S3M/点云 fallback 成功徽标', async () => {
    vi.mocked(client.createLegacyRhoRenderAsset).mockRejectedValue(
      new ApiError('RENDER_ASSET_CREATE_FAILED', 'NetCDF 资产创建失败', 500),
    )
    const wrapper = await mountView({ capability: supportedCapability() })
    // 失败后 GET 同步到持久化 failed 资产（含稳定错误码）：
    // once 链必须在挂载后的下一次 GET 才生效，初始 GET 保持 404
    vi.mocked(client.fetchLegacyRhoRenderAsset).mockResolvedValueOnce(LEGACY_FAILED_ASSET)

    await wrapper.find('[data-test="create-asset"]').trigger('click')
    await flushPromises()

    const createError = wrapper.find('[data-test="create-error"]')
    expect(createError.exists()).toBe(true)
    expect(createError.text()).toContain('RENDER_ASSET_CREATE_FAILED')
    const assetError = wrapper.find('[data-test="asset-error"]')
    expect(assetError.exists()).toBe(true)
    expect(assetError.text()).toContain('NETCDF_EXPORT_FAILED')

    // 失败不是成功：无渲染成功状态，也无任何 S3M/点云替代成功徽标
    expect(wrapper.find('[data-test="volume-phase"]').text()).not.toContain('已渲染')
    const text = wrapper.text()
    expect(text).not.toMatch(/体元缓存已加载|S3M 体元缓存加载成功|iServer 场景已加载/)
    expect(wrapper.find('.el-alert--success').exists()).toBe(false)
  })

  it('旧 iServer volume.available=true 不决定 NetCDF 资产成功：无登记网格仍不支持原生体渲染', async () => {
    const wrapper = await mountView({
      capability: missingGridCapability(TRANSFORM),
      volumeAvailable: true,
    })

    // 原生能力只认 render-capability GET：不支持即无创建入口
    expect(wrapper.find('[data-test="unsupported-reason"]').text()).toContain(
      'LEGACY_RENDER_SOURCE_NOT_REGISTERED',
    )
    expect(wrapper.find('[data-test="create-asset"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="volume-phase"]').text()).toContain('不支持体渲染')

    // 旧 S3M 发布可用性只作为历史证据展示，绝不渲染为成功徽标
    // （el-alert 根节点被 transition-stub 包裹，类断言落在内部 .el-alert 上）
    const s3m = wrapper.find('[data-test="s3m-evidence"]')
    expect(s3m.exists()).toBe(true)
    expect(s3m.text()).toContain('历史 S3M 发布证据')
    const s3mAlert = s3m.find('.el-alert')
    expect(s3mAlert.classes()).toContain('el-alert--info')
    expect(s3mAlert.classes()).not.toContain('el-alert--success')

    // 旧标签全部改名：页面上不再出现「体元缓存 / S3M 体元渲染 / 体元格」
    const text = wrapper.text()
    expect(text).not.toContain('体元缓存')
    expect(text).not.toContain('S3M 体元渲染')
    expect(text).not.toContain('体元格')
    expect(text).toContain('采样点')
  })

  it('未登记：显示导入入口；上传登记成功后转为可生成资产流程', async () => {
    vi.mocked(client.importLegacyRhoRenderSource).mockResolvedValue(REGISTRATION)
    const wrapper = await mountView({ capability: missingGridCapability(TRANSFORM) })

    // 未登记：显式导入入口，未选文件不可提交，且无创建资产入口
    const entry = wrapper.find('[data-test="legacy-import"]')
    expect(entry.exists()).toBe(true)
    expect(entry.text()).toContain('导入权威规则网格')
    expect(wrapper.find('[data-test="legacy-import-submit"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-test="create-asset"]').exists()).toBe(false)
    expect(client.importLegacyRhoRenderSource).not.toHaveBeenCalled()

    const file = await chooseImportFile(wrapper)
    // 登记成功后：capability GET 翻转为 supported（面板重挂载走既有流程）
    vi.mocked(client.fetchLegacyRhoRenderCapability).mockResolvedValue(supportedCapability())
    await wrapper.find('[data-test="legacy-import-submit"]').trigger('click')
    await flushPromises()

    // 列名/属性名/单位显式传入（默认 X/Y/Z/RHO）
    expect(client.importLegacyRhoRenderSource).toHaveBeenCalledWith(file, {
      xColumn: 'X',
      yColumn: 'Y',
      zColumn: 'Z',
      valueColumn: 'RHO',
      propertyName: 'RHO',
      units: 'unknown',
    })

    // 入口不再显示，展示已登记身份；面板转为可生成资产
    expect(wrapper.find('[data-test="legacy-import"]').exists()).toBe(false)
    const identity = wrapper.find('[data-test="legacy-import-identity"]')
    expect(identity.exists()).toBe(true)
    expect(identity.text()).toContain('resistivity')
    expect(wrapper.find('[data-test="legacy-import-error"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="create-asset"]').exists()).toBe(true)
  })

  it('导入失败：显示稳定错误码诊断，入口保留且绝不出现创建按钮', async () => {
    vi.mocked(client.importLegacyRhoRenderSource).mockRejectedValue(
      new ApiError(
        'LEGACY_IMPORT_GRID_INCOMPLETE',
        'legacy 网格缺失笛卡尔格点：每个格点必须恰好一行',
        422,
      ),
    )
    const wrapper = await mountView({ capability: missingGridCapability(TRANSFORM) })
    await chooseImportFile(wrapper)
    const capabilityCalls = vi.mocked(client.fetchLegacyRhoRenderCapability).mock.calls.length

    await wrapper.find('[data-test="legacy-import-submit"]').trigger('click')
    await flushPromises()

    const error = wrapper.find('[data-test="legacy-import-error"]')
    expect(error.exists()).toBe(true)
    expect(error.text()).toContain('LEGACY_IMPORT_GRID_INCOMPLETE')
    // 入口保留可重试；绝不显示登记身份，也绝不翻转为可生成资产
    expect(wrapper.find('[data-test="legacy-import"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="legacy-import-identity"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="create-asset"]').exists()).toBe(false)
    // 失败不触发能力重取（面板保持未登记状态）
    expect(vi.mocked(client.fetchLegacyRhoRenderCapability).mock.calls.length).toBe(capabilityCalls)
  })
})
