<script setup lang="ts">
// v0.9.0：案例工作台四阶段导航。阶段是用户认知层：数据概览 / 建模实验 /
// 成果分析 / 证据与报告。禁用阶段保留可见并说明原因；只发出命名导航
// 意图，绝不从标签拼 URL。
export type CaseStageId = 'data' | 'experiments' | 'results' | 'evidence'

export interface CaseStage {
  id: CaseStageId
  enabled: boolean
  reason?: string | null
}

const props = defineProps<{
  stages: CaseStage[]
  current: CaseStageId
}>()

const emit = defineEmits<{ navigate: [stage: CaseStageId] }>()

const STAGE_LABELS: Record<CaseStageId, string> = {
  data: '数据概览',
  experiments: '建模实验',
  results: '成果分析',
  evidence: '证据与报告',
}

function onSelect(stage: CaseStage) {
  if (!stage.enabled) return
  emit('navigate', stage.id)
}

function onKeydown(event: KeyboardEvent) {
  const enabled = props.stages.filter((stage) => stage.enabled)
  const currentIndex = Math.max(0, enabled.findIndex((stage) => stage.id === props.current))
  let nextIndex: number | null = null
  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
    nextIndex = (currentIndex + 1) % enabled.length
  } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
    nextIndex = (currentIndex - 1 + enabled.length) % enabled.length
  } else if (event.key === 'Home') {
    nextIndex = 0
  } else if (event.key === 'End') {
    nextIndex = enabled.length - 1
  }
  if (nextIndex === null || !enabled[nextIndex]) return
  event.preventDefault()
  emit('navigate', enabled[nextIndex].id)
}

void props
</script>

<template>
  <nav class="case-stage-nav" aria-label="案例业务阶段" role="tablist">
    <button
      v-for="stage in stages"
      :key="stage.id"
      type="button"
      class="stage-item"
      :class="{ active: stage.id === current, disabled: !stage.enabled }"
      :data-test="`stage-nav-${stage.id}`"
      role="tab"
      :aria-selected="stage.id === current ? 'true' : 'false'"
      :tabindex="stage.id === current ? 0 : -1"
      :disabled="!stage.enabled"
      :title="stage.enabled ? undefined : (stage.reason ?? '当前不可用')"
      @click="onSelect(stage)"
      @keydown="onKeydown"
    >
      <span class="stage-label">{{ STAGE_LABELS[stage.id] }}</span>
      <span v-if="!stage.enabled && stage.reason" class="stage-reason">{{ stage.reason }}</span>
    </button>
  </nav>
</template>

<style scoped>
.case-stage-nav {
  display: flex;
  gap: var(--s1-space-2);
  flex-wrap: wrap;
  padding: var(--s1-space-2);
  border: 1px solid var(--s1-border-soft);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-1);
  position: sticky;
  top: 60px;
  z-index: 20;
}

.stage-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  border: 1px solid transparent;
  border-radius: var(--s1-radius-sm);
  background: transparent;
  color: var(--s1-text-dim);
  font-size: var(--s1-font-md);
  padding: 6px 14px;
  cursor: pointer;
  transition:
    color var(--s1-motion-fast) var(--s1-ease-out),
    background var(--s1-motion-fast) var(--s1-ease-out),
    border-color var(--s1-motion-fast) var(--s1-ease-out);
}

.stage-item:hover:not(.disabled) {
  color: var(--s1-cyan-strong);
  background: var(--s1-cyan-ghost);
}

.stage-item.active {
  color: var(--s1-case-accent);
  border-color: var(--s1-case-accent);
  background: var(--s1-case-accent-soft);
  font-weight: 600;
}

.stage-item.disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.stage-reason {
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
}
</style>
