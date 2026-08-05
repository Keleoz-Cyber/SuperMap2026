import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import type { SliceAnalysisResponse, SliceAxis } from '../../../api/types'
import SliceAnalysisPanel from '../SliceAnalysisPanel.vue'

// v0.7.0 Batch 2 Task 10：剖面分析面板（最新请求获胜 + 统计 + 导出流）。

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

function mountPanel(api: ReturnType<typeof makeApi>) {
  return mount(SliceAnalysisPanel, {
    props: { api, assetId: 'nc-1', axisMeta: null, enabled: true },
    global: { plugins: [ElementPlus], stubs: { SliceHeatmap: HeatmapStub } },
    attachTo: document.body,
  })
}

describe('SliceAnalysisPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('首次进入切片模式：bootstrap z/0 → 轴元数据 → z/中位索引 → 显示统计并发出 analysis-loaded', async () => {
    const api = makeApi()
    const boot = makeResponse('z', 0, 0)
    const middle = makeResponse('z', 1, 1)
    api.fetchSliceAnalysis
      .mockResolvedValueOnce(boot)
      .mockResolvedValueOnce(middle)
    const wrapper = mountPanel(api)
    await wrapper.find('[data-test="enter-slice-mode"]').trigger('click')
    await flushPromises()
    expect(api.fetchSliceAnalysis).toHaveBeenCalledTimes(2)
    expect(api.fetchSliceAnalysis).toHaveBeenNthCalledWith(1, 'nc-1', 'z', 0)
    expect(api.fetchSliceAnalysis).toHaveBeenNthCalledWith(2, 'nc-1', 'z', 1)
    expect(wrapper.find('[data-test="slice-valid-count"]').text()).toContain('5')
    expect(wrapper.find('[data-test="slice-coordinate-label"]').text()).toContain('Z = 1')
    const loaded = wrapper.emitted('analysis-loaded')
    expect(loaded).toBeTruthy()
    expect((loaded![0][0] as SliceAnalysisResponse).slice.sdk_relative_position).toBeCloseTo(1 / 3)
  })

  it('竞态：stale 成功/失败/finally 均不得污染当前状态', async () => {
    const api = makeApi()
    api.fetchSliceAnalysis.mockResolvedValueOnce(makeResponse('z', 0, 0)).mockResolvedValueOnce(makeResponse('z', 1, 1))
    const wrapper = mountPanel(api)
    await wrapper.find('[data-test="enter-slice-mode"]').trigger('click')
    await flushPromises()

    const x1 = deferred<SliceAnalysisResponse>()
    const y2 = deferred<SliceAnalysisResponse>()
    api.fetchSliceAnalysis.mockImplementation((_assetId: string, axis: SliceAxis) =>
      axis === 'x' ? x1.promise : y2.promise,
    )
    await wrapper.find('[data-test="axis-x"]').trigger('click')
    await wrapper.find('[data-test="axis-y"]').trigger('click')
    y2.resolve(makeResponse('y', 1, 20))
    x1.reject(new Error('stale failure'))
    await flushPromises()
    expect(wrapper.text()).toContain('Y = 20 m')
    expect(wrapper.find('[data-test="slice-error"]').exists()).toBe(false)

    // stale 成功也不得覆盖
    const z3 = deferred<SliceAnalysisResponse>()
    const x4 = deferred<SliceAnalysisResponse>()
    api.fetchSliceAnalysis.mockImplementation((_assetId: string, axis: SliceAxis) =>
      axis === 'x' ? x4.promise : z3.promise,
    )
    await wrapper.find('[data-test="axis-z"]').trigger('click')
    await wrapper.find('[data-test="axis-x"]').trigger('click')
    x4.resolve(makeResponse('x', 1, 100))
    z3.resolve(makeResponse('z', 2, 2))
    await flushPromises()
    expect(wrapper.text()).toContain('X = 100 m')
    expect(wrapper.text()).not.toContain('Z = 2 m')
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
    }
    api.fetchSliceAnalysis
      .mockResolvedValueOnce(makeResponse('z', 0, 0))
      .mockResolvedValueOnce(empty)
    const wrapper = mountPanel(api)
    await wrapper.find('[data-test="enter-slice-mode"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="slice-valid-count"]').text()).toContain('0')
    expect(wrapper.find('[data-test="slice-error"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('—')
  })

  it('导出仅在已加载身份与当前选择一致时可用；成功后跳转下载', async () => {
    const api = makeApi()
    api.fetchSliceAnalysis
      .mockResolvedValueOnce(makeResponse('z', 0, 0))
      .mockResolvedValueOnce(makeResponse('z', 1, 1))
    const wrapper = mountPanel(api)
    await wrapper.find('[data-test="enter-slice-mode"]').trigger('click')
    await flushPromises()
    const exportButton = wrapper.get('[data-test="export-slice"]')
    expect(exportButton.attributes('disabled')).toBeUndefined()
    const assignSpy = vi.fn()
    Object.defineProperty(window, 'location', {
      value: { assign: assignSpy, origin: window.location.origin },
      configurable: true,
    })
    await exportButton.trigger('click')
    await flushPromises()
    expect(api.createSliceExport).toHaveBeenCalledWith('nc-1', 'z', 1, expect.any(Blob))
    expect(assignSpy).toHaveBeenCalledWith('/api/exports/exp-1/download')
  })

  it('切换选择后导出禁用直到新响应到达', async () => {
    const api = makeApi()
    api.fetchSliceAnalysis
      .mockResolvedValueOnce(makeResponse('z', 0, 0))
      .mockResolvedValueOnce(makeResponse('z', 1, 1))
    const wrapper = mountPanel(api)
    await wrapper.find('[data-test="enter-slice-mode"]').trigger('click')
    await flushPromises()

    const pending = deferred<SliceAnalysisResponse>()
    api.fetchSliceAnalysis.mockImplementation(() => pending.promise)
    await wrapper.find('[data-test="axis-x"]').trigger('click')
    expect(wrapper.get('[data-test="export-slice"]').attributes('disabled')).toBeDefined()
    pending.resolve(makeResponse('x', 0, 0))
    await flushPromises()
    expect(wrapper.get('[data-test="export-slice"]').attributes('disabled')).toBeUndefined()
  })
})
