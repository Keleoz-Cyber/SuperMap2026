<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { init as echartsInit, use as echartsUse } from 'echarts/core'
import { HeatmapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { SliceAnalysisResponse } from '../../api/types'
import {
  buildColorStops,
  normalizeForDisplay,
  type RenderPaletteId,
  type RenderScale,
} from './renderTransferFunctions'

// v0.7.0 Batch 2 Task 10：ECharts 剖面热力图（设计 §7.3）。
// 系列数据 [col, row, displayValue, rawValue]：颜色只经 itemStyle 按 display
// 归一化维度映射（不再使用 visualMap——其 pieces 曾用原始值域节点匹配 [0,1]
// 的 display，导致所有切片同色）；tooltip 一律读取原始维度；NoData 显示
// NoData，绝不显示伪造的 0。色带值域默认锁定全体数据 render_profile.value_range，
// 逐切片统计漂移不改变同一真实值的颜色。

echartsUse([HeatmapChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  analysis: SliceAnalysisResponse
  palette: RenderPaletteId
  scale: RenderScale
}>()

const host = ref<HTMLDivElement | null>(null)
let chart: ReturnType<typeof echartsInit> | null = null

const slice = computed(() => props.analysis.slice)
const property = computed(() => props.analysis.property)

// 色带值域：全体数据（render_profile）优先；缺失时退回逐片统计（保持旧行为）
const bandRange = computed<[number, number]>(() => {
  const profile = props.analysis.render_profile
  if (profile) return profile.value_range
  const stats = props.analysis.statistics
  const min = stats.min ?? 0
  const max = stats.max ?? min + 1
  return min < max ? [min, max] : [min, min + 1]
})

type HeatmapPoint = [number, number, number, number | null]

function buildPoints(): HeatmapPoint[] {
  const s = slice.value
  const range = bandRange.value
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
  const stops = buildColorStops(props.palette, props.scale, bandRange.value)
  return {
    grid: { left: 56, right: 16, top: 16, bottom: 40 },
    xAxis: { type: 'category', data: s.column_coordinates.map(String) },
    yAxis: { type: 'category', data: s.row_coordinates.map(String) },
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
