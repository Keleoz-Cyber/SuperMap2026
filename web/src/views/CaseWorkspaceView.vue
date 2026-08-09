<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { ApiError, fetchCaseWorkspace, fetchProfessionalDiagnostics } from '../api/client'
import type { CaseWorkspaceSummary, ProfessionalDiagnosticListItem } from '../api/types'
import DataPreparationPanel from '../components/cases/DataPreparationPanel.vue'
import CaseStageNav from '../components/cases/CaseStageNav.vue'
import type { CaseStage, CaseStageId } from '../components/cases/CaseStageNav.vue'
import PageNavigation from '../components/navigation/PageNavigation.vue'
import AsyncState from '../components/states/AsyncState.vue'
import { CASE_PRESENTATION, resolveCaseProfile } from '../domain/casePresentation'
import { clearShellContext, setShellContext } from '../stores/shellContext'

const route = useRoute()
const router = useRouter()
const caseId = computed(() => String(route.params.caseId))

const workspace = ref<CaseWorkspaceSummary | null>(null)
const loadError = ref<string | null>(null)
const notInitialized = ref(false)
// PRESET_NOT_INITIALIZED 的后端消息（按案例区分：微震/电阻率），前端不硬编码案例文案
const notInitializedMessage = ref('')
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
// v0.8.0 第二批：统计与空间分析中心入口仅对已验证数据版本开放；
// 未验证版本不出现入口，改显类型化原因文案
const canOpenAnalysisCenter = computed(
  () => workspace.value?.primary_dataset?.status === 'validated',
)
const officialAbnormal = computed(
  () =>
    !!workspace.value &&
    workspace.value.capabilities.official_result &&
    workspace.value.official_result === null,
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

// ---------------------------------------------------------------------------
// v0.9.0：四业务阶段 + 唯一主动作
// ---------------------------------------------------------------------------

const currentStage = ref<CaseStageId>('data')
const stageRefs = new Map<CaseStageId, HTMLElement>()

const preparationPending = computed(() => {
  const ws = workspace.value
  if (!ws || ws.workspace_kind !== 'user_upload') return false
  const prep = ws.data_preparation
  if (!prep) return false
  return prep.state !== 'ready' && prep.state !== 'validated'
})

const hasResults = computed(
  () => canOpenOfficial.value || recentResults.value.length > 0,
)

const stages = computed<CaseStage[]>(() => [
  { id: 'data', enabled: true },
  {
    id: 'experiments',
    enabled: canCreateExperiment.value,
    reason: canCreateExperiment.value ? null : '数据版本未验证或案例不开放实验',
  },
  {
    id: 'results',
    enabled: hasResults.value,
    reason: hasResults.value ? null : '暂无成果',
  },
  { id: 'evidence', enabled: true },
])

// 唯一主动作（设计：每页一个明确主动作）：
// 继续数据准备 > 查看成果/官方成果 > 新建实验；错误/未初始化态为返回首页
const primaryKind = computed<'official' | 'prepare' | 'experiment' | 'home' | null>(() => {
  if (loadError.value || notInitialized.value) return 'home'
  const ws = workspace.value
  if (!ws) return null
  if (preparationPending.value) return 'prepare'
  if (canOpenOfficial.value) return 'official'
  if (canCreateExperiment.value) return 'experiment'
  return null
})

function setStageRef(id: CaseStageId, el: unknown) {
  if (el instanceof HTMLElement) stageRefs.set(id, el)
}

function onStageNavigate(stage: CaseStageId) {
  currentStage.value = stage
  const el = stageRefs.get(stage)
  if (el && typeof el.scrollIntoView === 'function') {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

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
  // v0.8.0：DSI-like 离散平滑插值（工程近似，仅 3D，不等同 GOCAD DSI）
  dsi_like: 'DSI-like 离散平滑插值',
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
  notInitializedMessage.value = ''
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
      notInitializedMessage.value = exc.message
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

// 壳上下文：案例身份与当前阶段登记到全局头
const caseAccent = computed(
  () => CASE_PRESENTATION[resolveCaseProfile(workspace.value?.provenance_summary)].accent,
)
watch(
  [workspace, caseAccent],
  ([ws, accent]) => {
    if (ws) {
      setShellContext({
        caseId: ws.case_id,
        caseTitle: ws.title,
        stageLabel: '案例工作台',
        caseAccent: accent,
      })
    }
  },
  { immediate: true },
)
onBeforeUnmount(clearShellContext)
</script>

<template>
  <div class="case-workspace-page" :data-case-accent="caseAccent">
    <div v-if="notInitialized" class="workspace-state" data-test="workspace-not-initialized">
      <PageNavigation current-label="案例工作台" />
      <AsyncState
        kind="degraded"
        title="预置案例尚未初始化"
        :impact="notInitializedMessage || '官方数据与成果尚未登记到本运行库'"
        next-action="需由维护者执行文档化 seed 命令；初始化完成后官方普通克里金成果自动可用，无需任何用户操作。"
      >
        <template #action>
          <el-button
            type="primary"
            data-test="back-home"
            data-primary-action="true"
            @click="router.push('/')"
          >
            返回首页
          </el-button>
        </template>
      </AsyncState>
    </div>

    <div v-else-if="loadError" class="workspace-state" data-test="workspace-load-error">
      <PageNavigation current-label="案例工作台" />
      <AsyncState
        kind="error"
        title="案例工作台加载失败"
        :impact="loadError"
        next-action="返回首页选择其他案例，或稍后重试"
      >
        <template #action>
          <el-button data-primary-action="true" @click="router.push('/')">返回首页</el-button>
        </template>
      </AsyncState>
    </div>

    <div v-else v-loading="loading">
      <template v-if="workspace">
        <PageNavigation :case-id="caseId" :case-name="workspace.title" current-label="案例工作台" />
        <header class="workspace-header" data-test="case-workspace-header">
          <div class="header-left">
            <el-button :icon="ArrowLeft" circle title="返回首页" aria-label="返回首页" @click="router.push('/')" />
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

        <CaseStageNav
          :stages="stages"
          :current="currentStage"
          @navigate="onStageNavigate"
        />

        <!-- 阶段一：数据概览 -->
        <section :ref="(el) => setStageRef('data', el)" class="stage-block">
          <h2 class="stage-heading">数据概览</h2>

          <div class="workspace-section" data-test="workspace-overview">
            <p v-if="officialAbnormal" class="warn-line" data-test="official-abnormal">
              官方成果准备异常：已声明官方成果能力但缺少可用成果链接。
            </p>
            <div class="command-row">
              <el-button
                v-if="canOpenOfficial"
                type="primary"
                data-test="open-official-result"
                :data-primary-action="primaryKind === 'official' ? 'true' : undefined"
                @click="openOfficialResult"
              >
                {{ workspace.workspace_kind === 'builtin_preset' ? '查看官方成果' : '查看成果' }}
              </el-button>
            </div>
          </div>

          <div class="workspace-section" data-test="workspace-data">
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
            <!-- v0.8.0：builtin_preset 的 data_preparation 是固定 validated 摘要，
                 上传恢复面板仅对 user_upload 渲染；预置数据状态由上方数据版本行表达 -->
            <DataPreparationPanel
              v-if="workspace.data_preparation && workspace.workspace_kind === 'user_upload'"
              :preparation="workspace.data_preparation"
              :case-id="caseId"
              :primary="primaryKind === 'prepare'"
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
                  最近空间结构分析：{{ diagnosisStatusText(ds.id) }}
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
                    空间结构分析
                  </el-button>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- 阶段二：建模实验 -->
        <section :ref="(el) => setStageRef('experiments', el)" class="stage-block">
          <h2 class="stage-heading">建模实验</h2>
          <div class="workspace-section" data-test="workspace-experiments">
            <div v-if="canCreateExperiment" class="command-row">
              <el-button
                type="primary"
                data-test="new-experiment"
                :data-primary-action="primaryKind === 'experiment' ? 'true' : undefined"
                @click="createExperiment"
              >
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
            <p v-else class="muted-line">当前案例不开放新建实验。</p>
            <div v-if="recentExperiments.length" class="recent-list" data-test="recent-experiments">
              <div
                v-for="exp in recentExperiments"
                :key="exp.id"
                class="recent-row"
                :data-test="`recent-experiment-${exp.id}`"
              >
                <router-link :to="exp.url" class="recent-link" :data-test="`recent-experiment-${exp.id}`">
                  {{ exp.name }}
                </router-link>
                <span class="recent-meta">
                  {{ algorithmLabel(exp.algorithm) }}
                  <template v-if="exp.latest_run_status"> · {{ exp.latest_run_status }}</template>
                  <template v-if="exp.succeeded_candidate_count"> · 成功 {{ exp.succeeded_candidate_count }} 候选</template>
                </span>
              </div>
            </div>
          </div>
        </section>

        <!-- 阶段三：成果分析 -->
        <section :ref="(el) => setStageRef('results', el)" class="stage-block">
          <h2 class="stage-heading">成果分析</h2>
          <div class="workspace-section" data-test="workspace-results">
            <p v-if="workspace.official_result">
              {{ workspace.workspace_kind === 'builtin_preset' ? '官方成果' : '主打成果' }}：
              <router-link :to="workspace.official_result.url" class="recent-link">
                {{ workspace.official_result.url }}
              </router-link>
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
                <router-link :to="res.url" class="recent-link">
                  {{ algorithmLabel(res.algorithm) }} 成果
                </router-link>
                <span class="recent-meta">
                  {{ res.materialized ? '已物化' : '未物化' }}
                  <template v-if="res.featured"> · 主打</template>
                </span>
              </div>
            </div>
            <template v-if="workspace.primary_dataset">
              <router-link
                v-if="canOpenAnalysisCenter"
                class="analysis-entry"
                data-test="analysis-center-entry"
                :to="`/datasets/${workspace.primary_dataset.id}/analysis`"
              >
                统计与空间分析
              </router-link>
              <p v-else class="analysis-unavailable" data-test="analysis-center-unavailable">
                数据版本尚未通过验证：完成质量验证后，统计与空间分析才可用。
              </p>
            </template>
          </div>
        </section>

        <!-- 阶段四：证据与报告 -->
        <section :ref="(el) => setStageRef('evidence', el)" class="stage-block">
          <h2 class="stage-heading">证据与报告</h2>
          <div class="workspace-section" data-test="workspace-evidence">
            <p v-if="workspace.provenance_summary.badge" class="provenance-line">
              {{ workspace.provenance_summary.badge }}
            </p>
            <p class="provenance-line">
              坐标语义：{{ workspace.provenance_summary.coordinate_kind ?? 'local_linear' }}（局部坐标，显示锚点仅为展示变换，非真实地理配准）
            </p>
            <p v-if="workspace.workspace_kind === 'builtin_preset'" class="provenance-line">
              官方案例正式选择只读；用户可基于预置数据版本新建实验并登记自己的正式成果。
            </p>
            <p v-else-if="workspace.workspace_kind === 'user_upload'" class="provenance-line">
              成果的正式选择、导出与发布登记在成果工作台内完成。
            </p>
          </div>
        </section>
      </template>
    </div>
  </div>
</template>

<style scoped>
.case-workspace-page {
  min-height: 100%;
  padding: var(--s1-space-4) var(--s1-space-6) var(--s1-space-8);
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-3);
}

.workspace-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--s1-space-3);
}

.header-title h1 {
  margin: 0;
  font-size: var(--s1-font-2xl);
  color: var(--s1-text-strong);
}

.header-sub {
  display: flex;
  gap: var(--s1-space-3);
  align-items: center;
  margin: 6px 0 0;
  color: var(--s1-text-dim);
  font-size: var(--s1-font-md);
}

.stage-block {
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-3);
  scroll-margin-top: 120px;
}

.stage-heading {
  margin: var(--s1-space-2) 0 0;
  font-size: var(--s1-font-lg);
  font-weight: 700;
  color: var(--s1-text-strong);
  padding-left: 10px;
  border-left: 3px solid var(--s1-case-accent);
}

.workspace-section {
  background: var(--s1-surface-1);
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-md);
  padding: var(--s1-space-3) var(--s1-space-4);
}

.command-row {
  display: flex;
  gap: 10px;
}

.warn-line {
  color: var(--s1-warning);
  margin: 0 0 8px;
}

.muted-line {
  color: var(--s1-text-dim);
  font-size: var(--s1-font-md);
}

.provenance-line {
  color: var(--s1-text-dim);
  font-size: var(--s1-font-sm);
  margin: 4px 0;
}

.analysis-entry {
  display: inline-block;
  margin-top: 6px;
  color: var(--s1-cyan-strong);
  font-size: var(--s1-font-md);
  text-decoration: none;
}

.analysis-entry:hover {
  text-decoration: underline;
}

.analysis-unavailable {
  margin: 6px 0 0;
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
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
  border-top: 1px dashed var(--s1-border);
}

.dataset-label {
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
}

.diagnosis-status {
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
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
  border-top: 1px dashed var(--s1-border);
}

.recent-meta {
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
}

.recent-link {
  color: var(--s1-cyan-strong);
  text-decoration: none;
}

.recent-link:hover {
  text-decoration: underline;
}

.abandoned-history {
  margin-top: 8px;
  padding: 6px 0;
  border-top: 1px dashed var(--s1-border);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.abandoned-label {
  margin: 0;
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
}

.abandoned-item {
  font-size: var(--s1-font-sm);
  color: var(--s1-text-faint);
  text-decoration: line-through;
}

/* 窄屏（如 390x844）：收紧页边距并允许换行，避免横向溢出 */
@media (max-width: 480px) {
  .case-workspace-page {
    padding: var(--s1-space-3) var(--s1-space-3) var(--s1-space-6);
  }
  .header-title h1 {
    font-size: var(--s1-font-xl);
  }
  .header-sub {
    flex-wrap: wrap;
    gap: 8px;
  }
  .workspace-section {
    padding: var(--s1-space-3);
  }
  .command-row {
    flex-wrap: wrap;
  }
}
</style>
