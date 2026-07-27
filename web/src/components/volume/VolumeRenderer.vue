<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { PackedVolume } from './volumeGrid'
import { createVolumeRuntime, type VolumeRuntime } from './volumeRuntime'

const props = defineProps<{
  grid: PackedVolume
  threshold: number
  opacity: number
}>()
const emit = defineEmits<{ error: [message: string] }>()
const container = ref<HTMLElement | null>(null)
let runtime: VolumeRuntime | null = null

onMounted(() => {
  if (!container.value) return
  try {
    runtime = createVolumeRuntime(container.value, props.grid, props.threshold, props.opacity)
  } catch (error) {
    emit('error', error instanceof Error ? error.message : String(error))
  }
})

watch(() => props.threshold, (value) => runtime?.setThreshold(value))
watch(() => props.opacity, (value) => runtime?.setOpacity(value))

onBeforeUnmount(() => {
  runtime?.dispose()
  runtime = null
})
</script>

<template>
  <div ref="container" class="volume-renderer" data-test="volume-renderer"></div>
</template>

<style scoped>
.volume-renderer {
  min-height: 560px;
  width: 100%;
}
</style>
