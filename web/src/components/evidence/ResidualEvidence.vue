<script setup lang="ts">
// v0.9.0：观测—预测残差证据图（证据坞用）。仅使用有限观测/预测对；
// 无有限对时显示类型化空态，绝不渲染空画布伪成功。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { init as echartsInit, use as echartsUse } from 'echarts/core'
import { ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ResidualEvidence } from '../../api/types'

echartsUse([ScatterChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  evidence: ResidualEvidence | null
  unit: string | null
}>()

const host = ref<HTMLElement | null>(null)
let chart: ReturnType<typeof echartsInit> | null = null

const pairs = computed(() => {
  const ev = props.evidence
  if (!ev) return []
  const out: Array<[number, number]> = []
  const n = Math.min(ev.observed.length, ev.predicted.length)
  for (let i = 0; i < n; i++) {
    const o = ev.observed[i]
    const p = ev.predicted[i]
    if (o === null || p === null) continue
    if (!Number.isFinite(o) || !Number.isFinite(p)) continue
    out.push([o, p])
  }
  return out
})

const diagonal = computed(() => {
  if (pairs.value.length === 0) return null
  const flat = pairs.value.flat()
  const min = Math.min(...flat)
  const max = Math.max(...flat)
  return { min, max }
})

function buildOption() {
  const diag = diagonal.value
  return {
    backgroundColor: 'transparent',
    textStyle: { color: '#8fa39b', fontSize: 11 },
    tooltip: { trigger: 'item' },
    grid: { left: 52, right: 20, top: 20, bottom: 40 },
    xAxis: {
      type: 'value' as const,
      name: props.unit ? `观测（${props.unit}）` : '观测',
      nameTextStyle: { color: '#8fa39b' },
      axisLabel: { color: '#8fa39b' },
      splitLine: { lineStyle: { color: '#1a2b24' } },
    },
    yAxis: {
      type: 'value' as const,
      name: props.unit ? `预测（${props.unit}）` : '预测',
      nameTextStyle: { color: '#8fa39b' },
      axisLabel: { color: '#8fa39b' },
      splitLine: { lineStyle: { color: '#1a2b24' } },
    },
    series: [
      {
        name: '观测—预测',
        type: 'scatter' as const,
        symbolSize: 6,
        data: pairs.value,
        itemStyle: { color: '#4ab6e8', opacity: 0.75 },
      },
      ...(diag
        ? [
            {
              name: '理想线',
              type: 'line' as const,
              data: [
                [diag.min, diag.min],
                [diag.max, diag.max],
              ],
              showSymbol: false,
              lineStyle: { color: '#5f7168', type: 'dashed' as const, width: 1 },
              silent: true,
            },
          ]
        : []),
    ],
  }
}

function render() {
  if (pairs.value.length === 0 || !host.value) return
  if (!chart) chart = echartsInit(host.value, undefined, { renderer: 'canvas' })
  chart.setOption(buildOption(), true)
}

onMounted(render)
watch(() => props.evidence, render, { flush: 'post' })
onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div v-if="pairs.length > 0" ref="host" class="residual-chart" data-test="residual-chart" />
  <p v-else class="residual-empty" data-test="residual-empty">暂无有限观测—预测对。</p>
</template>

<style scoped>
.residual-chart {
  width: 100%;
  height: 240px;
}

.residual-empty {
  margin: 0;
  font-size: var(--s1-font-sm);
  color: var(--s1-text-faint);
  border: 1px dashed var(--s1-border);
  border-radius: var(--s1-radius-sm);
  padding: var(--s1-space-3);
  text-align: center;
}
</style>
