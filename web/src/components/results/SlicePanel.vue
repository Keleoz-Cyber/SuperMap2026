<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ApiError, fetchResultSlice } from '../../api/client'
import type { SliceResponse } from '../../api/types'
import Field2D from './Field2D.vue'

type Axis = 'x' | 'y' | 'z'

interface SourcePoints {
  x: number[]
  y: number[]
  values: number[]
}

const props = defineProps<{
  resultId: string
  dimension: '2d' | '3d'
  shape: number[]
  sourcePoints?: SourcePoints | null
}>()

// 2D 成果只有整场（合成 z=0）；3D 提供 Z 水平切片与 X/Y 垂直切片。
// 任意斜切不提供，也不在 UI 上暗示存在。
const availableAxes = computed<Axis[]>(() => (props.dimension === '3d' ? ['z', 'x', 'y'] : ['z']))

const AXIS_INDEX: Record<Axis, number> = { x: 0, y: 1, z: 2 }

const activeAxis = ref<Axis>('z')
const index = ref(0)
const slice = ref<SliceResponse | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

function axisSize(axis: Axis): number {
  if (props.dimension === '2d') return 1
  return props.shape[AXIS_INDEX[axis]] ?? 1
}

function middle(axis: Axis): number {
  return Math.max(0, Math.floor((axisSize(axis) - 1) / 2))
}

const maxIndex = computed(() => Math.max(0, axisSize(activeAxis.value) - 1))

const label = computed(() => {
  if (!slice.value) return ''
  const coordinate = Math.round(slice.value.fixed_coordinate * 1000) / 1000
  return `${activeAxis.value.toUpperCase()} = ${coordinate} m`
})

async function requestSlice() {
  loading.value = true
  error.value = null
  try {
    // 切片一律由服务端按持久化网格计算，浏览器不重采样
    slice.value = await fetchResultSlice(props.resultId, activeAxis.value, index.value)
  } catch (e) {
    error.value = e instanceof ApiError ? `${e.code}：${e.message}` : String(e)
    slice.value = null
  } finally {
    loading.value = false
  }
}

function selectAxis(axis: Axis) {
  activeAxis.value = axis
  index.value = middle(axis)
  void requestSlice()
}

watch(index, () => {
  void requestSlice()
})

onMounted(() => {
  index.value = middle(activeAxis.value)
  void requestSlice()
})
</script>

<template>
  <div class="slice-panel" data-test="slice-panel">
    <div class="slice-toolbar">
      <div class="axis-tabs">
        <button
          v-for="axis in availableAxes"
          :key="axis"
          class="axis-tab"
          :class="{ active: activeAxis === axis }"
          :data-test="`axis-${axis}`"
          @click="selectAxis(axis)"
        >
          {{ axis.toUpperCase() }} 切片
        </button>
      </div>
      <span class="slice-label" data-test="slice-label">{{ loading ? '加载中…' : label }}</span>
    </div>

    <input
      v-model.number="index"
      class="slice-slider"
      data-test="slice-slider"
      type="range"
      min="0"
      :max="maxIndex"
      step="1"
      :disabled="dimension === '2d'"
    />

    <div v-if="error" class="slice-error" data-test="slice-error">{{ error }}</div>
    <Field2D
      v-else-if="slice"
      :title="`${activeAxis.toUpperCase()} 切片`"
      :axes-names="slice.axes_names"
      :axes="slice.axes"
      :matrix="slice.matrix"
      :nodata-mask="slice.nodata_mask"
      :value-range="slice.value_range"
      :source-points="dimension === '2d' ? sourcePoints : null"
    />
  </div>
</template>

<style scoped>
.slice-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.slice-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.axis-tabs {
  display: flex;
  gap: 8px;
}

.axis-tab {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text-dim);
  border-radius: 8px;
  padding: 6px 14px;
  font-size: 12px;
  cursor: pointer;
}

.axis-tab.active {
  background: var(--gmp-accent);
  border-color: var(--gmp-accent);
  color: #0b0f14;
  font-weight: 600;
}

.slice-label {
  font-size: 13px;
  color: var(--gmp-accent);
  font-family: ui-monospace, monospace;
}

.slice-slider {
  width: 100%;
  accent-color: var(--gmp-accent);
}

.slice-error {
  border: 1px solid #a43d3d;
  background: rgba(164, 61, 61, 0.15);
  color: #ef9a9a;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
}
</style>
