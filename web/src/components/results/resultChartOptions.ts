import type { ResultComponentPreview, ResultDepthBin } from '../../api/types'

const AXIS_TEXT = '#a7b8b0'
const GRID_LINE = '#21382f'

export function formatCompactNumber(value: number): string {
  if (!Number.isFinite(value)) return '—'
  const abs = Math.abs(value)
  if (abs >= 100_000_000) return `${trimFixed(value / 100_000_000, 1)}亿`
  if (abs >= 10_000) return `${trimFixed(value / 10_000, 1)}万`
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: abs >= 100 ? 0 : 1 }).format(value)
}

export function formatDepthRange(lower: number, upper: number): string {
  const lowerText = Number.isFinite(lower) ? lower.toFixed(1) : '—'
  const upperText = Number.isFinite(upper) ? upper.toFixed(1) : '—'
  return `${lowerText}～${upperText} m`
}

function trimFixed(value: number, digits: number): string {
  if (!Number.isFinite(value)) return '—'
  return value.toFixed(digits).replace(/\.0+$/, '')
}

function axisBase() {
  return {
    axisLabel: { color: AXIS_TEXT },
    axisLine: { lineStyle: { color: '#456258' } },
    splitLine: { show: true, lineStyle: { color: GRID_LINE, opacity: 0.65 } },
  }
}

export function buildDepthTrendOption(bins: ResultDepthBin[], unit: string) {
  return {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: unknown) =>
        typeof value === 'number' && Number.isFinite(value) ? trimFixed(value, 1) : String(value ?? '—'),
    },
    grid: { left: 16, right: 18, top: 40, bottom: 18, containLabel: true },
    xAxis: {
      type: 'category',
      data: bins.map((bin) => formatDepthRange(bin.z_lower, bin.z_upper)),
      axisLabel: { color: AXIS_TEXT, hideOverlap: true },
      axisLine: { lineStyle: { color: '#456258' } },
    },
    yAxis: [
      {
        ...axisBase(),
        type: 'value',
        name: '高值占比',
        min: 0,
        max: 1,
        interval: 0.2,
        axisLabel: { color: AXIS_TEXT, formatter: (value: number) => `${(value * 100).toFixed(0)}%` },
      },
      {
        ...axisBase(),
        type: 'value',
        name: `层段均值（${unit}）`,
        axisLabel: { color: AXIS_TEXT, formatter: (value: number) => trimFixed(value, 1) },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '高值占比',
        type: 'bar',
        data: bins.map((bin) => bin.high_ratio),
        itemStyle: { color: '#d9a84e' },
      },
      {
        name: '层段均值',
        type: 'line',
        yAxisIndex: 1,
        data: bins.map((bin) => bin.mean),
        itemStyle: { color: '#64dab1' },
      },
    ],
  }
}

export function buildComponentOption(rows: ResultComponentPreview[], unit: string) {
  return {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: unknown) =>
        typeof value === 'number' && Number.isFinite(value) ? formatCompactNumber(value) : String(value ?? '—'),
    },
    grid: { left: 16, right: 18, top: 40, bottom: 18, containLabel: true },
    xAxis: {
      type: 'category',
      data: rows.map((row) => row.label),
      axisLabel: { color: AXIS_TEXT },
      axisLine: { lineStyle: { color: '#456258' } },
    },
    yAxis: [
      {
        ...axisBase(),
        type: 'value',
        name: '网格支持量',
        axisLabel: { color: AXIS_TEXT, formatter: formatCompactNumber },
      },
      {
        ...axisBase(),
        type: 'value',
        name: `峰值（${unit}）`,
        axisLabel: { color: AXIS_TEXT, formatter: (value: number) => trimFixed(value, 1) },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '网格支持量',
        type: 'bar',
        data: rows.map((row) => row.support_measure),
        itemStyle: { color: '#4d8de0' },
      },
      {
        name: '峰值',
        type: 'line',
        yAxisIndex: 1,
        data: rows.map((row) => row.value_max),
        itemStyle: { color: '#d9a84e' },
      },
    ],
  }
}
