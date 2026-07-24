<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { buildHeatmapData, nearestIndex } from './fieldData'

interface SourcePoints {
  x: number[]
  y: number[]
  values: number[]
}

const props = defineProps<{
  title: string
  axesNames: string[]
  axes: number[][]
  matrix: Array<Array<number | null>>
  nodataMask: boolean[][]
  valueRange: [number | null, number | null]
  sourcePoints?: SourcePoints | null
}>()

const chartEl = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

const cells = computed(() => buildHeatmapData(props.matrix, props.nodataMask))
const overlayCount = computed(() => props.sourcePoints?.x.length ?? 0)

function axisLabels(axis: number[]): string[] {
  return axis.map((v) => String(Math.round(v * 1000) / 1000))
}

function render() {
  if (!chartEl.value) return
  if (!chart) {
    try {
      chart = echarts.init(chartEl.value, undefined, { renderer: 'svg' })
    } catch {
      return // 无图形环境（如 jsdom 降级）：统计信息仍然可见
    }
  }
  const [xAxis, yAxis] = props.axes
  const range: [number, number] = [
    props.valueRange[0] ?? 0,
    props.valueRange[1] ?? 1,
  ]
  const heatData = cells.value.map((c) => [c.xIndex, c.yIndex, c.value])
  const overlay = (props.sourcePoints?.x ?? []).map((x, i) => ({
    value: [
      nearestIndex(xAxis, x),
      nearestIndex(yAxis, props.sourcePoints?.y[i] ?? 0),
      props.sourcePoints?.values[i] ?? 0,
    ],
  }))
  chart.setOption(
    {
      title: { text: props.title, textStyle: { fontSize: 13, color: '#c9d4e0' } },
      grid: { left: 70, right: 30, top: 44, bottom: 60 },
      xAxis: {
        type: 'category',
        name: props.axesNames[0] ?? 'x',
        data: axisLabels(xAxis),
        axisLabel: { color: '#8fa1b3', fontSize: 10 },
      },
      yAxis: {
        type: 'category',
        name: props.axesNames[1] ?? 'y',
        data: axisLabels(yAxis),
        axisLabel: { color: '#8fa1b3', fontSize: 10 },
      },
      visualMap: {
        min: range[0],
        max: range[0] === range[1] ? range[0] + 1 : range[1],
        calculable: true,
        orient: 'horizontal',
        left: 'center',
        bottom: 4,
        textStyle: { color: '#8fa1b3', fontSize: 10 },
        inRange: { color: ['#2b6cb0', '#38b2ac', '#faf089', '#dd6b20', '#c53030'] },
      },
      series: [
        {
          type: 'heatmap',
          data: heatData,
          emphasis: { disabled: true },
        },
        {
          type: 'scatter',
          data: overlay,
          symbolSize: 7,
          itemStyle: { borderColor: '#ffffff', borderWidth: 1, color: 'rgba(0,0,0,0.35)' },
          tooltip: { formatter: (p: { value: [number, number, number] }) => `实测值 ${p.value[2]}` },
        },
      ],
      tooltip: { trigger: 'item' },
    },
    { notMerge: true },
  )
  chart.resize()
}

onMounted(render)
watch(() => [props.matrix, props.axes, props.sourcePoints], render, { deep: false })
onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="field-2d" data-test="field-2d">
    <div ref="chartEl" class="chart" />
    <div class="field-stats">
      <span data-test="valid-cells">有效图元 {{ cells.length }}</span>
      <span v-if="sourcePoints" data-test="overlay-count">实测点叠加 {{ overlayCount }} 个</span>
      <span v-if="valueRange[0] !== null">值域 {{ valueRange[0] }} ~ {{ valueRange[1] }}</span>
    </div>
  </div>
</template>

<style scoped>
.field-2d {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.chart {
  width: 100%;
  height: 420px;
  background: var(--gmp-bg-soft);
  border: 1px solid var(--gmp-border);
  border-radius: 10px;
}

.field-stats {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--gmp-text-faint);
}
</style>
