<script setup lang="ts">
// v0.9.0：模型指标柱状图（证据坞用）。RMSE/MAE 同轴分组柱状，
// R² 独立标度；点击柱子发出候选身份选择事件。
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { init as echartsInit, use as echartsUse } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ModelComparisonCandidate } from '../analysis/analysisTypes'

echartsUse([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  candidates: ModelComparisonCandidate[]
  unit: string | null
}>()

const emit = defineEmits<{
  (e: 'select', resultId: string): void
}>()

const host = ref<HTMLElement | null>(null)
let chart: ReturnType<typeof echartsInit> | null = null

function metric(c: ModelComparisonCandidate, key: string): number | null {
  const v = c.metrics[key]
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function buildOption() {
  const rows = props.candidates
  return {
    backgroundColor: 'transparent',
    textStyle: { color: '#8fa39b', fontSize: 11 },
    legend: { textStyle: { color: '#8fa39b' }, top: 0 },
    tooltip: { trigger: 'axis' },
    grid: { left: 52, right: 44, top: 32, bottom: 24 },
    xAxis: {
      type: 'category' as const,
      data: rows.map((c) => `${c.algorithm}${c.formal_selection ? ' ★' : ''}`),
      axisLabel: { color: '#8fa39b', fontSize: 11 },
      axisLine: { lineStyle: { color: '#21382f' } },
    },
    yAxis: [
      {
        type: 'value' as const,
        name: props.unit ? `误差（${props.unit}）` : '误差',
        nameTextStyle: { color: '#8fa39b' },
        axisLabel: { color: '#8fa39b' },
        splitLine: { lineStyle: { color: '#1a2b24' } },
      },
      {
        type: 'value' as const,
        name: 'R²',
        nameTextStyle: { color: '#8fa39b' },
        axisLabel: { color: '#8fa39b' },
        splitLine: { show: false },
      },
    ],
    series: [
      { name: 'RMSE', type: 'bar' as const, yAxisIndex: 0, data: rows.map((c) => metric(c, 'rmse')), itemStyle: { color: '#46c2be' } },
      { name: 'MAE', type: 'bar' as const, yAxisIndex: 0, data: rows.map((c) => metric(c, 'mae')), itemStyle: { color: '#2e8b88' } },
      { name: 'R²', type: 'bar' as const, yAxisIndex: 1, data: rows.map((c) => metric(c, 'r2')), itemStyle: { color: '#e4bd63' } },
    ],
  }
}

function render() {
  if (props.candidates.length === 0 || !host.value) return
  if (!chart) {
    chart = echartsInit(host.value, undefined, { renderer: 'canvas' })
    chart.on('click', (param: { dataIndex?: number }) => {
      const row = props.candidates[param.dataIndex ?? -1]
      if (row) emit('select', row.result_id)
    })
  }
  chart.setOption(buildOption(), true)
}

onMounted(render)
watch(() => props.candidates, render, { deep: true, flush: 'post' })
onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="host" class="model-metric-bars" data-test="model-metric-bars" />
</template>

<style scoped>
.model-metric-bars {
  width: 100%;
  height: 240px;
}
</style>
