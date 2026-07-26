<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import {
  ApiError,
  fetchResultPreview,
  fetchResultUncertainty,
} from '../../api/client'
import type {
  ProfessionalCapabilities,
  UncertaintyLayerKind,
} from '../../api/types'

// 不确定性图层的值域/图例与预测值完全分开（§13.4）：三种图层各自独立
// 标题与值域；「不适用」是类型化状态——IDW 的 Kriging 标准差只显示
// not-applicable 提示，绝不请求、绝不伪造 0 场。
const props = defineProps<{
  resultId: string
  capabilities?: ProfessionalCapabilities | null
}>()

type LayerKey = 'value' | UncertaintyLayerKind

interface LayerData {
  title: string
  valueRange: [number | null, number | null]
  points: Array<{ x: number; y: number; value: number }>
  served: number
  total: number
}

const LAYER_TITLES: Record<LayerKey, string> = {
  value: '预测值',
  empirical_error: '经验误差尺度 (empirical_error)',
  kriging_std: 'Kriging 标准差 (kriging_std)',
}

// 不确定性颜色表与预测值颜色表分开（§13.4）
const VALUE_COLORS = ['#2b6cb0', '#38b2ac', '#faf089', '#dd6b20', '#c53030']
const UNCERTAINTY_COLORS = ['#443983', '#31688e', '#21918c', '#5ec962', '#fde725']

const activeLayer = ref<LayerKey>('value')
const layerData = ref<LayerData | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

const krigingStdNotApplicable = computed(
  () => props.capabilities?.native_kriging_std === 'not_applicable',
)

const layerColors = computed(() =>
  activeLayer.value === 'value' ? VALUE_COLORS : UNCERTAINTY_COLORS,
)

function describeError(e: unknown): string {
  if (e instanceof ApiError) return `${e.code}：${e.message}`
  return e instanceof Error ? e.message : String(e)
}

function toLayerData(
  title: string,
  body: {
    x: number[]
    y: number[]
    values: number[]
    is_nodata: boolean[]
    value_range: [number | null, number | null]
    served_cell_count: number
    original_cell_count: number
  },
): LayerData {
  const points: Array<{ x: number; y: number; value: number }> = []
  for (let i = 0; i < body.x.length; i += 1) {
    // NoData 不使用 0 着色（§13.4）：直接不进入散点集合
    if (body.is_nodata[i]) continue
    const value = body.values[i]
    if (!Number.isFinite(value)) continue
    points.push({ x: body.x[i], y: body.y[i], value })
  }
  return {
    title,
    valueRange: body.value_range,
    points,
    served: body.served_cell_count,
    total: body.original_cell_count,
  }
}

async function loadLayer(layer: LayerKey) {
  // 能力不适用是类型化状态：清空数据、显示提示，绝不发起请求
  if (layer === 'kriging_std' && krigingStdNotApplicable.value) {
    layerData.value = null
    error.value = null
    loading.value = false
    return
  }
  loading.value = true
  error.value = null
  const requestId = props.resultId
  try {
    if (layer === 'value') {
      const preview = await fetchResultPreview(requestId)
      if (props.resultId !== requestId || activeLayer.value !== layer) return
      layerData.value = toLayerData(LAYER_TITLES[layer], preview)
    } else {
      const uncertainty = await fetchResultUncertainty(requestId, layer)
      if (props.resultId !== requestId || activeLayer.value !== layer) return
      layerData.value = toLayerData(LAYER_TITLES[layer], uncertainty)
    }
  } catch (e) {
    if (props.resultId !== requestId) return
    error.value = describeError(e)
    layerData.value = null
  } finally {
    if (props.resultId === requestId) loading.value = false
  }
}

function selectLayer(layer: LayerKey) {
  activeLayer.value = layer
  void loadLayer(layer)
}

const chartEl = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

function render() {
  if (!chartEl.value) return
  if (!chart) {
    try {
      chart = echarts.init(chartEl.value, undefined, { renderer: 'svg' })
    } catch {
      return // 无图形环境（如 jsdom 降级）：图例与值域文本仍然可见
    }
  }
  const data = layerData.value
  const range: [number, number] = [
    data?.valueRange[0] ?? 0,
    data?.valueRange[1] ?? 1,
  ]
  chart.setOption(
    {
      title: {
        text: data?.title ?? '',
        textStyle: { fontSize: 12, color: '#c9d4e0' },
      },
      grid: { left: 70, right: 30, top: 44, bottom: 50 },
      xAxis: { type: 'value', name: 'x', axisLabel: { color: '#8fa1b3', fontSize: 10 } },
      yAxis: { type: 'value', name: 'y', axisLabel: { color: '#8fa1b3', fontSize: 10 } },
      visualMap: {
        dimension: 2,
        min: range[0],
        max: range[0] === range[1] ? range[0] + 1 : range[1],
        calculable: true,
        orient: 'horizontal',
        left: 'center',
        bottom: 4,
        textStyle: { color: '#8fa1b3', fontSize: 10 },
        inRange: { color: layerColors.value },
      },
      series: [
        {
          type: 'scatter',
          symbolSize: 6,
          data: (data?.points ?? []).map((p) => ({ value: [p.x, p.y, p.value] })),
        },
      ],
      tooltip: { trigger: 'item' },
    },
    { notMerge: true },
  )
  chart.resize()
}

function formatRangeValue(value: number | null): string {
  return value === null ? '—' : String(value)
}

const rangeText = computed(() => {
  const range = layerData.value?.valueRange
  if (!range) return ''
  return `${formatRangeValue(range[0])} ~ ${formatRangeValue(range[1])}`
})

// 候选切换：图层数据一律以新 result ID 重新请求，绝不复用旧候选缓存
watch(
  () => props.resultId,
  () => {
    layerData.value = null
    void loadLayer(activeLayer.value)
  },
)
watch([layerData, layerColors], render, { flush: 'post' })

onMounted(() => {
  void loadLayer(activeLayer.value)
  render()
})
onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>

<template>
  <section class="uncertainty-panel" data-test="uncertainty-panel">
    <header class="panel-head">
      <h3>误差与不确定性</h3>
      <div class="layer-tabs">
        <button
          class="layer-tab"
          :class="{ active: activeLayer === 'value' }"
          data-test="layer-tab-value"
          @click="selectLayer('value')"
        >
          预测值
        </button>
        <button
          class="layer-tab"
          :class="{ active: activeLayer === 'empirical_error' }"
          data-test="layer-tab-empirical"
          @click="selectLayer('empirical_error')"
        >
          经验误差尺度
        </button>
        <button
          class="layer-tab"
          :class="{ active: activeLayer === 'kriging_std' }"
          data-test="layer-tab-kriging-std"
          @click="selectLayer('kriging_std')"
        >
          Kriging 标准差
        </button>
      </div>
    </header>

    <div
      v-if="activeLayer === 'kriging_std' && krigingStdNotApplicable"
      class="not-applicable"
      data-test="kriging-std-na"
    >
      Kriging standard deviation not applicable
    </div>

    <template v-else>
      <div v-if="error" class="layer-error" data-test="layer-error">{{ error }}</div>
      <div v-else class="layer-legend">
        <span data-test="layer-title">{{ layerData?.title ?? LAYER_TITLES[activeLayer] }}</span>
        <span v-if="layerData" data-test="layer-value-range">值域 {{ rangeText }}</span>
        <span v-if="layerData" class="layer-served">
          抽稀 {{ layerData.served }} / {{ layerData.total }} 单元
        </span>
        <span v-if="loading" class="layer-loading">加载中…</span>
      </div>
      <div ref="chartEl" class="layer-chart" data-test="uncertainty-chart" />
    </template>
  </section>
</template>

<style scoped>
.uncertainty-panel {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.panel-head h3 {
  margin: 0;
  font-size: 15px;
}

.layer-tabs {
  display: flex;
  gap: 8px;
}

.layer-tab {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text-dim);
  border-radius: 8px;
  padding: 5px 14px;
  font-size: 12px;
  cursor: pointer;
}

.layer-tab.active {
  background: var(--gmp-accent);
  border-color: var(--gmp-accent);
  color: #0b0f14;
  font-weight: 600;
}

.not-applicable {
  border: 1px solid #9a7b2d;
  background: rgba(154, 123, 45, 0.12);
  color: #e5c76b;
  border-radius: 10px;
  padding: 12px 16px;
  font-size: 13px;
  font-family: ui-monospace, monospace;
}

.layer-error {
  border: 1px solid #a43d3d;
  background: rgba(164, 61, 61, 0.15);
  color: #ef9a9a;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
}

.layer-legend {
  display: flex;
  align-items: baseline;
  gap: 16px;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.layer-served,
.layer-loading {
  color: var(--gmp-text-faint);
}

.layer-chart {
  width: 100%;
  height: 320px;
  background: var(--gmp-bg-soft);
  border: 1px solid var(--gmp-border);
  border-radius: 10px;
}
</style>
