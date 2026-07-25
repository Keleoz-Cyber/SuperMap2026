// 场渲染的纯数据转换：与组件解耦，便于单元测试。

export interface HeatmapCell {
  xIndex: number
  yIndex: number
  value: number
}

// NoData / null 单元不生成任何图元（保持透明），不以 0 或插值冒充数据。
export function buildHeatmapData(
  matrix: Array<Array<number | null>>,
  nodataMask: boolean[][],
): HeatmapCell[] {
  const cells: HeatmapCell[] = []
  for (let xIndex = 0; xIndex < matrix.length; xIndex += 1) {
    const row = matrix[xIndex] ?? []
    for (let yIndex = 0; yIndex < row.length; yIndex += 1) {
      const value = row[yIndex]
      if (value === null || value === undefined) continue
      if (nodataMask[xIndex]?.[yIndex]) continue
      if (!Number.isFinite(value)) continue
      cells.push({ xIndex, yIndex, value })
    }
  }
  return cells
}

// 实测点叠加：把真实坐标吸附到最近的网格轴下标（ECharts 类目轴定位）。
export function nearestIndex(axis: number[], value: number): number {
  let best = 0
  let bestDistance = Number.POSITIVE_INFINITY
  for (let i = 0; i < axis.length; i += 1) {
    const distance = Math.abs(axis[i] - value)
    if (distance < bestDistance) {
      bestDistance = distance
      best = i
    }
  }
  return best
}
