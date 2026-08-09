<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { init as echartsInit, use as echartsUse } from 'echarts/core'
import { HeatmapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type {
  AnalysisModuleResult,
  AnalysisProfileId,
  AnalysisVariable,
  SpatialBin,
} from '../../api/types'
import {
  formatNumber,
  spatialAnomalyOf,
  spatialSummaryOf,
  type AnalysisSpatialSelection,
} from './analysisTypes'

// v0.8.0 第二批 Task 5：空间视图——SpatialSummary 的 XY 网格热力图
// （ECharts heatmap + visualMap）。count/mean 双度量切换；点击分箱发出类
// 型化 selection（axis/x_range/y_range/dataset_id/可选 result_id），由视
// 图决定是否导航到成果页。disabled/error/空数据一律解释性空状态；卸载
// 必须 dispose。坐标范围来自后端分箱，绝不使用原始文件路径。
// Task 6：spatial_anomaly 专属载荷（分位阈值高/低值区域）按 profile 渲染
// 差异化标题/图例/单位与阈值来源；单位未确认时不生成地质语义结论。
// v0.8.0 第三批 Task 8：瓦斯 profile 渲染「高/低含量区域」，阈值说明用
// 「探索性分位口径」表述；绝不输出「危险/安全」等规范判断词。

echartsUse([HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent, CanvasRenderer])

const props = defineProps<{
  module: AnalysisModuleResult
  variable: AnalysisVariable
  datasetId: string
  resultId?: string | null
  profile?: AnalysisProfileId
}>()

const emit = defineEmits<{ (e: 'select', selection: AnalysisSpatialSelection): void }>()

const spatial = computed(() => spatialSummaryOf(props.module))
const anomaly = computed(() => spatialAnomalyOf(props.module))
const anomalyMode = computed(() => anomaly.value !== null)
const usable = computed(
  () => props.module.status === 'ok' && (spatial.value?.bins.length ?? 0) > 0,
)

const anomalyLabels = computed(() => {
  if (props.profile === 'microseismic_velocity') {
    return { title: '速度高/低值区域', high: '速度高值区域', low: '速度低值区域' }
  }
  if (props.profile === 'resistivity') {
    return { title: '高/低阻区域', high: '高阻区域', low: '低阻区域' }
  }
  if (props.profile === 'gas_content') {
    return { title: '高/低含量区域', high: '高含量区域', low: '低含量区域' }
  }
  return { title: '空间高/低值区域', high: '高值区域', low: '低值区域' }
})

// 阈值说明措辞：瓦斯分位阈值明确为「探索性分位口径」（非权威阈值来源，
// 绝不引申规范结论），其余 profile 沿用「分位阈值口径」
const thresholdWording = computed(() =>
  props.profile === 'gas_content' ? '探索性分位口径' : '分位阈值口径',
)

const panelTitle = computed(() => (anomalyMode.value ? anomalyLabels.value.title : '空间分布'))

const REGION_CODES: Record<string, number> = { low: 0, normal: 1, high: 2, empty: -1 }

function regionOf(binIndex: number): 'high' | 'low' | 'normal' | 'empty' {
  return anomaly.value?.bins[binIndex]?.region ?? 'empty'
}

function regionLabel(region: 'high' | 'low' | 'normal' | 'empty'): string {
  if (region === 'high') return anomalyLabels.value.high
  if (region === 'low') return anomalyLabels.value.low
  if (region === 'normal') return '正常范围'
  return '无样本'
}

const anomalyLegendText = computed(() => {
  const summary = anomaly.value
  if (!summary) return ''
  const high = summary.thresholds.high
  const low = summary.thresholds.low
  const method = summary.thresholds.method ? `；阈值来源：${summary.thresholds.method}` : ''
  return (
    `${anomalyLabels.value.high} ≥ ${formatNumber(high)} ${unit.value} · ` +
    `${anomalyLabels.value.low} < ${formatNumber(low)} ${unit.value}${method}`
  )
})

const emptyMessage = computed(() => {
  if (props.module.status !== 'ok') {
    return props.module.message ?? '空间模块在当前数据版本不可用。'
  }
  return '暂无可用空间聚合数据（无有限有效样本）。'
})

const metric = ref<'count' | 'mean'>('count')
const unit = computed(() => props.variable.unit ?? '')

function metricValue(bin: SpatialBin): number {
  if (metric.value === 'count') return bin.count
  return bin.mean ?? 0
}

const maxMetric = computed(() => {
  const bins = spatial.value?.bins ?? []
  let max = 0
  for (const bin of bins) max = Math.max(max, metricValue(bin))
  return max > 0 ? max : 1
})

const nonEmptyCells = computed(
  () => (spatial.value?.bins ?? []).filter((bin) => bin.count > 0).length,
)

const summaryText = computed(() => {
  if (anomaly.value) {
    const summary = anomaly.value
    const highRatio =
      summary.highVolumeRatio !== null ? summary.highVolumeRatio * 100 : null
    const lowRatio = summary.lowVolumeRatio !== null ? summary.lowVolumeRatio * 100 : null
    return (
      `${anomalyLabels.value.high}体积占比 ${formatNumber(highRatio)}% · ` +
      `${anomalyLabels.value.low}体积占比 ${formatNumber(lowRatio)}%（按${thresholdWording.value}）`
    )
  }
  const summary = spatial.value
  if (!summary) return ''
  const maxCount = summary.bins.reduce((acc, bin) => Math.max(acc, bin.count), 0)
  return `XY 平面 ${summary.grid_size}×${summary.grid_size} 网格；含样本单元 ${nonEmptyCells.value}/${summary.bins.length}；单格最大样本数 ${formatNumber(maxCount)}`
})

const host = ref<HTMLDivElement | null>(null)
let chart: ReturnType<typeof echartsInit> | null = null

function columnLabels(): string[] {
  const summary = spatial.value
  if (!summary) return []
  const grid = summary.grid_size
  return summary.bins.slice(0, grid).map((bin) => formatNumber(bin.x_lower))
}

function rowLabels(): string[] {
  const summary = spatial.value
  if (!summary) return []
  const grid = summary.grid_size
  const labels: string[] = []
  for (let row = 0; row < grid; row += 1) {
    labels.push(formatNumber(summary.bins[row * grid].y_lower))
  }
  return labels
}

function buildOption() {
  const summary = spatial.value
  const bins = summary?.bins ?? []
  const grid = summary?.grid_size ?? 32
  if (anomaly.value) {
    const labels = anomalyLabels.value
    return {
      grid: { left: 64, right: 16, top: 16, bottom: 64 },
      xAxis: {
        type: 'category' as const,
        name: 'X',
        data: columnLabels(),
        axisLabel: { fontSize: 10 },
      },
      yAxis: {
        type: 'category' as const,
        name: 'Y',
        data: rowLabels(),
        axisLabel: { fontSize: 10 },
      },
      visualMap: {
        type: 'piecewise' as const,
        dimension: 2,
        orient: 'horizontal' as const,
        left: 'center',
        bottom: 0,
        textStyle: { color: '#8794a5', fontSize: 10 },
        pieces: [
          { value: 2, label: labels.high, color: '#e8c25a' },
          { value: 1, label: '正常范围', color: '#2b6cb0' },
          { value: 0, label: labels.low, color: '#35c4d8' },
          { value: -1, label: '无样本', color: '#16202c' },
        ],
      },
      tooltip: {
        formatter: (param: { data: [number, number, number]; dataIndex: number }) => {
          const bin = bins[param.dataIndex]
          if (!bin) return ''
          const head = `X ${formatNumber(bin.x_lower)} – ${formatNumber(bin.x_upper)} · Y ${formatNumber(bin.y_lower)} – ${formatNumber(bin.y_upper)}`
          if (bin.count === 0) return `${head}<br/>无样本`
          const meanText =
            bin.mean !== null
              ? `<br/>${props.variable.name} 均值 ${formatNumber(bin.mean)} ${unit.value}`
              : ''
          const regionText = `<br/>区域：${regionLabel(regionOf(param.dataIndex))}`
          return `${head}<br/>样本数 ${bin.count}${meanText}${regionText}`
        },
      },
      series: [
        {
          type: 'heatmap' as const,
          name: labels.title,
          data: bins.map((_bin, index) => [
            index % grid,
            Math.floor(index / grid),
            REGION_CODES[regionOf(index)] ?? -1,
          ]),
        },
      ],
    }
  }
  const metricLabel = metric.value === 'count' ? '样本数' : `${props.variable.name} 均值`
  return {
    grid: { left: 64, right: 16, top: 16, bottom: 64 },
    xAxis: { type: 'category' as const, name: 'X', data: columnLabels(), axisLabel: { fontSize: 10 } },
    yAxis: { type: 'category' as const, name: 'Y', data: rowLabels(), axisLabel: { fontSize: 10 } },
    visualMap: {
      min: 0,
      max: maxMetric.value,
      dimension: 2,
      calculable: true,
      orient: 'horizontal' as const,
      left: 'center',
      bottom: 0,
      text: [metricLabel, ''],
      textStyle: { color: '#8794a5', fontSize: 10 },
      inRange: { color: ['#16202c', '#2b6cb0', '#35c4d8', '#e8c25a'] },
    },
    tooltip: {
      formatter: (param: { data: [number, number, number]; dataIndex: number }) => {
        const bin = bins[param.dataIndex]
        if (!bin) return ''
        const head = `X ${formatNumber(bin.x_lower)} – ${formatNumber(bin.x_upper)} · Y ${formatNumber(bin.y_lower)} – ${formatNumber(bin.y_upper)}`
        if (bin.count === 0) return `${head}<br/>无样本`
        const meanText =
          bin.mean !== null
            ? `<br/>${props.variable.name} 均值 ${formatNumber(bin.mean)} ${unit.value}`
            : ''
        return `${head}<br/>样本数 ${bin.count}${meanText}`
      },
    },
    series: [
      {
        type: 'heatmap' as const,
        name: metricLabel,
        data: bins.map((bin, index) => [index % grid, Math.floor(index / grid), metricValue(bin)]),
      },
    ],
  }
}

function onChartClick(param: { dataIndex?: number }) {
  const bin = spatial.value?.bins[param.dataIndex ?? -1]
  if (!bin) return
  const selection: AnalysisSpatialSelection = {
    axis: 'xy',
    x_range: [bin.x_lower, bin.x_upper],
    y_range: [bin.y_lower, bin.y_upper],
    dataset_id: props.datasetId,
  }
  if (props.resultId) selection.result_id = props.resultId
  emit('select', selection)
}

function render() {
  if (!usable.value) return
  if (!chart && host.value) {
    chart = echartsInit(host.value, undefined, { renderer: 'canvas' })
    chart?.on('click', onChartClick)
  }
  chart?.setOption(buildOption(), true)
}

function onResize() {
  chart?.resize()
}

onMounted(() => {
  render()
  window.addEventListener('resize', onResize)
})

watch([() => props.module, metric], () => render(), { flush: 'post' })

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <section class="panel spatial-panel" data-test="spatial-feature-panel">
    <header class="panel-head">
      <h3>{{ panelTitle }}</h3>
      <div
        v-if="usable && !anomalyMode"
        class="metric-toggle"
        data-test="spatial-metric-toggle"
        role="group"
        aria-label="度量切换"
      >
        <label>
          <input
            type="radio"
            name="spatial-metric"
            value="count"
            data-test="metric-count"
            :checked="metric === 'count'"
            @change="metric = 'count'"
          />
          样本计数
        </label>
        <label>
          <input
            type="radio"
            name="spatial-metric"
            value="mean"
            data-test="metric-mean"
            :checked="metric === 'mean'"
            @change="metric = 'mean'"
          />
          均值
        </label>
      </div>
    </header>
    <template v-if="usable">
      <div ref="host" class="chart" data-test="spatial-chart" />
      <p v-if="anomalyMode" class="anomaly-legend" data-test="spatial-anomaly-legend">
        {{ anomalyLegendText }}
      </p>
      <p class="chart-summary" data-test="spatial-summary">{{ summaryText }}</p>
      <p class="hint">点击分箱可定位到对应空间范围的物化成果。</p>
    </template>
    <p v-else class="empty-note" data-test="spatial-empty">{{ emptyMessage }}</p>
  </section>
</template>

<style scoped>
.panel {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

h3 {
  margin: 0;
  font-size: 15px;
}

.metric-toggle {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.metric-toggle label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}

.chart {
  width: 100%;
  height: 360px;
}

.chart-summary {
  margin: 0;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.anomaly-legend {
  margin: 0;
  font-size: 12px;
  color: var(--gmp-gold);
}

.hint {
  margin: 0;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.empty-note {
  margin: 0;
  font-size: 13px;
  color: var(--gmp-text-faint);
}
</style>
