<script setup lang="ts">
// v0.9.0：轴向趋势折线图（证据坞用）。逐轴分箱均值趋势；
// 点击分箱点发出携带 dataset/result 身份的剖面区间选择。
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { init as echartsInit, use as echartsUse } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ProfileSliceSummary } from '../../api/types'
import type { AnalysisProfileSelection } from '../analysis/analysisTypes'

echartsUse([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  axes: ProfileSliceSummary[]
  unit: string | null
  datasetId: string
  resultId?: string | null
}>()

const emit = defineEmits<{
  (e: 'select', selection: AnalysisProfileSelection): void
}>()

const host = ref<HTMLElement | null>(null)
let chart: ReturnType<typeof echartsInit> | null = null

const AXIS_COLORS: Record<string, string> = { x: '#46c2be', y: '#9b8cf2', z: '#e4bd63' }

function buildOption() {
  return {
    backgroundColor: 'transparent',
    textStyle: { color: '#8fa39b', fontSize: 11 },
    legend: { textStyle: { color: '#8fa39b' }, top: 0 },
    tooltip: { trigger: 'axis' },
    grid: { left: 52, right: 20, top: 32, bottom: 24 },
    xAxis: {
      type: 'value' as const,
      name: '坐标（m）',
      nameTextStyle: { color: '#8fa39b' },
      axisLabel: { color: '#8fa39b' },
      splitLine: { lineStyle: { color: '#1a2b24' } },
    },
    yAxis: {
      type: 'value' as const,
      name: props.unit ? `均值（${props.unit}）` : '均值',
      nameTextStyle: { color: '#8fa39b' },
      axisLabel: { color: '#8fa39b' },
      splitLine: { lineStyle: { color: '#1a2b24' } },
    },
    series: props.axes.map((entry) => ({
      name: `${entry.axis.toUpperCase()} 轴`,
      type: 'line' as const,
      smooth: true,
      symbolSize: 7,
      itemStyle: { color: AXIS_COLORS[entry.axis] ?? '#46c2be' },
      lineStyle: { color: AXIS_COLORS[entry.axis] ?? '#46c2be', width: 2 },
      // 点横轴取分箱中点；点击时经 dataIndex 回查分箱区间
      data: entry.bins.map((bin) => [
        (bin.lower + bin.upper) / 2,
        bin.mean,
        entry.axis,
        bin.lower,
        bin.upper,
      ]),
    })),
  }
}

function render() {
  const usable = props.axes.some((a) => a.bins.length > 0)
  if (!usable || !host.value) return
  if (!chart) {
    chart = echartsInit(host.value, undefined, { renderer: 'canvas' })
    chart.on('click', (param: { dataIndex?: number; seriesIndex?: number }) => {
      const entry = props.axes[param.seriesIndex ?? -1]
      const bin = entry?.bins[param.dataIndex ?? -1]
      if (!entry || !bin) return
      emit('select', {
        axis: entry.axis,
        range: [bin.lower, bin.upper],
        dataset_id: props.datasetId,
        result_id: props.resultId ?? undefined,
      })
    })
  }
  chart.setOption(buildOption(), true)
}

onMounted(render)
watch(() => props.axes, render, { deep: true, flush: 'post' })
onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="host" class="axis-trend-chart" data-test="axis-trend-chart" />
</template>

<style scoped>
.axis-trend-chart {
  width: 100%;
  height: 240px;
}
</style>
