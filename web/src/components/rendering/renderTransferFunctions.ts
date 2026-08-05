// v0.7.0 Batch 2 Task 6：SuperMap 与 ECharts 共用的色带/标度纯函数。
// 线性与对数只改变颜色节点的值域分布，绝不修改原始值；对数要求全正值，
// 不可用即显式失败（LOG_SCALE_UNAVAILABLE），绝不丢弃或平移原始值。

export const PALETTES = {
  'native-spectrum': ['#1a40d9', '#1acccc', '#f2d926', '#f2591a', '#a60d1a'],
  viridis: ['#440154', '#3b528b', '#21918c', '#5ec962', '#fde725'],
  turbo: ['#30123b', '#28bbec', '#a4fc3c', '#fb7e21', '#7a0403'],
  coolwarm: ['#3b4cc0', '#8db0fe', '#dddcdc', '#f4987a', '#b40426'],
  grayscale: ['#000000', '#404040', '#808080', '#bfbfbf', '#ffffff'],
} as const

export type RenderPaletteId = keyof typeof PALETTES
export const PALETTE_IDS = Object.keys(PALETTES) as RenderPaletteId[]
export type RenderScale = 'linear' | 'log'

export interface ColorStop {
  value: number
  color: string
}

function requireRange(range: [number, number]): [number, number] {
  const [min, max] = range
  if (!Number.isFinite(min) || !Number.isFinite(max) || !(min < max)) {
    throw new Error('VALUE_RANGE_INVALID')
  }
  return [min, max]
}

function sampleValues(scale: RenderScale, [min, max]: [number, number], count: number): number[] {
  let values: number[]
  if (scale === 'log') {
    if (min <= 0) throw new Error('LOG_SCALE_UNAVAILABLE')
    const logMin = Math.log(min)
    const logMax = Math.log(max)
    values = Array.from({ length: count }, (_, i) =>
      Math.exp(logMin + ((logMax - logMin) * i) / (count - 1)),
    )
  } else {
    values = Array.from({ length: count }, (_, i) => min + ((max - min) * i) / (count - 1))
  }
  // 端点必须精确落在值域上（色带节点不能因浮点回算漂移出界）
  values[0] = min
  values[count - 1] = max
  return values
}

export function buildColorStops(
  palette: RenderPaletteId,
  scale: RenderScale,
  range: [number, number],
): ColorStop[] {
  const colors = PALETTES[palette]
  if (!colors) throw new Error('PALETTE_UNKNOWN')
  const [min, max] = requireRange(range)
  const values = sampleValues(scale, [min, max], colors.length)
  return colors.map((color, i) => ({ value: values[i], color }))
}

/** 显示插值归一化（钳制到 [0,1]）；仅用于颜色映射，绝不回写原始值。 */
export function normalizeForDisplay(
  scale: RenderScale,
  range: [number, number],
  value: number,
): number {
  const [min, max] = requireRange(range)
  if (scale === 'log') {
    if (min <= 0) throw new Error('LOG_SCALE_UNAVAILABLE')
    const n = (Math.log(Math.max(value, min)) - Math.log(min)) / (Math.log(max) - Math.log(min))
    return Math.min(1, Math.max(0, n))
  }
  const n = (value - min) / (max - min)
  return Math.min(1, Math.max(0, n))
}
