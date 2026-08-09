<script setup lang="ts">
// v0.9.0：模型指标比较图。RMSE/MAE 分组柱状（误差轴）与 R²/Bias 独立
// 标度分轴展示，绝不把不同量纲指标塞进一根无标注轴。不兼容、重复配置
// 指纹或有效指标不足时不渲染排名图（fail-closed）。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { init as echartsInit, use as echartsUse } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ComparisonCandidateSummary } from '../../api/types'
import { algorithmLabel } from '../../utils/modelingLabels'

echartsUse([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  candidates: ComparisonCandidateSummary[]
  comparable: boolean
}>()

const host = ref<HTMLElement | null>(null)
let chart: ReturnType<typeof echartsInit> | null = null

// 图表候选：至少一项有限误差指标（RMSE 或 MAE）
const chartable = computed(() =>
  props.candidates.filter(
    (c) =>
      (typeof c.metrics.rmse === 'number' && Number.isFinite(c.metrics.rmse)) ||
      (typeof c.metrics.mae === 'number' && Number.isFinite(c.metrics.mae)),
  ),
)

const hasDuplicateFingerprint = computed(() => {
  const seen = new Set<string>()
  for (const c of props.candidates) {
    if (seen.has(c.configuration_fingerprint)) return true
    seen.add(c.configuration_fingerprint)
  }
  return false
})

const canRender = computed(
  () => props.comparable && !hasDuplicateFingerprint.value && chartable.value.length >= 2,
)

const skipReason = computed(() => {
  if (!props.comparable) return null // 不兼容由视图层 mismatch 列表表达
  if (hasDuplicateFingerprint.value) return '存在相同配置的候选，指标对比无意义'
  if (chartable.value.length < 2) return '有效误差指标不足两个候选，无法对比'
  return null
})

function candidateLabel(c: ComparisonCandidateSummary): string {
  const short = c.candidate_result_id.slice(0, 8)
  return `${algorithmLabel(c.algorithm)}·${short}`
}

function metricValue(c: ComparisonCandidateSummary, key: 'rmse' | 'mae' | 'r2' | 'bias'): number | null {
  const v = c.metrics[key]
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function buildOption() {
  const rows = chartable.value
  return {
    backgroundColor: 'transparent',
    textStyle: { color: '#8fa39b', fontSize: 11 },
    legend: { textStyle: { color: '#8fa39b' }, top: 0 },
    tooltip: { trigger: 'axis' },
    grid: { left: 56, right: 56, top: 34, bottom: 26 },
    xAxis: {
      type: 'category',
      data: rows.map(candidateLabel),
      axisLabel: { color: '#8fa39b', fontSize: 11 },
      axisLine: { lineStyle: { color: '#21382f' } },
    },
    yAxis: [
      {
        type: 'value',
        name: '误差（RMSE/MAE）',
        nameTextStyle: { color: '#8fa39b' },
        axisLabel: { color: '#8fa39b' },
        splitLine: { lineStyle: { color: '#1a2b24' } },
      },
      {
        type: 'value',
        name: 'R² / Bias',
        nameTextStyle: { color: '#8fa39b' },
        axisLabel: { color: '#8fa39b' },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: 'RMSE',
        type: 'bar',
        yAxisIndex: 0,
        data: rows.map((c) => metricValue(c, 'rmse')),
        itemStyle: { color: '#46c2be' },
      },
      {
        name: 'MAE',
        type: 'bar',
        yAxisIndex: 0,
        data: rows.map((c) => metricValue(c, 'mae')),
        itemStyle: { color: '#2e8b88' },
      },
      {
        name: 'R²',
        type: 'bar',
        yAxisIndex: 1,
        data: rows.map((c) => metricValue(c, 'r2')),
        itemStyle: { color: '#e4bd63' },
      },
      {
        name: 'Bias',
        type: 'bar',
        yAxisIndex: 1,
        data: rows.map((c) => metricValue(c, 'bias')),
        itemStyle: { color: '#a8893f' },
      },
    ],
  }
}

function render() {
  if (!canRender.value || !host.value) return
  if (!chart) chart = echartsInit(host.value, undefined, { renderer: 'canvas' })
  chart.setOption(buildOption())
}

onMounted(render)
watch(canRender, (ok) => {
  if (!ok && chart) {
    chart.dispose()
    chart = null
  } else if (ok) {
    render()
  }
})
watch(() => props.candidates, render, { deep: true })
onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="metric-chart-wrap">
    <div v-if="canRender" ref="host" class="metric-chart" data-test="metric-comparison-chart" />
    <p v-else-if="skipReason" class="chart-skip" data-test="metric-chart-skip">{{ skipReason }}</p>
  </div>
</template>

<style scoped>
.metric-chart-wrap {
  min-width: 0;
}

.metric-chart {
  width: 100%;
  height: 280px;
}

.chart-skip {
  margin: 0;
  font-size: var(--s1-font-sm);
  color: var(--s1-text-faint);
  border: 1px dashed var(--s1-border);
  border-radius: var(--s1-radius-sm);
  padding: var(--s1-space-3);
  text-align: center;
}
</style>
