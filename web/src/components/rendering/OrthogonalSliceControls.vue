<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import type { SliceAxis } from '../../api/types'

// v0.7.0 Batch 2 Task 9：正交切片控制（设计 §7.2/§7.3）。
// 只在 slice 模式渲染；轴选择/前后层/整数滑块；初次进入每轴默认
// floor((length-1)/2)；到达轴首尾禁用对应按钮，不循环。
// 控件绝不计算 SDK 相对位置（该值只来自权威剖面响应）。

export interface SliceAxisMeta {
  length: number
  coordinates: number[]
  unit: string
}

const props = defineProps<{
  mode: 'volume' | 'slice' | 'contour'
  axes: Record<SliceAxis, SliceAxisMeta>
}>()

const emit = defineEmits<{
  change: [payload: { axis: SliceAxis; index: number; coordinate: number }]
  commit: [payload: { axis: SliceAxis; index: number }]
}>()

const AXES: SliceAxis[] = ['x', 'y', 'z']

const currentAxis = ref<SliceAxis>('z')
// 每轴独立的当前索引（切轴恢复该轴自己的选择）
const indices = reactive<Record<SliceAxis, number>>({ x: 0, y: 0, z: 0 })
let initialized = false

function defaultIndex(axis: SliceAxis): number {
  return Math.floor((props.axes[axis].length - 1) / 2)
}

if (!initialized) {
  for (const axis of AXES) indices[axis] = defaultIndex(axis)
  initialized = true
}

watch(
  () => props.axes,
  () => {
    for (const axis of AXES) {
      indices[axis] = Math.min(indices[axis], props.axes[axis].length - 1)
    }
  },
)

const visible = computed(() => props.mode === 'slice')
const currentIndex = computed(() => indices[currentAxis.value])
const currentCoordinate = computed(
  () => props.axes[currentAxis.value].coordinates[currentIndex.value],
)
const atStart = computed(() => currentIndex.value <= 0)
const atEnd = computed(() => currentIndex.value >= props.axes[currentAxis.value].length - 1)
const sliderMax = computed(() => props.axes[currentAxis.value].length - 1)

function axisLabel(axis: SliceAxis): string {
  return axis.toUpperCase()
}

function selectAxis(axis: SliceAxis) {
  currentAxis.value = axis
  emit('change', { axis, index: indices[axis], coordinate: props.axes[axis].coordinates[indices[axis]] })
  emit('commit', { axis, index: indices[axis] })
}

function step(delta: number) {
  const axis = currentAxis.value
  const next = Math.min(props.axes[axis].length - 1, Math.max(0, indices[axis] + delta))
  if (next === indices[axis]) return
  indices[axis] = next
  emit('change', { axis, index: next, coordinate: props.axes[axis].coordinates[next] })
  emit('commit', { axis, index: next })
}

const sliderModel = computed<number>({
  get: () => currentIndex.value,
  set: (value) => {
    const axis = currentAxis.value
    const next = Math.min(props.axes[axis].length - 1, Math.max(0, Math.round(value)))
    if (next === indices[axis]) return
    indices[axis] = next
    emit('change', { axis, index: next, coordinate: props.axes[axis].coordinates[next] })
  },
})

function onSliderCommit() {
  emit('commit', { axis: currentAxis.value, index: currentIndex.value })
}
</script>

<template>
  <div v-if="visible" class="slice-controls" data-test="slice-controls">
    <el-radio-group v-model="currentAxis" size="small" data-test="axis-segment">
      <el-radio-button
        v-for="axis in AXES"
        :key="axis"
        :value="axis"
        :data-test="`axis-${axis}`"
        @click="selectAxis(axis)"
      >
        {{ axisLabel(axis) }}
      </el-radio-button>
    </el-radio-group>

    <el-button
      size="small"
      :icon="ArrowLeft"
      :disabled="atStart"
      data-test="slice-prev"
      @click="step(-1)"
    />
    <el-slider
      v-model="sliderModel"
      class="slice-slider"
      :min="0"
      :max="sliderMax"
      :step="1"
      :show-tooltip="false"
      data-test="slice-slider"
      @change="onSliderCommit"
    />
    <el-button
      size="small"
      :icon="ArrowRight"
      :disabled="atEnd"
      data-test="slice-next"
      @click="step(1)"
    />

    <span class="slice-index" data-test="slice-index-value">{{ currentIndex }}</span>
    <span class="slice-coordinate" data-test="slice-coordinate">
      {{ currentAxis.toUpperCase() }} = {{ currentCoordinate }} {{ props.axes[currentAxis].unit }}
    </span>
  </div>
</template>

<style scoped>
.slice-controls {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.slice-slider {
  flex: 1;
  min-width: 160px;
}
.slice-index {
  font-family: ui-monospace, monospace;
  min-width: 2em;
  text-align: right;
}
.slice-coordinate {
  color: var(--gmp-text-dim);
  font-size: 12px;
}
</style>
