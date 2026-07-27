<script setup lang="ts">
import { onMounted, ref, shallowRef } from 'vue'
import { fetchVoxelCells } from '../api/client'
import type { VoxelCells } from '../api/types'
import VolumeRenderer from '../components/volume/VolumeRenderer.vue'
import {
  buildSourceVolume,
  packVolumeTexture,
  resampleVolume,
  type PackedVolume,
} from '../components/volume/volumeGrid'

type LoadState = 'loading' | 'ready' | 'failed'
const state = ref<LoadState>('loading')
const error = ref('')
const packed = shallowRef<PackedVolume | null>(null)
const sourceData = shallowRef<VoxelCells | null>(null)
const threshold = ref(0.18)
const opacity = ref(0.55)

onMounted(async () => {
  try {
    const data = await fetchVoxelCells()
    const source = buildSourceVolume(data)
    const target = resampleVolume(source)
    sourceData.value = data
    packed.value = packVolumeTexture(target)
    state.value = 'ready'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
    state.value = 'failed'
  }
})

function onRendererError(message: string) {
  error.value = message
  state.value = 'failed'
  packed.value = null
}
</script>

<template>
  <main class="volume-demo-page" data-test="volume-demo-page">
    <header>
      <h1>连续体渲染验证</h1>
      <p data-test="visualization-disclaimer">
        数据来自 RHO_KRIG_FINAL_20M_40 的 S3M 缓存采样；纹理经过仅用于显示的三线性可视化重采样，
        不是新的正式模型，也不是 VOLUME 精确逐单元导出。
      </p>
    </header>

    <el-skeleton v-if="state === 'loading'" :rows="8" animated data-test="volume-loading" />
    <el-alert
      v-else-if="state === 'failed'"
      type="error"
      :closable="false"
      :title="error"
      data-test="volume-error"
    />
    <section v-else-if="packed && sourceData" class="volume-layout">
      <div class="volume-canvas-panel">
        <VolumeRenderer
          :grid="packed"
          :threshold="threshold"
          :opacity="opacity"
          @error="onRendererError"
        />
      </div>
      <aside class="volume-controls">
        <p><strong>成果：</strong>{{ sourceData.result_id }}</p>
        <p data-test="source-shape"><strong>源采样：</strong>7 × 21 × 48 / 7,056</p>
        <p data-test="target-shape"><strong>显示纹理：</strong>7 × 23 × 42 / 6,762</p>
        <p><strong>采样值域：</strong>{{ sourceData.value_range[0] }}–{{ sourceData.value_range[1] }}</p>
        <p><strong>坐标：</strong>局部坐标，不可跨案例叠加</p>
        <label for="volume-threshold">强度阈值 {{ threshold.toFixed(2) }}</label>
        <input id="volume-threshold" v-model.number="threshold" type="range" min="0" max="0.95" step="0.01" data-test="volume-threshold" />
        <label for="volume-opacity">总体透明度 {{ opacity.toFixed(2) }}</label>
        <input id="volume-opacity" v-model.number="opacity" type="range" min="0.05" max="1" step="0.05" data-test="volume-opacity" />
      </aside>
    </section>
  </main>
</template>

<style scoped>
.volume-demo-page {
  min-height: 100%;
  padding: 20px;
}

.volume-demo-page h1 {
  margin: 0 0 8px;
  font-size: 20px;
  color: var(--gmp-text);
}

.volume-demo-page header p {
  margin: 0 0 16px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--gmp-text-dim);
}

.volume-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 16px;
  align-items: start;
}

.volume-canvas-panel {
  background: var(--gmp-panel);
  border: 1px solid var(--gmp-border);
  border-radius: 8px;
  overflow: hidden;
}

.volume-controls {
  background: var(--gmp-panel);
  border: 1px solid var(--gmp-border);
  border-radius: 8px;
  padding: 16px;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.volume-controls p {
  margin: 0 0 8px;
  line-height: 1.5;
}

.volume-controls strong {
  color: var(--gmp-text);
  font-weight: 600;
}

.volume-controls label {
  display: block;
  margin: 12px 0 4px;
  color: var(--gmp-text);
}

.volume-controls input[type='range'] {
  width: 100%;
  accent-color: var(--gmp-accent);
}

@media (max-width: 900px) {
  .volume-layout {
    grid-template-columns: 1fr;
  }
}
</style>
