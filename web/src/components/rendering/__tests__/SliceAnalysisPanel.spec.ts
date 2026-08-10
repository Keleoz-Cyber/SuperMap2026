import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type { SliceAnalysisResponse, SliceAxis } from '../../../api/types'
import SliceAnalysisPanel from '../SliceAnalysisPanel.vue'

// v0.7.0 Batch 2 Task 10/11：剖面分析面板（目标驱动 + 最新请求获胜）。

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function makeResponse(axis: SliceAxis, index: number, coordinate: number): SliceAnalysisResponse {
  return {
    asset_identity: {
      asset_id: 'nc-1',
      source_kind: 'candidate_result',
      source_id: 'r1',
      grid_sha256: 'g'.repeat(64),
      netcdf_sha256: 'n'.repeat(64),
    },
    property: { name: 'Vx', unit: 'km/s' },
    axes: {
      x: { length: 2, coordinates: [0, 100], unit: 'm' },
      y: { length: 3, coordinates: [0, 10, 20], unit: 'm' },
      z: { length: 4, coordinates: [0, 1, 2, 3], unit: 'm' },
    },
    slice: {
      fixed_axis: axis,
      index,
      coordinate,
      sdk_relative_position: index / 3,
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

function makeApi() {
  return {
    fetchSliceAnalysis: vi.fn(),
    createSliceExport: vi.fn().mockResolvedValue({ id: 'exp-1' }),
  }
}

const HeatmapStub = {
  name: 'SliceHeatmap',
  template: '<div data-test="slice-heatmap-stub" />',
  methods: {
    capturePng: () => Promise.resolve(new Blob(['png'], { type: 'image/png' })),
  },
}

const AXES_META = {
  x: { length: 2, coordinates: [0, 100], unit: 'm' },
  y: { length: 3, coordinates: [0, 10, 20], unit: 'm' },
  z: { length: 4, coordinates: [0, 1, 2, 3], unit: 'm' },
}

function mountPanel(
  api: ReturnType<typeof makeApi>,
  target: { axis: SliceAxis; index: number } | null,
  axesMeta: typeof AXES_META | null = AXES_META,
) {
  return mount(SliceAnalysisPanel, {
    props: { api, assetId: 'nc-1', target, axesMeta, enabled: true },
    global: { plugins: [ElementPlus], stubs: { SliceHeatmap: HeatmapStub } },
    attachTo: document.body,
  })
}

describe('SliceAnalysisPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('无轴元数据时先 z/0 引导并上报 axes-meta-loaded', async () => {
    const api = makeApi()
    api.fetchSliceAnalysis.mockResolvedValue(makeResponse('z', 0, 0))
    const wrapper = mountPanel(api, { axis: 'z', index: 1 }, null)
    await flushPromises()
    expect(api.fetchSliceAnalysis).toHaveBeenCalledWith('nc-1', 'z', 0)
    const meta = wrapper.emitted('axes-meta-loaded')
    expect(meta).toBeTruthy()
    expect(meta![0][0]).toEqual(AXES_META)
  })

  it('目标到达即请求并展示统计，上报 analysis-loaded', async () => {
    const api = makeApi()
    api.fetchSliceAnalysis.mockResolvedValue(makeResponse('z', 1, 1))
    const wrapper = mountPanel(api, { axis: 'z', index: 1 })
    await flushPromises()
    expect(api.fetchSliceAnalysis).toHaveBeenCalledWith('nc-1', 'z', 1)
    expect(wrapper.find('[data-test="slice-valid-count"]').text()).toContain('5')
    expect(wrapper.find('[data-test="slice-coordinate-label"]').text()).toContain('Z = 1')
    expect(wrapper.emitted('analysis-loaded')).toBeTruthy()
  })

  it('竞态：stale 成功/失败均不得污染当前目标状态', async () => {
    const api = makeApi()
    api.fetchSliceAnalysis.mockResolvedValue(makeResponse('z', 1, 1))
    const wrapper = mountPanel(api, { axis: 'z', index: 1 })
    await flushPromises()

    const x1 = deferred<SliceAnalysisResponse>()
    const y2 = deferred<SliceAnalysisResponse>()
    api.fetchSliceAnalysis.mockImplementation((_id: string, axis: SliceAxis) =>
      axis === 'x' ? x1.promise : y2.promise,
    )
    await wrapper.setProps({ target: { axis: 'x', index: 1 } })
    await wrapper.setProps({ target: { axis: 'y', index: 1 } })
    y2.resolve(makeResponse('y', 1, 20))
    x1.reject(new Error('stale failure'))
    await flushPromises()
    expect(wrapper.text()).toContain('Y = 20 m')
    expect(wrapper.find('[data-test="slice-error"]').exists()).toBe(false)
  })

  it('目标切换后导出禁用直到匹配响应到达', async () => {
    const api = makeApi()
    api.fetchSliceAnalysis.mockResolvedValue(makeResponse('z', 1, 1))
    const wrapper = mountPanel(api, { axis: 'z', index: 1 })
    await flushPromises()
    expect(wrapper.get('[data-test="export-slice"]').attributes('disabled')).toBeUndefined()

    const pending = deferred<SliceAnalysisResponse>()
    api.fetchSliceAnalysis.mockImplementation(() => pending.promise)
    await wrapper.setProps({ target: { axis: 'x', index: 0 } })
    expect(wrapper.get('[data-test="export-slice"]').attributes('disabled')).toBeDefined()
    pending.resolve(makeResponse('x', 0, 0))
    await flushPromises()
    expect(wrapper.get('[data-test="export-slice"]').attributes('disabled')).toBeUndefined()
  })

  it('全 NoData 剖面是有效结果：计数为 0 且统计为 —', async () => {
    const api = makeApi()
    const empty = makeResponse('z', 1, 1)
    empty.statistics = {
      total_count: 6,
      valid_count: 0,
      nodata_count: 6,
      min: null,
      max: null,
      mean: null,
      std_population: null,
      p10: null,
      p50: null,
      p90: null,
      low_count: null,
      normal_count: null,
      high_count: null,
      low_ratio: null,
      normal_ratio: null,
      high_ratio: null,
      thresholds: null,
    }
    api.fetchSliceAnalysis.mockResolvedValue(empty)
    const wrapper = mountPanel(api, { axis: 'z', index: 1 })
    await flushPromises()
    expect(wrapper.find('[data-test="slice-valid-count"]').text()).toContain('0')
    expect(wrapper.find('[data-test="slice-error"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('—')
  })

  it('导出携带当前目标的轴/索引与 PNG，成功后跳转下载', async () => {
    const api = makeApi()
    api.fetchSliceAnalysis.mockResolvedValue(makeResponse('z', 1, 1))
    const wrapper = mountPanel(api, { axis: 'z', index: 1 })
    await flushPromises()
    const assignSpy = vi.fn()
    Object.defineProperty(window, 'location', {
      value: { assign: assignSpy, origin: window.location.origin },
      configurable: true,
    })
    await wrapper.get('[data-test="export-slice"]').trigger('click')
    await flushPromises()
    expect(api.createSliceExport).toHaveBeenCalledWith('nc-1', 'z', 1, expect.any(Blob))
    expect(assignSpy).toHaveBeenCalledWith('/api/exports/exp-1/download')
  })
})
