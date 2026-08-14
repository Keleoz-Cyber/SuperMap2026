<script lang="ts">
import type { RunStatus } from '../../api/types'

// v0.9.0：流水线阶段推导。只从持久化 status + 粗进度（completed/total）
// 映射；后端不提供子阶段计时，粗进度推导的阶段一律标注「阶段估计」。
export type PipelineStage =
  | 'queued'
  | 'validation'
  | 'interpolation'
  | 'evaluation'
  | 'complete'
  | 'failed'
  | 'canceled'
  | 'interrupted'

export function stageFor(input: { status: RunStatus | string; progress?: number }): PipelineStage {
  switch (input.status) {
    case 'queued':
      return 'queued'
    case 'succeeded':
      return 'complete'
    case 'failed':
      return 'failed'
    case 'canceled':
      return 'canceled'
    case 'interrupted':
      return 'interrupted'
    case 'running': {
      const p = typeof input.progress === 'number' && Number.isFinite(input.progress) ? input.progress : 0
      if (p < 0.4) return 'validation'
      if (p < 0.8) return 'interpolation'
      return 'evaluation'
    }
    default:
      return 'queued'
  }
}
</script>

<script setup lang="ts">
import { computed } from 'vue'
import type { RunRecord } from '../../api/types'

const props = defineProps<{
  run: RunRecord | null
}>()

const progress = computed(() => {
  const metrics = props.run?.metrics ?? {}
  const completed = metrics.completed ?? 0
  const total = metrics.total ?? 0
  return total > 0 ? completed / total : 0
})

const stage = computed<PipelineStage>(() =>
  props.run ? stageFor({ status: props.run.status, progress: progress.value }) : 'queued',
)

// 五段流水线与推导阶段的映射：校验/折分同属 validation 组
const NODES: Array<{ id: string; label: string; group: PipelineStage }> = [
  { id: 'validate', label: '校验', group: 'validation' },
  { id: 'folds', label: '折分', group: 'validation' },
  { id: 'interpolate', label: '插值', group: 'interpolation' },
  { id: 'evaluate', label: '评估', group: 'evaluation' },
  { id: 'materialize', label: '物化', group: 'evaluation' },
]

const GROUP_ORDER: PipelineStage[] = ['validation', 'interpolation', 'evaluation', 'complete']

function nodeState(group: PipelineStage): 'pending' | 'active' | 'done' | 'failed' {
  const current = stage.value
  if (current === 'failed' || current === 'canceled' || current === 'interrupted') {
    // 失败/取消/中断：正在进行的组标失败态，之前的组保持完成
    const activeGroup = progress.value < 0.4 ? 'validation' : progress.value < 0.8 ? 'interpolation' : 'evaluation'
    const g = GROUP_ORDER.indexOf(group)
    const a = GROUP_ORDER.indexOf(activeGroup)
    if (g < a) return 'done'
    if (g === a) return 'failed'
    return 'pending'
  }
  if (current === 'complete') return 'done'
  if (current === 'queued') return 'pending'
  const g = GROUP_ORDER.indexOf(group)
  const c = GROUP_ORDER.indexOf(current)
  if (g < c) return 'done'
  if (g === c) return 'active'
  return 'pending'
}

const estimated = computed(() => props.run?.status === 'running')
</script>

<template>
  <section v-if="run" class="run-pipeline" data-test="run-pipeline" aria-label="运行流水线">
    <div class="pipeline-head">
      <span class="pipeline-title">运行流水线</span>
      <span v-if="estimated" class="estimate-chip" data-test="pipeline-estimate">阶段估计</span>
    </div>
    <ol class="pipeline-track">
      <li
        v-for="node in NODES"
        :key="node.id"
        class="pipeline-node"
        :class="nodeState(node.group)"
        :data-test="`pipeline-stage-${node.id}`"
        :data-state="nodeState(node.group)"
        :aria-current="nodeState(node.group) === 'active' ? 'step' : undefined"
      >
        <span class="node-dot" aria-hidden="true" />
        {{ node.label }}
      </li>
    </ol>
    <p v-if="stage === 'failed'" class="pipeline-error" data-test="pipeline-error">
      运行失败：可查看技术详情，修正参数后可重试。
    </p>
    <details v-if="stage === 'failed' && run.error_code" class="pipeline-technical" data-test="pipeline-technical-details">
      <summary>技术详情</summary>
      <p class="mono">错误码：{{ run.error_code }}</p>
    </details>
    <p v-else-if="stage === 'canceled' || stage === 'interrupted'" class="pipeline-error">
      {{ stage === 'canceled' ? '已取消' : '已中断' }}：可重试，已完成的候选结果保留。
    </p>
  </section>
</template>

<style scoped>
.run-pipeline {
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-1);
  padding: var(--s1-space-3) var(--s1-space-4);
}

.pipeline-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: var(--s1-space-2);
}

.pipeline-title {
  font-size: var(--s1-font-sm);
  font-weight: 600;
  color: var(--s1-text-dim);
  letter-spacing: 0.05em;
}

.estimate-chip {
  font-size: 12px;
  color: var(--s1-warning);
  border: 1px solid rgba(217, 168, 78, 0.4);
  border-radius: 999px;
  padding: 0 8px;
}

.pipeline-track {
  display: flex;
  align-items: center;
  gap: 0;
  list-style: none;
  margin: 0;
  padding: 0;
}

.pipeline-node {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--s1-font-sm);
  color: var(--s1-text-faint);
  position: relative;
  white-space: nowrap;
}

.pipeline-node:not(:last-child)::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--s1-border);
  margin: 0 8px;
  min-width: 12px;
}

.node-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 2px solid var(--s1-border);
  flex: none;
  transition:
    background var(--s1-motion-base) var(--s1-ease-out),
    border-color var(--s1-motion-base) var(--s1-ease-out);
}

.pipeline-node.done {
  color: var(--s1-text-dim);
}

.pipeline-node.done .node-dot {
  background: var(--s1-success);
  border-color: var(--s1-success);
}

.pipeline-node.active {
  color: var(--s1-cyan-strong);
  font-weight: 600;
}

.pipeline-node.active .node-dot {
  border-color: var(--s1-cyan);
  background: var(--s1-cyan-ghost);
  box-shadow: 0 0 8px rgba(74, 182, 232, 0.5);
  animation: pipeline-stage-pulse 1.4s var(--s1-ease-in-out) infinite;
}

@keyframes pipeline-stage-pulse {
  0%, 100% { opacity: 0.62; transform: scale(0.9); }
  50% { opacity: 1; transform: scale(1.12); }
}

.pipeline-node.failed {
  color: var(--s1-error);
}

.pipeline-node.failed .node-dot {
  background: var(--s1-error);
  border-color: var(--s1-error);
}

.pipeline-error {
  margin: var(--s1-space-2) 0 0;
  font-size: var(--s1-font-sm);
  color: var(--s1-error);
}

.pipeline-technical {
  margin-top: var(--s1-space-2);
  color: var(--s1-text-faint);
  font-size: var(--s1-font-sm);
}

.pipeline-technical summary {
  cursor: pointer;
}

.pipeline-technical p {
  margin: var(--s1-space-1) 0 0;
}

.mono {
  font-family: ui-monospace, monospace;
}
</style>
