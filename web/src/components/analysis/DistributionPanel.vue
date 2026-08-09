<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { init as echartsInit, use as echartsUse } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { AnalysisModuleResult, AnalysisProfileId, AnalysisVariable } from '../../api/types'
import { distributionBinsOf, formatNumber, log10DistributionOf } from './analysisTypes'

// v0.8.0 第二批 Task 5：属性值分布直方图（ECharts bar，后端确定性等宽
// 分箱，默认 32 格）。轴带变量单位，图下给出可访问文本摘要（样本数/分箱
// 数/值域/峰值分箱）；disabled/error/空分箱一律解释性空状态，绝不渲染空
// 图表。Task 6：电阻率 profile 携带 log10 载荷时切换为对数尺度分箱
// （仅严格正值，排除计数显式提示）；无 log10 载荷回退原始分箱并说明。
// v0.8.0 第三批 Task 8：瓦斯 profile 差异化标题「含量分布」（单位 ml/g）。
// 卸载必须 dispose。

echartsUse([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  module: AnalysisModuleResult
  variable: AnalysisVariable
  profile: AnalysisProfileId
}>()

const bins = computed(() => distributionBinsOf(props.module))
// 差异化标题：瓦斯为「含量分布」，其余 profile 沿用通用「属性值分布」
const panelTitle = computed(() =>
  props.profile === 'gas_content' ? '含量分布' : '属性值分布',
)
const log10 = computed(() =>
  props.profile === 'resistivity' ? log10DistributionOf(props.module) : null,
)
const activeBins = computed(() => log10.value?.bins ?? bins.value)
const usable = computed(() => props.module.status === 'ok' && activeBins.value.length > 0)

const emptyMessage = computed(() => {
  if (props.module.status !== 'ok') {
    return props.module.message ?? '分布模块在当前数据版本不可用。'
  }
  return '暂无可用分布数据（无有限有效样本）。'
})

const unit = computed(() => props.variable.unit ?? '')
const sampleCount = computed(() => activeBins.value.reduce((acc, bin) => acc + bin.count, 0))

const logNote = computed(() => {
  if (props.profile !== 'resistivity') return ''
  if (log10.value) {
    const method = log10.value.method ?? '对数尺度分箱仅使用严格正值有限值'
    return `对数尺度展示：${method}；已排除非正值样本 ${formatNumber(log10.value.excludedNonPositiveCount)} 个。`
  }
  return 'RHO 当前展示原始值分箱；对数尺度展示将在电阻率专业模块就位后提供。'
})

const binLabels = computed(() =>
  activeBins.value.map((bin) => `${formatNumber(bin.lower)} – ${formatNumber(bin.upper)}`),
)

const peakBin = computed(() => {
  let peak = 0
  for (let i = 1; i < activeBins.value.length; i += 1) {
    if (activeBins.value[i].count > activeBins.value[peak].count) peak = i
  }
  return activeBins.value.length > 0 ? peak : -1
})

const summaryText = computed(() => {
  if (!usable.value) return ''
  const first = activeBins.value[0]
  const last = activeBins.value[activeBins.value.length - 1]
  const peak = peakBin.value >= 0 ? activeBins.value[peakBin.value] : null
  const peakText = peak
    ? `；峰值分箱 ${formatNumber(peak.lower)} – ${formatNumber(peak.upper)}（计数 ${formatNumber(peak.count)}）`
    : ''
  const scaleText = log10.value ? '对数尺度（log10）' : '原始值'
  const unitText = log10.value ? '' : ` ${unit.value}`
  return `${scaleText}分布：样本数 ${formatNumber(sampleCount.value)}，${activeBins.value.length} 分箱；值域 ${formatNumber(first.lower)} – ${formatNumber(last.upper)}${unitText}${peakText}`
})

const host = ref<HTMLDivElement | null>(null)
let chart: ReturnType<typeof echartsInit> | null = null

function buildOption() {
  const axisName = log10.value
    ? `log10（${props.variable.name}）`
    : `${props.variable.name}${unit.value ? `（${unit.value}）` : ''}`
  return {
    grid: { left: 56, right: 16, top: 16, bottom: 72 },
    xAxis: {
      type: 'category' as const,
      name: axisName,
      nameLocation: 'middle' as const,
      nameGap: 56,
      data: binLabels.value,
      axisLabel: { interval: Math.ceil(activeBins.value.length / 8), rotate: 30, fontSize: 10 },
    },
    yAxis: { type: 'value' as const, name: '样本数', minInterval: 1 },
    tooltip: {
      formatter: (param: { dataIndex: number; data: number }) => {
        const bin = activeBins.value[param.dataIndex]
        if (!bin) return ''
        return `${axisName} ${formatNumber(bin.lower)} – ${formatNumber(bin.upper)}<br/>样本数 ${bin.count}`
      },
    },
    series: [
      {
        type: 'bar' as const,
        name: '样本数',
        data: activeBins.value.map((bin) => bin.count),
        itemStyle: { color: '#4ea1ff' },
      },
    ],
  }
}

function render() {
  if (!usable.value) return
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
  () => props.module,
  () => render(),
  { flush: 'post' },
)

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <section class="panel distribution-panel" data-test="distribution-panel">
    <h3>{{ panelTitle }}</h3>
    <p v-if="logNote" class="log-note" data-test="distribution-log-note">{{ logNote }}</p>
    <template v-if="usable">
      <div ref="host" class="chart" data-test="distribution-chart" />
      <p class="chart-summary" data-test="distribution-summary">{{ summaryText }}</p>
    </template>
    <p v-else class="empty-note" data-test="distribution-empty">{{ emptyMessage }}</p>
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

h3 {
  margin: 0;
  font-size: 15px;
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

.log-note {
  margin: 0;
  font-size: 12px;
  color: var(--gmp-gold);
}

.empty-note {
  margin: 0;
  font-size: 13px;
  color: var(--gmp-text-faint);
}
</style>
