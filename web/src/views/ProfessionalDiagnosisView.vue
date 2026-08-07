<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ApiError,
  confirmProfessionalDiagnosis,
  fetchAnalysisJob,
  fetchDataset,
  fetchDiagnosisVariogram,
  fetchProfessionalConfirmation,
  fetchProfessionalDiagnosis,
  fetchProfessionalDiagnostics,
  requestProfessionalDiagnosis,
  retryAnalysisJob,
} from '../api/client'
import type {
  AnalysisJobRecord,
  DatasetVersionRecord,
  DirectionPayload,
  ProfessionalConfirmationPayload,
  ProfessionalConfirmationRecord,
  ProfessionalDiagnosisRecord,
  ProfessionalDiagnosisRequestPayload,
  ProfessionalErrorBody,
  RunStatus,
  VariogramEvidence,
  VariogramModelName,
} from '../api/types'
import VariogramPanel from '../components/professional/VariogramPanel.vue'
import AnisotropyPanel from '../components/professional/AnisotropyPanel.vue'
import PageNavigation from '../components/navigation/PageNavigation.vue'

const route = useRoute()
const router = useRouter()

const POLL_INTERVAL_MS = 1000
const INFLIGHT = new Set(['queued', 'running'])

const datasetId = computed(() => String(route.params.datasetId ?? ''))
const queryCaseId = computed(() =>
  typeof route.query.case === 'string' ? route.query.case : '',
)
const queryDiagnosisId = computed(() => {
  const q = route.query.diagnosis
  return typeof q === 'string' && q ? q : null
})

const dataset = ref<DatasetVersionRecord | null>(null)
const loading = ref(true)
const loadError = ref<string | null>(null)
const actionError = ref<string | null>(null)

const caseId = computed(() => queryCaseId.value || dataset.value?.case_id || '')
const dimension = computed<'2d' | '3d'>(() =>
  dataset.value?.profile?.dimension === '3d' ? '3d' : '2d',
)
const gated = computed(() => dataset.value !== null && dataset.value.status !== 'validated')

type DiagnosisPhase =
  | { kind: 'config' }
  | {
      kind: 'running'
      diagnosisId: string
      jobId: string
      status: RunStatus
      progress: Record<string, unknown>
    }
  | {
      kind: 'failed'
      diagnosisId: string
      jobId: string
      status: RunStatus
      error: ProfessionalErrorBody
    }
  | { kind: 'succeeded'; diagnosisId: string }

const phase = ref<DiagnosisPhase>({ kind: 'config' })
const running = computed(() => (phase.value.kind === 'running' ? phase.value : null))
const failed = computed(() => (phase.value.kind === 'failed' ? phase.value : null))

const diagnosis = ref<ProfessionalDiagnosisRecord | null>(null)
const evidence = ref<VariogramEvidence | null>(null)
const confirmation = ref<ProfessionalConfirmationRecord | null>(null)
const confirmationFromExisting = ref(false)

const starting = ref(false)
const retrying = ref(false)
const confirming = ref(false)

const lagCount = ref(12)
const minPairs = ref(30)
const maxPairs = ref(50000)
const AZIMUTH_CHOICES = [0, 45, 90, 135]
const selectedAzimuths = ref<number[]>([0, 90])
const includeVertical = ref(false)

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

const routeIdentity = computed(
  () => `${datasetId.value}\u0000${queryDiagnosisId.value ?? ''}`,
)
let loadSequence = 0

async function loadForRoute() {
  const sequence = ++loadSequence
  const targetDatasetId = datasetId.value
  const targetDiagnosisId = queryDiagnosisId.value
  const current = () =>
    sequence === loadSequence &&
    targetDatasetId === datasetId.value &&
    targetDiagnosisId === queryDiagnosisId.value
  loading.value = true
  loadError.value = null
  stopPolling()
  dataset.value = null
  diagnosis.value = null
  evidence.value = null
  confirmation.value = null
  confirmationFromExisting.value = false
  phase.value = { kind: 'config' }
  try {
    const loadedDataset = await fetchDataset(targetDatasetId)
    if (!current()) return
    dataset.value = loadedDataset
    if (targetDiagnosisId) await resumeDiagnosis(targetDiagnosisId, current)
  } catch (error) {
    if (current()) loadError.value = describeError(error)
  } finally {
    if (current()) loading.value = false
  }
}

watch(routeIdentity, () => void loadForRoute(), { immediate: true })

async function resumeDiagnosis(diagnosisId: string, current: () => boolean) {
  const record = await fetchProfessionalDiagnosis(diagnosisId)
  if (!current()) return
  if (record.dataset_version_id !== datasetId.value) {
    throw new ApiError('DIAGNOSIS_DATASET_MISMATCH', '诊断不属于当前数据集', 409)
  }

  if (record.status === 'succeeded') {
    const variogram = await fetchDiagnosisVariogram(diagnosisId)
    if (!current()) return
    diagnosis.value = record
    evidence.value = variogram
    phase.value = { kind: 'succeeded', diagnosisId }
    if (record.latest_confirmation?.applicable) {
      try {
        const summary = await fetchProfessionalConfirmation(record.latest_confirmation.id)
        if (!current()) return
        const conf = summary.confirmation as Record<string, unknown>
        confirmation.value = {
          id: record.latest_confirmation.id,
          diagnostic_id: record.latest_confirmation.diagnostic_id,
          fingerprint: record.latest_confirmation.fingerprint,
          note: (conf.note as string) ?? '',
          config: (conf.config as Record<string, unknown>) ?? {},
          created_at: record.latest_confirmation.created_at,
        }
        confirmationFromExisting.value = true
      } catch {
        // non-blocking: diagnosis is still usable without confirmation snapshot
      }
    }
    return
  }

  const list = await fetchProfessionalDiagnostics(datasetId.value)
  if (!current()) return
  const item = list.diagnostics.find(
    (d) => (d.diagnosis as { id?: string }).id === diagnosisId,
  )
  if (!item) {
    throw new ApiError('DIAGNOSIS_NOT_FOUND', '未找到指定的诊断记录', 404)
  }
  const job = item.job as unknown as AnalysisJobRecord | null

  if ((record.status === 'failed' || record.status === 'interrupted') && job) {
    phase.value = {
      kind: 'failed',
      diagnosisId,
      jobId: job.id,
      status: job.status,
      error: job.error ?? record.error ?? {
        code: 'ANALYSIS_JOB_NOT_SUCCEEDED',
        message: `任务未成功（${record.status}）`,
      },
    }
    return
  }
  if (job) {
    phase.value = {
      kind: 'running',
      diagnosisId,
      jobId: job.id,
      status: job.status,
      progress: job.progress ?? {},
    }
    maybePoll()
  }
}

function toggleAzimuth(azimuth: number) {
  selectedAzimuths.value = selectedAzimuths.value.includes(azimuth)
    ? selectedAzimuths.value.filter((item) => item !== azimuth)
    : [...selectedAzimuths.value, azimuth].sort((a, b) => a - b)
}

function buildPayload(): ProfessionalDiagnosisRequestPayload {
  const directions: DirectionPayload[] = selectedAzimuths.value.map((azimuth) =>
    dimension.value === '3d'
      ? {
          dimension: '3d',
          azimuth_deg: azimuth,
          dip_deg: 0,
          azimuth_tolerance_deg: 15,
          dip_tolerance_deg: 15,
        }
      : { dimension: '2d', azimuth_deg: azimuth, azimuth_tolerance_deg: 15 },
  )
  if (dimension.value === '3d' && includeVertical.value) {
    directions.push({
      dimension: '3d',
      azimuth_deg: 0,
      dip_deg: 90,
      azimuth_tolerance_deg: 15,
      dip_tolerance_deg: 15,
    })
  }
  return {
    variogram: {
      lag_count: lagCount.value,
      min_pairs_per_bin: minPairs.value,
      max_pairs: maxPairs.value,
      directions,
    },
  }
}

async function loadSuccess(diagnosisId: string) {
  const [record, variogram] = await Promise.all([
    fetchProfessionalDiagnosis(diagnosisId),
    fetchDiagnosisVariogram(diagnosisId),
  ])
  diagnosis.value = record
  evidence.value = variogram
  phase.value = { kind: 'succeeded', diagnosisId }
}

async function start() {
  starting.value = true
  actionError.value = null
  try {
    const accepted = await requestProfessionalDiagnosis(datasetId.value, buildPayload())
    confirmation.value = null
    confirmationFromExisting.value = false
    diagnosis.value = null
    evidence.value = null
    if (accepted.job_id === null) {
      await loadSuccess(accepted.diagnosis_id)
      return
    }
    phase.value = {
      kind: 'running',
      diagnosisId: accepted.diagnosis_id,
      jobId: accepted.job_id,
      status: accepted.status,
      progress: {},
    }
    maybePoll()
  } catch (e) {
    actionError.value = describeError(e)
  } finally {
    starting.value = false
  }
}

async function tick() {
  const current = running.value
  if (!current) return
  try {
    const job = await fetchAnalysisJob(current.jobId)
    if (INFLIGHT.has(job.status)) {
      phase.value = { ...current, status: job.status, progress: job.progress }
      return
    }
    stopPolling()
    if (job.status === 'succeeded') {
      await loadSuccess(current.diagnosisId)
      return
    }
    phase.value = {
      kind: 'failed',
      diagnosisId: current.diagnosisId,
      jobId: current.jobId,
      status: job.status,
      error: job.error ?? { code: 'ANALYSIS_JOB_NOT_SUCCEEDED', message: `任务未成功（${job.status}）` },
    }
  } catch (e) {
    stopPolling()
    actionError.value = describeError(e)
  }
}

function maybePoll() {
  stopPolling()
  if (running.value && INFLIGHT.has(running.value.status)) {
    pollTimer = setInterval(() => {
      void tick()
    }, POLL_INTERVAL_MS)
  }
}

async function onRetry() {
  const current = failed.value
  if (!current) return
  retrying.value = true
  actionError.value = null
  try {
    const job = await retryAnalysisJob(current.jobId)
    phase.value = {
      kind: 'running',
      diagnosisId: current.diagnosisId,
      jobId: job.id,
      status: job.status,
      progress: job.progress,
    }
    maybePoll()
  } catch (e) {
    actionError.value = describeError(e)
  } finally {
    retrying.value = false
  }
}

const fittedModelNames = computed<VariogramModelName[]>(
  () => diagnosis.value?.manifest?.summary?.fitted_models ?? [],
)
const minSseModel = computed<VariogramModelName | null>(
  () => diagnosis.value?.manifest?.summary?.min_sse_model ?? null,
)
const fittedModelsSha256 = computed(
  () => diagnosis.value?.manifest?.artifacts.fitted_models?.sha256 ?? null,
)
const anisotropyCandidatesSha256 = computed(
  () => diagnosis.value?.manifest?.artifacts.anisotropy_candidates?.sha256 ?? null,
)

async function onConfirm(payload: ProfessionalConfirmationPayload) {
  const current = phase.value
  if (current.kind !== 'succeeded') return
  confirming.value = true
  actionError.value = null
  try {
    confirmation.value = await confirmProfessionalDiagnosis(current.diagnosisId, payload)
    confirmationFromExisting.value = false
  } catch (e) {
    actionError.value = describeError(e)
  } finally {
    confirming.value = false
  }
}

function gotoExperiment() {
  if (!confirmation.value) return
  void router.push({
    name: 'experiment-create',
    params: { caseId: caseId.value },
    query: { dataset: datasetId.value, professional_confirmation: confirmation.value.id },
  })
}

onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="diagnosis-page">
    <PageNavigation home :case-id="caseId || undefined" new-experiment />
    <header class="page-header">
      <h1>空间结构分析</h1>
      <p class="page-sub">
        数据集 <span class="mono">{{ datasetId }}</span>
        <template v-if="dataset"> · {{ dimension === '3d' ? '三维' : '二维' }}</template>
      </p>
      <p class="intro-text">
        空间结构分析为普通克里金插值提供各向异性证据；IDW 不需要此分析。分析仅读取数据，不修改任何已有成果。
      </p>
    </header>

    <el-result v-if="loadError" icon="error" title="数据集加载失败" :sub-title="loadError" />
    <div v-else-if="loading" v-loading="true" class="page-loading" data-test="page-loading" />

    <div v-else-if="gated" class="gate-blocked" data-test="quality-gate-blocked">
      数据集尚未通过质量门禁（当前状态 {{ dataset?.status }}）：请先完成数据准备与质量校验，
      空间结构分析入口只在质量门禁通过后开放。
    </div>

    <main v-else class="diagnosis-main">
      <div v-if="actionError" class="action-error" data-test="action-error">{{ actionError }}</div>

      <section v-if="phase.kind === 'config'" class="config-section" data-test="diagnosis-config">
        <h2 class="section-heading">分析配置</h2>
        <p class="section-hint">
          经验半变异函数诊断在服务端异步执行；提交后轮询任务状态，证据全部来自登记工件。
        </p>
        <el-collapse>
          <el-collapse-item title="高级设置" name="advanced">
            <div class="cfg-grid">
              <label class="field">
                <span>滞后 bin 数 lag_count</span>
                <input v-model.number="lagCount" type="number" min="4" max="48" class="gmp-input" data-test="cfg-lag-count" />
              </label>
              <label class="field">
                <span>每 bin 最小点对</span>
                <input v-model.number="minPairs" type="number" min="2" max="10000" class="gmp-input" data-test="cfg-min-pairs" />
              </label>
              <label class="field">
                <span>点对上限 max_pairs</span>
                <input v-model.number="maxPairs" type="number" min="100" max="500000" class="gmp-input" data-test="cfg-max-pairs" />
              </label>
            </div>
            <div class="cfg-directions">
              <span class="row-label">方向诊断</span>
              <label v-for="azimuth in AZIMUTH_CHOICES" :key="azimuth" class="radio inline">
                <input
                  type="checkbox"
                  :data-test="`cfg-dir-${azimuth}`"
                  :checked="selectedAzimuths.includes(azimuth)"
                  @change="toggleAzimuth(azimuth)"
                />
                方位 {{ azimuth }}°
              </label>
              <label v-if="dimension === '3d'" class="radio inline">
                <input v-model="includeVertical" type="checkbox" data-test="cfg-dir-vertical" />
                垂向（倾角 90°）
              </label>
            </div>
          </el-collapse-item>
        </el-collapse>
        <div class="cfg-actions">
          <button class="gmp-btn primary" data-test="start-diagnosis" :disabled="starting" @click="start">
            {{ starting ? '提交中…' : '开始空间结构分析' }}
          </button>
        </div>
      </section>

      <section v-else-if="running" class="job-section" data-test="job-status">
        <p>
          诊断任务 <span class="mono">{{ running.jobId }}</span> · 状态 {{ running.status }}
          <template v-if="running.progress.phase"> · 阶段 {{ running.progress.phase }}</template>
          <template v-if="running.progress.total_bins">
            · bin {{ running.progress.completed_bins ?? 0 }} / {{ running.progress.total_bins }}
          </template>
        </p>
        <div v-loading="true" class="job-loading" />
      </section>

      <section v-else-if="failed" class="job-section">
        <div class="job-error" data-test="job-error">
          <p class="error-head">
            {{ failed.status === 'interrupted' ? '诊断任务已中断' : '诊断任务未成功' }}（{{ failed.status }}）
          </p>
          <p class="error-body">
            <b class="mono">{{ failed.error.code }}</b>：{{ failed.error.message }}
          </p>
        </div>
        <button class="gmp-btn" data-test="retry-diagnosis" :disabled="retrying" @click="onRetry">
          {{ retrying ? '重试中…' : '重试诊断（创建新任务）' }}
        </button>
      </section>

      <template v-else-if="phase.kind === 'succeeded' && diagnosis && evidence">
        <section class="diagnosis-meta">
          <span>诊断 <span class="mono">{{ diagnosis.id }}</span></span>
          <span data-test="diagnosis-fingerprint">
            指纹 <span class="mono">{{ diagnosis.fingerprint }}</span>
          </span>
          <span>状态 {{ diagnosis.status }}</span>
        </section>

        <VariogramPanel :evidence="evidence" />

        <section v-if="confirmation" class="confirmation-snapshot" data-test="confirmation-snapshot">
          <h2 class="section-heading">不可变确认快照</h2>
          <p data-test="confirmation-id">确认 ID：<span class="mono">{{ confirmation.id }}</span></p>
          <p data-test="confirmation-fingerprint">
            指纹：<span class="mono">{{ confirmation.fingerprint }}</span>
          </p>
          <p v-if="confirmation.note">说明：{{ confirmation.note }}</p>
          <p class="snapshot-hint">快照已创建且永不修改；如需调整，请创建新的确认。</p>
          <button v-if="confirmationFromExisting" class="gmp-btn primary" data-test="apply-confirmation" @click="gotoExperiment">
            采用建议并创建克里金实验
          </button>
          <button v-else class="gmp-btn primary" data-test="goto-experiment" @click="gotoExperiment">
            用于新建 Kriging 实验
          </button>
        </section>

        <AnisotropyPanel
          v-else
          :suggestion="evidence.anisotropy_candidates"
          :fitted-model-names="fittedModelNames"
          :min-sse-model="minSseModel"
          :fitted-models-sha256="fittedModelsSha256"
          :anisotropy-candidates-sha256="anisotropyCandidatesSha256"
          :dimension="dimension"
          :submitting="confirming"
          @confirm="onConfirm"
        />
      </template>
    </main>
  </div>
</template>

<style scoped>
.diagnosis-page {
  min-height: 100%;
  max-width: 1080px;
  margin: 0 auto;
  padding: 28px 20px 48px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-x: hidden;
}

.page-header h1 {
  margin: 0;
  font-size: 20px;
}

.page-sub {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.intro-text {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--gmp-text-dim);
  line-height: 1.6;
}

.mono {
  font-family: ui-monospace, monospace;
}

.page-loading {
  min-height: 200px;
}

.gate-blocked {
  border: 1px solid #9a7b2d;
  background: rgba(154, 123, 45, 0.12);
  color: #e5c76b;
  border-radius: 10px;
  padding: 14px 16px;
  font-size: 13px;
  line-height: 1.6;
}

.diagnosis-main {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.action-error {
  border: 1px solid #a43d3d;
  background: rgba(164, 61, 61, 0.15);
  color: #ef9a9a;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
}

.config-section,
.job-section,
.diagnosis-meta,
.confirmation-snapshot {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-heading {
  margin: 0;
  font-size: 15px;
}

.section-hint {
  margin: 0;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.cfg-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
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
}

.cfg-directions {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.row-label {
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.radio {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  cursor: pointer;
}

.job-section p {
  margin: 0;
  font-size: 13px;
}

.job-loading {
  min-height: 120px;
}

.job-error {
  border: 1px solid #a43d3d;
  background: rgba(164, 61, 61, 0.12);
  border-radius: 10px;
  padding: 12px 16px;
}

.error-head {
  margin: 0 0 8px;
  color: #ef9a9a;
  font-weight: 600;
}

.error-body {
  margin: 0;
  font-size: 13px;
}

.diagnosis-meta {
  flex-direction: row;
  flex-wrap: wrap;
  gap: 8px 20px;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.confirmation-snapshot p {
  margin: 0;
  font-size: 13px;
}

.snapshot-hint {
  color: var(--gmp-text-faint);
  font-size: 12px;
}

.gmp-btn {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text);
  border-radius: 8px;
  padding: 8px 18px;
  font-size: 13px;
  cursor: pointer;
  align-self: flex-start;
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
</style>
