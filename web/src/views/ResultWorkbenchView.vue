<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  ApiError,
  fetchDatasetPoints,
  fetchExperiment,
  fetchResult,
  fetchResultPreview,
} from '../api/client'
import type { DatasetPoints, ExperimentRecord, ResultMetadata, ResultPreview } from '../api/types'
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

        <Field3D v-if="metadata.dimension === '3d' && activeTab === 'field'" :preview="preview" />
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

.page-loading {
  min-height: 240px;
}
</style>
