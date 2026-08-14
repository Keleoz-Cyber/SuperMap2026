<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ApiError,
  createExport,
  createRenderAssetSliceExport,
  createResultRenderAsset,
  fetchCase,
  fetchCases,
  fetchDatasetPoints,
  fetchExperiment,
  fetchFormalSelections,
  fetchRenderAssetSliceAnalysis,
  fetchResultAnalysisSummary,
  fetchResultPreview,
  fetchResultRenderAsset,
  fetchResultRenderCapability,
  materializeResult,
} from '../api/client'
import type {
  AnalysisSummaryResponse,
  DatasetPoints,
  ExperimentRecord,
  PlatformCaseRecord,
  ResidualEvidence,
  ResultAnalysisSummary,
  ResultMetadata,
  MLResultField,
  ResultPreview,
  SliceAnalysisResponse,
} from '../api/types'
import NativeVolumePanel from '../components/rendering/NativeVolumePanel.vue'
import type {
  NativeVolumeAuxPoints,
  NativeVolumeRenderApi,
} from '../components/rendering/NativeVolumePanel.vue'
import SlicePanel from '../components/results/SlicePanel.vue'
import FormalSelectionPanel from '../components/results/FormalSelectionPanel.vue'
import ExportPublicationPanel from '../components/results/ExportPublicationPanel.vue'
import V6ResultSummary from '../components/results/V6ResultSummary.vue'
import AsyncState from '../components/states/AsyncState.vue'
import ResultAnalysisWorkbench from '../components/results/ResultAnalysisWorkbench.vue'
import { buildPresentationFindings, type PresentationFinding } from '../domain/findings'
import { fetchAnalysisSummary, fetchResultResiduals } from '../api/client'
import type { AnalysisSelection } from '../components/analysis/analysisTypes'
import { createAnalysisSelectionController } from '../composables/useAnalysisSelection'
import type { SliceAxis } from '../api/types'
import { clearShellContext, setShellContext } from '../stores/shellContext'
import MLFieldSelector from '../components/results/MLFieldSelector.vue'

// v0.9.0 V6 Task 3：成果页 = 成果专用顶栏 + 成果摘要条 + 一屏工作台外壳。
// 页面本身在大屏下禁止纵向滚动；长内容只在右栏与证据窗内部滚动。

const route = useRoute()
const router = useRouter()
const resultId = computed(() => String(route.params.resultId))

const metadata = ref<ResultMetadata | null>(null)
const experiment = ref<ExperimentRecord | null>(null)
const preview = ref<ResultPreview | null>(null)
const points = ref<DatasetPoints | null>(null)
const loadError = ref<string | null>(null)
const activeTab = ref<'field' | 'slices'>('field')

// v0.9.0：分析摘要与残差证据（只读 GET；不可用不阻断成果页主链）
const analysis = ref<AnalysisSummaryResponse | null>(null)
const residuals = ref<ResidualEvidence | null>(null)

// v0.9.0 Task 9：成果级分析（只读 GET；identity 绑定 result_id + grid_sha256）
const resultAnalysis = ref<ResultAnalysisSummary | null>(null)
const resultAnalysisError = ref<string | null>(null)
const resultAnalysisLoading = ref(false)
const currentSlice = ref<SliceAnalysisResponse | null>(null)
const focusedComponentId = ref<number | null>(null)
const volumePanelRef = ref<InstanceType<typeof NativeVolumePanel> | null>(null)
// 三维舞台与异常清单必须共享同一份完整组件集合，避免卡片可点击却无法定位。
// 视觉拥挤由渲染层的聚焦/显隐策略解决，不能通过截断数据身份规避。
const sceneComponents = computed(() => {
  const summary = resultAnalysis.value
  if (!summary) return null
  return [
    ...summary.components_preview.rows,
    ...(summary.low_components_preview?.rows ?? []),
  ]
})

// v0.9.0 V6：顶栏/摘要条上下文（案例、案例列表、正式成果状态、导出状态）
const caseRecord = ref<PlatformCaseRecord | null>(null)
const caseOptions = ref<Array<{ id: string; name: string }>>([])
const formalSelected = ref<boolean | null>(null)
const exporting = ref(false)
const exportError = ref<string | null>(null)
const renderAssetIdentity = ref<{
  assetId: string
  renderer: string
  status: string
  gridSha256: string
  netcdfSha256: string | null
  geolocationStatus: string
} | null>(null)
const activeMLField = ref<MLResultField>('prediction')
const mlFieldLoading = ref(false)
const mlFieldError = ref<string | null>(null)

const availableMLFields = computed<MLResultField[]>(() =>
  resultAnalysis.value?.machine_learning?.available_fields ?? [],
)

const activeMLFieldLabel = computed(() => ({
  prediction: '预测结果',
  model_dispersion: '模型离散度',
  kriging_baseline: '克里金基线',
  residual_correction: '残差校正',
})[activeMLField.value])

function selectMLField(field: MLResultField) {
  if (field === activeMLField.value) return
  activeMLField.value = field
  mlFieldLoading.value = true
  mlFieldError.value = null
  currentSlice.value = null
  focusedComponentId.value = null
  renderAssetIdentity.value = null
}

function onAssetIdentity(info: typeof renderAssetIdentity.value) {
  renderAssetIdentity.value = info
}

function onMLSourceLoadState(payload: { key: string; loading: boolean; error: string | null }) {
  if (payload.key !== activeMLField.value) return
  mlFieldLoading.value = payload.loading
  mlFieldError.value = payload.error
}

const findings = computed<PresentationFinding[]>(() =>
  analysis.value ? buildPresentationFindings(analysis.value) : [],
)

// ---------------------------------------------------------------------------
// v0.9.0 Task 12：图表—三维双向联动
// ---------------------------------------------------------------------------
const selection = createAnalysisSelectionController()
const sliceRequest = ref<{ axis: SliceAxis; range: [number, number]; token: number } | null>(null)
const capabilityNotice = ref<string | null>(null)
const dockTab = ref<'overview' | 'slices' | 'model' | 'provenance'>('overview')
let sliceToken = 0

function requestSlice(axis: SliceAxis, range: [number, number]) {
  sliceToken += 1
  capabilityNotice.value = null
  sliceRequest.value = { axis, range, token: sliceToken }
}

function onFindingLocate(finding: PresentationFinding) {
  const target = finding.spatialTarget
  const datasetId = experiment.value?.params.dataset_version_id
  if (!target || !datasetId) return
  if (target.axis === 'xy') {
    if (target.xRange && target.yRange) {
      const ok = selection.select({
        axis: 'xy',
        x_range: target.xRange,
        y_range: target.yRange,
        dataset_id: datasetId,
        result_id: resultId.value,
      })
      if (ok) {
        // 当前体渲染器不支持 XY 区域过滤：类型化能力通知，不伪报定位
        capabilityNotice.value =
          '当前成果渲染器不支持 XY 区域过滤定位；可使用对应轴切片查看该区域剖面。'
      }
    }
    return
  }
  if (!target.range) return
  const ok = selection.select({
    axis: target.axis,
    range: target.range,
    dataset_id: datasetId,
    result_id: resultId.value,
  })
  if (ok) requestSlice(target.axis, target.range)
}

function onEvidenceSelect(sel: AnalysisSelection) {
  if (!selection.select(sel)) return
  if (sel.axis === 'xy') {
    capabilityNotice.value =
      '当前成果渲染器不支持 XY 区域过滤定位；可使用对应轴切片查看该区域剖面。'
    return
  }
  requestSlice(sel.axis, sel.range)
}

function onSelectResult(nextResultId: string) {
  if (nextResultId && nextResultId !== resultId.value) {
    void router.push(`/results/${nextResultId}`)
  }
}

function onSliceChange() {
  // 三维切片移动 → 证据窗切到「切片与异常」标签（反向联动）
  dockTab.value = 'slices'
}

function onSliceRequestFailed(payload: { reason: string }) {
  capabilityNotice.value = payload.reason
}

// ---------------------------------------------------------------------------
// v0.9.0 Task 9：成果级研判 ↔ 三维双向联动
// ---------------------------------------------------------------------------

function onFocusComponent(componentId: number) {
  focusedComponentId.value = componentId
  volumePanelRef.value?.focusComponent(componentId)
}

function onAnnotationSelected(payload: { componentId: number }) {
  focusedComponentId.value = payload.componentId
}

function onFocusDepthBin(index: number) {
  const bin = resultAnalysis.value?.depth_profile.bins[index]
  if (!bin) return
  requestSlice('z', [bin.z_lower, bin.z_upper])
}

function onSliceAnalysis(response: SliceAnalysisResponse) {
  currentSlice.value = response
  dockTab.value = 'slices'
}

async function exportCurrentSlice(png: Blob) {
  const slice = currentSlice.value
  const assetId = renderAssetIdentity.value?.assetId
  if (!slice || !assetId) throw new Error('当前切片尚未就绪')
  const record = await createRenderAssetSliceExport(
    assetId,
    slice.slice.fixed_axis,
    slice.slice.index,
    png,
  )
  window.location.assign(`/api/exports/${record.id}/download`)
}

// ---------------------------------------------------------------------------
// v0.9.0 V6：顶栏导航 / 案例切换 / 导出分析报告
// ---------------------------------------------------------------------------

function onSelectCase(caseId: string) {
  if (caseId && caseId !== experiment.value?.case_id) {
    void router.push({ name: 'case-workspace', params: { caseId } })
  }
}

// 导出分析报告：显式 POST 创建成果导出包，随后浏览器下载（唯一计费/写操作）
async function onExportReport() {
  if (exporting.value) return
  exporting.value = true
  exportError.value = null
  try {
    const record = await createExport(resultId.value)
    const link = document.createElement('a')
    link.href = `/api/exports/${record.id}/download`
    link.download = ''
    document.body.appendChild(link)
    link.click()
    link.remove()
  } catch (e) {
    exportError.value = e instanceof ApiError ? `${e.code}：${e.message}` : String(e)
  } finally {
    exporting.value = false
  }
}

// 深链恢复：?axis=z&range=a,b&dataset=… 进入成果页时还原选择并定位切片
function restoreSelectionFromQuery() {
  const q = route.query
  const datasetId = experiment.value?.params.dataset_version_id
  if (!datasetId || typeof q.axis !== 'string' || typeof q.range !== 'string') return
  if (q.dataset !== datasetId) return
  const axis = q.axis
  if (axis !== 'x' && axis !== 'y' && axis !== 'z') return
  const parts = q.range.split(',').map(Number)
  if (parts.length !== 2 || !parts.every(Number.isFinite) || parts[0] > parts[1]) return
  const range: [number, number] = [parts[0], parts[1]]
  const ok = selection.select({
    axis,
    range,
    dataset_id: datasetId,
    result_id: resultId.value,
  })
  if (ok) requestSlice(axis, range)
}

// ---------------------------------------------------------------------------
// v0.6.1 NetCDF 原生体渲染：NativeVolumePanel 接线
// ---------------------------------------------------------------------------

const volumeApi: NativeVolumeRenderApi = {
  fetchCapability: () => fetchResultRenderCapability(resultId.value, activeMLField.value),
  fetchAsset: () => fetchResultRenderAsset(resultId.value, activeMLField.value),
  createAsset: (retryFailed) => createResultRenderAsset(resultId.value, retryFailed, activeMLField.value),
  fetchSliceAnalysis: (assetId, axis, index) => fetchRenderAssetSliceAnalysis(assetId, axis, index),
  createSliceExport: (assetId, axis, index, png) =>
    createRenderAssetSliceExport(assetId, axis, index, png),
}

// 网格采样预览作为辅助点层载荷（默认关，仅作数据分布参考，绝不参与连续体渲染）
const gridSamplePoints = computed<NativeVolumeAuxPoints | null>(() => {
  const p = preview.value
  if (!p || !p.z) return null
  return {
    id: 'grid-samples',
    role: 'auxiliary',
    x: p.x,
    y: p.y,
    z: p.z,
    values: p.values,
    isNodata: p.is_nodata,
    style: { color: '#22d3ee', pixelSize: 4 },
  }
})

const sourcePoints = computed(() => {
  if (!points.value) return null
  return { x: points.value.x, y: points.value.y, values: points.value.values }
})

// 成果身份切换：先清空旧身份派生状态（分析/切片/聚焦/网格哈希），再重新加载；
// 绝不把上一成果的分析数字、组件标注或 AI 记录残留到新身份下
function resetForIdentityChange() {
  metadata.value = null
  experiment.value = null
  preview.value = null
  points.value = null
  loadError.value = null
  analysis.value = null
  residuals.value = null
  resultAnalysis.value = null
  resultAnalysisError.value = null
  resultAnalysisLoading.value = false
  currentSlice.value = null
  focusedComponentId.value = null
  sliceRequest.value = null
  capabilityNotice.value = null
  caseRecord.value = null
  formalSelected.value = null
  exportError.value = null
  renderAssetIdentity.value = null
  activeMLField.value = 'prediction'
  mlFieldLoading.value = false
  mlFieldError.value = null
}

// 加载序号：A→B→A 快速切换时，只有最新一次 load 的响应可以写入状态；
// 旧请求无论成功/失败/finally 都不得覆盖（异步竞态守卫）
let loadSeq = 0

async function load() {
  const seq = ++loadSeq
  const currentResultId = resultId.value
  const isCurrent = () => seq === loadSeq
  try {
    // v0.6.1：物化是唯一显式变异入口（POST 一次）；绝不把 fetchResult 当创建捷径。
    const meta = await materializeResult(currentResultId)
    if (!isCurrent()) return
    metadata.value = meta
    const exp = await fetchExperiment(meta.experiment_id)
    if (!isCurrent()) return
    experiment.value = exp
    selection.setContext({ datasetId: exp.params.dataset_version_id, resultId: currentResultId })
    restoreSelectionFromQuery()
    resultAnalysisLoading.value = true
    const datasetId = exp.params.dataset_version_id
    const fetches: Promise<void>[] = [
      fetchDatasetPoints(datasetId).then((p) => {
        if (isCurrent()) points.value = p
      }),
      fetchAnalysisSummary(datasetId)
        .then((s) => {
          if (isCurrent()) analysis.value = s
        })
        .catch(() => {
          if (isCurrent()) analysis.value = null
        }),
      fetchResultResiduals(currentResultId, 4)
        .then((r) => {
          if (isCurrent()) residuals.value = r
        })
        .catch(() => {
          if (isCurrent()) residuals.value = null
        }),
      fetchResultAnalysisSummary(currentResultId)
        .then((s) => {
          if (!isCurrent()) return
          resultAnalysis.value = s
          resultAnalysisError.value = null
        })
        .catch((e) => {
          if (!isCurrent()) return
          resultAnalysis.value = null
          resultAnalysisError.value = e instanceof ApiError ? `${e.code}：${e.message}` : String(e)
        })
        .finally(() => {
          if (isCurrent()) resultAnalysisLoading.value = false
        }),
      // V6 顶栏/摘要条上下文（只读；失败不阻断主链）
      fetchCase(exp.case_id)
        .then((c) => {
          if (isCurrent()) caseRecord.value = c
        })
        .catch(() => {
          if (isCurrent()) caseRecord.value = null
        }),
      fetchCases()
        .then((c) => {
          if (isCurrent()) {
            caseOptions.value = c.cases.map((item) => ({ id: item.case_id, name: item.title }))
          }
        })
        .catch(() => {
          if (isCurrent()) caseOptions.value = []
        }),
      fetchFormalSelections(exp.case_id)
        .then((s) => {
          if (isCurrent()) {
            formalSelected.value = s.selections.some((sel) => sel.candidate_result_id === currentResultId)
          }
        })
        .catch(() => {
          if (isCurrent()) formalSelected.value = null
        }),
    ]
    if (meta.dimension === '3d') {
      activeTab.value = 'field'
      fetches.push(
        fetchResultPreview(currentResultId).then((p) => {
          if (isCurrent()) preview.value = p
        }),
      )
    } else {
      activeTab.value = 'slices'
    }
    await Promise.all(fetches)
  } catch (e) {
    if (!isCurrent()) return
    loadError.value = e instanceof ApiError ? `${e.code}：${e.message}` : String(e)
  }
}

onMounted(load)

// 同页切换成果（模型比较选择/深链）：清旧身份后完整重载
watch(resultId, (next, prev) => {
  if (!next || next === prev) return
  resetForIdentityChange()
  void load()
})

watch(
  [experiment, caseRecord, resultId],
  ([exp, caseInfo, activeResultId]) => {
    setShellContext({
      caseId: exp?.case_id ?? null,
      caseTitle: caseInfo?.name ?? null,
      stageLabel: '成果空间',
      caseAccent: null,
      datasetId: exp?.params.dataset_version_id ?? null,
      experimentId: exp?.id ?? null,
      resultId: activeResultId,
    })
  },
  { immediate: true },
)
onBeforeUnmount(clearShellContext)
</script>

<template>
  <div class="v6-result-page" data-test="v6-result-page">
    <div v-if="loadError" class="v6-error">
      <AsyncState
        kind="error"
        title="成果加载失败"
        :impact="loadError"
        next-action="返回首页或实验页重新进入"
      />
      <div class="v6-error-links">
        <RouterLink to="/" data-test="crumb-home">首页</RouterLink>
        <RouterLink
          v-if="metadata?.experiment_id"
          :to="{ name: 'experiment-detail', params: { experimentId: metadata.experiment_id } }"
          data-test="crumb-experiment"
        >
          实验
        </RouterLink>
      </div>
    </div>

    <template v-else-if="metadata">
      <p v-if="exportError" class="export-error" data-test="export-error" role="status">
        导出失败：{{ exportError }}
      </p>
      <V6ResultSummary
        :case-title="caseRecord?.name ?? null"
        :metadata="metadata"
        :variable="resultAnalysis?.variable ?? null"
        :valid-sample-count="analysis?.quality.valid_count ?? null"
        :r2="metadata.evaluation_summary?.r2 ?? null"
        :common-valid-count="metadata.evaluation_summary?.common_valid_count ?? null"
        :formal-selected="formalSelected"
        :result-id="resultId"
        :current-case-id="experiment?.case_id ?? null"
        :case-options="caseOptions.length > 0 ? caseOptions : experiment ? [{ id: experiment.case_id, name: caseRecord?.name ?? experiment.case_id }] : []"
        :exporting="exporting"
        @select-case="onSelectCase"
        @export-report="onExportReport"
      />

      <ResultAnalysisWorkbench
        class="v6-body"
        v-model:dock-tab="dockTab"
        :findings="findings"
        :summary="analysis"
        :residuals="residuals"
        :dataset-id="experiment?.params.dataset_version_id ?? null"
        :result-id="resultId"
        :analysis="resultAnalysis"
        :analysis-loading="resultAnalysisLoading"
        :analysis-error="resultAnalysisError"
        :current-slice="currentSlice"
        :focused-component-id="focusedComponentId"
        :asset-identity="renderAssetIdentity"
        :selection-notice="capabilityNotice"
        :export-slice="exportCurrentSlice"
        @locate="onFindingLocate"
        @select="onEvidenceSelect"
        @select-result="onSelectResult"
        @focus-component="onFocusComponent"
        @focus-depth-bin="onFocusDepthBin"
      >
        <template #scene>
          <div v-if="metadata.dimension === '3d'" class="field-scene">
            <MLFieldSelector
              v-if="availableMLFields.length > 1"
              :model-value="activeMLField"
              :available-fields="availableMLFields"
              :property-unit="resultAnalysis?.variable.unit ?? null"
              :loading="mlFieldLoading"
              @update:model-value="selectMLField"
            />
            <p
              v-if="activeMLField !== 'prediction'"
              class="active-field-note"
              data-test="active-ml-field-note"
            >
              当前显示：{{ activeMLFieldLabel }}。异常连通区标注仅属于主预测场，已暂时隐藏。
            </p>
            <p v-if="mlFieldError" class="field-load-error" data-test="ml-field-load-error" role="alert">
              当前字段暂时无法加载：{{ mlFieldError }}。可以切换到其他字段后重试。
            </p>
            <NativeVolumePanel
              ref="volumePanelRef"
              variant="workbench"
              :api="volumeApi"
              :api-key="activeMLField"
              :aux-points="gridSamplePoints"
              :slice-request="sliceRequest"
              :components="activeMLField === 'prediction' ? sceneComponents : null"
              :focused-component-id="focusedComponentId"
              @slice-change="onSliceChange"
              @slice-request-failed="onSliceRequestFailed"
              @annotation-selected="onAnnotationSelected"
              @slice-analysis="onSliceAnalysis"
              @asset-identity="onAssetIdentity"
              @source-load-state="onMLSourceLoadState"
            />
          </div>
          <SlicePanel
            v-else
            :result-id="resultId"
            :dimension="metadata.dimension"
            :shape="metadata.shape"
            :source-points="sourcePoints"
          />
        </template>
        <template #evaluation>
          <FormalSelectionPanel v-if="experiment" :result-id="resultId" :case-id="experiment.case_id" />
        </template>
        <template #provenance>
          <ExportPublicationPanel :result-id="resultId" />
        </template>
      </ResultAnalysisWorkbench>
    </template>

    <div v-else v-loading="true" class="page-loading" />
  </div>
</template>

<style scoped>
.v6-result-page {
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

.field-scene {
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-2);
}

.field-scene :deep(.native-volume-panel) {
  flex: 1;
  min-height: 0;
}

.active-field-note {
  margin: 0;
  padding: 5px 10px;
  border-left: 2px solid var(--s1-cyan-dim);
  color: var(--s1-text-dim);
  background: var(--s1-cyan-ghost);
  font-size: var(--s1-font-xs);
}

.field-load-error {
  margin: 0;
  padding: 7px 10px;
  border-left: 2px solid var(--s1-warning, #d9a84e);
  color: var(--s1-warning, #d9a84e);
  background: rgba(217, 168, 78, 0.08);
  font-size: var(--s1-font-xs);
}

/* 宽且高的演示屏使用一屏工作台；短屏桌面回到自然文档流，确保三维、
   控件和证据坞都能通过页面滚动到达，而不是要求浏览器缩放。 */
@media (min-width: 1200px) and (min-height: 820px) {
  .v6-result-page {
    height: 100%;
    overflow: hidden;
  }

  .v6-body {
    flex: 1;
    min-height: 0;
  }
}

.v6-error {
  padding: 48px 20px;
  max-width: 720px;
  margin: 0 auto;
}

.v6-error-links {
  display: flex;
  gap: 16px;
  justify-content: center;
  margin-top: 12px;
}

.v6-error-links a {
  color: var(--gmp-accent);
  text-decoration: none;
  font-size: 13px;
}

.export-error {
  margin: 0;
  padding: 4px 18px;
  font-size: 12px;
  color: var(--s1-warning, #d9a84e);
  border-bottom: 1px solid var(--s1-border, #22322c);
}

.page-loading {
  min-height: 240px;
}
</style>
