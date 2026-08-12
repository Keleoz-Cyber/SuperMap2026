<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ApiError,
  fetchAnalysisJob,
  fetchAnomalyExtraction,
  fetchResultPreview,
  requestAnomalyExtraction,
} from '../../api/client'
import type {
  AnomalyExtractionAccepted,
  AnomalyExtractionPayload,
  AnomalyExtractionRecord,
  ProfessionalCapabilities,
  ResultPreview,
} from '../../api/types'

// 异常提取是长任务：POST 落库入队（202/幂等 200），前端只轮询任务与读取
// 已登记提取结果；阈值预览只是控件反馈（基于既有抽稀预览计数），真正的
// 掩膜与连通区全部由服务端计算。NoData/拒绝节点绝不进入高亮集合。
const props = defineProps<{
  resultId: string
  capabilities?: ProfessionalCapabilities | null
}>()

const POLL_INTERVAL_MS = 1000
const INFLIGHT = new Set(['queued', 'running'])

const krigingStdSupported = computed(
  () => props.capabilities?.native_kriging_std === 'supported',
)

// 预览控件（契约严格校验在服务端；前端只收集原始载荷）
const direction = ref<'high' | 'low'>('high')
const threshold = ref<number | null>(null)
const empiricalErrorMax = ref<number | null>(null)
const krigingStdMax = ref<number | null>(null)
const minSupportNodes = ref(1)

const preview = ref<ResultPreview | null>(null)
const previewError = ref<string | null>(null)
const actionError = ref<string | null>(null)
const saving = ref(false)

const extraction = ref<AnomalyExtractionRecord | null>(null)
const jobStatus = ref<string | null>(null)
const jobError = ref<{ code: string; message: string } | null>(null)

let pollTimer: ReturnType<typeof setInterval> | null = null

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function describeError(e: unknown): string {
  if (e instanceof ApiError) return `${e.code}：${e.message}`
  return e instanceof Error ? e.message : String(e)
}

// 阈值预览计数：只统计预览中非 NoData 且满足阈值方向的节点（控件反馈）
const previewCount = computed(() => {
  const body = preview.value
  const limit = threshold.value
  if (!body || limit === null || !Number.isFinite(limit)) return null
  let count = 0
  for (let i = 0; i < body.values.length; i += 1) {
    if (body.is_nodata[i]) continue
    const value = body.values[i]
    if (!Number.isFinite(value)) continue
    if (direction.value === 'high' ? value >= limit : value <= limit) count += 1
  }
  return count
})

function optionalGate(value: number | null): number | null {
  // v-model.number 的空输入是 ''：未设置的门槛一律归一为 null，绝不发送空字符串
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function buildPayload(): AnomalyExtractionPayload {
  return {
    direction: direction.value,
    threshold: threshold.value ?? 0,
    empirical_error_max: optionalGate(empiricalErrorMax.value),
    kriging_std_max: krigingStdSupported.value ? optionalGate(krigingStdMax.value) : null,
    min_support_nodes: minSupportNodes.value,
    connectivity_rule: 'face_2d4_3d6_v1',
  }
}

const canSave = computed(
  () =>
    threshold.value !== null &&
    Number.isFinite(threshold.value) &&
    !saving.value &&
    jobStatus.value === null,
)

async function loadPreview() {
  previewError.value = null
  const requestId = props.resultId
  try {
    const body = await fetchResultPreview(requestId)
    if (props.resultId !== requestId) return
    preview.value = body
  } catch (e) {
    if (props.resultId !== requestId) return
    previewError.value = describeError(e)
    preview.value = null
  }
}

async function loadExtraction(extractionId: string) {
  extraction.value = await fetchAnomalyExtraction(extractionId)
  jobStatus.value = null
}

async function tick(jobId: string, extractionId: string) {
  try {
    const job = await fetchAnalysisJob(jobId)
    if (INFLIGHT.has(job.status)) {
      jobStatus.value = job.status
      return
    }
    stopPolling()
    if (job.status === 'succeeded') {
      await loadExtraction(extractionId)
      return
    }
    jobStatus.value = null
    jobError.value = job.error ?? {
      code: 'ANALYSIS_JOB_NOT_SUCCEEDED',
      message: `提取任务未成功（${job.status}）`,
    }
  } catch (e) {
    stopPolling()
    jobStatus.value = null
    actionError.value = describeError(e)
  }
}

function startPolling(jobId: string, extractionId: string) {
  stopPolling()
  pollTimer = setInterval(() => {
    void tick(jobId, extractionId)
  }, POLL_INTERVAL_MS)
}

async function save() {
  if (!canSave.value) return
  saving.value = true
  actionError.value = null
  jobError.value = null
  extraction.value = null
  try {
    const accepted: AnomalyExtractionAccepted = await requestAnomalyExtraction(
      props.resultId,
      buildPayload(),
    )
    if (accepted.job_id === null) {
      // 幂等复用：同成果同配置成功提取直接读取，不产生新任务
      await loadExtraction(accepted.extraction_id)
      return
    }
    jobStatus.value = accepted.status
    startPolling(accepted.job_id, accepted.extraction_id)
  } catch (e) {
    actionError.value = describeError(e)
  } finally {
    saving.value = false
  }
}

// 高亮集合：任一已登记连通区包围盒内的非 NoData 预览节点
const highlightCount = computed(() => {
  const body = preview.value
  const components = extraction.value?.components?.rows
  if (!body || !components || components.length === 0) return null
  let count = 0
  for (let i = 0; i < body.x.length; i += 1) {
    if (body.is_nodata[i]) continue
    const inside = components.some((row) => {
      const xb = row.bounds[0]
      const yb = row.bounds[1]
      if (!xb || !yb) return false
      return body.x[i] >= xb[0] && body.x[i] <= xb[1] && body.y[i] >= yb[0] && body.y[i] <= yb[1]
    })
    if (inside) count += 1
  }
  return count
})

function formatBounds(bounds: Array<[number, number]>): string {
  return bounds.map(([lo, hi]) => `[${lo}, ${hi}]`).join(' × ')
}

// 候选切换：提取身份/控件状态全部重置，绝不把旧候选的提取结果带过来
watch(
  () => props.resultId,
  () => {
    stopPolling()
    extraction.value = null
    jobStatus.value = null
    jobError.value = null
    actionError.value = null
    preview.value = null
    void loadPreview()
  },
)

onMounted(() => {
  void loadPreview()
})
onBeforeUnmount(stopPolling)
</script>

<template>
  <section class="anomaly-panel" data-test="anomaly-panel">
    <header class="panel-head">
      <h3>异常区域提取</h3>
    </header>

    <div v-if="previewError" class="panel-error" data-test="preview-error">{{ previewError }}</div>

    <div class="controls">
      <label class="radio inline">
        <input v-model="direction" type="radio" value="high" data-test="anomaly-direction-high" />
        高值（≥ 阈值）
      </label>
      <label class="radio inline">
        <input v-model="direction" type="radio" value="low" data-test="anomaly-direction-low" />
        低值（≤ 阈值）
      </label>
      <label class="field inline">
        <span>阈值</span>
        <input v-model.number="threshold" type="number" step="any" class="gmp-input" data-test="anomaly-threshold" />
      </label>
      <label class="field inline">
        <span>经验误差上限</span>
        <input
          v-model.number="empiricalErrorMax"
          type="number"
          step="any"
          min="0"
          class="gmp-input"
          data-test="anomaly-empirical-max"
        />
      </label>
      <label v-if="krigingStdSupported" class="field inline">
        <span>Kriging 标准差上限</span>
        <input
          v-model.number="krigingStdMax"
          type="number"
          step="any"
          min="0"
          class="gmp-input"
          data-test="anomaly-kriging-max"
        />
      </label>
      <label class="field inline">
        <span>最小支持节点</span>
        <input
          v-model.number="minSupportNodes"
          type="number"
          min="1"
          class="gmp-input"
          data-test="anomaly-min-support"
        />
      </label>
      <button class="gmp-btn primary" data-test="anomaly-save" :disabled="!canSave" @click="save">
        {{ saving ? '提交中…' : '保存异常提取' }}
      </button>
    </div>

    <p class="preview-hint" data-test="anomaly-preview-count">
      <template v-if="previewCount !== null">
        预计合格节点 {{ previewCount }} 个（基于抽稀预览，仅供阈值调节参考；NoData 节点不计入）
      </template>
      <template v-else>输入阈值后显示预览计数（基于抽稀预览）</template>
    </p>

    <div v-if="actionError" class="panel-error" data-test="action-error">{{ actionError }}</div>
    <div v-if="jobStatus" class="job-status" data-test="extraction-job-status">
      提取任务执行中（{{ jobStatus }}）…
    </div>
    <div v-if="jobError" class="panel-error" data-test="job-error">
      <b class="mono">{{ jobError.code }}</b>：{{ jobError.message }}
    </div>

    <template v-if="extraction">
      <details class="extraction-technical" data-test="extraction-technical-details">
        <summary>技术详情</summary>
        <div class="extraction-meta">
        <span data-test="extraction-identity">提取 <span class="mono">{{ extraction.id }}</span></span>
        <span data-test="extraction-fingerprint">
          指纹 <span class="mono">{{ extraction.fingerprint }}</span>
        </span>
        <span data-test="extraction-status">状态 {{ extraction.status }}</span>
        </div>
      </details>
      <p class="extraction-legend" data-test="extraction-legend">
        阈值 {{ extraction.config.threshold }}（{{ extraction.config.direction === 'low' ? '低值' : '高值' }}）
        <template v-if="extraction.config.empirical_error_max != null">
          · 经验误差 ≤ {{ extraction.config.empirical_error_max }}
        </template>
        <template v-if="extraction.config.kriging_std_max != null">
          · Kriging 标准差 ≤ {{ extraction.config.kriging_std_max }}
        </template>
      </p>

      <div v-if="extraction.components" class="components">
        <span class="component-count" data-test="component-count">
          连通区 {{ extraction.components.returned }} / {{ extraction.components.total }} 个
        </span>
        <span v-if="highlightCount !== null" class="highlight-count" data-test="highlight-count">
          网格高亮节点 {{ highlightCount }} 个（NoData 不进入）
        </span>
        <table class="component-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>支持节点</th>
              <th>值域</th>
              <th>均值</th>
              <th>包围盒</th>
              <th>触边界</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in extraction.components.rows" :key="row.component_id" data-test="component-row">
              <td>{{ row.component_id }}</td>
              <td>{{ row.support_node_count }}</td>
              <td>{{ row.value_min }} ~ {{ row.value_max }}</td>
              <td>{{ row.value_mean }}</td>
              <td class="mono">{{ formatBounds(row.bounds) }}</td>
              <td>{{ row.touches_grid_boundary ? '是' : '否' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.anomaly-panel {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel-head h3 {
  margin: 0;
  font-size: 15px;
}

.controls {
  display: flex;
  align-items: flex-end;
  gap: 14px;
  flex-wrap: wrap;
}

.radio {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  cursor: pointer;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.gmp-input {
  background: var(--gmp-bg-soft);
  border: 1px solid var(--gmp-border);
  color: var(--gmp-text);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 13px;
  width: 120px;
}

.gmp-btn {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text);
  border-radius: 8px;
  padding: 7px 16px;
  font-size: 13px;
  cursor: pointer;
}

.gmp-btn.primary {
  background: var(--gmp-accent);
  border-color: var(--gmp-accent);
  color: #0b0f14;
  font-weight: 600;
}

.gmp-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.preview-hint {
  margin: 0;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.panel-error {
  border: 1px solid #a43d3d;
  background: rgba(164, 61, 61, 0.15);
  color: #ef9a9a;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
}

.job-status {
  font-size: 13px;
  color: var(--gmp-text-dim);
}

.extraction-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.extraction-legend {
  margin: 0;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.mono {
  font-family: ui-monospace, monospace;
}

.components {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 12px;
}

.component-count,
.highlight-count {
  color: var(--gmp-text-dim);
}

.component-table {
  border-collapse: collapse;
  font-size: 12px;
}

.component-table th,
.component-table td {
  border: 1px solid var(--gmp-border);
  padding: 5px 10px;
  text-align: left;
}

.component-table th {
  color: var(--gmp-text-faint);
  font-weight: 600;
}
</style>
