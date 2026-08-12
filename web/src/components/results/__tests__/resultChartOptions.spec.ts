import { describe, expect, it } from 'vitest'
import type { ResultComponentPreview, ResultDepthBin } from '../../../api/types'
import {
  buildComponentOption,
  buildDepthTrendOption,
  formatCompactNumber,
  formatDepthRange,
} from '../resultChartOptions'

const DEPTH_BINS: ResultDepthBin[] = [
  {
    z_lower: -833.0047143,
    z_upper: -731.3291125125,
    valid_count: 12,
    mean: 32.51888470611583,
    high_count: 5,
    high_ratio: 0.4389233954451346,
  },
]

const COMPONENTS: ResultComponentPreview[] = [
  {
    rank: 1,
    label: 'A',
    component_id: 1,
    support_node_count: 100,
    support_measure: 6_899_061.565,
    support_unit: 'volume_coordinate_unit3',
    bounds: [[-150, -80], [260, 580], [-800, -200]],
    centroid: [-100.463, 441.015, -85.795],
    value_min: 27.647,
    value_max: 133.097,
    value_mean: 61.2,
    touches_grid_boundary: true,
  },
]

describe('成果分析图表合同', () => {
  it('双轴图只由左轴绘制水平网格线，避免左右刻度错线', () => {
    const depth = buildDepthTrendOption(DEPTH_BINS, 'Ω·m') as any
    const components = buildComponentOption(COMPONENTS, 'Ω·m') as any

    expect(depth.yAxis[0].splitLine.show).toBe(true)
    expect(depth.yAxis[1].splitLine.show).toBe(false)
    expect(components.yAxis[0].splitLine.show).toBe(true)
    expect(components.yAxis[1].splitLine.show).toBe(false)
  })

  it('图表包含完整标签并把大数值转换为可读单位', () => {
    const option = buildComponentOption(COMPONENTS, 'Ω·m') as any
    expect(option.grid.containLabel).toBe(true)
    expect(option.yAxis[0].axisLabel.formatter(6_899_061.565)).toBe('689.9万')
    expect(formatCompactNumber(1_910_509.357)).toBe('191.1万')
  })

  it('深度、占比和提示数据使用面向用户的精度', () => {
    const option = buildDepthTrendOption(DEPTH_BINS, 'Ω·m') as any
    expect(option.xAxis.data).toEqual(['-833.0～-731.3 m'])
    expect(option.yAxis[0].axisLabel.formatter(0.4389233954451346)).toBe('44%')
    expect(option.yAxis[1].axisLabel.formatter(32.51888470611583)).toBe('32.5')
    expect(formatDepthRange(-833.0047143, -731.3291125125)).toBe('-833.0～-731.3 m')
  })
})
