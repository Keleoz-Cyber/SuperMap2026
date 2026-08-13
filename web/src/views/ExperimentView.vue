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
  fetchMLCapability,
  fetchExperiment,
  fetchProfessionalConfirmation,
  fetchProfessionalDiagnostics,
  retryRun,
  startRun,
  fetchRun,
} from '../api/client'
import type {
  CandidateRecord,
  DatasetVersionRecord,
  ExperimentCreatePayload,
  ExperimentRecord,
  NeighborhoodPayload,
  MLCapability,
  Algorithm,
  ProfessionalConfirmationSummary,
  ProfessionalDiagnosticListItem,
  RunRecord,
} from '../api/types'
import ParameterEditor, { type ParameterSubmit } from '../components/experiments/ParameterEditor.vue'
import { parseNumberList, resolveDatasetPreset, combinationCount } from '../components/experiments/searchSpace'
import SearchSummary from '../components/experiments/SearchSummary.vue'
import RunProgress from '../components/experiments/RunProgress.vue'
import RunPipeline from '../components/experiments/RunPipeline.vue'
import ResultStatusPanel from '../components/experiments/ResultStatusPanel.vue'
import CandidateLeaderboard from '../components/experiments/CandidateLeaderboard.vue'
import ExperimentLabLayout from '../components/experiments/ExperimentLabLayout.vue'
import ParameterImpactSummary from '../components/experiments/ParameterImpactSummary.vue'
import SpatialPreview, { type SpatialPointInput } from '../components/upload/SpatialPreview.vue'
import PageContextHeader from '../components/navigation/PageContextHeader.vue'
import AsyncState from '../components/states/AsyncState.vue'
import { fetchDatasetPoints } from '../api/client'

const route = useRoute()
const router = useRouter()

const POLL_INTERVAL_MS = 1000
const INFLIGHT = new Set(['queued', 'running'])

const isCreate = computed(() => route.name === 'experiment-create')
const caseId = computed(() => String(route.params.caseId ?? ''))
const experimentId = computed(() => String(route.params.experimentId ?? ''))

const dataset = ref<DatasetVersionRecord | null>(null)
const mlCapability = ref<MLCapability | null>(null)
const name = ref('插值实验')
const submitting = ref(false)

// v0.9.0：实验画布测点预览与参数实时快照
const datasetPoints = ref<SpatialPointInput[] | null>(null)
const datasetPointTotal = ref<number | null>(null)
const editorSnapshot = ref<ParameterSubmit | null>(null)

function onEditorSnapshot(payload: ParameterSubmit) {
  editorSnapshot.value = payload
  editorAlgorithm.value = payload.algorithm
}

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
  if (e instanceof ApiError) return e.message
  return e instanceof Error ? e.message : String(e)
}

const dimension = computed<'2d' | '3d'>(() =>
  dataset.value?.profile?.dimension === '3d' ? '3d' : '2d',
)

const preset = computed(() => resolveDatasetPreset(dataset.value?.profile ?? null))
const datasetDisplayName = computed(() => {
  const filename = dataset.value?.profile?.original_filename
  return typeof filename === 'string' && filename ? filename : '已验证数据版本'
})

// 候选摘要组合数：与 ParameterEditor 同一纯函数口径（手动恒 1，网格按离散候选乘积）
const snapshotCombinationCount = computed(() => {
  const snap = editorSnapshot.value
  if (!snap) return 1
  return snap.search_mode === 'manual' ? 1 : combinationCount(snap.parameters, 'grid')
})

const professionalConfirmationId = computed(() => {
  const q = route.query.professional_confirmation
  return typeof q === 'string' && q ? q : null
})

const professionalEnabled = computed(() => professionalConfirmationId.value !== null)

const confirmationSummary = ref<ProfessionalConfirmationSummary | null>(null)
const confirmationNote = computed(() => {
  const raw = confirmationSummary.value?.confirmation as { note?: string } | undefined
  return raw?.note ?? null
})

const editorAlgorithm = ref<Algorithm>('idw')
function onEditorChange(event: Event) {
  const target = event.target as HTMLInputElement | null
  if (!target || target.name !== 'algo') return
  editorAlgorithm.value = target.dataset.test === 'algo-kriging' ? 'ordinary_kriging' : 'idw'
}

type KrigingBasis = 'quick' | 'analysis'
const krigingBasis = ref<KrigingBasis>('quick')
const latestSucceededDiagnosis = ref<ProfessionalDiagnosticListItem | null>(null)

const showKrigingBasis = computed(
  () => editorAlgorithm.value === 'ordinary_kriging' && !professionalConfirmationId.value,
)

const nbRadii = ref('')
const nbAzimuth = ref(0)
const nbMin = ref(3)
const nbMax = ref(24)
const nbSectors = ref(4)
const nbPerSector = ref(8)
const uncMin = ref(3)
const uncMax = ref(24)
const uncPower = ref(2)

function effectiveRadii(): number[] | null {
  const parsed = nbRadii.value.trim() === '' ? null : parseNumberList(nbRadii.value)
  if (nbRadii.value.trim() !== '' && parsed === null) return null
  const radii = parsed ?? (dimension.value === '3d' ? [80, 40, 20] : [80, 40])
  const expected = dimension.value === '3d' ? 3 : 2
  if (radii.length !== expected) return null
  return radii.every((r) => Number.isFinite(r) && r > 0) ? radii : null
}

const professionalInvalid = computed<string | null>(() => {
  if (!professionalEnabled.value) return null
  if (effectiveRadii() === null) {
    return `邻域半径需为逗号分隔的正数（${dimension.value === '3d' ? '主, 次, 垂 三个' : '主, 次 两个'}）`
  }
  if (!(nbMin.value >= 1 && nbMax.value >= nbMin.value)) return '邻域点数需满足 1 ≤ 最少 ≤ 最多'
  if (nbSectors.value * nbPerSector.value < nbMin.value) {
    return '扇区数 × 每扇区上限必须不小于最少邻点数'
  }
  if (!(uncMin.value >= 1 && uncMax.value >= uncMin.value && uncPower.value > 0)) {
    return '经验误差设置需满足 1 ≤ 最少 ≤ 最多 且 power > 0'
  }
  return null
})

function buildNeighborhood(): NeighborhoodPayload | null {
  const radii = effectiveRadii()
  if (radii === null) return null
  return {
    radii,
    azimuth_deg: nbAzimuth.value,
    min_neighbors: nbMin.value,
    max_neighbors: nbMax.value,
    sector_count: nbSectors.value,
    max_per_sector: nbPerSector.value,
  }
}

function gotoAnalysisNew() {
  if (!dataset.value) return
  void router.push({
    name: 'professional-diagnosis',
    params: { datasetId: dataset.value.id },
    query: { case: confirmationSummary.value?.case_id ?? caseId.value },
  })
}

function gotoAnalysisDetail() {
  if (!latestSucceededDiagnosis.value) return
  const url = latestSucceededDiagnosis.value.url
  const stripped = url.startsWith('/#/') ? url.slice(2) : url
  void router.push(stripped)
}

let diagnosisHistorySeq = 0

async function loadDiagnosisHistory() {
  if (!dataset.value) return
  const targetDatasetId = dataset.value.id
  const seq = ++diagnosisHistorySeq
  try {
    const list = await fetchProfessionalDiagnostics(targetDatasetId)
    if (seq !== diagnosisHistorySeq || dataset.value?.id !== targetDatasetId) return
    const succeeded = list.diagnostics.find(
      (d) => (d.diagnosis as { status?: string }).status === 'succeeded',
    )
    latestSucceededDiagnosis.value = succeeded ?? null
  } catch {
    if (seq !== diagnosisHistorySeq) return
    latestSucceededDiagnosis.value = null
  }
}

async function resolveDataset() {
  if (professionalConfirmationId.value) {
    const summary = await fetchProfessionalConfirmation(professionalConfirmationId.value)
    confirmationSummary.value = summary
    editorAlgorithm.value = 'ordinary_kriging'
    dataset.value = await fetchDataset(summary.dataset_id)
    mlCapability.value = await fetchMLCapability(summary.dataset_id)
    return
  }
  confirmationSummary.value = null
  latestSucceededDiagnosis.value = null
  const fromQuery = route.query.dataset
  if (typeof fromQuery === 'string' && fromQuery) {
    dataset.value = await fetchDataset(fromQuery)
  } else {
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
  if (dataset.value?.status === 'validated') {
    mlCapability.value = await fetchMLCapability(dataset.value.id)
    void loadDiagnosisHistory()
    void loadDatasetPoints(dataset.value.id)
  }
}

// 实验画布：测点空间预览（抽稀只影响预览，不影响建模数据）
async function loadDatasetPoints(targetDatasetId: string) {
  datasetPoints.value = null
  datasetPointTotal.value = null
  try {
    const body = await fetchDatasetPoints(targetDatasetId, 4)
    if (dataset.value?.id !== targetDatasetId) return
    const count = Math.min(body.x.length, body.y.length)
    const pts: SpatialPointInput[] = []
    for (let i = 0; i < count; i++) {
      pts.push({ x: body.x[i], y: body.y[i], z: body.z ? body.z[i] : null })
    }
    datasetPoints.value = pts
    datasetPointTotal.value = count
  } catch {
    // 预览不可用不阻断实验创建；画布显示解释性状态
    datasetPoints.value = null
  }
}

async function submit(payload: ParameterSubmit) {
  if (!dataset.value) return
  actionError.value = null
  const effectiveCaseId = confirmationSummary.value?.case_id ?? caseId.value
  const body: ExperimentCreatePayload = {
    case_id: effectiveCaseId,
    name: name.value.trim() || '插值实验',
    algorithm: payload.algorithm,
    dataset_version_id: dataset.value.id,
    search_mode: payload.search_mode,
    parameters: payload.parameters,
    validation: payload.validation,
    grid: payload.grid,
    ml_experimental_confirmed: payload.ml_experimental_confirmed,
  }
  if (professionalConfirmationId.value) {
    body.professional_confirmation_id = professionalConfirmationId.value
  }
  if (professionalEnabled.value) {
    const invalid = professionalInvalid.value
    const neighborhood = buildNeighborhood()
    if (invalid !== null || neighborhood === null) {
      actionError.value = invalid ?? '搜索邻域配置非法'
      return
    }
    body.neighborhood = neighborhood
    body.empirical_uncertainty = {
      min_neighbors: uncMin.value,
      max_neighbors: uncMax.value,
      power: uncPower.value,
    }
  }
  submitting.value = true
  try {
    const created = await createExperiment(body)
    const run = await startRun(created.id)
    latestRun.value = run
    await router.replace({ name: 'experiment-detail', params: { experimentId: created.id } })
  } catch (e) {
    actionError.value = describeError(e)
  } finally {
    submitting.value = false
  }
}

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
  <div class="experiment-page product-page">
    <PageContextHeader
      v-if="isCreate"
      title="新建建模实验"
      subtitle="选择插值算法、验证方法和参数组合，运行后可在模型比较中查看结果。"
      :case-id="caseId"
    />
    <PageContextHeader
      v-else
      :title="`${experiment?.name ?? '建模实验'} · 实验详情`"
      subtitle="查看运行进度、候选成果、验证指标和失败原因。"
      :case-id="experiment?.case_id"
      :experiment-id="experimentId"
    />
    <AsyncState
      v-if="loadError"
      kind="error"
      title="加载失败"
      :impact="loadError"
      next-action="返回案例工作台重新进入，或稍后重试"
    />

    <template v-else-if="isCreate">
      <div v-if="dataset" class="experiment-context" data-test="experiment-dataset-context">
        <div class="experiment-context-summary" data-test="experiment-dataset-summary">
          <div><span class="context-label">建模数据</span><strong>{{ datasetDisplayName }}</strong></div>
          <div><span class="context-label">质量状态</span><strong>已通过质量检查</strong></div>
          <div><span class="context-label">空间维度</span><strong>{{ dimension === '3d' ? '三维点数据' : '二维点数据' }}</strong></div>
        </div>
        <details data-test="experiment-technical-details">
          <summary>技术详情</summary>
          <span class="mono">案例 {{ caseId }} · 数据版本 {{ dataset.id }}</span>
        </details>
      </div>
      <div v-if="actionError" class="action-error" role="alert" data-test="action-error">{{ actionError }}</div>
      <ExperimentLabLayout
        v-if="dataset"
        :title="name.trim() || '插值实验'"
        :dataset-label="`${datasetDisplayName} · ${dimension === '3d' ? '三维' : '二维'}`"
      >
        <template #actions>
          <label class="name-field">
            <span>实验名称</span>
            <input v-model="name" class="gmp-input" data-test="exp-name" maxlength="256" name="experiment-name" autocomplete="off" />
          </label>
        </template>
        <template #params>
          <div class="editor-wrap" @change="onEditorChange">
            <ParameterEditor
              :dimension="dimension"
              :submitting="submitting"
              :preset="preset"
              :algorithm-lock="professionalConfirmationId ? 'ordinary_kriging' : null"
              :z-scale-lock="professionalConfirmationId ? 1 : null"
              :ml-capability="mlCapability"
              @submit="submit"
              @change="onEditorSnapshot"
            />
          </div>
          <section class="professional-section" data-test="professional-section">
        <div v-if="professionalConfirmationId" class="pro-block">
          <p class="confirmation-chip" data-test="professional-confirmation">
            变异函数确认快照：<span class="mono">{{ professionalConfirmationId }}</span>
            <template v-if="confirmationSummary">
              （指纹 <span class="mono">{{ confirmationSummary.fingerprint }}</span>）
            </template>
            <template v-if="confirmationNote">
              · {{ confirmationNote }}
            </template>
          </p>
        </div>
        <div v-if="showKrigingBasis" class="kriging-basis" data-test="kriging-basis" role="radiogroup">
          <span class="block-title">建模依据</span>
          <div class="basis-options">
            <div
              class="basis-option"
              role="radio"
              :aria-checked="krigingBasis === 'quick'"
              data-test="basis-quick"
              tabindex="0"
              @click="krigingBasis = 'quick'"
              @keydown.enter="krigingBasis = 'quick'"
            >
              快速建模
            </div>
            <div
              class="basis-option"
              role="radio"
              :aria-checked="krigingBasis === 'analysis'"
              data-test="basis-analysis"
              tabindex="0"
              @click="krigingBasis = 'analysis'"
              @keydown.enter="krigingBasis = 'analysis'"
            >
              采用空间结构分析建议
            </div>
          </div>
          <div v-if="krigingBasis === 'analysis'" class="analysis-entry">
            <button
              v-if="latestSucceededDiagnosis"
              class="gmp-btn"
              data-test="spatial-analysis-entry"
              @click="gotoAnalysisDetail"
            >
              查看并采用已有分析
            </button>
            <button
              v-else
              class="gmp-btn"
              data-test="spatial-analysis-entry"
              @click="gotoAnalysisNew"
            >
              开始空间结构分析
            </button>
          </div>
        </div>
        <template v-if="professionalEnabled">
          <el-collapse :model-value="['advanced']">
            <el-collapse-item title="高级参数" name="advanced">
              <div class="pro-block" data-test="professional-neighborhood">
                <span class="block-title">搜索邻域（旋转椭圆/椭球）</span>
                <div class="pro-grid">
                  <label class="field">
                    <span>半径 radii（{{ dimension === '3d' ? '主, 次, 垂' : '主, 次' }}）</span>
                    <input
                      v-model="nbRadii"
                      class="gmp-input"
                      data-test="nb-radii"
                      :placeholder="dimension === '3d' ? '默认 80, 40, 20' : '默认 80, 40'"
                    />
                  </label>
                  <label class="field small">
                    <span>方位角（度）</span>
                    <input v-model.number="nbAzimuth" type="number" min="0" max="180" class="gmp-input" data-test="nb-azimuth" />
                  </label>
                  <label class="field small">
                    <span>最少邻点</span>
                    <input v-model.number="nbMin" type="number" min="1" max="64" class="gmp-input" data-test="nb-min" />
                  </label>
                  <label class="field small">
                    <span>最多邻点</span>
                    <input v-model.number="nbMax" type="number" min="1" max="128" class="gmp-input" data-test="nb-max" />
                  </label>
                  <label class="field small">
                    <span>扇区数</span>
                    <input v-model.number="nbSectors" type="number" min="1" max="16" class="gmp-input" data-test="nb-sectors" />
                  </label>
                  <label class="field small">
                    <span>每扇区上限</span>
                    <input v-model.number="nbPerSector" type="number" min="1" max="128" class="gmp-input" data-test="nb-per-sector" />
                  </label>
                </div>
              </div>
              <div class="pro-block" data-test="professional-uncertainty">
                <span class="block-title">经验不确定性（折外残差距离加权局部 RMSE）</span>
                <div class="pro-grid">
                  <label class="field small">
                    <span>最少邻点</span>
                    <input v-model.number="uncMin" type="number" min="1" max="64" class="gmp-input" data-test="unc-min" />
                  </label>
                  <label class="field small">
                    <span>最多邻点</span>
                    <input v-model.number="uncMax" type="number" min="1" max="128" class="gmp-input" data-test="unc-max" />
                  </label>
                  <label class="field small">
                    <span>幂次 power</span>
                    <input v-model.number="uncPower" type="number" step="0.5" min="0.5" max="8" class="gmp-input" data-test="unc-power" />
                  </label>
                </div>
              </div>
              <p v-if="professionalInvalid" class="pro-error" data-test="professional-invalid">{{ professionalInvalid }}</p>
            </el-collapse-item>
          </el-collapse>
        </template>
          </section>
        </template>
        <template #canvas>
          <SpatialPreview
            v-if="datasetPoints && datasetPoints.length > 0"
            :points="datasetPoints"
            :total-rows="datasetPointTotal"
          />
          <div v-else class="canvas-unavailable" data-test="canvas-unavailable">
            测点预览不可用：不影响参数配置与实验创建。
          </div>
          <div v-if="editorSnapshot?.algorithm === 'ordinary_kriging'" class="canvas-note">
            普通克里金：变异函数证据见「空间结构分析」；快速建模使用自动拟合。
          </div>
          <div v-else-if="editorSnapshot?.algorithm === 'idw'" class="canvas-note">
            IDW：权重随距离幂次衰减，邻点数以局部采样为准。
          </div>
        </template>
        <template #summary>
          <ParameterImpactSummary
            v-if="editorSnapshot"
            :algorithm="editorSnapshot.algorithm"
            :search-mode="editorSnapshot.search_mode"
            :combination-count="snapshotCombinationCount"
            :grid="editorSnapshot.grid"
            :validation="editorSnapshot.validation"
            :parameters="editorSnapshot.parameters"
            :warnings="[]"
          />
        </template>
        <template #queue>
          <p class="queue-hint">实验创建后，运行流水线、候选指标与比较入口将显示在实验队列中。</p>
        </template>
      </ExperimentLabLayout>
      <div v-if="!dataset" v-loading="true" class="page-loading" />
    </template>

    <template v-else>
      <div class="experiment-context">
        <p class="page-sub">
          实验 <span class="mono">{{ experimentId }}</span>
        </p>
      </div>
      <div v-if="actionError" class="action-error" role="alert" data-test="action-error">{{ actionError }}</div>
      <SearchSummary v-if="experiment" :params="experiment.params" />
      <RunPipeline :run="latestRun" />
      <RunProgress :run="latestRun" :acting="acting" @cancel="onCancel" @retry="onRetry" />
      <ResultStatusPanel :run="latestRun" :candidates="candidates" />
      <CandidateLeaderboard
        :candidates="candidates"
        :public-metrics="publicMetrics"
        :algorithm="experiment?.params.algorithm"
      />
    </template>
  </div>
</template>

<style scoped>
.experiment-page {
  min-height: 100%;
  max-width: var(--s1-page-standard);
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

.experiment-context {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px 0;
  border-block: 1px solid var(--s1-border);
}

.experiment-context-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.experiment-context-summary > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.context-label {
  color: var(--s1-text-faint);
  font-size: var(--s1-font-xs);
}

.experiment-context-summary strong {
  color: var(--s1-text-strong);
  overflow-wrap: anywhere;
}

.experiment-context details {
  color: var(--s1-text-faint);
  font-size: var(--s1-font-xs);
}

.experiment-context summary {
  width: fit-content;
  cursor: pointer;
}

.mono {
  font-family: ui-monospace, monospace;
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

.professional-section {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 14px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.pro-block {
  border-top: 1px dashed var(--gmp-border);
  padding-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.block-title {
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.pro-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px 14px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.field.small {
  min-width: 110px;
}

.confirmation-chip {
  margin: 0;
  font-size: 13px;
  color: var(--gmp-text);
}

.pro-error {
  margin: 0;
  font-size: 12px;
  color: #ef9a9a;
}

.kriging-basis {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.basis-options {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.basis-option {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  cursor: pointer;
  padding: 6px 14px;
  border: 1px solid var(--gmp-border);
  border-radius: 8px;
  background: var(--gmp-bg-soft);
  color: var(--gmp-text);
  transition: border-color 0.15s, background 0.15s;
}

.basis-option[aria-checked="true"] {
  border-color: var(--gmp-accent);
  background: rgba(56, 178, 172, 0.12);
  font-weight: 600;
}

.basis-option:focus-visible {
  outline: 2px solid var(--gmp-accent);
  outline-offset: 2px;
}

.analysis-entry {
  padding-top: 4px;
}

.action-error {
  border: 1px solid #a43d3d;
  background: rgba(164, 61, 61, 0.15);
  color: #ef9a9a;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
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

.gmp-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

@media (max-width: 640px) {
  .experiment-context-summary {
    grid-template-columns: 1fr;
  }
}
</style>
