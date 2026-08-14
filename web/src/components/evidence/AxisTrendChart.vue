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

const AXIS_COLORS: Record<string, string> = { x: '#4ab6e8', y: '#9b8cf2', z: '#e4bd63' }

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
      itemStyle: { color: AXIS_COLORS[entry.axis] ?? '#4ab6e8' },
      lineStyle: { color: AXIS_COLORS[entry.axis] ?? '#4ab6e8', width: 2 },
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
    // 点击画布空白也定位最近分箱（真实浏览器里用户很难精确命中折线点）；
    // zrender 层能力缺失（单测 mock）时自动退化为仅数据点点击
    const zr = (chart as { getZr?: () => { on: (ev: string, cb: (e: { offsetX: number; offsetY: number }) => void) => void } }).getZr?.()
    zr?.on('click', (e) => {
      if (!chart) return
      // 命中数据元素时由系列 click 处理，避免重复选择
      if ((e as { target?: unknown }).target) return
      let best: { entry: (typeof props.axes)[number]; bin: ProfileSliceSummary['bins'][number]; dist: number } | null = null
      for (let s = 0; s < props.axes.length; s++) {
        const entry = props.axes[s]
        const converted = chart.convertFromPixel({ seriesIndex: s }, [e.offsetX, e.offsetY]) as [number, number] | null
        if (!converted || !Number.isFinite(converted[0])) continue
        for (const bin of entry.bins) {
          const mid = (bin.lower + bin.upper) / 2
          const dist = Math.abs(mid - converted[0])
          if (!best || dist < best.dist) best = { entry, bin, dist }
        }
      }
      if (!best) return
      emit('select', {
        axis: best.entry.axis,
        range: [best.bin.lower, best.bin.upper],
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
