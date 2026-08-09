<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ApiError,
  createRenderAssetSliceExport,
  createResultRenderAsset,
  fetchDatasetPoints,
  fetchExperiment,
  fetchRenderAssetSliceAnalysis,
  fetchResultPreview,
  fetchResultRenderAsset,
  fetchResultRenderCapability,
  materializeResult,
} from '../api/client'
import type {
  AnalysisSummaryResponse,
  DatasetPoints,
  ExperimentRecord,
  ResidualEvidence,
  ResultMetadata,
  ResultPreview,
} from '../api/types'
import NativeVolumePanel from '../components/rendering/NativeVolumePanel.vue'
import type {
  NativeVolumeAuxPoints,
  NativeVolumeRenderApi,
} from '../components/rendering/NativeVolumePanel.vue'
import SlicePanel from '../components/results/SlicePanel.vue'
import FormalSelectionPanel from '../components/results/FormalSelectionPanel.vue'
import ExportPublicationPanel from '../components/results/ExportPublicationPanel.vue'
import PageNavigation from '../components/navigation/PageNavigation.vue'
import AsyncState from '../components/states/AsyncState.vue'
import ResultAnalysisWorkbench from '../components/results/ResultAnalysisWorkbench.vue'
import { buildPresentationFindings, type PresentationFinding } from '../domain/findings'
import { fetchAnalysisSummary, fetchResultResiduals } from '../api/client'
import type { AnalysisSelection } from '../components/analysis/analysisTypes'
import { createAnalysisSelectionController } from '../composables/useAnalysisSelection'
import type { SliceAxis } from '../api/types'

const route = useRoute()
const router = useRouter()
const resultId = computed(() => String(route.params.resultId))

// v0.7.0：每个已物化成果都有模型评估入口
function gotoModelEvaluation() {
  void router.push({ name: 'model-evaluation', params: { resultId: resultId.value } })
}

const metadata = ref<ResultMetadata | null>(null)
const experiment = ref<ExperimentRecord | null>(null)
const preview = ref<ResultPreview | null>(null)
const points = ref<DatasetPoints | null>(null)
const loadError = ref<string | null>(null)
const activeTab = ref<'field' | 'slices'>('field')

// v0.9.0：分析摘要与残差证据（只读 GET；不可用不阻断成果页主链）
const analysis = ref<AnalysisSummaryResponse | null>(null)
const residuals = ref<ResidualEvidence | null>(null)

const findings = computed<PresentationFinding[]>(() =>
  analysis.value ? buildPresentationFindings(analysis.value) : [],
)

// ---------------------------------------------------------------------------
// v0.9.0 Task 12：图表—三维双向联动
// 选择控制器持有身份上下文；图表区间/发现定位 → 正交切片请求；
// 渲染器不支持的请求显示类型化能力通知，绝不伪报定位成功。
// ---------------------------------------------------------------------------
const selection = createAnalysisSelectionController()
const sliceRequest = ref<{ axis: SliceAxis; range: [number, number]; token: number } | null>(null)
const capabilityNotice = ref<string | null>(null)
const dockTab = ref<'quality' | 'distribution' | 'model' | 'trends' | 'residuals'>('quality')
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
  // 三维切片移动 → 证据带切到趋势剖面标签（反向联动）
  dockTab.value = 'trends'
}

function onSliceRequestFailed(payload: { reason: string }) {
  capabilityNotice.value = payload.reason
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

// 面板数据层以回调注入：能力与资产状态一律纯 GET，创建是唯一 POST；
// 剖面分析/导出经 RenderAsset 统一 API（v0.7.0 第二批，三来源共用）
const volumeApi: NativeVolumeRenderApi = {
  fetchCapability: () => fetchResultRenderCapability(resultId.value),
  fetchAsset: () => fetchResultRenderAsset(resultId.value),
  createAsset: (retryFailed) => createResultRenderAsset(resultId.value, retryFailed),
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

onMounted(async () => {
  try {
    // v0.6.1：物化是唯一显式变异入口（POST 一次）；绝不把 fetchResult 当创建捷径。
    // 切片/预览/证据只在物化成功后获取。
    const meta = await materializeResult(resultId.value)
    metadata.value = meta
    const exp = await fetchExperiment(meta.experiment_id)
    experiment.value = exp
    // 选择上下文与该成果身份绑定；随后还原深链选择（若有）
    selection.setContext({ datasetId: exp.params.dataset_version_id, resultId: resultId.value })
    restoreSelectionFromQuery()
    const fetches: Promise<void>[] = [
      fetchDatasetPoints(exp.params.dataset_version_id).then((p) => {
        points.value = p
      }),
      // 分析摘要只读：未验证/不可用时不产生结论，工作台显示真实空态
      fetchAnalysisSummary(exp.params.dataset_version_id)
        .then((s) => {
          analysis.value = s
        })
        .catch(() => {
          analysis.value = null
        }),
      fetchResultResiduals(resultId.value, 4)
        .then((r) => {
          residuals.value = r
        })
        .catch(() => {
          residuals.value = null
        }),
    ]
    if (meta.dimension === '3d') {
      activeTab.value = 'field'
      fetches.push(
        fetchResultPreview(resultId.value).then((p) => {
          preview.value = p
        }),
      )
    } else {
      activeTab.value = 'slices'
    }
    await Promise.all(fetches)
  } catch (e) {
    loadError.value = e instanceof ApiError ? `${e.code}：${e.message}` : String(e)
  }
})
</script>

<template>
  <div class="workbench-page">
    <PageNavigation
      :case-id="experiment?.case_id"
      :experiment-id="metadata?.experiment_id"
      :result-id="resultId"
      current-label="成果工作台"
    />
    <AsyncState
      v-if="loadError"
      kind="error"
      title="成果加载失败"
      :impact="loadError"
      next-action="返回案例工作台或实验页重新进入"
    />

    <template v-else-if="metadata">
      <header class="page-header">
        <h1>成果工作台</h1>
        <p class="page-sub">
          算法 <b>{{ metadata.algorithm }}</b> ·
          <span class="mono">{{ metadata.fingerprint.slice(0, 12) }}</span> ·
          {{ metadata.dimension === '3d' ? '三维' : '二维' }} ·
          网格 {{ metadata.shape.join('×') }} ·
          值域 {{ metadata.value_range[0] }} ~ {{ metadata.value_range[1] }}
        </p>
        <button
          class="professional-entry"
          data-test="model-evaluation-entry"
          @click="gotoModelEvaluation"
        >
          模型评估
        </button>
      </header>

      <ResultAnalysisWorkbench
        v-model:dock-tab="dockTab"
        :findings="findings"
        :summary="analysis"
        :residuals="residuals"
        :dataset-id="experiment?.params.dataset_version_id ?? null"
        :result-id="resultId"
        :evaluation="metadata.evaluation_summary ?? null"
        :selection-notice="capabilityNotice"
        @locate="onFindingLocate"
        @select="onEvidenceSelect"
        @select-result="onSelectResult"
      >
        <template #scene>
          <section class="panel">
            <div v-if="metadata.dimension === '3d'" class="view-tabs">
              <button
                class="view-tab"
                :class="{ active: activeTab === 'field' }"
                data-test="tab-field"
                @click="activeTab = 'field'"
              >
                完整场
              </button>
              <button
                class="view-tab"
                :class="{ active: activeTab === 'slices' }"
                data-test="tab-slices"
                @click="activeTab = 'slices'"
              >
                X / Y / Z 切片
              </button>
            </div>

            <NativeVolumePanel
              v-if="metadata.dimension === '3d' && activeTab === 'field'"
              :api="volumeApi"
              :aux-points="gridSamplePoints"
              :slice-request="sliceRequest"
              @slice-change="onSliceChange"
              @slice-request-failed="onSliceRequestFailed"
            />
            <SlicePanel
              v-else
              :result-id="resultId"
              :dimension="metadata.dimension"
              :shape="metadata.shape"
              :source-points="sourcePoints"
            />
          </section>
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
.workbench-page {
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

.professional-entry {
  margin-top: 10px;
  border: 1px solid var(--gmp-accent);
  background: transparent;
  color: var(--gmp-accent);
  border-radius: 8px;
  padding: 6px 16px;
  font-size: 12px;
  cursor: pointer;
  align-self: flex-start;
}

.professional-entry:hover {
  background: rgba(79, 209, 197, 0.1);
}

.panel {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.view-tabs {
  display: flex;
  gap: 8px;
}

.view-tab {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text-dim);
  border-radius: 8px;
  padding: 6px 14px;
  font-size: 12px;
  cursor: pointer;
}

.view-tab.active {
  background: var(--gmp-accent);
  border-color: var(--gmp-accent);
  color: #0b0f14;
  font-weight: 600;
}

.page-loading {
  min-height: 240px;
}
</style>
