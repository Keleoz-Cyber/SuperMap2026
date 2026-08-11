<script setup lang="ts">
// v0.9.0：成果与分析融合工作台（成果级分析版）。中央三维主视图 + 右侧
// 成果级规则研判（Task 6 起替代数据集级关键发现）+ 底部成果网格证据带 +
// 模型评估摘要 + 溯源/证据抽屉。
// 组合器不 fetch：一切 DTO 由路由视图（ResultWorkbenchView）注入。
import { computed, ref } from 'vue'
import type {
  AnalysisSummaryResponse,
  ResidualEvidence,
  ResultAnalysisSummary,
  ResultEvaluationSummary,
  SliceAnalysisResponse,
} from '../../api/types'
import type { PresentationFinding } from '../../domain/findings'
import type { AnalysisSelection } from '../analysis/analysisTypes'
import { formatNumber } from '../analysis/analysisTypes'
import ResultInterpretationPanel from './ResultInterpretationPanel.vue'
import ResultGridEvidence from './ResultGridEvidence.vue'
import AIAssistedReview from './AIAssistedReview.vue'

const props = defineProps<{
  findings: PresentationFinding[]
  summary: AnalysisSummaryResponse | null
  residuals: ResidualEvidence | null
  datasetId: string | null
  resultId: string
  evaluation: ResultEvaluationSummary | null
  // 成果级分析（identity 绑定 result_id + grid_sha256；失败/未就绪为 null）
  analysis: ResultAnalysisSummary | null
  analysisLoading?: boolean
  analysisError?: string | null
  // 权威剖面响应（当前切片证据，与三维共用同一份）
  currentSlice: SliceAnalysisResponse | null
  focusedComponentId?: number | null
  // 图表—三维联动的类型化能力通知（如 XY 区域过滤不受支持）
  selectionNotice?: string | null
}>()

const emit = defineEmits<{
  (e: 'locate', finding: PresentationFinding): void
  (e: 'select', selection: AnalysisSelection): void
  (e: 'select-result', resultId: string): void
  (e: 'focus-component', componentId: number): void
  (e: 'focus-depth-bin', index: number): void
}>()

// 三维→证据带反向联动：视图经 v-model:dock-tab 切换当前证据标签
const dockTabModel = defineModel<
  'composition' | 'depth' | 'components' | 'slice' | 'model' | 'input' | 'provenance'
>('dockTab', { default: 'composition' })

// 右侧研判区：规则研判（默认）/ AI 辅助切换；AI 不可用不拖垮规则研判
const sideTab = ref<'rules' | 'ai'>('rules')

// AI evidence ref 联动：组件/层段向上聚焦；全局证据切到对应证据标签
function onFocusEvidence(ref: string) {
  const component = /^component-(\d+)$/.exec(ref)
  if (component) {
    emit('focus-component', Number(component[1]))
    return
  }
  const depthBin = /^depth_bin-(\d+)$/.exec(ref)
  if (depthBin) {
    emit('focus-depth-bin', Number(depthBin[1]))
    return
  }
  const tabByRef: Record<string, typeof dockTabModel.value> = {
    result_grid: 'composition',
    composition: 'composition',
    depth_profile: 'depth',
    current_slice: 'slice',
    model_evidence: 'model',
    uncertainty: 'model',
    input_quality: 'input',
  }
  const tab = tabByRef[ref]
  if (tab) dockTabModel.value = tab
}

const provenanceOpen = ref(false)

const metrics = computed(() => {
  const ev = props.evaluation
  if (!ev) return []
  return [
    { label: 'RMSE', value: ev.rmse },
    { label: 'MAE', value: ev.mae },
    { label: 'R²', value: ev.r2 },
    { label: 'Bias', value: ev.bias },
  ].filter((m) => m.value !== null && Number.isFinite(m.value))
})
</script>

<template>
  <div class="result-workbench" data-test="result-analysis-workbench">
    <p v-if="selectionNotice" class="selection-notice" data-test="selection-notice" role="status">
      {{ selectionNotice }}
    </p>
    <div class="workbench-grid">
      <div class="workbench-scene" data-test="result-scene">
        <slot name="scene" />
      </div>

      <aside class="workbench-side">
        <div class="side-tabs" role="tablist" data-test="side-tabs">
          <button
            type="button"
            role="tab"
            class="side-tab"
            :class="{ active: sideTab === 'rules' }"
            :aria-selected="sideTab === 'rules' ? 'true' : 'false'"
            data-test="side-tab-rules"
            @click="sideTab = 'rules'"
          >
            规则研判
          </button>
          <button
            type="button"
            role="tab"
            class="side-tab"
            :class="{ active: sideTab === 'ai' }"
            :aria-selected="sideTab === 'ai' ? 'true' : 'false'"
            data-test="side-tab-ai"
            @click="sideTab = 'ai'"
          >
            AI 辅助
          </button>
        </div>

        <ResultInterpretationPanel
          v-if="sideTab === 'rules'"
          :analysis="analysis"
          :current-slice="currentSlice"
          :focused-component-id="focusedComponentId ?? null"
          :loading="analysisLoading ?? false"
          :error="analysisError ?? null"
          @focus-component="emit('focus-component', $event)"
          @focus-depth-bin="emit('focus-depth-bin', $event)"
        />
        <AIAssistedReview
          v-else
          :result-id="resultId"
          :grid-sha256="analysis?.identity.grid_sha256 ?? null"
          @focus-evidence="onFocusEvidence"
        />

        <section class="side-block" data-test="result-evaluation">
          <h3 class="side-title">模型评估</h3>
          <div v-if="metrics.length > 0" class="metric-grid">
            <div v-for="m in metrics" :key="m.label" class="metric-cell">
              <span class="metric-label">{{ m.label }}</span>
              <span class="metric-value mono">{{ formatNumber(m.value) }}</span>
            </div>
          </div>
          <p v-else class="side-note">暂无评估指标。</p>
          <p v-if="evaluation?.common_valid_count" class="side-note">
            公共有效集 {{ evaluation.common_valid_count.toLocaleString() }} 点
          </p>
          <slot name="evaluation" />
        </section>
      </aside>
    </div>

    <div class="workbench-dock" data-test="result-evidence-dock">
      <ResultGridEvidence
        v-model:active-tab="dockTabModel"
        :analysis="analysis"
        :current-slice="currentSlice"
        :dataset-summary="summary"
        :dataset-findings="findings"
        :residuals="residuals"
        :result-id="resultId"
        :dataset-id="datasetId"
        @focus-component="emit('focus-component', $event)"
        @focus-depth-bin="emit('focus-depth-bin', $event)"
        @locate="emit('locate', $event)"
        @select="emit('select', $event)"
        @select-result="emit('select-result', $event)"
      />
    </div>

    <section class="provenance-drawer" data-test="provenance-drawer">
      <button
        type="button"
        class="provenance-toggle"
        data-test="provenance-toggle"
        :aria-expanded="provenanceOpen ? 'true' : 'false'"
        @click="provenanceOpen = !provenanceOpen"
      >
        证据与溯源 {{ provenanceOpen ? '▾' : '▸' }}
      </button>
      <div v-show="provenanceOpen" class="provenance-body">
        <slot name="provenance" />
      </div>
    </section>
  </div>
</template>

<style scoped>
.result-workbench {
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-4);
}

.selection-notice {
  margin: 0;
  font-size: var(--s1-font-sm);
  color: var(--s1-warning);
  border: 1px solid rgba(217, 168, 78, 0.4);
  border-radius: var(--s1-radius-sm);
  background: rgba(217, 168, 78, 0.08);
  padding: 6px 12px;
}

.workbench-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: var(--s1-space-4);
  align-items: start;
}

.workbench-scene {
  min-width: 0;
}

.workbench-side {
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-3);
  min-width: 0;
}

.side-tabs {
  display: flex;
  gap: 4px;
}

.side-tab {
  flex: 1;
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
  background: transparent;
  border: 1px solid var(--s1-border);
  border-radius: 6px;
  padding: 5px 0;
  cursor: pointer;
}

.side-tab.active {
  color: var(--s1-cyan-strong);
  background: var(--s1-cyan-ghost);
  border-color: var(--s1-cyan-dim);
  font-weight: 600;
}

.side-block {
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-1);
  padding: var(--s1-space-3);
}

.side-title {
  margin: 0 0 var(--s1-space-2);
  font-size: var(--s1-font-xs);
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--s1-text-dim);
}

.metric-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s1-space-2);
}

.metric-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  border: 1px solid var(--s1-border-soft);
  border-radius: var(--s1-radius-sm);
  padding: 6px 10px;
}

.metric-label {
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
}

.metric-value {
  font-size: var(--s1-font-lg);
  color: var(--s1-gold);
  font-weight: 600;
}

.side-note {
  margin: var(--s1-space-2) 0 0;
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
}

.provenance-drawer {
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-1);
}

.provenance-toggle {
  width: 100%;
  text-align: left;
  background: transparent;
  border: none;
  color: var(--s1-text-dim);
  font-size: var(--s1-font-md);
  font-weight: 600;
  padding: var(--s1-space-3) var(--s1-space-4);
  cursor: pointer;
}

.provenance-toggle:hover {
  color: var(--s1-cyan-strong);
}

.provenance-body {
  padding: 0 var(--s1-space-4) var(--s1-space-4);
}

@media (max-width: 1000px) {
  .workbench-grid {
    grid-template-columns: 1fr;
  }
}

.mono {
  font-family: ui-monospace, monospace;
}

@media (min-width: 1200px) and (min-height: 800px) {
  .result-workbench {
    position: relative;
    min-height: 0;
    display: grid;
    grid-template-rows: minmax(0, 1fr) auto auto;
    gap: 8px;
  }

  .selection-notice {
    position: absolute;
    z-index: 2;
    left: 50%;
    transform: translateX(-50%);
    max-width: min(720px, 60vw);
  }

  .workbench-grid {
    min-height: 0;
    align-items: stretch;
  }

  .workbench-scene,
  .workbench-side {
    min-height: 0;
    overflow-y: auto;
    scrollbar-gutter: stable;
  }

  .workbench-dock {
    max-height: 220px;
    overflow-y: auto;
  }
}
</style>
