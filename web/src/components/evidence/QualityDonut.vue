<script setup lang="ts">
// v0.9.0：质量组成环图（唯一允许的环图口径：有效/无效/未判定 部分-整体）。
// 输入必须可加总到声明总量，否则显示类型化 nodata，绝不渲染失真环图。
import { computed } from 'vue'

const props = defineProps<{
  valid: number | null
  invalid: number | null
  total: number | null
  // 可选第三段：未判定/缺失行数；缺省按 total - valid - invalid 推导
  missing?: number | null
}>()

const finite = (v: number | null | undefined): v is number => typeof v === 'number' && Number.isFinite(v)

const parts = computed(() => {
  if (!finite(props.valid) || !finite(props.invalid) || !finite(props.total) || props.total <= 0) {
    return null
  }
  const missing = finite(props.missing) ? props.missing : props.total - props.valid - props.invalid
  if (missing < 0) return null
  if (props.valid + props.invalid + missing !== props.total) return null
  return {
    valid: props.valid,
    invalid: props.invalid,
    missing,
    total: props.total,
    ratio: props.valid / props.total,
  }
})

const donutDash = computed(() => {
  if (!parts.value) return '0 100'
  const pct = parts.value.ratio * 100
  return `${pct} ${100 - pct}`
})
</script>

<template>
  <div class="quality-donut-wrap">
    <div v-if="parts" class="quality-donut" data-test="quality-donut">
      <svg viewBox="0 0 42 42" class="donut" role="img" :aria-label="`有效数据占比 ${(parts.ratio * 100).toFixed(1)}%`">
        <circle class="track" cx="21" cy="21" r="15.9155" />
        <circle class="valid-arc" cx="21" cy="21" r="15.9155" :stroke-dasharray="donutDash" />
        <text x="21" y="23.5" class="donut-text">{{ Math.round(parts.ratio * 100) }}%</text>
      </svg>
      <div class="legend">
        <span><i class="swatch valid" />有效 {{ parts.valid }}</span>
        <span><i class="swatch invalid" />无效 {{ parts.invalid }}</span>
        <span v-if="parts.missing > 0"><i class="swatch missing" />未判定 {{ parts.missing }}</span>
        <span class="total">共 {{ parts.total }} 行</span>
      </div>
    </div>
    <p v-else class="donut-nodata" data-test="quality-donut-nodata">
      质量计数不一致或不可用，环图未渲染。
    </p>
  </div>
</template>

<style scoped>
.quality-donut {
  display: flex;
  align-items: center;
  gap: var(--s1-space-3);
}

.donut {
  width: 72px;
  height: 72px;
}

.track {
  fill: none;
  stroke: var(--s1-surface-3);
  stroke-width: 5;
}

.valid-arc {
  fill: none;
  stroke: var(--s1-cyan);
  stroke-width: 5;
  stroke-linecap: round;
  transform: rotate(-90deg);
  transform-origin: center;
  transition: stroke-dasharray var(--s1-motion-panel) var(--s1-ease-out);
}

.donut-text {
  fill: var(--s1-text-strong);
  font-size: 12px;
  font-weight: 700;
  text-anchor: middle;
  font-variant-numeric: tabular-nums;
}

.legend {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: var(--s1-font-xs);
  color: var(--s1-text-dim);
}

.swatch {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 2px;
  margin-right: 5px;
}

.swatch.valid {
  background: var(--s1-cyan);
}

.swatch.invalid {
  background: var(--s1-error);
}

.swatch.missing {
  background: var(--s1-surface-3);
}

.total {
  color: var(--s1-text-faint);
}

.donut-nodata {
  margin: 0;
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
  border: 1px dashed var(--s1-border);
  border-radius: var(--s1-radius-sm);
  padding: var(--s1-space-3);
}
</style>
