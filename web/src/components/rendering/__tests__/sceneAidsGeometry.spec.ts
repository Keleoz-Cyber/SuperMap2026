import { describe, expect, it } from 'vitest'
import {
  AXIS_LENGTH_RATIO,
  computeSceneAidsGeometry,
} from '../../../../public/supermap-volume-frame/sceneAidsGeometry.js'

// v0.9.0 V6 Task 5：XYZ 坐标架几何合同。
// 原点位于包围盒外（west/south/bottom 三向同时外移）；三轴可见长度为对应
// 包围盒跨度的 1.2–1.3 倍；深度刻度为独立 Z 标尺（不复用包围盒边/不贴轴端）。
// 只改变显示位置，不改变数据坐标。

const BOUNDS = { west: 120.0, south: 30.0, east: 120.02, north: 30.03 }
const Z_BOUNDS: [number, number] = [-840, 0]

describe('sceneAidsGeometry（V6 坐标架）', () => {
  it('原点三向位于包围盒外，轴长比锁定 1.2–1.3', () => {
    const geo = computeSceneAidsGeometry(BOUNDS, Z_BOUNDS, 0)
    // 原点外移：west/south/bottom 同时超出包围盒
    expect(geo.originOutsideBounds).toBe(true)
    expect(geo.origin[0]).toBeLessThan(BOUNDS.west)
    expect(geo.origin[1]).toBeLessThan(BOUNDS.south)
    expect(geo.origin[2]).toBeLessThan(Z_BOUNDS[0])
    // 轴长 = 对应跨度 × 1.2–1.3
    expect(geo.axisLengthRatios.x).toBeGreaterThanOrEqual(1.2)
    expect(geo.axisLengthRatios.x).toBeLessThanOrEqual(1.3)
    expect(geo.axisLengthRatios.y).toBeGreaterThanOrEqual(1.2)
    expect(geo.axisLengthRatios.y).toBeLessThanOrEqual(1.3)
    expect(geo.axisLengthRatios.z).toBeGreaterThanOrEqual(1.2)
    expect(geo.axisLengthRatios.z).toBeLessThanOrEqual(1.3)
    // 轴端坐标与跨度一致（度轴用度跨，Z 轴用米跨）
    const lonSpan = BOUNDS.east - BOUNDS.west
    const zSpan = Z_BOUNDS[1] - Z_BOUNDS[0]
    expect(geo.axes.x.to[0] - geo.axes.x.from[0]).toBeCloseTo(lonSpan * AXIS_LENGTH_RATIO, 10)
    expect(geo.axes.z.to[2] - geo.axes.z.from[2]).toBeCloseTo(zSpan * AXIS_LENGTH_RATIO, 10)
  })

  it('深度刻度为独立 Z 标尺：不复用包围盒边且标签为局部坐标', () => {
    const geo = computeSceneAidsGeometry(BOUNDS, Z_BOUNDS, 0)
    expect(geo.depthTicks.length).toBe(5)
    // 刻度线沿 -Y 独立偏移（不与 Z 轴同位，也不在包围盒 south 边上）
    const tickLat = geo.depthTicks[0].position[1]
    expect(tickLat).toBeLessThan(geo.origin[1])
    // 标签展示局部 z 值（display 高度 − anchorHeight）
    expect(geo.depthTicks[0].localZ).toBeCloseTo(Z_BOUNDS[0], 6)
    expect(geo.depthTicks[4].localZ).toBeCloseTo(Z_BOUNDS[1], 6)
    // anchorHeight 参与局部值换算
    const shifted = computeSceneAidsGeometry(BOUNDS, Z_BOUNDS, 100)
    expect(shifted.depthTicks[0].localZ).toBeCloseTo(Z_BOUNDS[0] - 100, 6)
  })

  it('非正跨度 fail-closed', () => {
    expect(() =>
      computeSceneAidsGeometry({ west: 1, south: 2, east: 1, north: 3 }, [0, 1], 0),
    ).toThrow()
    expect(() => computeSceneAidsGeometry(BOUNDS, [5, 5], 0)).toThrow()
  })
})
