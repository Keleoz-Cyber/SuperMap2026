<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { init as echartsInit, use as echartsUse } from 'echarts/core'
import { HeatmapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { SliceAnalysisResponse } from '../../api/types'
import {
  buildColorStops,
  normalizeForDisplay,
  type RenderPaletteId,
  type RenderScale,
} from './renderTransferFunctions'

// v0.7.0 Batch 2 Task 10：ECharts 剖面热力图（设计 §7.3）。
// 系列数据 [col, row, displayValue, rawValue]：颜色用显示归一化维度，
// tooltip 一律读取原始维度；NoData 显示 NoData，绝不显示伪造的 0。

echartsUse([HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent, CanvasRenderer])

const props = defineProps<{
  analysis: SliceAnalysisResponse
  palette: RenderPaletteId
  scale: RenderScale
}>()

const host = ref<HTMLDivElement | null>(null)
let chart: ReturnType<typeof echartsInit> | null = null

const slice = computed(() => props.analysis.slice)
const property = computed(() => props.analysis.property)

type HeatmapPoint = [number, number, number, number | null]

function buildPoints(): HeatmapPoint[] {
  const s = slice.value
  const stops = buildColorStops(props.palette, props.scale, [
    props.analysis.statistics.min ?? s.coordinate,
    props.analysis.statistics.max ?? s.coordinate + 1,
  ])
  void stops
  const stats = props.analysis.statistics
  const range: [number, number] = [
    stats.min ?? s.coordinate,
    stats.max ?? s.coordinate + 1,
  ]
  const points: HeatmapPoint[] = []
  for (let r = 0; r < s.row_coordinates.length; r += 1) {
    for (let c = 0; c < s.column_coordinates.length; c += 1) {
      const raw = s.values[r][c]
      const display = raw === null || s.nodata_mask[r][c] ? 0 : normalizeForDisplay(props.scale, range, raw)
      points.push([c, r, display, raw])
    }
  }
  return points
}

function buildOption() {
  const s = slice.value
  const stats = props.analysis.statistics
  const range: [number, number] = [
    stats.min ?? s.coordinate,
    stats.max ?? s.coordinate + 1,
  ]
  const stops = buildColorStops(props.palette, props.scale, range)
  return {
    grid: { left: 56, right: 16, top: 16, bottom: 40 },
    xAxis: { type: 'category', data: s.column_coordinates.map(String) },
    yAxis: { type: 'category', data: s.row_coordinates.map(String) },
    visualMap: {
      show: false,
      type: 'piecewise',
      pieces: stops.map((stop) => ({ gt: stop.value, color: stop.color })),
    },
    tooltip: {
      formatter: (param: { data: [number, number, number, number | null] }) => {
        const [c, r, , raw] = param.data
        const col = s.column_coordinates[c]
        const row = s.row_coordinates[r]
        const head = `${s.column_axis.toUpperCase()} = ${col} ${props.analysis.axes[s.column_axis].unit} · ${s.row_axis.toUpperCase()} = ${row} ${props.analysis.axes[s.row_axis].unit} · ${s.fixed_axis.toUpperCase()} = ${s.coordinate}`
        if (raw === null) return `${head}<br/>NoData`
        return `${head}<br/>${property.value.name}：${raw} ${property.value.unit}`
      },
    },
    series: [
      {
        type: 'heatmap',
        data: buildPoints(),
        itemStyle: {
          color: (param: { data: [number, number, number, number | null] }) => {
            const [, , display, raw] = param.data
            if (raw === null) return 'rgba(120, 130, 145, 0.35)'
            const ratio = Math.min(1, Math.max(0, display))
            const index = Math.min(stops.length - 1, Math.floor(ratio * stops.length))
            return stops[index].color
          },
        },
      },
    ],
  }
}

function render() {
  if (!chart && host.value) {
    chart = echartsInit(host.value, undefined, { renderer: 'canvas' })
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

watch(
  () => [props.analysis, props.palette, props.scale],
  () => render(),
  { deep: false },
)

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})

async function capturePng(): Promise<Blob> {
  if (!chart) throw new Error('HEATMAP_NOT_READY')
  const dataUrl = chart.getDataURL({ type: 'png', pixelRatio: 2 })
  // 手工解码 data URL：fetch(data:) 在部分环境（Node/undici 与 jsdom 并存）会
  // 产生跨 realm Blob；此处始终用当前窗口的 Blob 构造，浏览器/测试语义一致
  const [header, payload] = dataUrl.split(',')
  const mime = /data:(.*?)(?:;|$)/.exec(header)?.[1] || 'image/png'
  const binary = atob(payload ?? '')
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  return new Blob([bytes], { type: mime })
}

defineExpose({ capturePng })
</script>

<template>
  <div ref="host" class="slice-heatmap" data-test="slice-heatmap" />
</template>

<style scoped>
.slice-heatmap {
  width: 100%;
  min-width: 320px;
  height: 320px;
}
</style>
