<script setup lang="ts">
// v0.9.0：混合证据坞。一个主图 + 紧凑标签页（质量/分布/模型指标/趋势/
// 残差）；只接收数据不 fetch；环图仅用于可加总口径；畸形载荷一律
// AsyncState nodata，绝不渲染空画布。所有选择事件携带数据/成果身份。
import { computed, ref } from 'vue'
import type { AnalysisSummaryResponse, ResidualEvidence } from '../../api/types'
import type { AnalysisSelection } from '../analysis/analysisTypes'
import { comparisonCandidatesOf, distributionBinsOf, profileAxesOf } from '../analysis/analysisTypes'
import AsyncState from '../states/AsyncState.vue'
import DistributionPanel from '../analysis/DistributionPanel.vue'
import QualityDonut from './QualityDonut.vue'
import ModelMetricBars from './ModelMetricBars.vue'
import AxisTrendChart from './AxisTrendChart.vue'
import ResidualEvidenceChart from './ResidualEvidence.vue'

const props = defineProps<{
  summary: AnalysisSummaryResponse | null
  residuals?: ResidualEvidence | null
  datasetId: string
  resultId?: string | null
}>()

const emit = defineEmits<{
  (e: 'select', selection: AnalysisSelection): void
  (e: 'select-result', resultId: string): void
}>()

type DockTab = 'quality' | 'distribution' | 'model' | 'trends' | 'residuals'

// v-model:active-tab：三维侧联动（如切片移动）可驱动证据带切到对应标签
const activeTab = defineModel<DockTab>('activeTab', { default: 'quality' })
const expanded = ref(true)

function moduleOf(id: string) {
  return props.summary?.modules.find((m) => m.module_id === id) ?? null
}

const distributionModule = computed(() => moduleOf('distribution'))
const distributionUsable = computed(() => {
  const m = distributionModule.value
  return m !== null && m.status === 'ok' && distributionBinsOf(m).length > 0
})

const modelCandidates = computed(() => comparisonCandidatesOf(moduleOf('model_comparison')))

const trendAxes = computed(() => {
  const m = moduleOf('profile_slices')
  if (!m || m.status !== 'ok') return []
  return profileAxesOf(m).filter((a) => a.bins.length > 0)
})

const hasResiduals = computed(() => (props.residuals?.returned ?? 0) > 0)

const quality = computed(() => props.summary?.quality ?? null)

const tabs = computed<Array<{ id: DockTab; label: string; available: boolean }>>(() => [
  { id: 'quality', label: '质量', available: quality.value !== null },
  { id: 'distribution', label: props.summary?.analysis_profile === 'gas_content' ? '含量分布' : '分布', available: distributionModule.value !== null },
  { id: 'model', label: '模型指标', available: modelCandidates.value.length > 0 },
  { id: 'trends', label: '趋势剖面', available: trendAxes.value.length > 0 },
  { id: 'residuals', label: '残差', available: hasResiduals.value },
])

function selectTab(tab: DockTab) {
  activeTab.value = tab
  expanded.value = true
}
</script>

<template>
  <section class="evidence-dock" data-test="evidence-dock" aria-label="证据带">
    <header class="dock-head">
      <div class="dock-tabs" role="tablist">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          type="button"
          role="tab"
          class="dock-tab"
          :class="{ active: activeTab === tab.id, unavailable: !tab.available }"
          :aria-selected="activeTab === tab.id ? 'true' : 'false'"
          :data-test="`dock-tab-${tab.id}`"
          @click="selectTab(tab.id)"
        >
          {{ tab.label }}
        </button>
      </div>
      <span class="dock-note">部分模块为探索性统计口径</span>
      <button
        type="button"
        class="dock-toggle"
        data-test="dock-toggle"
        :aria-expanded="expanded ? 'true' : 'false'"
        @click="expanded = !expanded"
      >
        {{ expanded ? '收起' : '展开' }}
      </button>
    </header>

    <div v-show="expanded" class="dock-body">
      <div v-if="activeTab === 'quality'" class="dock-pane" data-test="dock-pane-quality">
        <QualityDonut
          v-if="quality"
          :valid="quality.valid_count"
          :invalid="quality.invalid_count"
          :total="quality.row_count"
        />
        <AsyncState v-else kind="nodata" title="暂无质量数据" />
      </div>

      <div v-if="activeTab === 'distribution'" class="dock-pane" data-test="dock-pane-distribution">
        <AsyncState
          v-if="!distributionModule"
          kind="nodata"
          title="分布模块不可用"
        />
        <AsyncState
          v-else-if="!distributionUsable"
          kind="nodata"
          title="分布数据不可用"
          impact="分布载荷缺失或形态不符"
          next-action="检查数据版本后重试"
        />
        <div v-else data-test="dock-distribution-chart" class="dock-chart">
          <DistributionPanel
            :module="distributionModule"
            :variable="summary!.variable"
            :profile="summary!.analysis_profile"
          />
        </div>
      </div>

      <div v-if="activeTab === 'model'" class="dock-pane" data-test="dock-pane-model">
        <AsyncState v-if="modelCandidates.length === 0" kind="nodata" title="暂无候选指标" />
        <ModelMetricBars
          v-else
          :candidates="modelCandidates"
          :unit="summary?.variable.unit ?? null"
          @select="emit('select-result', $event)"
        />
      </div>

      <div v-if="activeTab === 'trends'" class="dock-pane" data-test="dock-pane-trends">
        <AsyncState v-if="trendAxes.length === 0" kind="nodata" title="暂无趋势剖面数据" />
        <AxisTrendChart
          v-else
          :axes="trendAxes"
          :unit="summary?.variable.unit ?? null"
          :dataset-id="datasetId"
          :result-id="resultId ?? null"
          @select="emit('select', $event)"
        />
      </div>

      <div v-if="activeTab === 'residuals'" class="dock-pane" data-test="dock-pane-residuals">
        <AsyncState v-if="!hasResiduals" kind="nodata" title="暂无残差证据" />
        <ResidualEvidenceChart
          v-else
          :evidence="residuals ?? null"
          :unit="summary?.variable.unit ?? null"
        />
      </div>
    </div>
  </section>
</template>

<style scoped>
.evidence-dock {
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-1);
  min-width: 0;
}

.dock-head {
  display: flex;
  align-items: center;
  gap: var(--s1-space-3);
  padding: var(--s1-space-2) var(--s1-space-3);
  border-bottom: 1px solid var(--s1-border-soft);
}

.dock-tabs {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  flex: 1;
}

.dock-tab {
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  padding: 4px 12px;
  cursor: pointer;
  transition:
    color var(--s1-motion-fast) var(--s1-ease-out),
    background var(--s1-motion-fast) var(--s1-ease-out);
}

.dock-tab:hover {
  color: var(--s1-cyan-strong);
}

.dock-tab.active {
  color: var(--s1-cyan-strong);
  background: var(--s1-cyan-ghost);
  border-color: var(--s1-cyan-dim);
}

.dock-tab.unavailable {
  opacity: 0.5;
}

.dock-note {
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
  white-space: nowrap;
}

.dock-toggle {
  font-size: var(--s1-font-xs);
  color: var(--s1-cyan-strong);
  background: transparent;
  border: 1px solid var(--s1-cyan-dim);
  border-radius: 6px;
  padding: 3px 10px;
  cursor: pointer;
}

.dock-body {
  padding: var(--s1-space-3);
}

.dock-pane {
  min-height: 120px;
}

.dock-chart :deep(.distribution-panel) {
  background: transparent;
  border: none;
  padding: 0;
}
</style>
