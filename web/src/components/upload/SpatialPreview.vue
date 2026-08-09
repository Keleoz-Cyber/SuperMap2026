<script setup lang="ts">
// v0.9.0：数据接入空间预览。只用映射列的有限值渲染 XY 散点；
// 映射未完成时显示解释性引导，绝不渲染伪造散点。
import { computed } from 'vue'
import type { InspectionResult } from '../../api/types'

export interface SpatialMapping {
  x: string
  y: string
  z?: string | null
  value?: string | null
}

// 直接点输入（实验画布复用）：与 preview_rows+mapping 二选一
export interface SpatialPointInput {
  x: number
  y: number
  z?: number | null
}

const props = defineProps<{
  inspection?: InspectionResult | null
  mapping?: SpatialMapping | null
  points?: SpatialPointInput[] | null
  // 直接点模式下的总行数说明（如抽稀前的全量行数）
  totalRows?: number | null
}>()

interface PreviewPoint {
  x: number
  y: number
  z: number | null
}

const points = computed<PreviewPoint[]>(() => {
  if (props.points && props.points.length > 0) {
    return props.points
      .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y))
      .map((p) => ({
        x: p.x,
        y: p.y,
        z: typeof p.z === 'number' && Number.isFinite(p.z) ? p.z : null,
      }))
  }
  const mapping = props.mapping
  if (!mapping?.x || !mapping.y || !props.inspection) return []
  const rows = props.inspection.preview_rows ?? []
  const out: PreviewPoint[] = []
  for (const row of rows) {
    const x = Number(row[mapping.x])
    const y = Number(row[mapping.y])
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue
    const z = mapping.z ? Number(row[mapping.z]) : null
    out.push({ x, y, z: z !== null && Number.isFinite(z) ? z : null })
  }
  return out
})

const extent = computed(() => {
  if (points.value.length === 0) return null
  const xs = points.value.map((p) => p.x)
  const ys = points.value.map((p) => p.y)
  const zs = points.value.map((p) => p.z).filter((z): z is number => z !== null)
  return {
    x: [Math.min(...xs), Math.max(...xs)] as [number, number],
    y: [Math.min(...ys), Math.max(...ys)] as [number, number],
    z: zs.length > 0 ? ([Math.min(...zs), Math.max(...zs)] as [number, number]) : null,
  }
})

// SVG 视口坐标映射（留边距，零跨度轴退化为中心线）
const W = 320
const H = 220
const PAD = 18

const positioned = computed(() => {
  const ext = extent.value
  if (!ext) return []
  const spanX = ext.x[1] - ext.x[0]
  const spanY = ext.y[1] - ext.y[0]
  return points.value.map((p) => ({
    cx: PAD + (spanX > 0 ? ((p.x - ext.x[0]) / spanX) * (W - 2 * PAD) : (W - 2 * PAD) / 2),
    cy: H - PAD - (spanY > 0 ? ((p.y - ext.y[0]) / spanY) * (H - 2 * PAD) : (H - 2 * PAD) / 2),
  }))
})

function fmt(v: number): string {
  return Math.abs(v) >= 1000 ? v.toFixed(0) : String(Math.round(v * 100) / 100)
}
</script>

<template>
  <section class="spatial-preview" data-test="spatial-preview-panel">
    <h4 class="preview-title">空间预览</h4>
    <div v-if="points.length === 0" class="preview-empty" data-test="spatial-preview-empty">
      <p>完成字段映射后，此处显示测点空间分布预览</p>
      <p class="empty-note">预览只使用映射列的有限数值，用于发现范围与疑似错位点。</p>
    </div>
    <template v-else>
      <svg
        :viewBox="`0 0 ${W} ${H}`"
        class="preview-svg"
        data-test="spatial-preview"
        role="img"
        :aria-label="`测点空间分布预览，共 ${points.length} 个预览点`"
      >
        <rect :width="W" :height="H" class="preview-frame" />
        <circle
          v-for="(p, i) in positioned"
          :key="i"
          :cx="p.cx"
          :cy="p.cy"
          r="3"
          class="preview-point"
          data-test="spatial-point"
        />
      </svg>
      <div v-if="extent" class="preview-extent">
        <p>X ∈ [{{ fmt(extent.x[0]) }}, {{ fmt(extent.x[1]) }}] · Y ∈ [{{ fmt(extent.y[0]) }}, {{ fmt(extent.y[1]) }}]</p>
        <p v-if="extent.z" data-test="spatial-z-range">Z ∈ [{{ fmt(extent.z[0]) }}, {{ fmt(extent.z[1]) }}]</p>
        <p class="extent-note">预览点 {{ points.length }}<template v-if="totalRows !== null && totalRows !== undefined"> / 共 {{ totalRows }} 行</template><template v-else-if="inspection"> / {{ inspection.row_count }} 行</template></p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.spatial-preview {
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-1);
  padding: var(--s1-space-3);
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-2);
}

.preview-title {
  margin: 0;
  font-size: var(--s1-font-sm);
  font-weight: 600;
  color: var(--s1-text-dim);
  letter-spacing: 0.05em;
}

.preview-empty {
  border: 1px dashed var(--s1-border);
  border-radius: var(--s1-radius-sm);
  padding: var(--s1-space-4);
  text-align: center;
  color: var(--s1-text-dim);
  font-size: var(--s1-font-sm);
}

.preview-empty p {
  margin: 0;
}

.empty-note {
  margin-top: 6px !important;
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
}

.preview-svg {
  width: 100%;
  height: auto;
  background:
    linear-gradient(var(--s1-stage-grid) 1px, transparent 1px) 0 0 / 100% 25%,
    linear-gradient(90deg, var(--s1-stage-grid) 1px, transparent 1px) 0 0 / 25% 100%,
    var(--s1-canvas-soft);
  border-radius: var(--s1-radius-sm);
}

.preview-frame {
  fill: none;
  stroke: var(--s1-border);
}

.preview-point {
  fill: var(--s1-cyan);
  fill-opacity: 0.85;
}

.preview-extent {
  font-size: var(--s1-font-xs);
  color: var(--s1-text-dim);
  font-variant-numeric: tabular-nums;
}

.preview-extent p {
  margin: 2px 0;
}

.extent-note {
  color: var(--s1-text-faint);
}
</style>
