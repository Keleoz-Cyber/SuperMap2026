import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { SliceAnalysisResponse } from '../../../api/types'

// v0.7.0 Batch 2 Task 10：ECharts 剖面热力图（模块边界 mock echarts）。

const chartInstances: FakeChart[] = []

interface FakeChart {
  setOption: ReturnType<typeof vi.fn>
  resize: ReturnType<typeof vi.fn>
  dispose: ReturnType<typeof vi.fn>
  getDataURL: ReturnType<typeof vi.fn>
  on: ReturnType<typeof vi.fn>
}

vi.mock('echarts/core', () => ({
  init: vi.fn(() => {
    const instance: FakeChart = {
      setOption: vi.fn(),
      resize: vi.fn(),
      dispose: vi.fn(),
      getDataURL: vi.fn(() => 'data:image/png;base64,ZmFrZQ=='),
      on: vi.fn(),
    }
    chartInstances.push(instance)
    return instance
  }),
  use: vi.fn(),
}))
vi.mock('echarts/charts', () => ({ HeatmapChart: {} }))
vi.mock('echarts/components', () => ({
  GridComponent: {},
  TooltipComponent: {},
  VisualMapComponent: {},
}))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

import SliceHeatmap from '../SliceHeatmap.vue'

function makeAnalysis(): SliceAnalysisResponse {
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
      fixed_axis: 'z',
      index: 1,
      coordinate: 1,
      sdk_relative_position: 1 / 3,
      row_axis: 'y',
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

describe('SliceHeatmap', () => {
  beforeEach(() => {
    chartInstances.length = 0
  })

  it('按行/列坐标构建热力图，原始值入数据（不做零填充）', async () => {
    mount(SliceHeatmap, {
      props: { analysis: makeAnalysis(), palette: 'viridis', scale: 'linear' },
      attachTo: document.body,
    })
    await flushPromises()
    expect(chartInstances).toHaveLength(1)
    const option = chartInstances[0].setOption.mock.calls[0][0]
    expect(option.xAxis.data).toEqual(['0', '100'])
    expect(option.yAxis.data).toEqual(['0', '10', '20'])
    // series 数据：[col, row, displayValue, rawValue]；NoData 的 raw 为 null
    const points = option.series[0].data
    expect(points).toHaveLength(6)
    const nodataPoint = points.find((p: unknown[]) => p[0] === 1 && p[1] === 1)
    expect(nodataPoint[3]).toBeNull()
    const rawPoint = points.find((p: unknown[]) => p[0] === 1 && p[1] === 2)
    expect(rawPoint[3]).toBe(121)
  })

  it('tooltip 显示双平面坐标、固定轴坐标、原始值与单位；NoData 不显示 0', async () => {
    mount(SliceHeatmap, {
      props: { analysis: makeAnalysis(), palette: 'viridis', scale: 'linear' },
      attachTo: document.body,
    })
    await flushPromises()
    const option = chartInstances[0].setOption.mock.calls[0][0]
    const format = option.tooltip.formatter
    const valid = format({ data: [1, 2, 0.8, 121] })
    expect(valid).toContain('100')
    expect(valid).toContain('20')
    expect(valid).toContain('Z = 1')
    expect(valid).toContain('121')
    expect(valid).toContain('km/s')
    const nodata = format({ data: [1, 1, 0, null] })
    expect(nodata).toContain('NoData')
    expect(nodata).not.toContain('>0<')
  })

  it('resize 转发到底层图表；卸载时 dispose', async () => {
    const wrapper = mount(SliceHeatmap, {
      props: { analysis: makeAnalysis(), palette: 'viridis', scale: 'linear' },
      attachTo: document.body,
    })
    await flushPromises()
    window.dispatchEvent(new Event('resize'))
    await flushPromises()
    expect(chartInstances[0].resize).toHaveBeenCalled()
    wrapper.unmount()
    expect(chartInstances[0].dispose).toHaveBeenCalled()
  })

  it('capturePng 返回 image/png Blob', async () => {
    const wrapper = mount(SliceHeatmap, {
      props: { analysis: makeAnalysis(), palette: 'viridis', scale: 'linear' },
      attachTo: document.body,
    })
    await flushPromises()
    const api = wrapper.vm as unknown as { capturePng: () => Promise<Blob> }
    const blob = await api.capturePng()
    expect(blob).toBeInstanceOf(Blob)
    expect(blob.type).toBe('image/png')
  })

  it('颜色由 itemStyle 按 display 归一化维度映射：不同值必须不同色，visualMap 不参与着色', async () => {
    mount(SliceHeatmap, {
      props: { analysis: makeAnalysis(), palette: 'viridis', scale: 'linear' },
      attachTo: document.body,
    })
    await flushPromises()
    const option = chartInstances[0].setOption.mock.calls[0][0]
    // ECharts dev 模式要求 heatmap 注册 visualMap；这里允许一个隐藏且
    // inRange 为空的占位配置，但禁止它覆盖 itemStyle 的真实颜色映射。
    expect(option.visualMap).toMatchObject({
      show: false,
      seriesIndex: 0,
      dimension: 2,
      inRange: {},
    })
    const color = option.series[0].itemStyle.color
    // 同一切片内多个不同值 → 不同颜色（display 已归一化，直接驱动分段）
    const low = color({ data: [0, 0, 0.0, 1] })
    const mid = color({ data: [0, 1, 0.45, 61] })
    const high = color({ data: [1, 2, 1.0, 121] })
    expect(new Set([low, mid, high]).size).toBe(3)
  })

  it('色带值域锁定全体数据 render_profile.value_range：切片统计不同不影响同色值', async () => {
    const profile = {
      property_name: 'Vx',
      unit: 'km/s',
      default_scale: 'linear' as const,
      default_palette: 'viridis' as const,
      log_available: true,
      value_range: [0, 200] as [number, number],
      filter_range: [0, 200] as [number, number],
      lighting: true,
      gradient_opacity: true,
      bounding_box: true,
      opacity: 1,
    }
    const a = makeAnalysis()
    a.render_profile = profile
    const wrapperA = mount(SliceHeatmap, {
      props: { analysis: a, palette: 'viridis', scale: 'linear' },
      attachTo: document.body,
    })
    await flushPromises()
    const colorA = chartInstances[0].setOption.mock.calls[0][0].series[0].itemStyle.color(
      { data: [1, 2, 0.605, 121] },
    )
    wrapperA.unmount()

    // 另一切片（不同索引/不同逐片统计），同一全体值域：raw=121 必须同色
    const b = makeAnalysis()
    b.render_profile = profile
    b.slice = { ...b.slice, index: 2, coordinate: 2 }
    b.statistics = { ...b.statistics, min: 10, max: 100 }
    mount(SliceHeatmap, {
      props: { analysis: b, palette: 'viridis', scale: 'linear' },
      attachTo: document.body,
    })
    await flushPromises()
    const colorB = chartInstances[1].setOption.mock.calls[0][0].series[0].itemStyle.color(
      { data: [1, 2, 0.605, 121] },
    )
    expect(colorB).toBe(colorA)
  })

  it('切换切片索引：数据随真实值变化，颜色随之变化', async () => {
    const a = makeAnalysis()
    mount(SliceHeatmap, { props: { analysis: a, palette: 'viridis', scale: 'linear' }, attachTo: document.body })
    await flushPromises()
    const optionA = chartInstances[0].setOption.mock.calls[0][0]

    const b = makeAnalysis()
    b.slice = { ...b.slice, index: 3, coordinate: 3 }
    b.slice.values = [
      [5, 15],
      [25, null],
      [35, 45],
    ]
    mount(SliceHeatmap, { props: { analysis: b, palette: 'viridis', scale: 'linear' }, attachTo: document.body })
    await flushPromises()
    const optionB = chartInstances[1].setOption.mock.calls[0][0]
    // 数据确实变化
    expect(optionB.series[0].data).not.toEqual(optionA.series[0].data)
    // 同一单元格（0,0）：raw 1（值域底部）vs 121（顶部）→ 颜色不同
    const colorA = optionA.series[0].itemStyle.color({ data: [0, 0, 0, 1] })
    const colorB = optionB.series[0].itemStyle.color({ data: [0, 0, 1, 121] })
    expect(colorB).not.toBe(colorA)
  })

  it('NoData 使用灰化标记色，绝不占用色带颜色、不伪装成有效值', async () => {
    mount(SliceHeatmap, {
      props: { analysis: makeAnalysis(), palette: 'viridis', scale: 'linear' },
      attachTo: document.body,
    })
    await flushPromises()
    const option = chartInstances[0].setOption.mock.calls[0][0]
    const color = option.series[0].itemStyle.color
    const nodataColor = color({ data: [1, 1, 0, null] })
    expect(nodataColor).toBe('rgba(120, 130, 145, 0.35)')
    // 与任何有效值颜色不同
    const validColor = color({ data: [0, 0, 0, 1] })
    expect(nodataColor).not.toBe(validColor)
  })
})
