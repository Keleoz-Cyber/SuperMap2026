<script setup lang="ts">
// v0.9.0 Task 6：统一 ECharts 容器。负责 init/setOption/watch/dispose 全生命周期；
// 卸载或标签切换即 dispose，绝不泄漏图表实例。option 为 null 时不初始化。
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { init as echartsInit, use as echartsUse } from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echartsUse([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ option: Record<string, unknown> }>()

const host = ref<HTMLDivElement | null>(null)
let chart: ReturnType<typeof echartsInit> | null = null

onMounted(() => {
  if (!host.value) return
  chart = echartsInit(host.value)
  chart.setOption(props.option)
})

watch(
  () => props.option,
  (option) => {
    chart?.setOption(option, true)
  },
  { deep: true },
)

onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="host" class="echart-box" />
</template>

<style scoped>
.echart-box {
  width: 100%;
  height: 200px;
}
</style>
