<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { ApiError, fetchCaseWorkspace, fetchProfessionalDiagnostics } from '../api/client'
import type { CaseWorkspaceSummary, ProfessionalDiagnosticListItem } from '../api/types'
import DataPreparationPanel from '../components/cases/DataPreparationPanel.vue'
import PageNavigation from '../components/navigation/PageNavigation.vue'
import RhoCaseView from './RhoCaseView.vue'

const route = useRoute()
const router = useRouter()
const caseId = computed(() => String(route.params.caseId))

const workspace = ref<CaseWorkspaceSummary | null>(null)
const loadError = ref<string | null>(null)
const notInitialized = ref(false)
const loading = ref(true)

type DiagnosisLookupState =
  | { kind: 'loading' }
  | { kind: 'ready'; item: ProfessionalDiagnosticListItem | null }
  | { kind: 'error' }

const diagnosisByDataset = ref(new Map<string, DiagnosisLookupState>())

const KIND_LABELS: Record<CaseWorkspaceSummary['workspace_kind'], string> = {
  builtin_legacy: '内置案例',
  builtin_preset: 'CSV 预置',
  user_upload: '用户上传',
}

const kindLabel = computed(() =>
  workspace.value ? KIND_LABELS[workspace.value.workspace_kind] : '',
)

const canOpenOfficial = computed(
  () =>
    !!workspace.value &&
    workspace.value.capabilities.official_result &&
    workspace.value.official_result !== null,
)
const canCreateExperiment = computed(
  () =>
    !!workspace.value &&
    workspace.value.capabilities.experiments &&
    workspace.value.primary_dataset !== null,
)
const officialAbnormal = computed(
  () =>
    !!workspace.value &&
    workspace.value.capabilities.official_result &&
    workspace.value.official_result === null,
)
const isResistivity = computed(
  () => workspace.value?.workspace_kind === 'builtin_legacy' && caseId.value === 'resistivity',
)
const mapping = computed(() => {
  const profile = workspace.value?.primary_dataset?.profile as
    | { mapping?: Record<string, unknown>; row_count?: number; valid_row_count?: number }
    | undefined
  return profile?.mapping ?? null
})
const rowCounts = computed(() => {
  const profile = workspace.value?.primary_dataset?.profile as
    | { row_count?: number; valid_row_count?: number; invalid_row_count?: number }
    | undefined
  return profile ?? null
})

const abandonedDatasets = computed(() => {
  return workspace.value?.abandoned_datasets ?? []
})

const recentExperiments = computed(() => workspace.value?.recent_experiments ?? [])
const recentResults = computed(() => workspace.value?.recent_results ?? [])

function openOfficialResult() {
  const url = workspace.value?.official_result?.url
  if (url) router.push(url)
}
function createExperiment() {
  const datasetId = workspace.value?.primary_dataset?.id
  void router.push({
    path: `/cases/${caseId.value}/experiments/new`,
    query: datasetId ? { dataset: datasetId } : {},
  })
}
function gotoDiagnosisDetail(datasetId: string) {
  const state = diagnosisByDataset.value.get(datasetId)
  if (state?.kind === 'ready' && state.item) {
    const url = state.item.url
    const stripped = url.startsWith('/#/') ? url.slice(2) : url
    void router.push(stripped)
  }
}
function reanalyzeDataset(datasetId: string) {
  void router.push({
    name: 'professional-diagnosis',
    params: { datasetId },
    query: { case: caseId.value },
  })
}
function gotoComparisonForDataset(datasetId: string) {
  void router.push({
    path: `/datasets/${datasetId}/candidate-comparison`,
    query: { case: caseId.value },
  })
}

function diagnosisStatusText(datasetId: string): string {
  const state = diagnosisByDataset.value.get(datasetId)
  if (!state || state.kind === 'loading') return ''
  if (state.kind === 'error') return '分析状态暂不可用'
  if (!state.item) return ''
  const status = (state.item.diagnosis as { status?: string }).status ?? ''
  const labels: Record<string, string> = {
    succeeded: '成功',
    running: '运行中',
    failed: '失败',
    queued: '排队中',
    interrupted: '已中断',
    canceled: '已取消',
  }
  return labels[status] ?? status
}

function diagnosisHasDetail(datasetId: string): boolean {
  const state = diagnosisByDataset.value.get(datasetId)
  return state?.kind === 'ready' && state.item !== null
}

const ALGORITHM_LABELS: Record<string, string> = {
  idw: 'IDW',
  ordinary_kriging: '普通克里金',
}

function algorithmLabel(id: string): string {
  return ALGORITHM_LABELS[id] ?? id
}

async function loadDiagnosisStatuses() {
  const datasets = workspace.value?.validated_datasets ?? []
  const targetCaseId = caseId.value
  const seq = workspaceRequestSeq
  for (const ds of datasets) {
    try {
      const list = await fetchProfessionalDiagnostics(ds.id)
      if (seq !== workspaceRequestSeq || targetCaseId !== caseId.value) return
      const first = list.diagnostics[0] ?? null
      diagnosisByDataset.value.set(ds.id, { kind: 'ready', item: first })
    } catch {
      if (seq !== workspaceRequestSeq || targetCaseId !== caseId.value) return
      diagnosisByDataset.value.set(ds.id, { kind: 'error' })
    }
  }
}

let workspaceRequestSeq = 0

async function loadWorkspace() {
  const targetId = caseId.value
  const seq = ++workspaceRequestSeq
  const isCurrent = () => seq === workspaceRequestSeq && targetId === caseId.value
  loading.value = true
  workspace.value = null
  loadError.value = null
  notInitialized.value = false
  diagnosisByDataset.value.clear()
  try {
    const result = await fetchCaseWorkspace(targetId)
    if (!isCurrent()) return
    workspace.value = result
    void loadDiagnosisStatuses()
  } catch (exc) {
    if (!isCurrent()) return
    if (exc instanceof ApiError && exc.code === 'PRESET_NOT_INITIALIZED') {
      notInitialized.value = true
    } else {
      loadError.value = exc instanceof Error ? exc.message : String(exc)
    }
  } finally {
    if (isCurrent()) loading.value = false
  }
}

onMounted(loadWorkspace)

watch(caseId, (next, prev) => {
  if (next !== prev) void loadWorkspace()
})
</script>

<template>
  <div class="case-workspace-page">
    <div v-if="notInitialized" class="workspace-state" data-test="workspace-not-initialized">
      <PageNavigation current-label="案例工作台" />
      <el-result
        icon="warning"
        title="微震预置案例尚未初始化"
        sub-title="需由维护者执行文档化 seed 命令；初始化完成后官方普通克里金成果自动可用，无需任何用户操作。"
        role="alert"
      >
        <template #extra>
          <el-button type="primary" data-test="back-home" @click="router.push('/')">
            返回首页
          </el-button>
        </template>
      </el-result>
    </div>

    <div v-else-if="loadError" class="workspace-state" data-test="workspace-load-error">
      <PageNavigation current-label="案例工作台" />
      <el-result icon="error" title="案例工作台加载失败" :sub-title="loadError" role="alert">
        <template #extra>
          <el-button @click="router.push('/')">返回首页</el-button>
        </template>
      </el-result>
    </div>

    <div v-else v-loading="loading">
      <template v-if="workspace">
        <PageNavigation :case-id="caseId" :case-name="workspace.title" current-label="案例工作台" />
        <header class="workspace-header" data-test="case-workspace-header">
          <div class="header-left">
            <el-button :icon="ArrowLeft" circle title="返回首页" @click="router.push('/')" />
            <div class="header-title">
              <h1>{{ workspace.title }} · 案例工作台</h1>
              <p class="header-sub">
                <el-tag size="small" effect="dark" round>{{ kindLabel }}</el-tag>
                <span v-if="workspace.provenance_summary.data_form">
                  {{ workspace.provenance_summary.data_form }}
                </span>
                <span v-if="workspace.provenance_summary.value_unit">
                  单位：{{ workspace.provenance_summary.value_unit }}
                </span>
                <span v-if="workspace.provenance_summary.coordinate_kind">
                  坐标：{{ workspace.provenance_summary.coordinate_kind }}
                </span>
              </p>
            </div>
          </div>
        </header>

        <section class="workspace-section" data-test="workspace-overview">
          <h2 class="section-title">概览</h2>
          <p v-if="officialAbnormal" class="warn-line" data-test="official-abnormal">
            官方成果准备异常：已声明官方成果能力但缺少可用成果链接。
          </p>
          <div class="command-row">
            <el-button
              v-if="canOpenOfficial"
              type="primary"
              data-test="open-official-result"
              @click="openOfficialResult"
            >
              {{ workspace.workspace_kind === 'builtin_preset' ? '查看官方成果' : '查看成果' }}
            </el-button>
          </div>
        </section>

        <section class="workspace-section" data-test="workspace-data">
          <h2 class="section-title">数据</h2>
          <template v-if="workspace.primary_dataset">
            <p>
              数据版本 v{{ workspace.primary_dataset.version }} · 状态
              {{ workspace.primary_dataset.status }}
              <template v-if="rowCounts?.row_count">
                · 行数 {{ rowCounts.row_count }}
                <template v-if="rowCounts.valid_row_count !== undefined">
                  （有效 {{ rowCounts.valid_row_count }}）
                </template>
              </template>
            </p>
            <p v-if="mapping">
              字段：{{ mapping.x }}/{{ mapping.y }}/{{ mapping.z }} -> {{ mapping.value }}（
              {{ mapping.value_name }}<template v-if="mapping.value_unit">
                ，{{ mapping.value_unit }}</template
              >）
            </p>
          </template>
          <p v-else>当前没有可查看的数据版本。</p>
          <p v-if="workspace.provenance_summary.badge" class="provenance-line">
            {{ workspace.provenance_summary.badge }}
          </p>
          <DataPreparationPanel
            v-if="workspace.data_preparation"
            :preparation="workspace.data_preparation"
            :case-id="caseId"
          />
          <div
            v-if="abandonedDatasets.length"
            class="abandoned-history"
            data-test="abandoned-datasets"
          >
            <p class="abandoned-label">已放弃的数据版本：</p>
            <span
              v-for="ds in abandonedDatasets"
              :key="ds.id"
              class="abandoned-item"
            >
              v{{ ds.version }} · {{ ds.id }}
            </span>
          </div>
          <div
            v-if="workspace.validated_datasets?.length"
            class="validated-datasets"
            data-test="validated-datasets"
          >
            <div
              v-for="ds in workspace.validated_datasets"
              :key="ds.id"
              class="dataset-row"
              :data-test="`validated-dataset-${ds.id}`"
            >
              <span class="dataset-label">
                数据版本 v{{ ds.version }} · {{ ds.id }}
              </span>
              <span
                v-if="diagnosisStatusText(ds.id)"
                class="diagnosis-status"
                :data-test="`diagnosis-status-${ds.id}`"
              >
                最近分析：{{ diagnosisStatusText(ds.id) }}
              </span>
              <div class="command-row">
                <el-button
                  v-if="diagnosisHasDetail(ds.id)"
                  size="small"
                  data-test="diagnosis-detail-btn"
                  @click="gotoDiagnosisDetail(ds.id)"
                >
                  查看分析详情
                </el-button>
                <el-button
                  v-if="ds.status === 'validated'"
                  size="small"
                  data-test="reanalyze-btn"
                  @click="reanalyzeDataset(ds.id)"
                >
                  重新分析
                </el-button>
              </div>
            </div>
          </div>
        </section>

        <section class="workspace-section" data-test="workspace-experiments">
          <h2 class="section-title">实验</h2>
          <div v-if="canCreateExperiment" class="command-row">
            <el-button type="primary" data-test="new-experiment" @click="createExperiment">
              新建实验
            </el-button>
            <el-button
              v-if="workspace.primary_dataset"
              data-test="model-comparison"
              @click="gotoComparisonForDataset(workspace.primary_dataset.id)"
            >
              模型比较
            </el-button>
          </div>
          <p v-else>当前案例不开放新建实验。</p>
          <div v-if="recentExperiments.length" class="recent-list" data-test="recent-experiments">
            <div
              v-for="exp in recentExperiments"
              :key="exp.id"
              class="recent-row"
              :data-test="`recent-experiment-${exp.id}`"
            >
              <el-link type="primary" :underline="false" @click="router.push(exp.url)">
                {{ exp.name }}
              </el-link>
              <span class="recent-meta">
                {{ algorithmLabel(exp.algorithm) }}
                <template v-if="exp.latest_run_status"> · {{ exp.latest_run_status }}</template>
                <template v-if="exp.succeeded_candidate_count"> · 成功 {{ exp.succeeded_candidate_count }} 候选</template>
              </span>
            </div>
          </div>
        </section>

        <section class="workspace-section" data-test="workspace-results">
          <h2 class="section-title">成果</h2>
          <p v-if="workspace.official_result">
            {{ workspace.workspace_kind === 'builtin_preset' ? '官方成果' : '主打成果' }}：
            <el-link type="primary" @click="openOfficialResult">
              {{ workspace.official_result.url }}
            </el-link>
            （{{ workspace.official_result.materialized ? '已物化' : '未物化' }}）
          </p>
          <p v-else-if="workspace.workspace_kind !== 'builtin_legacy'" data-test="results-empty">
            暂无成果。
          </p>
          <div v-if="recentResults.length" class="recent-list" data-test="recent-results">
            <div
              v-for="res in recentResults"
              :key="res.result_id"
              class="recent-row"
              :data-test="`recent-result-${res.result_id}`"
            >
              <el-link type="primary" :underline="false" @click="router.push(res.url)">
                {{ algorithmLabel(res.algorithm) }} 成果
              </el-link>
              <span class="recent-meta">
                {{ res.materialized ? '已物化' : '未物化' }}
                <template v-if="res.featured"> · 主打</template>
              </span>
            </div>
          </div>
          <div v-if="isResistivity" class="rho-block" data-test="workspace-rho-block">
            <RhoCaseView embedded />
          </div>
        </section>
      </template>
    </div>
  </div>
</template>

<style scoped>
.case-workspace-page {
  min-height: 100vh;
  background: #0f141c;
  color: #d5dde8;
  padding: 16px 24px 40px;
}
.workspace-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.header-title h1 {
  margin: 0;
  font-size: 20px;
}
.header-sub {
  display: flex;
  gap: 12px;
  align-items: center;
  margin: 6px 0 0;
  color: #93a1b3;
  font-size: 13px;
}
.workspace-section {
  background: #151c26;
  border: 1px solid #263142;
  border-radius: 8px;
  padding: 14px 18px;
  margin-bottom: 14px;
}
.section-title {
  margin: 0 0 10px;
  font-size: 15px;
  color: #9db4d0;
}
.command-row {
  display: flex;
  gap: 10px;
}
.warn-line {
  color: #e6a23c;
}
.provenance-line {
  color: #7f8ca0;
  font-size: 12px;
}
.rho-block {
  margin-top: 10px;
}
.validated-datasets {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.dataset-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 6px 0;
  border-top: 1px dashed #263142;
}
.dataset-label {
  font-size: 12px;
  color: #93a1b3;
}
.diagnosis-status {
  font-size: 12px;
  color: #7f8ca0;
  display: flex;
  align-items: center;
  gap: 4px;
}
.recent-list {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.recent-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 4px 0;
  border-top: 1px dashed #263142;
}
.recent-meta {
  font-size: 12px;
  color: #7f8ca0;
}
.abandoned-history {
  margin-top: 8px;
  padding: 6px 0;
  border-top: 1px dashed #263142;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.abandoned-label {
  margin: 0;
  font-size: 12px;
  color: #7f8ca0;
}
.abandoned-item {
  font-size: 12px;
  color: #6b7785;
  text-decoration: line-through;
}
</style>
