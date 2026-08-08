<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ApiError, fetchAnalysisSummary } from '../api/client'
import type { AnalysisProfileId, AnalysisSummaryResponse } from '../api/types'
import PageNavigation from '../components/navigation/PageNavigation.vue'

// v0.8.0 第二批 Task 4：分析中心占位视图——只拉取分析摘要并呈现案例身份 /
// 加载 / 类型化错误三态；完整 A+B 工作台壳与模块面板属 Task 5。

const route = useRoute()
const datasetId = computed(() => String(route.params.datasetId ?? ''))
const queryCaseId = computed(() => {
  const q = route.query.case
  return typeof q === 'string' ? q : ''
})

const loading = ref(true)
const loadError = ref<string | null>(null)
const summary = ref<AnalysisSummaryResponse | null>(null)

const PROFILE_LABELS: Record<AnalysisProfileId, string> = {
  microseismic_velocity: '微震速度',
  resistivity: '电阻率',
  gas_content: '瓦斯含量',
  generic_3d: '通用三维',
}

const profileLabel = computed(() =>
  summary.value ? PROFILE_LABELS[summary.value.analysis_profile] : '',
)

const caseLinkId = computed(() => summary.value?.case_id ?? queryCaseId.value)

function describeError(e: unknown): string {
  if (e instanceof ApiError) return `${e.code}：${e.message}`
  return e instanceof Error ? e.message : String(e)
}

let requestSeq = 0

async function loadSummary() {
  const targetId = datasetId.value
  const seq = ++requestSeq
  loading.value = true
  loadError.value = null
  summary.value = null
  try {
    const result = await fetchAnalysisSummary(targetId)
    if (seq !== requestSeq || targetId !== datasetId.value) return
    summary.value = result
  } catch (e) {
    if (seq !== requestSeq || targetId !== datasetId.value) return
    loadError.value = describeError(e)
  } finally {
    if (seq === requestSeq && targetId === datasetId.value) loading.value = false
  }
}

onMounted(loadSummary)

watch(datasetId, (next, prev) => {
  if (next !== prev) void loadSummary()
})
</script>

<template>
  <div class="analysis-center-page" data-test="analysis-center-view">
    <PageNavigation
      :case-id="caseLinkId || undefined"
      :dataset-id="datasetId"
      current-label="统计与空间分析"
    />
    <header class="page-header">
      <h1>统计与空间分析</h1>
      <p class="page-sub">数据集 <span class="mono">{{ datasetId }}</span></p>
    </header>

    <el-result
      v-if="loadError"
      icon="error"
      title="分析摘要加载失败"
      :sub-title="loadError"
      data-test="analysis-error"
      role="alert"
    />
    <div v-else-if="loading" v-loading="true" class="page-loading" data-test="analysis-loading" />

    <main v-else-if="summary" class="analysis-main" data-test="analysis-content">
      <section class="identity-card">
        <div class="identity-head">
          <el-tag type="primary" effect="dark" data-test="analysis-profile-badge">
            {{ profileLabel }}
          </el-tag>
          <span class="mono profile-id">{{ summary.analysis_profile }}</span>
        </div>
        <p class="identity-line" data-test="analysis-variable">
          变量：{{ summary.variable.name
          }}<template v-if="summary.variable.unit">（{{ summary.variable.unit }}）</template>
        </p>
        <p class="identity-line" data-test="analysis-identity">
          案例 {{ summary.case_id }} · 数据版本 v{{ summary.provenance.dataset_version }} ·
          计算版本 {{ summary.provenance.calculation_version }}
        </p>
        <p class="placeholder-hint">分析面板将在后续版本就位，当前为分析中心占位视图。</p>
      </section>
    </main>
  </div>
</template>

<style scoped>
.analysis-center-page {
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
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.mono {
  font-family: ui-monospace, monospace;
}

.page-loading {
  min-height: 200px;
}

.analysis-main {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.identity-card {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.identity-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.profile-id {
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.identity-line {
  margin: 0;
  font-size: 13px;
  color: var(--gmp-text-dim);
}

.placeholder-hint {
  margin: 0;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

@media (max-width: 480px) {
  .analysis-center-page {
    padding: 16px 12px 32px;
  }

  .page-header h1 {
    font-size: 16px;
  }
}
</style>
