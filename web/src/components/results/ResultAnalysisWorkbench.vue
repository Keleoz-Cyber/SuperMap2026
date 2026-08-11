<script setup lang="ts">
// v0.9.0 V6 Task 3/4：成果工作台一屏布局。
// 主舞台三栏（显示工具 328px / 成果场景 1fr / 分析研判 390px），
// 底部证据窗四个一级标签（综合分析/切片与异常/模型证据/数据溯源）。
// 组合器不 fetch：一切 DTO 由路由视图（ResultWorkbenchView）注入。
import { ref } from 'vue'
import type {
  AnalysisSummaryResponse,
  ResidualEvidence,
  ResultAnalysisSummary,
  SliceAnalysisResponse,
} from '../../api/types'
import type { PresentationFinding } from '../../domain/findings'
import type { AnalysisSelection } from '../analysis/analysisTypes'
import ResultInterpretationPanel from './ResultInterpretationPanel.vue'
import ResultGridEvidence from './ResultGridEvidence.vue'
import type { RenderAssetIdentity } from './ResultGridEvidence.vue'
import AIAssistedReview from './AIAssistedReview.vue'

const props = defineProps<{
  findings: PresentationFinding[]
  summary: AnalysisSummaryResponse | null
  residuals: ResidualEvidence | null
  datasetId: string | null
  resultId: string
  // 成果级分析（identity 绑定 result_id + grid_sha256；失败/未就绪为 null）
  analysis: ResultAnalysisSummary | null
  analysisLoading?: boolean
  analysisError?: string | null
  // 权威剖面响应（当前切片证据，与三维共用同一份）
  currentSlice: SliceAnalysisResponse | null
  focusedComponentId?: number | null
  // 渲染资产身份（数据溯源展示）
  assetIdentity?: RenderAssetIdentity | null
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

void props

// 三维→证据窗反向联动：视图经 v-model:dock-tab 切换当前证据标签
const dockTabModel = defineModel<'overview' | 'slices' | 'model' | 'provenance'>('dockTab', {
  default: 'overview',
})

// 右侧研判区：规则研判（默认）/ AI 辅助切换；AI 不可用不拖垮规则研判
const sideTab = ref<'rules' | 'ai'>('rules')
const evidenceExpanded = ref(false)

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
    result_grid: 'overview',
    composition: 'overview',
    depth_profile: 'overview',
    current_slice: 'slices',
    model_evidence: 'model',
    uncertainty: 'model',
    input_quality: 'provenance',
  }
  const tab = tabByRef[ref]
  if (tab) dockTabModel.value = tab
}
</script>

<template>
  <div class="result-workbench" data-test="result-analysis-workbench">
    <p v-if="selectionNotice" class="selection-notice" data-test="selection-notice" role="status">
      {{ selectionNotice }}
    </p>
    <div class="workbench-grid" data-test="v6-main-stage">
      <div class="workbench-scene" data-test="result-scene">
        <slot name="scene" />
      </div>

      <aside class="workbench-side" data-test="result-analysis-side">
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

        <div class="side-scroll">
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
            <slot name="evaluation" />
          </section>
        </div>
      </aside>
    </div>

    <div
      class="workbench-dock"
      :class="{ expanded: evidenceExpanded }"
      data-test="result-evidence-dock"
    >
      <button
        type="button"
        class="dock-size-toggle"
        data-test="evidence-dock-toggle"
        :aria-expanded="evidenceExpanded"
        @click="evidenceExpanded = !evidenceExpanded"
      >
        {{ evidenceExpanded ? '收起分析' : '展开分析' }}
      </button>
      <ResultGridEvidence
        v-model:active-tab="dockTabModel"
        :analysis="analysis"
        :current-slice="currentSlice"
        :dataset-summary="summary"
        :dataset-findings="findings"
        :residuals="residuals"
        :result-id="resultId"
        :dataset-id="datasetId"
        :asset-identity="assetIdentity ?? null"
        @focus-component="emit('focus-component', $event)"
        @focus-depth-bin="emit('focus-depth-bin', $event)"
        @locate="emit('locate', $event)"
        @select="emit('select', $event)"
        @select-result="emit('select-result', $event)"
      >
        <template #provenance-actions>
          <slot name="provenance" />
        </template>
      </ResultGridEvidence>
    </div>
  </div>
</template>

<style scoped>
.result-workbench {
  /* 成果页是演示主工作台，局部提高最小字号，不影响上传/实验等高密度表单。 */
  --s1-font-xs: 12px;
  --s1-font-sm: 13px;
  --s1-font-md: 14px;
  --s1-font-lg: 16px;
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-2);
  min-height: 0;
  height: 100%;
}

.selection-notice {
  margin: 0;
  font-size: var(--s1-font-sm);
  color: var(--s1-warning);
  border: 1px solid rgba(217, 168, 78, 0.4);
  border-radius: var(--s1-radius-sm);
  background: rgba(217, 168, 78, 0.08);
  padding: 6px 12px;
  flex: none;
}

.workbench-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 390px;
  gap: var(--s1-space-3);
  align-items: stretch;
  flex: 1;
  min-height: 0;
  padding: 0 var(--s1-space-3);
}

.workbench-scene {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.workbench-side {
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-2);
  min-width: 0;
  min-height: 0;
  border-left: 1px solid var(--s1-border-soft);
  padding-left: var(--s1-space-3);
}

.side-tabs {
  display: flex;
  gap: 4px;
  flex: none;
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

/* 右栏内容独立滚动（页面本身不滚动） */
.side-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-3);
  padding-right: 2px;
}

.side-block {
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-1);
  padding: var(--s1-space-3);
}

.workbench-dock {
  flex: none;
  height: clamp(280px, 29vh, 330px);
  min-height: 0;
  position: relative;
  transition: height var(--s1-motion-normal) var(--s1-ease-out);
}

.workbench-dock.expanded {
  height: 52vh;
}

.dock-size-toggle {
  position: absolute;
  top: 6px;
  right: 92px;
  z-index: 3;
  border: 1px solid var(--s1-cyan-dim);
  border-radius: 6px;
  background: var(--s1-cyan-ghost);
  color: var(--s1-cyan-strong);
  padding: 4px 12px;
  font-size: var(--s1-font-sm);
  cursor: pointer;
}

.workbench-dock :deep(.grid-evidence) {
  height: 100%;
}

@media (max-width: 1199px) {
  .workbench-grid {
    grid-template-columns: 1fr;
  }

  .workbench-side {
    border-left: none;
    padding-left: 0;
  }

  .workbench-dock {
    height: auto;
  }

  .dock-size-toggle {
    display: none;
  }
}
</style>
