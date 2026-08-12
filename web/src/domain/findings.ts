// v0.9.0：证据结论选择器。从只读分析摘要 DTO 确定性推导演示结论卡；
// 每条结论必须携带数据版本/源哈希/计算版本溯源、可信状态与限制说明。
// 绝不根据颜色、案例名或不完整指标自由生成地质解释；模块缺失/形态
// 不符时不产出结论，绝不伪造零值证据。

import type { AnalysisModuleResult, AnalysisSummaryResponse } from '../api/types'
import { comparisonCandidatesOf, formatNumber, spatialAnomalyOf } from '../components/analysis/analysisTypes'
import { algorithmLabel } from '../utils/modelingLabels'

export type FindingConfidence = 'verified' | 'exploratory' | 'insufficient' | 'unavailable'

export interface FindingSpatialTarget {
  axis: 'xy' | 'x' | 'y' | 'z'
  xRange?: [number, number]
  yRange?: [number, number]
  range?: [number, number]
  resultId?: string
}

export interface PresentationFinding {
  id: string
  title: string
  statement: string
  evidence: string[]
  source: {
    datasetId: string
    sourceSha256: string
    calculationVersion: string
  }
  confidence: FindingConfidence
  limitations: string[]
  spatialTarget?: FindingSpatialTarget
}

export type FindingBuilder = (
  summary: AnalysisSummaryResponse,
) => PresentationFinding[]

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function moduleOf(summary: AnalysisSummaryResponse, moduleId: string): AnalysisModuleResult | null {
  const found = summary.modules.find((m) => m.module_id === moduleId)
  return found && found.status === 'ok' ? found : null
}

function sourceOf(summary: AnalysisSummaryResponse) {
  return {
    datasetId: summary.dataset_id,
    sourceSha256: summary.provenance.source_sha256,
    calculationVersion: summary.provenance.calculation_version,
  }
}

/** 百分比展示：整数不带小数点，否则保留一位 */
function formatPercent(ratio: number): string {
  const pct = ratio * 100
  return `${Number.isInteger(pct) ? pct : pct.toFixed(1)}%`
}

export function qualityFinding(summary: AnalysisSummaryResponse): PresentationFinding | null {
  const q = summary.quality
  const rows = asNumber(q.row_count)
  const valid = asNumber(q.valid_count)
  if (rows === null || valid === null || rows <= 0) return null
  const ratio = valid / rows
  const invalid = asNumber(q.invalid_count)
  const consistent = invalid !== null && rows === valid + invalid
  const evidence: string[] = []
  const dup = asNumber(q.duplicate_coordinate_count)
  if (dup !== null) evidence.push(`重复坐标 ${dup}`)
  if (q.bounds) {
    const axes = Object.keys(q.bounds).sort()
    if (axes.length > 0) evidence.push(`空间范围 ${axes.map((a) => a.toUpperCase()).join('/')} 已登记`)
  }
  return {
    id: 'quality',
    title: '数据质量',
    statement: `有效数据 ${valid}/${rows}（${formatPercent(ratio)}）`,
    evidence,
    source: sourceOf(summary),
    confidence: consistent ? 'verified' : 'insufficient',
    limitations: ['质量口径来自数据版本质量报告，无效行不参与插值建模'],
  }
}

export function formalModelFinding(summary: AnalysisSummaryResponse): PresentationFinding | null {
  const module = moduleOf(summary, 'model_comparison')
  if (!module) return null
  const candidates = comparisonCandidatesOf(module)
  // 只认显式正式选择；绝不按指标排序推断“最好”
  const formal = candidates.find((c) => c.formal_selection)
  if (!formal) return null
  const metricLabels: Array<[string, string]> = [
    ['rmse', 'RMSE'],
    ['mae', 'MAE'],
    ['r2', 'R²'],
    ['bias', 'Bias'],
  ]
  const evidence = metricLabels.flatMap(([key, label]) => {
    const value = formal.metrics[key]
    return value === undefined ? [] : [`${label} ${formatNumber(value)}`]
  })
  const unit = summary.variable.unit
  return {
    id: 'formal-model',
    title: '正式模型',
    statement: `正式成果采用${algorithmLabel(formal.algorithm)}`,
    evidence,
    source: sourceOf(summary),
    confidence: 'verified',
    limitations: [
      '误差指标为公共有效集空间折分验证口径，不代表区域外推精度',
      ...(unit ? [] : ['变量单位未确认，结论仅限相对比较']),
    ],
    spatialTarget: { axis: 'xy', resultId: formal.result_id },
  }
}

const ANOMALY_REGION_WORDING: Record<string, { high: string; low: string }> = {
  resistivity: { high: '高阻', low: '低阻' },
  microseismic_velocity: { high: '高速度', low: '低速度' },
  gas_content: { high: '高含量', low: '低含量' },
  generic_3d: { high: '高值', low: '低值' },
}

export function anomalyFinding(summary: AnalysisSummaryResponse): PresentationFinding | null {
  const module = moduleOf(summary, 'spatial_anomaly')
  if (!module) return null
  const anomaly = spatialAnomalyOf(module)
  if (!anomaly) return null
  const wording = ANOMALY_REGION_WORDING[summary.analysis_profile] ?? ANOMALY_REGION_WORDING.generic_3d
  const evidence: string[] = []
  if (anomaly.thresholds.high !== null) evidence.push(`高值阈值 ≥ ${formatNumber(anomaly.thresholds.high)}`)
  if (anomaly.thresholds.low !== null) evidence.push(`低值阈值 ≤ ${formatNumber(anomaly.thresholds.low)}`)
  if (anomaly.thresholds.method) evidence.push(`阈值来源 ${anomaly.thresholds.method}`)

  const parts: string[] = []
  if (anomaly.highVolumeRatio !== null) {
    parts.push(`${wording.high}区域样本占比 ${formatPercent(anomaly.highVolumeRatio)}`)
  }
  if (anomaly.lowVolumeRatio !== null) {
    parts.push(`${wording.low}区域样本占比 ${formatPercent(anomaly.lowVolumeRatio)}`)
  }
  if (parts.length === 0) return null

  // 三维定位：高值区域（无则低值区域）XY 包围盒并集
  const regionBins = anomaly.bins.filter((b) => b.region === 'high')
  const fallback = regionBins.length > 0 ? regionBins : anomaly.bins.filter((b) => b.region === 'low')
  const spatialTarget: FindingSpatialTarget | undefined =
    fallback.length > 0
      ? {
          axis: 'xy',
          xRange: [
            Math.min(...fallback.map((b) => b.x_lower)),
            Math.max(...fallback.map((b) => b.x_upper)),
          ],
          yRange: [
            Math.min(...fallback.map((b) => b.y_lower)),
            Math.max(...fallback.map((b) => b.y_upper)),
          ],
        }
      : undefined

  return {
    id: 'spatial-anomaly',
    title: '空间异常',
    statement: `${parts.join('，')}（探索性网格支持口径）`,
    evidence,
    source: sourceOf(summary),
    confidence: 'exploratory',
    limitations: [
      '空间异常为分位阈值的探索性网格支持占比，不构成储量、危险或安全结论',
      '体积/面积占比以样本计数为口径',
    ],
    ...(spatialTarget ? { spatialTarget } : {}),
  }
}

export function strongestProfileFinding(
  summary: AnalysisSummaryResponse,
): PresentationFinding | null {
  const profile = summary.analysis_profile
  if (profile === 'resistivity' || profile === 'gas_content') {
    const module = moduleOf(summary, 'depth_slices')
    if (!module || !Array.isArray(module.payload.slices)) return null
    let best: { z0: number; z1: number; ratio: number } | null = null
    for (const raw of module.payload.slices) {
      if (!isRecord(raw)) continue
      const ratio = asNumber(raw.high_ratio)
      const z0 = asNumber(raw.z_lower)
      const z1 = asNumber(raw.z_upper)
      if (ratio === null || z0 === null || z1 === null) continue
      if (!best || ratio > best.ratio) best = { z0, z1, ratio }
    }
    if (!best) return null
    const unit = summary.variable.unit ? ` ${summary.variable.unit}` : ''
    const wording = profile === 'resistivity' ? '高阻样本占比最高' : '高含量样本占比最高'
    return {
      id: 'profile-depth-slices',
      title: profile === 'resistivity' ? '深度分层' : 'Z 向分层',
      statement: `Z ∈ [${formatNumber(best.z0)}, ${formatNumber(best.z1)}] 层${wording}（${formatPercent(best.ratio)}）`,
      evidence: [`变量 ${summary.variable.name}${unit}`, '层内占比以样本计数为口径'],
      source: sourceOf(summary),
      confidence: 'exploratory',
      limitations:
        profile === 'gas_content'
          ? ['稀疏采样下的分层结果为解释性估计，不构成规范阈值结论']
          : ['深度分层为样本级 p25/p75 分位口径，异常阈值来源见空间异常证据'],
      spatialTarget: { axis: 'z', range: [best.z0, best.z1] },
    }
  }
  if (profile === 'microseismic_velocity') {
    const module = moduleOf(summary, 'gradient')
    if (!module) return null
    const mean = asNumber(module.payload.mean)
    const count = asNumber(module.payload.count)
    if (mean === null || count === null || count <= 0) return null
    const unit = summary.variable.unit ? ` ${summary.variable.unit}` : ''
    return {
      id: 'profile-gradient',
      title: '空间梯度',
      statement: `局部空间梯度均值 ${formatNumber(mean)}${unit}（相邻单元差分口径）`,
      evidence: [`参与统计的相邻单元对 ${count}`],
      source: sourceOf(summary),
      confidence: 'exploratory',
      limitations: ['梯度为 XY 相邻单元均值差分幅值，不代表已确认地质各向异性'],
    }
  }
  return null
}

/** generic_3d 的基础分布描述：只陈述事实范围，不生成专业语义 */
function distributionFinding(summary: AnalysisSummaryResponse): PresentationFinding | null {
  const module = moduleOf(summary, 'distribution')
  if (!module || !Array.isArray(module.payload.bins)) return null
  const stats = summary.statistics
  const min = stats ? asNumber(stats.min) : null
  const max = stats ? asNumber(stats.max) : null
  const count = stats ? asNumber(stats.count) : null
  if (min === null || max === null || count === null) return null
  const unit = summary.variable.unit ? ` ${summary.variable.unit}` : ''
  return {
    id: 'distribution',
    title: '属性分布',
    statement: `有效值分布于 ${formatNumber(min)} ~ ${formatNumber(max)}${unit}（${count} 个有效样本）`,
    evidence: ['分布为描述性统计'],
    source: sourceOf(summary),
    confidence: 'verified',
    limitations: ['自定义数据仅提供通用统计描述，不生成专业地质结论'],
  }
}

export const buildPresentationFindings: FindingBuilder = (summary) => {
  const findings: PresentationFinding[] = []
  const quality = qualityFinding(summary)
  if (quality) findings.push(quality)
  const formal = formalModelFinding(summary)
  if (formal) findings.push(formal)
  const anomaly = anomalyFinding(summary)
  if (anomaly) findings.push(anomaly)
  const profile = strongestProfileFinding(summary)
  if (profile) findings.push(profile)
  if (summary.analysis_profile === 'generic_3d') {
    const distribution = distributionFinding(summary)
    if (distribution) findings.push(distribution)
  }
  return findings
}
