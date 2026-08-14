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

const STATUS_LABELS: Record<string, string> = {
  queued: '排队中',
  running: '运行中',
  succeeded: '验证完成',
  failed: '运行失败',
  canceled: '已取消',
  interrupted: '已中断',
}

const statusLabel = computed(() => (props.run ? STATUS_LABELS[props.run.status] ?? '状态未知' : ''))

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

const indeterminate = computed(
  () => props.run?.status === 'queued' || (props.run?.status === 'running' && progress.value.total <= 0),
)

const liveMessage = computed(() => {
  if (!props.run) return ''
  if (props.run.status === 'queued') return '正在等待执行资源，任务已进入队列'
  if (props.run.status === 'running') {
    return progress.value.total > 0
      ? `正在计算候选结果，已完成 ${progress.value.completed}/${progress.value.total}`
      : '模型正在运行，正在等待第一批计算结果'
  }
  if (props.run.status === 'succeeded') return '运行完成，可以查看模型评估与成果'
  if (props.run.status === 'failed') return '运行失败，请查看技术详情或修正参数后重试'
  if (props.run.status === 'canceled') return '运行已取消，已完成的候选结果仍会保留'
  if (props.run.status === 'interrupted') return '运行被中断，可以重新提交运行'
  return '正在获取运行状态'
})
</script>

<template>
  <section v-if="run" class="run-progress" data-test="run-progress">
    <div class="run-head" data-test="run-progress-primary">
      <el-tag :type="statusType" effect="dark" size="small">{{ statusLabel }}</el-tag>
      <span
        v-if="inflight"
        class="run-status-spinner"
        data-test="run-status-spinner"
        aria-hidden="true"
      />
      <p class="run-live-status" data-test="run-live-status" aria-live="polite">
        {{ liveMessage }}
      </p>
    </div>

    <div class="run-bar-row">
      <div
        class="run-bar"
        :class="{ indeterminate }"
        data-test="run-progress-bar"
        role="progressbar"
        :aria-valuenow="indeterminate ? undefined : percent"
        aria-valuemin="0"
        aria-valuemax="100"
      >
        <div class="run-bar-fill" :style="indeterminate ? undefined : { width: `${percent}%` }" />
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
    <details class="run-technical" data-test="run-technical-details">
      <summary>技术详情</summary>
      <p>运行标识 <span class="mono">{{ run.id }}</span></p>
      <p v-if="run.error_code" class="error-code" data-test="run-error-code">错误码 {{ run.error_code }}</p>
    </details>
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

.run-live-status {
  margin: 0;
  color: var(--gmp-text-dim);
  font-size: 12px;
}

.run-status-spinner {
  width: 13px;
  height: 13px;
  flex: none;
  border: 2px solid rgba(74, 182, 232, 0.24);
  border-top-color: var(--gmp-accent);
  border-radius: 50%;
  animation: run-status-spin 0.8s linear infinite;
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
  transition: width var(--s1-motion-panel) var(--s1-ease-out);
}

.run-bar.indeterminate .run-bar-fill {
  width: 38%;
  animation: run-progress-sweep 1.25s var(--s1-ease-in-out) infinite;
}

@keyframes run-status-spin {
  to { transform: rotate(360deg); }
}

@keyframes run-progress-sweep {
  from { transform: translateX(-120%); }
  to { transform: translateX(310%); }
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

.run-technical {
  color: var(--gmp-text-faint);
  font-size: 12px;
}

.run-technical summary {
  cursor: pointer;
}

.run-technical p {
  margin: 6px 0 0;
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
