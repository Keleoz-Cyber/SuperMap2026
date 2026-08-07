import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type {
  DatasetPoints,
  DisplayTransform,
  ExportRecord,
  ExperimentRecord,
  FormalSelectionRecord,
  PublicationRecord,
  RenderAssetRecord,
  RenderCapability,
  ResultMetadata,
  ResultPreview,
  SliceResponse,
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
    fetchResultRenderCapability: vi.fn(),
    fetchResultRenderAsset: vi.fn(),
    createResultRenderAsset: vi.fn(),
  }
})

const T = '2026-07-23T00:00:00Z'

function makeMetadata(dimension: '2d' | '3d'): ResultMetadata {
  return {
    result_id: 'r1',
    run_id: 'run1',
    experiment_id: 'exp1',
    dataset_version_id: 'ds1',
    algorithm: 'idw',
    parameters: { power: 2, neighbor_count: 8 },
    dimension,
    shape: dimension === '3d' ? [11, 11, 11] : [11, 11],
    cell_count: dimension === '3d' ? 1331 : 121,
    bounds: dimension === '3d' ? [[-150, -60], [260, 580], [-800, -200]] : [[-150, -60], [260, 580]],
    resolution: dimension === '3d' ? [9, 32, 60] : [9, 32],
    value_range: [1.4, 133.1],
    nodata_count: 0,
    grid_sha256: 'cd'.repeat(32),
    source_sha256: 'ab'.repeat(32),
    standardized_sha256: 'ab'.repeat(32),
    fingerprint: 'fp1',
    validation: { folds: 3 },
    created_at: T,
  }
}

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
    parameters: { power: 2 },
    validation: { method: 'spatial_kfold', folds: 3, seed: 1, holdout_fraction: 0.2 },
    grid: null,
  },
  created_at: T,
  updated_at: T,
}

const SLICE_2D: SliceResponse = {
  result_id: 'r1',
  fixed_axis: 'z',
  fixed_coordinate: 0,
  axes_names: ['x', 'y'],
  axes: [
    [-150, -141, -132],
    [260, 292, 324],
  ],
  matrix: [
    [10, 20, 30],
    [40, null, 60],
  ],
  nodata_mask: [
    [false, false, false],
    [false, true, false],
  ],
  value_range: [10, 60],
}

const POINTS: DatasetPoints = {
  dataset_id: 'ds1',
  dimension: '2d',
  count: 3,
  served: 3,
  decimate: 1,
  x: [-150, -141, -132],
  y: [260, 292, 324],
  z: null,
  values: [10, 50, 60],
  value_range: [10, 60],
  value_name: '电阻率',
  source_sha256: 'ab'.repeat(32),
}

const PREVIEW_3D: ResultPreview = {
  result_id: 'r1',
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
  source_id: 'r1',
  supported: true,
  reason_code: null,
  reason: null,
  dimension: '3d',
  grid_kind: 'regular',
  property_name: 'rho',
  units: 'unknown',
  geolocation_status: 'display_anchor_only',
  display_transform: TRANSFORM,
}

const ASSET_READY: RenderAssetRecord = {
  id: `nc-${'a'.repeat(32)}`,
  source_kind: 'candidate_result',
  source_id: 'r1',
  renderer: 'supermap_voxelgrid_netcdf',
  status: 'ready',
  grid_sha256: 'cd'.repeat(32),
  netcdf_sha256: 'ef'.repeat(32),
  manifest_url: `/api/render-assets/nc-${'a'.repeat(32)}/manifest`,
  netcdf_url: `/api/render-assets/nc-${'a'.repeat(32)}/volume.nc`,
  error: null,
}

const SELECTION: FormalSelectionRecord = {
  id: 'sel1',
  case_id: 'c1',
  candidate_result_id: 'r1',
  selected_by: 'tester',
  note: '公共验证 RMSE 最低',
  created_at: T,
}

const EXPORT: ExportRecord = {
  id: 'exp-zip1',
  candidate_result_id: 'r1',
  case_id: 'c1',
  package_sha256: 'ef'.repeat(32),
  file_count: 3,
  files: ['manifest.json', 'metadata.json', 'grid.csv'],
  manifest: {},
}

const PUBLICATION: PublicationRecord = {
  id: 'pub1',
  export_id: 'exp-zip1',
  status: 'manual_required',
  evidence: {
    export_id: 'exp-zip1',
    package: 'var/geomodeling/exports/exp-zip1.zip',
    manual_instruction: '请通过 iServer 管理界面手动发布导出的成果包',
    iserver_rest_publish_status: 'unsupported_on_this_build',
  },
}

async function mountWorkbench(metadata: ResultMetadata) {
  vi.mocked(client.materializeResult).mockResolvedValue(metadata)
  vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
  vi.mocked(client.fetchResultSlice).mockResolvedValue(SLICE_2D)
  vi.mocked(client.fetchResultPreview).mockResolvedValue(PREVIEW_3D)
  vi.mocked(client.fetchDatasetPoints).mockResolvedValue(POINTS)
  vi.mocked(client.fetchFormalSelections).mockResolvedValue({ case_id: 'c1', selections: [] })
  vi.mocked(client.fetchResultRenderCapability).mockResolvedValue(CAPABILITY_3D)
  vi.mocked(client.fetchResultRenderAsset).mockRejectedValue(
    new client.ApiError('RENDER_ASSET_NOT_FOUND', '该渲染源尚未创建渲染资产', 404),
  )
  vi.mocked(client.createResultRenderAsset).mockResolvedValue(ASSET_READY)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/experiments/:experimentId', name: 'experiment-detail', component: { template: '<div />' } },
      { path: '/results/:resultId', name: 'result-workbench', component: ResultWorkbenchView },
      { path: '/results/:resultId/professional', name: 'professional-analysis', component: { template: '<div />' } },
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

describe('ResultWorkbenchView', () => {
  it('3D：显式 POST materialize 一次，完整场 tab 使用 NativeVolumePanel', async () => {
    const { wrapper } = await mountWorkbench(makeMetadata('3d'))
    // 物化是唯一显式变异：POST 一次，绝不把 fetchResult 当创建捷径
    expect(client.materializeResult).toHaveBeenCalledTimes(1)
    expect(client.materializeResult).toHaveBeenCalledWith('r1')
    expect(client.fetchResult).not.toHaveBeenCalled()
    // 预览只在物化成功后获取
    expect(client.fetchResultPreview).toHaveBeenCalledTimes(1)
    expect(vi.mocked(client.materializeResult).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(client.fetchResultPreview).mock.invocationCallOrder[0],
    )

    // 完整场 tab = NativeVolumePanel；Field3D/Cesium 降级已移除
    expect(wrapper.find('[data-test="native-volume-panel"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="field-3d"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="cesium-fallback"]').exists()).toBe(false)
    // 未创建资产前无 iframe
    expect(wrapper.find('iframe').exists()).toBe(false)

    // 显式资产创建后挂载隔离 SuperMap iframe
    await wrapper.find('[data-test="create-asset"]').trigger('click')
    await flushPromises()
    expect(client.createResultRenderAsset).toHaveBeenCalledTimes(1)
    expect(client.createResultRenderAsset).toHaveBeenCalledWith('r1', false)
    const iframe = wrapper.find('iframe')
    expect(iframe.exists()).toBe(true)
    expect(iframe.attributes('src')).toContain('/supermap-volume-frame/index.html?request_id=')
  })

  it('2D：无 iframe、无原生体渲染面板，保留整场热力图切片行为', async () => {
    const { wrapper } = await mountWorkbench(makeMetadata('2d'))
    expect(client.materializeResult).toHaveBeenCalledTimes(1)
    expect(client.fetchResult).not.toHaveBeenCalled()
    expect(wrapper.find('[data-test="native-volume-panel"]').exists()).toBe(false)
    expect(wrapper.find('iframe').exists()).toBe(false)
    // 切片只在物化成功后获取，热力图与实测点叠加保持既有口径
    expect(client.fetchResultSlice).toHaveBeenCalledWith('r1', 'z', 0)
    expect(vi.mocked(client.materializeResult).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(client.fetchResultSlice).mock.invocationCallOrder[0],
    )
    expect(wrapper.find('[data-test="field-2d"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="overlay-count"]').text()).toContain('3')
    // 6 单元 1 NoData → 5 个有效图元
    expect(wrapper.find('[data-test="valid-cells"]').text()).toContain('5')
  })

  it('v0.7.0：成果工作台不再渲染 DAT 微震证据图层控制组', async () => {
    const { wrapper } = await mountWorkbench(makeMetadata('3d'))
    // DAT 派生探测与证据图层已退出产品面（客户端不再有对应 API）
    expect('fetchMicroseismicDerivation' in client).toBe(false)
    expect(wrapper.find('[data-test="evidence-layers"]').exists()).toBe(false)
  })

  it('正式选择必须填写理由', async () => {
    const { wrapper } = await mountWorkbench(makeMetadata('2d'))
    await wrapper.find('[data-test="selection-submit"]').trigger('click')
    await flushPromises()
    expect(client.selectFormal).not.toHaveBeenCalled()
    expect(wrapper.find('[data-test="selection-error"]').exists()).toBe(true)

    vi.mocked(client.selectFormal).mockResolvedValue(SELECTION)
    vi.mocked(client.fetchFormalSelections).mockResolvedValue({ case_id: 'c1', selections: [SELECTION] })
    await wrapper.find('[data-test="selection-note"]').setValue('公共验证 RMSE 最低')
    await wrapper.find('[data-test="selection-submit"]').trigger('click')
    await flushPromises()
    expect(client.selectFormal).toHaveBeenCalledWith('r1', '公共验证 RMSE 最低', undefined)
    expect(wrapper.text()).toContain('公共验证 RMSE 最低')
  })

  it('导出与发布状态相互独立', async () => {
    vi.mocked(client.createExport).mockResolvedValue(EXPORT)
    vi.mocked(client.createPublication).mockResolvedValue(PUBLICATION)
    const { wrapper } = await mountWorkbench(makeMetadata('2d'))

    expect(wrapper.find('[data-test="publication-status"]').text()).toContain('未请求')
    await wrapper.find('[data-test="export-button"]').trigger('click')
    await flushPromises()
    expect(client.createExport).toHaveBeenCalledWith('r1')
    const files = wrapper.findAll('[data-test="export-file"]')
    expect(files).toHaveLength(3)
    expect(files.map((f) => f.text())).toContain('manifest.json')
    // 导出成功不改变发布状态
    expect(wrapper.find('[data-test="publication-status"]').text()).toContain('未请求')

    await wrapper.find('[data-test="publish-button"]').trigger('click')
    await flushPromises()
    expect(client.createPublication).toHaveBeenCalledWith('r1')
    expect(wrapper.find('[data-test="publication-status"]').text()).toContain('manual_required')
    expect(wrapper.find('[data-test="publication-instruction"]').text()).toContain('手动发布')
  })

  it('专业分析入口保留并跳转专业分析台', async () => {
    const krigingMeta = makeMetadata('3d')
    krigingMeta.algorithm = 'ordinary_kriging'
    krigingMeta.professional_analysis_supported = true
    const { wrapper, router } = await mountWorkbench(krigingMeta)
    await wrapper.get('[data-test="professional-entry"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value).toMatchObject({
      name: 'professional-analysis',
      params: { resultId: 'r1' },
    })
  })
})

describe('导航', () => {
  it('成果页显示 nav-home 与 nav-experiment（精确实验 ID）', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'home', component: { template: '<div />' } },
        { path: '/experiments/:experimentId', name: 'experiment-detail', component: { template: '<div />' } },
        { path: '/results/:resultId', name: 'result-workbench', component: ResultWorkbenchView },
      ],
    })
    const metadata = makeMetadata('2d')
    vi.mocked(client.materializeResult).mockResolvedValue(metadata)
    vi.mocked(client.fetchExperiment).mockResolvedValue(EXP)
    vi.mocked(client.fetchResultSlice).mockResolvedValue(SLICE_2D)
    vi.mocked(client.fetchDatasetPoints).mockResolvedValue(POINTS)
    vi.mocked(client.fetchFormalSelections).mockResolvedValue({ case_id: 'c1', selections: [] })
    await router.push('/results/r1')
    const wrapper = mount(ResultWorkbenchView, { global: { plugins: [router, ElementPlus] } })
    await flushPromises()

    await wrapper.get('[data-test="nav-experiment"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value).toMatchObject({
      name: 'experiment-detail',
      params: { experimentId: 'exp1' },
    })

    await router.push('/results/r1')
    await flushPromises()
    await wrapper.get('[data-test="nav-home"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('home')
  })

  it('物化失败：显示错误页且不取切片/预览，仍能返回首页', async () => {
    vi.mocked(client.materializeResult).mockRejectedValue(
      new client.ApiError('CANDIDATE_NOT_FOUND', '不存在', 404),
    )
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'home', component: { template: '<div />' } },
        { path: '/results/:resultId', name: 'result-workbench', component: ResultWorkbenchView },
      ],
    })
    await router.push('/results/r-missing')
    const wrapper = mount(ResultWorkbenchView, { global: { plugins: [router, ElementPlus] } })
    await flushPromises()
    expect(wrapper.text()).toContain('成果加载失败')
    // 物化失败绝不继续取切片/预览
    expect(client.fetchResultSlice).not.toHaveBeenCalled()
    expect(client.fetchResultPreview).not.toHaveBeenCalled()
    await wrapper.get('[data-test="nav-home"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('home')
  })
})

describe('导出下载', () => {
  it('下载链接使用返回的 export id 而非 result id', async () => {
    vi.mocked(client.createExport).mockResolvedValue(EXPORT)
    const { wrapper } = await mountWorkbench(makeMetadata('2d'))
    await wrapper.find('[data-test="export-button"]').trigger('click')
    await flushPromises()
    const link = wrapper.get('[data-test="export-download"]')
    expect(link.attributes('href')).toBe(`/api/exports/${EXPORT.id}/download`)
    expect(link.attributes('href')).not.toContain('/r1/')
  })
})

describe('专业分析入口', () => {
  it('IDW 成果不显示专业分析入口，显示禁用原因', async () => {
    const { wrapper } = await mountWorkbench(makeMetadata('3d'))
    expect(wrapper.find('[data-test="professional-entry"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="professional-disabled"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('仅生成专业证据的成果支持专业分析')
  })

  it('Kriging 成果有专业证据时显示可点击入口', async () => {
    const krigingMeta = makeMetadata('3d')
    krigingMeta.algorithm = 'ordinary_kriging'
    krigingMeta.professional_analysis_supported = true
    const { wrapper } = await mountWorkbench(krigingMeta)
    expect(wrapper.find('[data-test="professional-entry"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="professional-disabled"]').exists()).toBe(false)
  })
})
