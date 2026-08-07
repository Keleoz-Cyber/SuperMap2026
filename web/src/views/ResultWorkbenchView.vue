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
  DatasetPoints,
  ExperimentRecord,
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

const route = useRoute()
const router = useRouter()
const resultId = computed(() => String(route.params.resultId))

// v0.6：统一专业分析台入口；只跳转路由，不改变现有完整场/切片/选择/导出行为
function gotoProfessionalAnalysis() {
  void router.push({ name: 'professional-analysis', params: { resultId: resultId.value } })
}

const metadata = ref<ResultMetadata | null>(null)
const experiment = ref<ExperimentRecord | null>(null)
const preview = ref<ResultPreview | null>(null)
const points = ref<DatasetPoints | null>(null)
const loadError = ref<string | null>(null)
const activeTab = ref<'field' | 'slices'>('field')

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
    const fetches: Promise<void>[] = [
      fetchDatasetPoints(exp.params.dataset_version_id).then((p) => {
        points.value = p
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
    <PageNavigation home :experiment-id="metadata?.experiment_id" />
    <el-result v-if="loadError" icon="error" title="成果加载失败" :sub-title="loadError" />

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
          v-if="metadata.professional_analysis_supported"
          class="professional-entry"
          data-test="professional-entry"
          @click="gotoProfessionalAnalysis"
        >
          专业分析
        </button>
        <span v-else class="professional-disabled" data-test="professional-disabled">
          仅生成专业证据的成果支持专业分析
        </span>
      </header>

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
        />
        <SlicePanel
          v-else
          :result-id="resultId"
          :dimension="metadata.dimension"
          :shape="metadata.shape"
          :source-points="sourcePoints"
        />
      </section>

      <FormalSelectionPanel v-if="experiment" :result-id="resultId" :case-id="experiment.case_id" />
      <ExportPublicationPanel :result-id="resultId" />
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

.professional-disabled {
  margin-top: 10px;
  font-size: 12px;
  color: var(--gmp-text-faint);
  align-self: flex-start;
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
