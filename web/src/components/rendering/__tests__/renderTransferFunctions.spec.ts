import { describe, expect, it } from 'vitest'
import {
  PALETTES,
  PALETTE_IDS,
  buildColorStops,
  normalizeForDisplay,
} from '../renderTransferFunctions'

// v0.7.0 Batch 2 Task 6：SuperMap 与 ECharts 共用的色带/标度纯函数。

describe('renderTransferFunctions', () => {
  it('五个固定色带 ID 与色值稳定', () => {
    expect(PALETTE_IDS).toEqual([
      'native-spectrum',
      'viridis',
      'turbo',
      'coolwarm',
      'grayscale',
    ])
    expect(PALETTES['native-spectrum']).toEqual([
      '#1a40d9',
      '#1acccc',
      '#f2d926',
      '#f2591a',
      '#a60d1a',
    ])
    expect(PALETTES.viridis[0]).toBe('#440154')
    expect(PALETTES.turbo).toHaveLength(5)
    expect(PALETTES.coolwarm).toHaveLength(5)
    expect(PALETTES.grayscale[4]).toBe('#ffffff')
  })

  it('maps linear and log values without changing raw values', () => {
    const linear = buildColorStops('viridis', 'linear', [1, 1000])
    const log = buildColorStops('viridis', 'log', [1, 1000])
    expect(linear.map((s) => s.value)).toEqual([1, 250.75, 500.5, 750.25, 1000])
    expect(log.map((s) => s.value)).toHaveLength(5)
    expect(log[0].value).toBe(1)
    expect(log[1].value).toBeCloseTo(Math.pow(1000, 1 / 4), 10)
    expect(log[2].value).toBeCloseTo(Math.sqrt(1000), 10)
    expect(log[3].value).toBeCloseTo(Math.pow(1000, 3 / 4), 10)
    expect(log[4].value).toBe(1000)
    expect(log[2].value).toBeCloseTo(Math.sqrt(1000))
    // 两端颜色一致（同一色带），仅值域节点分布不同
    expect(linear[0].color).toBe(log[0].color)
    expect(linear[4].color).toBe(log[4].color)
  })

  it('rejects log mode when min is not positive', () => {
    expect(() => buildColorStops('viridis', 'log', [-1, 10])).toThrow('LOG_SCALE_UNAVAILABLE')
    expect(() => buildColorStops('viridis', 'log', [0, 10])).toThrow('LOG_SCALE_UNAVAILABLE')
  })

  it('rejects unknown palette and invalid range', () => {
    expect(() => buildColorStops('no-such' as never, 'linear', [1, 10])).toThrow()
    expect(() => buildColorStops('viridis', 'linear', [10, 10])).toThrow()
    expect(() => buildColorStops('viridis', 'linear', [Number.NaN, 10])).toThrow()
  })

  it('normalizeForDisplay 只用于显示插值，不回写原始值', () => {
    const normalized = normalizeForDisplay('linear', [1, 1000], 500.5)
    expect(normalized).toBeCloseTo(0.5)
    const logNorm = normalizeForDisplay('log', [1, 1000], Math.sqrt(1000))
    expect(logNorm).toBeCloseTo(0.5)
    // 原始值在范围外被钳制，但绝不修改输入
    expect(normalizeForDisplay('linear', [1, 1000], -5)).toBe(0)
    expect(normalizeForDisplay('linear', [1, 1000], 5000)).toBe(1)
  })
})
