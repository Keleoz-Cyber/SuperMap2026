<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { init as echartsInit, use as echartsUse } from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { AnalysisModuleResult, AnalysisVariable } from '../../api/types'
import { formatNumber, profileAxesOf, type AnalysisProfileSelection } from './analysisTypes'

// v0.8.0 第二批 Task 5：X/Y/Z 三轴剖面统计——分段控件切换轴；每轴
// count（柱）/mean/median（线）分箱图。点击分箱发出类型化 selection
// （axis/range/dataset_id/可选 result_id）。disabled/error/空数据一律解
// 释性空状态；卸载必须 dispose。

echartsUse([BarChart, LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

type AxisId = 'x' | 'y' | 'z'

const AXIS_LABELS: Record<AxisId, string> = { x: 'X', y: 'Y', z: 'Z' }

const props = defineProps<{
  module: AnalysisModuleResult
  variable: AnalysisVariable
  datasetId: string
  resultId?: string | null
}>()

const emit = defineEmits<{ (e: 'select', selection: AnalysisProfileSelection): void }>()

const axes = computed(() => profileAxesOf(props.module))
const usable = computed(
  () => props.module.status === 'ok' && axes.value.some((entry) => entry.bins.length > 0),
)

const emptyMessage = computed(() => {
  if (props.module.status !== 'ok') {
    return props.module.message ?? '剖面统计模块在当前数据版本不可用。'
  }
  return '暂无可用剖面统计数据（无有限有效样本）。'
})

const activeAxis = ref<AxisId>('x')

const availableAxes = computed(() => axes.value.map((entry) => entry.axis))

const activeSummary = computed(() => {
  return (
    axes.value.find((entry) => entry.axis === activeAxis.value) ??
    axes.value[0] ??
    null
  )
})

// 数据到达/变化时确保选中轴存在（绝不沿用旧数据集的轴身份）
watch(
  axes,
  (entries) => {
    if (!entries.some((entry) => entry.axis === activeAxis.value)) {
      activeAxis.value = entries[0]?.axis ?? 'x'
    }
  },
  { immediate: true },
)

const unit = computed(() => props.variable.unit ?? '')

const summaryText = computed(() => {
  const summary = activeSummary.value
  if (!summary || summary.bins.length === 0) return ''
  const total = summary.bins.reduce((acc, bin) => acc + bin.count, 0)
  return `${AXIS_LABELS[summary.axis]} 轴剖面：${summary.bins.length} 分箱；样本数 ${formatNumber(total)}；范围 ${formatNumber(summary.bins[0].lower)} – ${formatNumber(summary.bins[summary.bins.length - 1].upper)}`
})

const host = ref<HTMLDivElement | null>(null)
let chart: ReturnType<typeof echartsInit> | null = null

function buildOption() {
  const summary = activeSummary.value
  const bins = summary?.bins ?? []
  const labels = bins.map((bin) => `${formatNumber(bin.lower)}–${formatNumber(bin.upper)}`)
  return {
    grid: { left: 56, right: 56, top: 40, bottom: 64 },
    legend: { top: 0, textStyle: { color: '#8794a5', fontSize: 11 } },
    xAxis: {
      type: 'category' as const,
      name: `${AXIS_LABELS[activeAxis.value]} 坐标区间`,
      nameLocation: 'middle' as const,
      nameGap: 48,
      data: labels,
      axisLabel: { interval: Math.ceil(bins.length / 8), rotate: 30, fontSize: 10 },
    },
    yAxis: [
      { type: 'value' as const, name: '样本数', minInterval: 1 },
      { type: 'value' as const, name: unit.value || props.variable.name },
    ],
    tooltip: { trigger: 'axis' as const },
    series: [
      {
        type: 'bar' as const,
        name: '样本数',
        data: bins.map((bin) => bin.count),
        itemStyle: { color: '#2b6cb0' },
      },
      {
        type: 'line' as const,
        name: '均值',
        yAxisIndex: 1,
        data: bins.map((bin) => bin.mean),
        connectNulls: false,
        itemStyle: { color: '#35c4d8' },
      },
      {
        type: 'line' as const,
        name: '中位数',
        yAxisIndex: 1,
        data: bins.map((bin) => bin.median),
        connectNulls: false,
        itemStyle: { color: '#e8c25a' },
      },
    ],
  }
}

function onChartClick(param: { dataIndex?: number }) {
  const summary = activeSummary.value
  const bin = summary?.bins[param.dataIndex ?? -1]
  if (!summary || !bin) return
  const selection: AnalysisProfileSelection = {
    axis: summary.axis,
    range: [bin.lower, bin.upper],
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

watch([() => props.module, activeAxis], () => render(), { flush: 'post' })

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <section class="panel profile-panel" data-test="profile-analysis-panel">
    <header class="panel-head">
      <h3>剖面统计</h3>
      <div v-if="usable" class="axis-toggle" data-test="profile-axis-tabs" role="group" aria-label="剖面轴切换">
        <label v-for="axis in availableAxes" :key="axis">
          <input
            type="radio"
            name="profile-axis"
            :value="axis"
            :data-test="`axis-${axis}`"
            :checked="activeAxis === axis"
            @change="activeAxis = axis"
          />
          {{ AXIS_LABELS[axis] }} 轴
        </label>
      </div>
    </header>
    <template v-if="usable">
      <div ref="host" class="chart" data-test="profile-chart" />
      <p class="chart-summary" data-test="profile-summary">{{ summaryText }}</p>
    </template>
    <p v-else class="empty-note" data-test="profile-empty">{{ emptyMessage }}</p>
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

.axis-toggle {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.axis-toggle label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}

.chart {
  width: 100%;
  height: 280px;
}

.chart-summary {
  margin: 0;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.empty-note {
  margin: 0;
  font-size: 13px;
  color: var(--gmp-text-faint);
}
</style>
