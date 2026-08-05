<script setup lang="ts">
import { computed } from 'vue'
import type { ExperimentCreatePayload } from '../../api/types'
import { combinationCount, searchSpaceState } from './searchSpace'

const props = defineProps<{
  params: ExperimentCreatePayload
}>()

const algorithmLabel = computed(() => (props.params.algorithm === 'idw' ? 'IDW' : '普通克里金'))
const modeLabel = computed(() =>
  props.params.search_mode === 'manual' ? '单组参数（1 个候选）' : '参数网格（自动组合）',
)

const count = computed(() =>
  combinationCount(props.params.parameters ?? {}, props.params.search_mode ?? 'manual'),
)
const state = computed(() => searchSpaceState(count.value))

const parameterPreview = computed(() => {
  const entries = Object.entries(props.params.parameters ?? {})
  return entries
    .map(([key, value]) => `${key}=${Array.isArray(value) ? `[${value.join(', ')}]` : String(value)}`)
    .join('，')
})
</script>

<template>
  <section class="summary" data-test="search-summary">
    <div class="summary-line">
      <el-tag size="small" effect="dark" type="primary">{{ algorithmLabel }}</el-tag>
      <el-tag size="small" effect="plain">{{ modeLabel }}</el-tag>
      <span class="count" :class="state">{{ count }} 个候选组合</span>
      <span v-if="state === 'warn'" class="note warn">搜索规模较大</span>
      <span v-if="state === 'blocked'" class="note bad">超出 50 组合硬上限（后端将拒绝）</span>
    </div>
    <div class="summary-line dim">
      验证：{{ params.validation.method }} · {{ params.validation.folds }} 折 · 种子
      {{ params.validation.seed }} · 留出 {{ params.validation.holdout_fraction }}
    </div>
    <div class="summary-line dim mono">{{ parameterPreview }}</div>
  </section>
</template>

<style scoped>
.summary {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.summary-line {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  flex-wrap: wrap;
}

.summary-line.dim {
  color: var(--gmp-text-dim);
  font-size: 12px;
}

.mono {
  font-family: ui-monospace, monospace;
}

.count.warn {
  color: #e5c76b;
}

.count.blocked {
  color: #ef9a9a;
}

.note.warn {
  color: #e5c76b;
  font-size: 12px;
}

.note.bad {
  color: #ef9a9a;
  font-size: 12px;
}
</style>
