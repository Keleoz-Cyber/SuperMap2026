<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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
const coordinateLabel = computed(() => {
  const kind = workspace.value?.provenance_summary.coordinate_kind
  if (kind === 'local_linear') return '局部线性米制坐标'
  if (kind === 'projected') return '投影坐标'
  if (kind === 'geographic') return '地理坐标'
  return kind || '坐标口径未登记'
})
const datasetReadyLabel = computed(() => {
  const status = workspace.value?.primary_dataset?.status
  const labels: Record<string, string> = {
    uploaded: '等待字段确认',
    mapped: '等待质量检查',
    validated: '质量检查通过',
    blocked: '存在阻断问题',
    abandoned: '已放弃',
  }
  return status ? (labels[status] ?? '状态待确认') : '尚未接入数据'
})
const formattedRows = computed(() => {
  const value = rowCounts.value?.valid_row_count ?? rowCounts.value?.row_count
  return typeof value === 'number' ? value.toLocaleString('zh-CN') : '—'
})
const valueLabel = computed(() => {
  const name = typeof mapping.value?.value_name === 'string' ? mapping.value.value_name : '建模属性'
  const displayNames: Record<string, string> = {
    CH4_content: '瓦斯含量',
    RHO: '电阻率',
    Vx: '微震速度',
  }
  const displayName = displayNames[name] ?? name
  const unit = typeof mapping.value?.value_unit === 'string' ? mapping.value.value_unit : ''
  return unit ? `${displayName}（${unit}）` : displayName
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
    enabled: hasResults.value || canOpenAnalysisCenter.value,
    reason: hasResults.value || canOpenAnalysisCenter.value ? null : '数据尚未通过验证',
  },
  { id: 'evidence', enabled: true },
])

// 唯一主动作（设计：每页一个明确主动作）：
// 继续数据准备 > 查看成果/官方成果 > 新建建模实验；错误/未初始化态为返回首页
const primaryKind = computed<'official' | 'prepare' | 'experiment' | 'home' | null>(() => {
  if (loadError.value || notInitialized.value) return 'home'
  const ws = workspace.value
  if (!ws) return null
  if (preparationPending.value) return 'prepare'
  if (canOpenOfficial.value) return 'official'
  if (canCreateExperiment.value) return 'experiment'
  return null
})

function onStageNavigate(stage: CaseStageId) {
  if (!stages.value.some((item) => item.id === stage && item.enabled)) return
  currentStage.value = stage
  void router.push({ query: { ...route.query, stage } })
}

function syncStageFromRoute() {
  const requested = String(route.query.stage ?? '') as CaseStageId
  const available = stages.value.find((item) => item.id === requested && item.enabled)
  currentStage.value = available?.id ?? 'data'
}

watch([() => route.query.stage, stages], syncStageFromRoute, { immediate: true })

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

function runStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    succeeded: '验证完成',
    running: '运行中',
    queued: '排队中',
    failed: '运行失败',
    interrupted: '已中断',
    canceled: '已取消',
  }
  return labels[status] ?? '状态待确认'
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
  <div class="case-workspace-page product-page product-page--wide" :data-case-accent="caseAccent">
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
          <div class="header-title">
            <span class="workspace-kicker">{{ kindLabel }}</span>
            <h1>{{ workspace.title }}</h1>
            <p class="header-sub">
              <span v-if="workspace.provenance_summary.data_form">{{ workspace.provenance_summary.data_form }}</span>
              <span>{{ coordinateLabel }}</span>
            </p>
          </div>
        </header>

        <section class="workspace-summary" data-test="workspace-summary">
          <div class="summary-status">
            <span class="summary-label">当前状态</span>
            <strong>{{ workspace.primary_dataset ? '数据可用于建模' : '等待数据接入' }}</strong>
            <p>{{ datasetReadyLabel }}<template v-if="workspace.primary_dataset">，可继续开展实验、诊断与成果分析。</template></p>
          </div>
          <dl class="summary-metrics">
            <div><dt>有效样本</dt><dd>{{ formattedRows }}</dd></div>
            <div><dt>建模属性</dt><dd>{{ valueLabel }}</dd></div>
            <div><dt>可用成果</dt><dd>{{ hasResults ? '已生成' : '暂无' }}</dd></div>
          </dl>
          <el-button
            v-if="canOpenOfficial"
            type="primary"
            data-test="open-official-result"
            :data-primary-action="primaryKind === 'official' ? 'true' : undefined"
            @click="openOfficialResult"
          >
            {{ workspace.workspace_kind === 'builtin_preset' ? '查看官方成果' : '查看成果' }}
          </el-button>
        </section>

        <CaseStageNav
          :stages="stages"
          :current="currentStage"
          @navigate="onStageNavigate"
        />

        <!-- 阶段一：数据概览 -->
        <section
          :class="{ 'is-hidden': currentStage !== 'data' }"
          id="case-panel-data"
          class="stage-block"
          data-test="stage-panel-data"
          role="tabpanel"
        >
          <h2 class="stage-heading">数据概览</h2>

          <div class="workspace-section overview-notice" data-test="workspace-overview">
            <p v-if="officialAbnormal" class="warn-line" data-test="official-abnormal">
              官方成果准备异常：已声明官方成果能力但缺少可用成果链接。
            </p>
            <p v-else>这里确认当前建模数据的质量、属性与历史版本；参数实验在“建模实验”中进行。</p>
          </div>

          <div class="workspace-section" data-test="workspace-data">
            <template v-if="workspace.primary_dataset">
              <dl class="data-summary-grid">
                <div><dt>数据版本</dt><dd>v{{ workspace.primary_dataset.version }}</dd></div>
                <div><dt>质量状态</dt><dd>{{ datasetReadyLabel }}</dd></div>
                <div><dt>有效样本</dt><dd>{{ formattedRows }}</dd></div>
                <div><dt>建模属性</dt><dd>{{ valueLabel }}</dd></div>
              </dl>
              <div class="task-grid" data-test="data-readiness-grid">
                <article class="task-item">
                  <span class="task-index">01</span>
                  <div><strong>数据质量已确认</strong><p>{{ formattedRows }} 个有效样本可参与插值，无效记录不会进入建模。</p></div>
                </article>
                <article class="task-item">
                  <span class="task-index">02</span>
                  <div><strong>空间口径已登记</strong><p>{{ coordinateLabel }}，当前用于局部工程场景的相对位置分析。</p></div>
                </article>
                <article class="task-item">
                  <span class="task-index">03</span>
                  <div><strong>下一步可执行</strong><p>进入建模实验比较插值方案，或先做空间结构诊断与统计分析。</p></div>
                </article>
              </div>
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
                数据版本 v{{ ds.version }}
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
                <span class="dataset-label">数据版本 v{{ ds.version }}</span>
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
                    查看诊断结论
                  </el-button>
                  <el-button
                    v-if="ds.status === 'validated'"
                    size="small"
                    data-test="reanalyze-btn"
                    @click="reanalyzeDataset(ds.id)"
                  >
                    {{ diagnosisHasDetail(ds.id) ? '重新计算' : '开始空间结构诊断' }}
                  </el-button>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- 阶段二：建模实验 -->
        <section
          :class="{ 'is-hidden': currentStage !== 'experiments' }"
          id="case-panel-experiments"
          class="stage-block"
          data-test="stage-panel-experiments"
          role="tabpanel"
        >
          <h2 class="stage-heading">建模实验</h2>
          <div class="workspace-section" data-test="workspace-experiments">
            <div class="section-intro">
              <div><strong>构建与比较插值方案</strong><p>选择 IDW、普通克里金或 DSI-like，运行一个或多个参数组合并比较结果。</p></div>
              <div class="command-row">
                <el-button v-if="canCreateExperiment" type="primary" data-test="new-experiment" :data-primary-action="primaryKind === 'experiment' ? 'true' : undefined" @click="createExperiment">新建建模实验</el-button>
                <el-button v-if="workspace.primary_dataset" data-test="model-comparison" @click="gotoComparisonForDataset(workspace.primary_dataset.id)">比较已有模型</el-button>
              </div>
            </div>
            <div class="algorithm-paths" data-test="algorithm-paths">
              <article class="algorithm-path">
                <span class="path-tag">快速基线</span>
                <strong>IDW 反距离加权</strong>
                <p>适合快速形成基线并检查局部数据影响，参数少、计算开销较低。</p>
              </article>
              <article class="algorithm-path recommended">
                <span class="path-tag">推荐比较</span>
                <strong>普通克里金</strong>
                <p>结合空间相关结构进行估计，可配合空间诊断与交叉验证选择参数。</p>
              </article>
              <article class="algorithm-path">
                <span class="path-tag">工程对照</span>
                <strong>DSI-like 离散平滑</strong>
                <p>以观测点约束连续场并进行邻域平滑，适合作为工程近似对照。</p>
              </article>
            </div>
            <p v-if="!canCreateExperiment" class="muted-line">当前案例不开放新建建模实验。</p>
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
                  <template v-if="exp.latest_run_status"> · {{ runStatusLabel(exp.latest_run_status) }}</template>
                  <template v-if="exp.succeeded_candidate_count"> · 成功 {{ exp.succeeded_candidate_count }} 候选</template>
                </span>
              </div>
            </div>
          </div>
        </section>

        <!-- 阶段三：成果分析 -->
        <section
          :class="{ 'is-hidden': currentStage !== 'results' }"
          id="case-panel-results"
          class="stage-block"
          data-test="stage-panel-results"
          role="tabpanel"
        >
          <h2 class="stage-heading">成果分析</h2>
          <div class="workspace-section" data-test="workspace-results">
            <div v-if="workspace.official_result" class="section-intro">
              <div><strong>{{ workspace.workspace_kind === 'builtin_preset' ? '官方成果已就绪' : '主打成果已就绪' }}</strong><p>可进入三维成果工作台进行体渲染、切片、剖面和评价。</p></div>
            </div>
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
                  {{ res.materialized ? '三维网格已生成' : '等待生成三维网格' }}
                  <template v-if="res.featured"> · 主打</template>
                </span>
              </div>
            </div>
            <div v-if="workspace.primary_dataset" class="destination-grid" data-test="result-destinations">
              <router-link
                v-if="workspace.official_result"
                :to="workspace.official_result.url"
                class="destination-item primary"
                data-test="open-result-workbench"
              >
                <span class="destination-label">三维成果工作台</span>
                <strong>体渲染、切片与剖面</strong>
                <small>在连续体中查看空间分布，并导出当前剖面证据。</small>
              </router-link>
              <router-link
                v-if="canOpenAnalysisCenter"
                class="destination-item"
                data-test="analysis-center-entry"
                :to="`/datasets/${workspace.primary_dataset.id}/analysis`"
              >
                <span class="destination-label">统计与空间分析</span>
                <strong>分布、异常与深度分层</strong>
                <small>查看与当前地质属性对应的专属统计结论和空间证据。</small>
              </router-link>
              <router-link
                v-if="workspace.official_result"
                class="destination-item"
                data-test="model-evaluation-entry"
                :to="`/results/${workspace.official_result.result_id}/evaluation`"
              >
                <span class="destination-label">模型评估</span>
                <strong>误差指标与限制</strong>
                <small>核对交叉验证指标、残差证据、适用范围与决策建议。</small>
              </router-link>
            </div>
            <template v-if="workspace.primary_dataset">
              <p v-if="!canOpenAnalysisCenter" class="analysis-unavailable" data-test="analysis-center-unavailable">
                数据版本尚未通过验证：完成质量验证后，统计与空间分析才可用。
              </p>
            </template>
          </div>
        </section>

        <!-- 阶段四：证据与报告 -->
        <section
          :class="{ 'is-hidden': currentStage !== 'evidence' }"
          id="case-panel-evidence"
          class="stage-block"
          data-test="stage-panel-evidence"
          role="tabpanel"
        >
          <h2 class="stage-heading">证据与报告</h2>
          <div class="workspace-section" data-test="workspace-evidence">
            <p v-if="workspace.provenance_summary.badge" class="provenance-line">
              {{ workspace.provenance_summary.badge }}
            </p>
            <p class="provenance-line">坐标口径：{{ coordinateLabel }}（显示锚点仅为展示变换，非真实地理配准）</p>
            <p v-if="workspace.workspace_kind === 'builtin_preset'" class="provenance-line">
              官方案例正式选择只读；用户可基于预置数据版本新建建模实验并登记自己的正式成果。
            </p>
            <p v-else-if="workspace.workspace_kind === 'user_upload'" class="provenance-line">
              成果的正式选择、导出与发布登记在成果工作台内完成。
            </p>
            <ul class="evidence-boundaries" data-test="evidence-boundaries">
              <li><strong>数据依据</strong><span>样本数量、字段映射和质量状态来自当前数据版本。</span></li>
              <li><strong>模型依据</strong><span>误差指标采用公共有效集空间验证口径，不代表区域外推精度。</span></li>
              <li><strong>空间边界</strong><span>当前为局部工程坐标展示，不能替代真实地理配准或安全规范结论。</span></li>
            </ul>
            <details v-if="workspace.primary_dataset" class="dataset-technical" data-test="dataset-technical-details">
              <summary>技术详情</summary>
              <dl>
                <div><dt>案例标识</dt><dd class="mono">{{ workspace.case_id }}</dd></div>
                <div><dt>数据版本标识</dt><dd class="mono">{{ workspace.primary_dataset.id }}</dd></div>
                <div><dt>服务端状态</dt><dd class="mono">{{ workspace.primary_dataset.status }}</dd></div>
                <div v-if="mapping"><dt>字段映射</dt><dd class="mono">{{ mapping.x }}/{{ mapping.y }}/{{ mapping.z }} -&gt; {{ mapping.value }}</dd></div>
                <div><dt>坐标枚举</dt><dd class="mono">{{ workspace.provenance_summary.coordinate_kind ?? 'local_linear' }}</dd></div>
              </dl>
            </details>
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

.workspace-kicker {
  display: inline-block;
  margin-bottom: 5px;
  color: var(--s1-case-accent);
  font-size: var(--s1-font-sm);
  font-weight: 600;
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

.workspace-summary {
  display: grid;
  grid-template-columns: minmax(240px, 1.1fr) minmax(360px, 1fr) auto;
  gap: var(--s1-space-5);
  align-items: center;
  padding: var(--s1-space-5) 0;
  border-block: 1px solid var(--s1-border);
}

.summary-status,
.section-intro > div:first-child {
  min-width: 0;
}

.summary-label {
  display: block;
  margin-bottom: 6px;
  color: var(--s1-text-faint);
  font-size: var(--s1-font-xs);
}

.summary-status strong {
  color: var(--s1-text-strong);
  font-size: var(--s1-font-xl);
}

.summary-status p,
.section-intro p,
.overview-notice p {
  margin: 6px 0 0;
  color: var(--s1-text-dim);
  font-size: var(--s1-font-sm);
  line-height: var(--s1-leading);
}

.summary-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 0;
}

.summary-metrics div {
  min-width: 0;
  padding: 0 var(--s1-space-4);
  border-left: 1px solid var(--s1-border);
}

.summary-metrics dt,
.data-summary-grid dt,
.dataset-technical dt {
  color: var(--s1-text-faint);
  font-size: var(--s1-font-xs);
}

.summary-metrics dd,
.data-summary-grid dd {
  margin: 5px 0 0;
  color: var(--s1-text-strong);
  font-weight: 600;
  overflow-wrap: anywhere;
}

.stage-block {
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-3);
  scroll-margin-top: 120px;
}

.stage-block.is-hidden {
  display: none;
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
  align-items: center;
  flex-wrap: wrap;
}

.data-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  margin: 0;
  border: 1px solid var(--s1-border);
  background: var(--s1-border);
}

.data-summary-grid div {
  min-width: 0;
  padding: var(--s1-space-3);
  background: var(--s1-surface-2);
}

.task-grid,
.algorithm-paths,
.destination-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s1-space-3);
  margin-top: var(--s1-space-4);
}

.task-item,
.algorithm-path,
.destination-item {
  min-width: 0;
  padding: var(--s1-space-4);
  border: 1px solid var(--s1-border-soft);
  background: var(--s1-surface-2);
}

.task-item {
  display: flex;
  gap: var(--s1-space-3);
  align-items: flex-start;
}

.task-index,
.path-tag,
.destination-label {
  color: var(--s1-case-accent);
  font-size: var(--s1-font-xs);
  font-weight: 700;
  letter-spacing: 0.04em;
}

.task-item strong,
.algorithm-path strong,
.destination-item strong {
  display: block;
  margin-top: 4px;
  color: var(--s1-text-strong);
  font-size: var(--s1-font-md);
}

.task-item p,
.algorithm-path p,
.destination-item small {
  display: block;
  margin: 6px 0 0;
  color: var(--s1-text-dim);
  font-size: var(--s1-font-sm);
  line-height: var(--s1-leading);
}

.algorithm-path.recommended,
.destination-item.primary {
  border-color: var(--s1-case-accent);
  box-shadow: inset 3px 0 0 var(--s1-case-accent);
}

.destination-item {
  color: inherit;
  text-decoration: none;
  transition:
    border-color var(--s1-motion-fast) var(--s1-ease-out),
    background var(--s1-motion-fast) var(--s1-ease-out);
}

.destination-item:hover,
.destination-item:focus-visible {
  border-color: var(--s1-case-accent);
  background: var(--s1-case-accent-soft);
}

.destination-item:focus-visible {
  outline: 2px solid var(--s1-case-accent);
  outline-offset: 2px;
}

.evidence-boundaries {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s1-space-3);
  margin: var(--s1-space-4) 0 0;
  padding: 0;
  list-style: none;
}

.evidence-boundaries li {
  padding: var(--s1-space-3);
  border-top: 2px solid var(--s1-case-accent);
  background: var(--s1-surface-2);
}

.evidence-boundaries strong,
.evidence-boundaries span {
  display: block;
}

.evidence-boundaries strong {
  color: var(--s1-text-strong);
  font-size: var(--s1-font-md);
}

.evidence-boundaries span {
  margin-top: 6px;
  color: var(--s1-text-dim);
  font-size: var(--s1-font-sm);
  line-height: var(--s1-leading);
}

.section-intro {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s1-space-4);
}

.section-intro strong {
  color: var(--s1-text-strong);
  font-size: var(--s1-font-lg);
}

.dataset-technical {
  margin-top: var(--s1-space-4);
  padding-top: var(--s1-space-3);
  border-top: 1px solid var(--s1-border);
  color: var(--s1-text-dim);
  font-size: var(--s1-font-sm);
}

.dataset-technical summary {
  width: fit-content;
  cursor: pointer;
}

.dataset-technical dl {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s1-space-3);
  margin: var(--s1-space-3) 0 0;
}

.dataset-technical dd {
  margin: 4px 0 0;
  overflow-wrap: anywhere;
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

  .workspace-summary,
  .summary-metrics,
  .data-summary-grid,
  .dataset-technical dl,
  .task-grid,
  .algorithm-paths,
  .destination-grid,
  .evidence-boundaries {
    grid-template-columns: 1fr;
  }

  .workspace-summary {
    align-items: stretch;
    gap: var(--s1-space-3);
  }

  .summary-metrics div {
    padding: var(--s1-space-2) 0;
    border-left: 0;
    border-top: 1px solid var(--s1-border);
  }

  .section-intro {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
