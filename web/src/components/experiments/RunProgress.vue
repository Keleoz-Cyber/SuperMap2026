<script setup lang="ts">
import { computed } from 'vue'
import type { RunRecord } from '../../api/types'

const props = defineProps<{
  run: RunRecord | null
  acting: boolean
}>()

const emit = defineEmits<{
  (e: 'cancel'): void
  (e: 'retry'): void
}>()

const INFLIGHT = new Set(['queued', 'running'])
const RETRYABLE = new Set(['canceled', 'interrupted', 'failed'])

const inflight = computed(() => props.run !== null && INFLIGHT.has(props.run.status))
const retryable = computed(() => props.run !== null && RETRYABLE.has(props.run.status))

const statusType = computed(() => {
  if (!props.run) return 'info'
  switch (props.run.status) {
    case 'succeeded':
      return 'success'
    case 'failed':
      return 'danger'
    case 'canceled':
    case 'interrupted':
      return 'warning'
    default:
      return 'primary'
  }
})

const progress = computed(() => {
  const metrics = props.run?.metrics ?? {}
  return {
    completed: metrics.completed ?? 0,
    total: metrics.total ?? 0,
    failed: metrics.failed ?? 0,
  }
})

const percent = computed(() =>
  progress.value.total > 0 ? Math.round((progress.value.completed / progress.value.total) * 100) : 0,
)
</script>

<template>
  <section v-if="run" class="run-progress" data-test="run-progress">
    <div class="run-head">
      <el-tag :type="statusType" effect="dark" size="small">{{ run.status }}</el-tag>
      <span class="run-id mono">{{ run.id }}</span>
      <span v-if="run.error_code" class="error-code" data-test="run-error-code">{{ run.error_code }}</span>
    </div>

    <div class="run-bar-row">
      <div class="run-bar">
        <div class="run-bar-fill" :style="{ width: `${percent}%` }" />
      </div>
      <span class="run-count" data-test="run-count">
        {{ progress.completed }}/{{ progress.total }} 完成
        <template v-if="progress.failed">（失败 {{ progress.failed }}）</template>
      </span>
    </div>

    <div class="run-actions">
      <button v-if="inflight" class="gmp-btn danger" data-test="cancel-run" :disabled="acting" @click="emit('cancel')">
        取消运行
      </button>
      <button v-if="retryable" class="gmp-btn primary" data-test="retry-run" :disabled="acting" @click="emit('retry')">
        重试运行
      </button>
    </div>
  </section>
  <section v-else class="run-progress empty" data-test="run-progress-empty">尚未启动运行</section>
</template>

<style scoped>
.run-progress {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.run-progress.empty {
  color: var(--gmp-text-faint);
  font-size: 13px;
}

.run-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.mono {
  font-family: ui-monospace, monospace;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.error-code {
  color: #ef9a9a;
  font-size: 12px;
}

.run-bar-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.run-bar {
  flex: 1;
  height: 8px;
  border-radius: 4px;
  background: var(--gmp-bg-soft);
  overflow: hidden;
}

.run-bar-fill {
  height: 100%;
  background: var(--gmp-accent);
  transition: width 0.4s;
}

.run-count {
  font-size: 12px;
  color: var(--gmp-text-dim);
  white-space: nowrap;
}

.run-actions {
  display: flex;
  gap: 10px;
}

.gmp-btn {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text);
  border-radius: 8px;
  padding: 6px 16px;
  font-size: 12px;
  cursor: pointer;
}

.gmp-btn.primary {
  background: var(--gmp-accent);
  border-color: var(--gmp-accent);
  color: #0b0f14;
  font-weight: 600;
}

.gmp-btn.danger {
  border-color: #a43d3d;
  color: #ef9a9a;
}

.gmp-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
