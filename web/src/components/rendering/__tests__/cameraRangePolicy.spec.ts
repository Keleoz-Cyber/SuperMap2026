import { describe, expect, it } from 'vitest'
import {
  cameraRangeBounds,
  clampCameraRange,
  nextWheelCameraRange,
} from '../../../../public/supermap-volume-frame/cameraRangePolicy.js'

describe('cameraRangePolicy', () => {
  it('以成果最大物理跨度生成可见安全区间', () => {
    expect(cameraRangeBounds(100)).toEqual([90, 450])
    expect(() => cameraRangeBounds(0)).toThrow()
  })

  it('单次滚轮只改变约 8%，并在安全区间内限幅', () => {
    expect(nextWheelCameraRange(212, 100, -120)).toBeCloseTo(212 / 1.08)
    expect(nextWheelCameraRange(212, 100, 120)).toBeCloseTo(212 * 1.08)
    expect(nextWheelCameraRange(91, 100, -120)).toBe(90)
    expect(nextWheelCameraRange(449, 100, 120)).toBe(450)
  })

  it('导航缩放条产生的越界距离会被拉回，不允许体数据消失', () => {
    expect(clampCameraRange(1, 100)).toBe(90)
    expect(clampCameraRange(1000, 100)).toBe(450)
    expect(clampCameraRange(212, 100)).toBe(212)
  })
})
