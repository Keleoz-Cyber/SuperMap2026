<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { init as echartsInit, use as echartsUse } from 'echarts/core'
import { HeatmapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { AnalysisModuleResult, AnalysisVariable, SpatialBin } from '../../api/types'
import { formatNumber, spatialSummaryOf, type AnalysisSpatialSelection } from './analysisTypes'

// v0.8.0 第二批 Task 5：空间视图——SpatialSummary 的 XY 网格热力图
// （ECharts heatmap + visualMap）。count/mean 双度量切换；点击分箱发出类
// 型化 selection（axis/x_range/y_range/dataset_id/可选 result_id），由视
// 图决定是否导航到成果页。disabled/error/空数据一律解释性空状态；卸载
// 必须 dispose。坐标范围来自后端分箱，绝不使用原始文件路径。

echartsUse([HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent, CanvasRenderer])

const props = defineProps<{
  module: AnalysisModuleResult
  variable: AnalysisVariable
  datasetId: string
  resultId?: string | null
}>()

const emit = defineEmits<{ (e: 'select', selection: AnalysisSpatialSelection): void }>()

const spatial = computed(() => spatialSummaryOf(props.module))
const usable = computed(
  () => props.module.status === 'ok' && (spatial.value?.bins.length ?? 0) > 0,
)

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
      <h3>空间分布</h3>
      <div v-if="usable" class="metric-toggle" data-test="spatial-metric-toggle" role="group" aria-label="度量切换">
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
