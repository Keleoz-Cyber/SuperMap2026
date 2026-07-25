<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ApiError,
  cancelRun,
  createExperiment,
  fetchCandidates,
  fetchCaseDatasets,
  fetchDataset,
  fetchExperiment,
  retryRun,
  startRun,
  fetchRun,
} from '../api/client'
import type {
  CandidateRecord,
  DatasetVersionRecord,
  ExperimentRecord,
  RunRecord,
} from '../api/types'
import ParameterEditor, { type ParameterSubmit } from '../components/experiments/ParameterEditor.vue'
import SearchSummary from '../components/experiments/SearchSummary.vue'
import RunProgress from '../components/experiments/RunProgress.vue'
import CandidateLeaderboard from '../components/experiments/CandidateLeaderboard.vue'
import PageNavigation from '../components/navigation/PageNavigation.vue'

const route = useRoute()
const router = useRouter()

const POLL_INTERVAL_MS = 1000
const INFLIGHT = new Set(['queued', 'running'])

const isCreate = computed(() => route.name === 'experiment-create')
const caseId = computed(() => String(route.params.caseId ?? ''))
const experimentId = computed(() => String(route.params.experimentId ?? ''))

// ---------------------------------------------------------- create state
const dataset = ref<DatasetVersionRecord | null>(null)
const name = ref('插值实验')
const submitting = ref(false)

// ----------------------------------------------------------- view state
const experiment = ref<ExperimentRecord | null>(null)
const candidates = ref<CandidateRecord[]>([])
const publicMetrics = ref<Record<string, number>>({})
const latestRun = ref<RunRecord | null>(null)
const acting = ref(false)

const loadError = ref<string | null>(null)
const actionError = ref<string | null>(null)

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

const dimension = computed<'2d' | '3d'>(() =>
  dataset.value?.profile?.dimension === '3d' ? '3d' : '2d',
)

// ----------------------------------------------------------- create flow
async function resolveDataset() {
  const fromQuery = route.query.dataset
  if (typeof fromQuery === 'string' && fromQuery) {
    dataset.value = await fetchDataset(fromQuery)
    return
  }
  // 案例工作台入口：自动选择本案例最新一个已过质量门禁的数据集
  const list = await fetchCaseDatasets(caseId.value)
  const ready = list.datasets.filter((d) => d.status === 'validated')
  const picked = ready.at(-1) ?? null
  if (!picked) {
    throw new ApiError(
      'NO_READY_DATASET',
      '本案例还没有通过质量校验的数据集，请先完成数据准备向导',
      409,
    )
  }
  dataset.value = await fetchDataset(picked.id)
}

async function submit(payload: ParameterSubmit) {
  if (!dataset.value) return
  submitting.value = true
  actionError.value = null
  try {
    const created = await createExperiment({
      case_id: caseId.value,
      name: name.value.trim() || '插值实验',
      algorithm: payload.algorithm,
      dataset_version_id: dataset.value.id,
      search_mode: payload.search_mode,
      parameters: payload.parameters,
      validation: payload.validation,
      grid: payload.grid,
    })
    const run = await startRun(created.id)
    latestRun.value = run
    // 立即切到详情路由：刷新页面后按路由 ID 从服务端恢复进度
    await router.replace({ name: 'experiment-detail', params: { experimentId: created.id } })
  } catch (e) {
    actionError.value = describeError(e)
  } finally {
    submitting.value = false
  }
}

// ----------------------------------------------------------- view flow
async function refreshCandidates() {
  if (!experimentId.value) return
  const body = await fetchCandidates(experimentId.value)
  candidates.value = body.candidates
  publicMetrics.value = body.public_metrics
  if (body.latest_run) {
    latestRun.value = body.latest_run
  }
}

async function tick() {
  if (!latestRun.value) return
  try {
    const run = await fetchRun(latestRun.value.id)
    latestRun.value = run
    if (!INFLIGHT.has(run.status)) {
      stopPolling()
      await refreshCandidates()
    }
  } catch (e) {
    stopPolling()
    actionError.value = describeError(e)
  }
}

function maybePoll() {
  stopPolling()
  if (latestRun.value && INFLIGHT.has(latestRun.value.status)) {
    pollTimer = setInterval(() => {
      void tick()
    }, POLL_INTERVAL_MS)
  }
}

async function loadDetail(id: string) {
  stopPolling()
  loadError.value = null
  try {
    const [exp] = await Promise.all([fetchExperiment(id), refreshCandidates()])
    experiment.value = exp
    maybePoll()
  } catch (e) {
    loadError.value = describeError(e)
  }
}

async function onCancel() {
  if (!latestRun.value) return
  acting.value = true
  actionError.value = null
  try {
    await cancelRun(latestRun.value.id)
  } catch (e) {
    actionError.value = describeError(e)
  } finally {
    acting.value = false
  }
}

async function onRetry() {
  if (!latestRun.value) return
  acting.value = true
  actionError.value = null
  try {
    latestRun.value = await retryRun(latestRun.value.id)
    maybePoll()
  } catch (e) {
    actionError.value = describeError(e)
  } finally {
    acting.value = false
  }
}

// ------------------------------------------------------------- lifecycle
watch(
  () => route.fullPath,
  async () => {
    if (isCreate.value) {
      stopPolling()
      loadError.value = null
      try {
        await resolveDataset()
      } catch (e) {
        loadError.value = describeError(e)
      }
    } else if (experimentId.value) {
      await loadDetail(experimentId.value)
    }
  },
  { immediate: true },
)

onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="experiment-page">
    <PageNavigation v-if="isCreate" home />
    <PageNavigation v-else home :case-id="experiment?.case_id" new-experiment />
    <el-result v-if="loadError" icon="error" title="加载失败" :sub-title="loadError" />

    <template v-else-if="isCreate">
      <header class="page-header">
        <h1>调参实验室</h1>
        <p v-if="dataset" class="page-sub">
          数据集 <b>{{ dataset.profile?.original_filename ?? dataset.id }}</b> ·
          {{ dimension === '3d' ? '三维' : '二维' }} · 案例
          <span class="mono">{{ caseId }}</span>
        </p>
      </header>
      <div v-if="actionError" class="action-error" data-test="action-error">{{ actionError }}</div>
      <label class="name-field">
        <span>实验名称</span>
        <input v-model="name" class="gmp-input" data-test="exp-name" maxlength="256" />
      </label>
      <ParameterEditor v-if="dataset" :dimension="dimension" :submitting="submitting" @submit="submit" />
      <div v-else v-loading="true" class="page-loading" />
    </template>

    <template v-else>
      <header class="page-header">
        <h1>{{ experiment?.name ?? '实验详情' }}</h1>
        <p class="page-sub">
          实验 <span class="mono">{{ experimentId }}</span>
        </p>
      </header>
      <div v-if="actionError" class="action-error" data-test="action-error">{{ actionError }}</div>
      <SearchSummary v-if="experiment" :params="experiment.params" />
      <RunProgress :run="latestRun" :acting="acting" @cancel="onCancel" @retry="onRetry" />
      <CandidateLeaderboard :candidates="candidates" :public-metrics="publicMetrics" />
    </template>
  </div>
</template>

<style scoped>
.experiment-page {
  min-height: 100%;
  max-width: 1080px;
  margin: 0 auto;
  padding: 28px 20px 48px;
  display: flex;
  flex-direction: column;
  gap: 16px;
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

.mono {
  font-family: ui-monospace, monospace;
}

.back-link {
  margin-left: 12px;
  color: var(--gmp-accent);
  text-decoration: none;
}

.name-field {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--gmp-text-dim);
}

.gmp-input {
  background: var(--gmp-bg-soft);
  border: 1px solid var(--gmp-border);
  color: var(--gmp-text);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 13px;
  min-width: 260px;
}

.page-loading {
  min-height: 200px;
}

.action-error {
  border: 1px solid #a43d3d;
  background: rgba(164, 61, 61, 0.15);
  color: #ef9a9a;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
}
</style>
