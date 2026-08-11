import type {
  AnalysisModuleResult,
  HistogramBin,
  ProfileSliceSummary,
  SpatialBin,
  SpatialSummary,
} from '../../api/types'

// v0.8.0 第二批 Task 5：分析中心面板共享类型与 payload 解析。
// AnalysisModuleResult.payload 是 Record<string, unknown>（与后端按模块出
// 不同载荷的合同一致）；本模块集中做防御性解析，组件只消费类型化数据。
// 解析宽容但绝不伪造：载荷缺失/形态不符一律回退到空集合，由面板呈现
// 解释性空状态（设计 §8），绝不渲染空图表伪成功。

/** 空间（XY 平面）分箱选择：点击空间热力图单元发出 */
export interface AnalysisSpatialSelection {
  axis: 'xy'
  x_range: [number, number]
  y_range: [number, number]
  dataset_id: string
  result_id?: string
}

/** 剖面区间选择：点击某轴剖面分箱发出 */
export interface AnalysisProfileSelection {
  axis: 'x' | 'y' | 'z'
  range: [number, number]
  dataset_id: string
  result_id?: string
}

export type AnalysisSelection = AnalysisSpatialSelection | AnalysisProfileSelection

/** model_comparison 载荷中的单个候选（后端只读既有 succeeded 记录） */
export interface ModelComparisonCandidate {
  result_id: string
  algorithm: string
  parameters: Record<string, unknown>
  metrics: Record<string, number>
  materialized: boolean
  formal_selection: boolean
  result_url: string
}

/** 模块中文标签；未知模块 id 原样展示（绝不硬编码案例语义） */
export const MODULE_LABELS: Record<string, string> = {
  quality: '数据质量',
  statistics: '基础统计',
  distribution: '属性分布',
  spatial_extent: '空间视图',
  profile_slices: '剖面统计',
  model_comparison: '模型比较',
  axis_trends: '轴向趋势',
  gradient: '速度梯度',
  spatial_anomaly: '空间异常',
  depth_slices: '深度切片',
}

/** 瓦斯 profile 差异化模块标签（v0.8.0 第三批 Task 8）；未列出的模块沿用
 *  ``MODULE_LABELS``。措辞只含可计算表述，绝无「危险/安全」规范判断词 */
export const GAS_MODULE_LABELS: Record<string, string> = {
  distribution: '含量分布',
  depth_slices: '深度分层',
  spatial_anomaly: '含量区域',
  gradient: '含量梯度',
}

/** 模块标签解析：gas_content 用差异化措辞，其余 profile 沿用通用标签 */
export function moduleLabel(profile: string, moduleId: string): string {
  if (profile === 'gas_content') {
    const label = GAS_MODULE_LABELS[moduleId]
    if (label) return label
  }
  return MODULE_LABELS[moduleId] ?? moduleId
}

const numberFormatter = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 3 })

/** 数字展示：null/undefined/非有限 → 占位符，绝不显示 NaN/undefined 字样 */
export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return numberFormatter.format(value)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** distribution 载荷 → 直方图分箱；缺失/形态不符 → 空数组 */
export function distributionBinsOf(module: AnalysisModuleResult): HistogramBin[] {
  const raw = module.payload.bins
  if (!Array.isArray(raw)) return []
  const bins: HistogramBin[] = []
  for (const item of raw) {
    if (!isRecord(item)) continue
    const lower = asNumber(item.lower)
    const upper = asNumber(item.upper)
    const count = asNumber(item.count)
    if (lower === null || upper === null || count === null) continue
    bins.push({ lower, upper, count })
  }
  return bins
}

function parseBounds(raw: unknown): Record<string, [number, number]> | null {
  if (!isRecord(raw)) return null
  const bounds: Record<string, [number, number]> = {}
  for (const [axis, pair] of Object.entries(raw)) {
    if (!Array.isArray(pair) || pair.length !== 2) continue
    const low = asNumber(pair[0])
    const high = asNumber(pair[1])
    if (low === null || high === null) continue
    bounds[axis] = [low, high]
  }
  return Object.keys(bounds).length > 0 ? bounds : null
}

/** spatial_extent 载荷 → 空间聚合；bins 非数组 → null（面板走空状态） */
export function spatialSummaryOf(module: AnalysisModuleResult): SpatialSummary | null {
  const raw = module.payload.bins
  if (!Array.isArray(raw)) return null
  const bins: SpatialBin[] = []
  for (const item of raw) {
    if (!isRecord(item)) continue
    const xLower = asNumber(item.x_lower)
    const xUpper = asNumber(item.x_upper)
    const yLower = asNumber(item.y_lower)
    const yUpper = asNumber(item.y_upper)
    const count = asNumber(item.count)
    if (xLower === null || xUpper === null || yLower === null || yUpper === null) continue
    bins.push({
      x_lower: xLower,
      x_upper: xUpper,
      y_lower: yLower,
      y_upper: yUpper,
      count: count ?? 0,
      mean: asNumber(item.mean),
    })
  }
  return {
    grid_size: asNumber(module.payload.grid_size) ?? 32,
    cell_count: asNumber(module.payload.cell_count),
    bounds: parseBounds(module.payload.bounds),
    bins,
  }
}

/** profile_slices 载荷 → 逐轴分箱摘要（仅保留 x/y/z 且 bins 为数组的轴） */
export function profileAxesOf(module: AnalysisModuleResult): ProfileSliceSummary[] {
  const raw = module.payload.axes
  if (!Array.isArray(raw)) return []
  const axes: ProfileSliceSummary[] = []
  for (const item of raw) {
    if (!isRecord(item)) continue
    const axis = item.axis
    if (axis !== 'x' && axis !== 'y' && axis !== 'z') continue
    if (!Array.isArray(item.bins)) continue
    const bins = item.bins.flatMap((bin) => {
      if (!isRecord(bin)) return []
      const lower = asNumber(bin.lower)
      const upper = asNumber(bin.upper)
      if (lower === null || upper === null) return []
      return [
        {
          lower,
          upper,
          count: asNumber(bin.count) ?? 0,
          mean: asNumber(bin.mean),
          median: asNumber(bin.median),
        },
      ]
    })
    axes.push({ axis, bins })
  }
  return axes
}

/** model_comparison 载荷 → 候选列表；缺失 → 空数组（面板走解释性空状态） */
export function comparisonCandidatesOf(
  module: AnalysisModuleResult | null | undefined,
): ModelComparisonCandidate[] {
  if (!module) return []
  const raw = module.payload.candidates
  if (!Array.isArray(raw)) return []
  const candidates: ModelComparisonCandidate[] = []
  for (const item of raw) {
    if (!isRecord(item) || typeof item.result_id !== 'string') continue
    const metrics: Record<string, number> = {}
    if (isRecord(item.metrics)) {
      for (const [key, value] of Object.entries(item.metrics)) {
        const parsed = asNumber(value)
        if (parsed !== null) metrics[key] = parsed
      }
    }
    candidates.push({
      result_id: item.result_id,
      algorithm: typeof item.algorithm === 'string' ? item.algorithm : 'unknown',
      parameters: isRecord(item.parameters) ? item.parameters : {},
      metrics,
      materialized: item.materialized === true,
      formal_selection: item.formal_selection === true,
      result_url:
        typeof item.result_url === 'string' ? item.result_url : `/results/${item.result_id}`,
    })
  }
  return candidates
}

// ---------------------------------------------------------------------------
// Task 6：profile 专属载荷（log10 分布 / 空间异常区域）
// ---------------------------------------------------------------------------

/** distribution.log10 载荷：仅严格正值进 log10 的分箱与排除计数 */
export interface Log10Distribution {
  bins: HistogramBin[]
  excludedNonPositiveCount: number
  method: string | null
}

export function log10DistributionOf(module: AnalysisModuleResult): Log10Distribution | null {
  const raw = module.payload.log10
  if (!isRecord(raw) || !Array.isArray(raw.bins)) return null
  const bins: HistogramBin[] = []
  for (const item of raw.bins) {
    if (!isRecord(item)) continue
    const lower = asNumber(item.lower)
    const upper = asNumber(item.upper)
    const count = asNumber(item.count)
    if (lower === null || upper === null || count === null) continue
    bins.push({ lower, upper, count })
  }
  if (bins.length === 0) return null
  return {
    bins,
    excludedNonPositiveCount: asNumber(raw.excluded_non_positive_count) ?? 0,
    method: typeof raw.method === 'string' ? raw.method : null,
  }
}

/** spatial_anomaly 载荷：高/低值区域聚合（分位阈值来源随载荷出站） */
export interface SpatialAnomalySummary {
  grid_size: number
  bins: Array<SpatialBin & { region: 'high' | 'low' | 'normal' | 'empty' }>
  thresholds: { high: number | null; low: number | null; method: string | null }
  highVolumeRatio: number | null
  lowVolumeRatio: number | null
}

const ANOMALY_REGIONS = new Set(['high', 'low', 'normal', 'empty'])

export function spatialAnomalyOf(module: AnalysisModuleResult): SpatialAnomalySummary | null {
  const rawThresholds = module.payload.thresholds
  if (!isRecord(rawThresholds)) return null
  const raw = module.payload.bins
  if (!Array.isArray(raw)) return null
  const bins: SpatialAnomalySummary['bins'] = []
  for (const item of raw) {
    if (!isRecord(item)) continue
    const xLower = asNumber(item.x_lower)
    const xUpper = asNumber(item.x_upper)
    const yLower = asNumber(item.y_lower)
    const yUpper = asNumber(item.y_upper)
    if (xLower === null || xUpper === null || yLower === null || yUpper === null) continue
    const region =
      typeof item.region === 'string' && ANOMALY_REGIONS.has(item.region)
        ? (item.region as 'high' | 'low' | 'normal' | 'empty')
        : 'empty'
    bins.push({
      x_lower: xLower,
      x_upper: xUpper,
      y_lower: yLower,
      y_upper: yUpper,
      count: asNumber(item.count) ?? 0,
      mean: asNumber(item.mean),
      region,
    })
  }
  if (bins.length === 0) return null
  return {
    grid_size: asNumber(module.payload.grid_size) ?? 32,
    bins,
    thresholds: {
      high: asNumber(rawThresholds.high),
      low: asNumber(rawThresholds.low),
      method: typeof rawThresholds.method === 'string' ? rawThresholds.method : null,
    },
    highVolumeRatio: asNumber(module.payload.high_volume_ratio),
    lowVolumeRatio: asNumber(module.payload.low_volume_ratio),
  }
}
