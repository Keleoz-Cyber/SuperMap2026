<script setup lang="ts">
// v0.9.0：单条证据结论卡。结论、证据、可信状态、限制与三维定位一体；
// 只有携带 spatialTarget 的结论才允许发出定位动作。
import { computed } from 'vue'
import { Aim } from '@element-plus/icons-vue'
import type { PresentationFinding } from '../../domain/findings'

const props = defineProps<{ finding: PresentationFinding }>()
const emit = defineEmits<{ locate: [finding: PresentationFinding] }>()

const CONFIDENCE_LABELS: Record<PresentationFinding['confidence'], string> = {
  verified: '已验证',
  exploratory: '探索性',
  insufficient: '证据不足',
  unavailable: '不可用',
}

const confidenceLabel = computed(() => CONFIDENCE_LABELS[props.finding.confidence])
</script>

<template>
  <article class="finding-card" :class="`is-${finding.confidence}`" data-test="finding-card">
    <header class="finding-head">
      <h4 class="finding-title">{{ finding.title }}</h4>
      <span class="confidence" :class="finding.confidence">{{ confidenceLabel }}</span>
    </header>
    <p class="finding-statement">{{ finding.statement }}</p>
    <div v-if="finding.evidence.length > 0" class="finding-evidence">
      <span v-for="item in finding.evidence" :key="item" class="evidence-chip">{{ item }}</span>
    </div>
    <ul class="finding-limitations">
      <li v-for="item in finding.limitations" :key="item">{{ item }}</li>
    </ul>
    <button
      v-if="finding.spatialTarget"
      type="button"
      class="locate-btn"
      data-test="finding-locate"
      @click="emit('locate', finding)"
    >
      <el-icon :size="13"><Aim /></el-icon>
      定位到三维
    </button>
  </article>
</template>

<style scoped>
.finding-card {
  border: 1px solid var(--s1-border);
  border-left: 3px solid var(--s1-case-accent);
  border-radius: var(--s1-radius-sm);
  background: var(--s1-surface-2);
  padding: var(--s1-space-3);
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-2);
}

.finding-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s1-space-2);
}

.finding-title {
  margin: 0;
  font-size: var(--s1-font-md);
  font-weight: 600;
  color: var(--s1-text-strong);
}

.confidence {
  font-size: var(--s1-font-sm);
  border-radius: 999px;
  padding: 1px 8px;
  border: 1px solid var(--s1-border);
  color: var(--s1-text-dim);
  white-space: nowrap;
}

.confidence.verified {
  color: var(--s1-success);
  border-color: rgba(70, 185, 124, 0.4);
}

.confidence.exploratory {
  color: var(--s1-warning);
  border-color: rgba(217, 168, 78, 0.4);
}

.finding-statement {
  margin: 0;
  font-size: var(--s1-font-md);
  line-height: var(--s1-leading);
  color: var(--s1-text);
}

.finding-evidence {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.evidence-chip {
  font-size: var(--s1-font-sm);
  color: var(--s1-cyan-strong);
  background: var(--s1-cyan-ghost);
  border-radius: 6px;
  padding: 2px 8px;
  font-variant-numeric: tabular-nums;
}

.finding-limitations {
  margin: 0;
  padding: 0 0 0 14px;
  font-size: var(--s1-font-sm);
  color: var(--s1-text-faint);
  line-height: 1.5;
}

.locate-btn {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--s1-font-sm);
  color: var(--s1-cyan-strong);
  background: transparent;
  border: 1px solid var(--s1-cyan-dim);
  border-radius: 6px;
  padding: 3px 10px;
  cursor: pointer;
  transition: background var(--s1-motion-fast) var(--s1-ease-out);
}

.locate-btn:hover {
  background: var(--s1-cyan-ghost);
}
</style>
