<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ResultPreview } from '../../api/types'

const props = defineProps<{
  preview: ResultPreview | null
}>()

const containerEl = ref<HTMLDivElement | null>(null)
const cesiumAvailable = typeof window !== 'undefined' && Boolean((window as { Cesium?: unknown }).Cesium)
const pointsVisible = ref(true)
const renderError = ref<string | null>(null)

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let viewer: any = null
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let pointCollection: any = null

const validCount = computed(() => {
  if (!props.preview) return 0
  return props.preview.is_nodata.filter((n) => !n).length
})

function colorFor(value: number, lo: number, hi: number) {
  const t = hi > lo ? (value - lo) / (hi - lo) : 0.5
  // 与 2D 热力图同向的蓝→青色→黄→红渐变
  const hue = (1 - Math.min(Math.max(t, 0), 1)) * 220
  return Cesium.Color.fromHsl(hue / 360, 0.75, 0.55, 0.95)
}

// v0.3.1 实证结论：本机 Cesium 1.67 的 PointPrimitiveCollection.show 无效，
// 可见性切换一律 removeAll + 内存数据重建，不依赖 .show。
function rebuildPoints() {
  if (!pointCollection || !props.preview) return
  pointCollection.removeAll()
  if (!pointsVisible.value) return
  const { x, y, z, values, is_nodata: nodata, value_range: range } = props.preview
  const lo = range[0] ?? 0
  const hi = range[1] ?? 1
  for (let i = 0; i < x.length; i += 1) {
    if (nodata[i]) continue
    pointCollection.add({
      position: Cesium.Cartesian3.fromDegrees(x[i], y[i], z?.[i] ?? 0),
      pixelSize: 5,
      color: colorFor(values[i], lo, hi),
    })
  }
}

function togglePoints() {
  pointsVisible.value = !pointsVisible.value
  rebuildPoints()
}

function initViewer() {
  if (!cesiumAvailable || !containerEl.value || viewer) return
  try {
    viewer = new Cesium.Viewer(containerEl.value, {
      animation: false,
      timeline: false,
      baseLayerPicker: false,
      geocoder: false,
      sceneModePicker: false,
      navigationHelpButton: false,
    })
    pointCollection = viewer.scene.primitives.add(new Cesium.PointPrimitiveCollection())
    rebuildPoints()
  } catch (e) {
    renderError.value = e instanceof Error ? e.message : String(e)
  }
}

onMounted(initViewer)
watch(() => props.preview, rebuildPoints)
onBeforeUnmount(() => {
  if (viewer && !(viewer.isDestroyed?.() ?? false)) viewer.destroy?.()
  viewer = null
  pointCollection = null
})
</script>

<template>
  <div class="field-3d" data-test="field-3d">
    <div class="field-3d-toolbar">
      <span data-test="preview-count">
        完整场点云 {{ preview?.served_cell_count ?? 0 }} / {{ preview?.original_cell_count ?? 0 }} 单元
        <template v-if="preview && preview.stride > 1">（抽稀步长 {{ preview.stride }}）</template>
      </span>
      <button v-if="cesiumAvailable" class="gmp-btn" data-test="toggle-points" @click="togglePoints">
        {{ pointsVisible ? '隐藏点云' : '显示点云' }}
      </button>
    </div>
    <div v-if="!cesiumAvailable" class="cesium-fallback" data-test="cesium-fallback">
      当前环境无 Cesium 运行时，三维点云渲染不可用；有效单元 {{ validCount }} 个，请通过切片查看数值。
    </div>
    <div v-else-if="renderError" class="cesium-fallback" data-test="cesium-error">{{ renderError }}</div>
    <div v-show="cesiumAvailable" ref="containerEl" class="cesium-container" data-test="cesium-container" />
  </div>
</template>

<style scoped>
.field-3d {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-3d-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.cesium-container {
  width: 100%;
  height: 480px;
  border: 1px solid var(--gmp-border);
  border-radius: 10px;
  overflow: hidden;
}

.cesium-fallback {
  border: 1px dashed var(--gmp-border);
  border-radius: 10px;
  padding: 22px;
  font-size: 13px;
  color: var(--gmp-text-dim);
  text-align: center;
}

.gmp-btn {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text);
  border-radius: 8px;
  padding: 6px 14px;
  font-size: 12px;
  cursor: pointer;
}
</style>
