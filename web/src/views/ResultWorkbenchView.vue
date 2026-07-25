<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  ApiError,
  fetchDatasetPoints,
  fetchExperiment,
  fetchMicroseismicDerivation,
  fetchMicroseismicDerivationPoints,
  fetchResult,
  fetchResultPreview,
  MICROSEISMIC_SOURCE_KIND,
} from '../api/client'
import type {
  DatasetPoints,
  ExperimentRecord,
  MicroseismicDerivation,
  MicroseismicPointLayer,
  MicroseismicPointLayerName,
  ResultMetadata,
  ResultPreview,
} from '../api/types'
import Field3D from '../components/results/Field3D.vue'
import SlicePanel from '../components/results/SlicePanel.vue'
import FormalSelectionPanel from '../components/results/FormalSelectionPanel.vue'
import ExportPublicationPanel from '../components/results/ExportPublicationPanel.vue'
import PageNavigation from '../components/navigation/PageNavigation.vue'

const route = useRoute()
const resultId = computed(() => String(route.params.resultId))

const metadata = ref<ResultMetadata | null>(null)
const experiment = ref<ExperimentRecord | null>(null)
const preview = ref<ResultPreview | null>(null)
const points = ref<DatasetPoints | null>(null)
const loadError = ref<string | null>(null)
const activeTab = ref<'field' | 'slices'>('field')

// 微震证据图层：仅当成果所属数据集 source_kind 为 microseismic_dat_bundle 时出现。
// 图层开关只影响渲染集合，绝不触碰网格阈值、值域、指标与正式选择。
const derivation = ref<MicroseismicDerivation | null>(null)
const layerStates = reactive<
  Record<MicroseismicPointLayerName, { visible: boolean; points: MicroseismicPointLayer | null }>
>({
  aggregated: { visible: true, points: null },
  accepted: { visible: false, points: null },
  rejected: { visible: false, points: null },
})

const EVIDENCE_LAYER_ORDER: MicroseismicPointLayerName[] = ['aggregated', 'accepted', 'rejected']

function formatCount(n: number): string {
  return n.toLocaleString('en-US')
}

const layerControls = computed(() => {
  const counts = derivation.value?.layer_counts
  if (!counts) return []
  const labels: Record<MicroseismicPointLayerName, string> = {
    aggregated: `${formatCount(counts.aggregated_nodes)} 个唯一建模节点`,
    accepted: `${formatCount(counts.accepted_modeling)} 条3σ候选来源`,
    rejected: `${formatCount(counts.rejected_3sigma)} 条3σ剔除诊断`,
  }
  return EVIDENCE_LAYER_ORDER.map((name) => ({
    name,
    label: labels[name],
    visible: layerStates[name].visible,
  }))
})

const evidenceLayers = computed(() =>
  EVIDENCE_LAYER_ORDER.map((name) => ({
    name,
    visible: layerStates[name].visible,
    points: layerStates[name].points,
  })),
)

async function loadLayerPoints(name: MicroseismicPointLayerName): Promise<void> {
  const state = layerStates[name]
  if (state.points || !derivation.value) return
  try {
    state.points = await fetchMicroseismicDerivationPoints(derivation.value.dataset_id, name)
  } catch {
    // 单层加载失败仅影响该层：回退为关，主点云与其他层不受影响
    state.visible = false
  }
}

async function toggleEvidenceLayer(name: MicroseismicPointLayerName): Promise<void> {
  layerStates[name].visible = !layerStates[name].visible
  if (layerStates[name].visible) await loadLayerPoints(name)
}

// 成果元数据给出 dataset_version_id 后，用派生元数据探测领域身份；
// 409（非微震）或任何失败都静默降级，绝不阻塞成果工作台本身。
async function loadEvidence(datasetId: string): Promise<void> {
  let report: MicroseismicDerivation
  try {
    report = await fetchMicroseismicDerivation(datasetId)
  } catch {
    return
  }
  if (report?.source_kind !== MICROSEISMIC_SOURCE_KIND) return
  derivation.value = report
  // 默认只加载聚合节点层；候选与剔除层保持关，等用户显式打开
  await loadLayerPoints('aggregated')
}

const sourcePoints = computed(() => {
  if (!points.value) return null
  return { x: points.value.x, y: points.value.y, values: points.value.values }
})

onMounted(async () => {
  try {
    const meta = await fetchResult(resultId.value)
    metadata.value = meta
    const exp = await fetchExperiment(meta.experiment_id)
    experiment.value = exp
    const fetches: Promise<void>[] = [
      fetchDatasetPoints(exp.params.dataset_version_id).then((p) => {
        points.value = p
      }),
      loadEvidence(meta.dataset_version_id),
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

        <div
          v-if="derivation && metadata.dimension === '3d' && activeTab === 'field'"
          class="evidence-layers"
          data-test="evidence-layers"
        >
          <span class="evidence-title">微震证据图层</span>
          <button
            v-for="control in layerControls"
            :key="control.name"
            class="layer-toggle"
            :class="{ on: control.visible }"
            :data-test="`layer-toggle-${control.name}`"
            @click="toggleEvidenceLayer(control.name)"
          >
            {{ control.visible ? '[on]' : '[off]' }} {{ control.label }}
          </button>
        </div>

        <Field3D
          v-if="metadata.dimension === '3d' && activeTab === 'field'"
          :preview="preview"
          :evidence-layers="evidenceLayers"
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

.evidence-layers {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
}

.evidence-title {
  color: var(--gmp-text-dim);
  margin-right: 4px;
}

.layer-toggle {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text-dim);
  border-radius: 8px;
  padding: 5px 12px;
  font-size: 12px;
  font-family: ui-monospace, monospace;
  cursor: pointer;
}

.layer-toggle.on {
  border-color: var(--gmp-accent);
  color: var(--gmp-text);
  font-weight: 600;
}

.page-loading {
  min-height: 240px;
}
</style>
