<script setup lang="ts">
// v0.9.0 V6 Task 3：成果摘要条（72px）。
// 左侧：成果名称、算法、网格、坐标语义与变量单位；
// 右侧：有效样本、模型拟合 R²、公共有效集与正式成果状态。
// 只展示判断所需信息；fingerprint、完整哈希、资产 ID 一律进入「数据溯源」。
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { ResultMetadata } from '../../api/types'
import { algorithmLabel } from '../../utils/modelingLabels'
import { formatNumber } from '../analysis/analysisTypes'

const props = defineProps<{
  caseTitle: string | null
  metadata: ResultMetadata
  variable: { name: string; unit: string } | null
  validSampleCount: number | null
  r2: number | null
  commonValidCount: number | null
  formalSelected: boolean | null
  resultId: string
  currentCaseId: string | null
  caseOptions: Array<{ id: string; name: string }>
  exporting?: boolean
}>()

const emit = defineEmits<{
  (event: 'select-case', caseId: string): void
  (event: 'export-report'): void
}>()

function onCaseChange(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  if (value) emit('select-case', value)
}

const dimensionText = computed(() => (props.metadata.dimension === '3d' ? '三维' : '二维'))
const shapeText = computed(() => props.metadata.shape.join(' × '))

const formalText = computed(() => {
  if (props.formalSelected === null) return '正式成果状态未知'
  return props.formalSelected ? '正式成果已登记' : '未登记正式成果'
})

const VARIABLE_LABELS: Record<string, string> = {
  RHO: '电阻率',
  Vx: '微震速度',
  CH4_content: '瓦斯含量',
}

const variableLabel = computed(() => {
  const name = props.variable?.name ?? ''
  return VARIABLE_LABELS[name] ?? (name || '建模属性')
})
</script>

<template>
  <section class="v6-summary" data-test="v6-result-summary" aria-label="成果摘要">
    <div class="summary-left">
      <h1 class="summary-title">
        {{ caseTitle ?? '成果' }}{{ metadata.dimension === '3d' ? '连续场' : '剖面场' }} ·
        {{ algorithmLabel(metadata.algorithm) }}
      </h1>
      <p class="summary-meta">
        {{ shapeText }} 网格 · {{ dimensionText }} · 局部线性坐标 ·
        {{ variableLabel }}<template v-if="variable?.unit">（{{ variable.unit }}）</template>
      </p>
    </div>
    <div class="summary-right">
      <select
        class="case-select"
        data-test="result-case-select"
        aria-label="切换案例"
        :value="currentCaseId ?? ''"
        @change="onCaseChange"
      >
        <option v-for="option in caseOptions" :key="option.id" :value="option.id">
          {{ option.name }}
        </option>
      </select>
      <div class="summary-metric" data-test="summary-metric-samples">
        <span class="metric-label">有效样本</span>
        <span class="metric-value mono">
          {{ validSampleCount !== null ? validSampleCount.toLocaleString() : '—' }}
        </span>
      </div>
      <div class="summary-metric" data-test="summary-metric-r2">
        <span class="metric-label">模型拟合</span>
        <span class="metric-value mono">R² {{ formatNumber(r2) }}</span>
      </div>
      <div class="summary-metric" data-test="summary-metric-common">
        <span class="metric-label">公共有效集</span>
        <span class="metric-value mono">
          {{ commonValidCount !== null ? commonValidCount.toLocaleString() : '—' }}
        </span>
      </div>
      <div class="summary-metric status" data-test="summary-metric-formal">
        <span class="metric-label">成果状态</span>
        <span class="metric-value" :class="{ verified: formalSelected === true }">{{ formalText }}</span>
      </div>
      <RouterLink
        class="eval-link"
        data-test="result-back-experiment"
        :to="{ name: 'experiment-detail', params: { experimentId: metadata.experiment_id } }"
      >
        返回实验
      </RouterLink>
      <RouterLink
        class="eval-link"
        data-test="model-evaluation-entry"
        :to="{ name: 'model-evaluation', params: { resultId } }"
      >
        模型评估
      </RouterLink>
      <button
        type="button"
        class="export-action"
        data-test="result-export-report"
        :disabled="exporting"
        @click="emit('export-report')"
      >
        {{ exporting ? '正在导出…' : '导出分析报告' }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.v6-summary {
  height: 72px;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 0 18px;
  border-bottom: 1px solid var(--s1-border);
  background: var(--s1-bg);
}

.summary-left {
  min-width: 0;
}

.summary-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--s1-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.summary-meta {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--s1-text-faint);
  font-family: ui-monospace, monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.summary-right {
  display: flex;
  gap: 10px;
  flex: none;
}

.case-select,
.export-action {
  align-self: center;
  min-height: 34px;
  border-radius: var(--s1-radius-sm);
  font-size: var(--s1-font-sm);
}

.case-select {
  max-width: 160px;
  border: 1px solid var(--s1-border);
  background: var(--s1-bg-soft);
  color: var(--s1-text);
  padding: 0 10px;
}

.export-action {
  border: 1px solid var(--s1-cyan-strong);
  background: var(--s1-cyan-strong);
  color: #06110f;
  padding: 0 14px;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
}

.export-action:disabled {
  opacity: 0.55;
  cursor: wait;
}

.summary-metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
  border: 1px solid var(--s1-border-soft);
  border-radius: var(--s1-radius-sm);
  padding: 6px 12px;
  min-width: 96px;
}

.metric-label {
  font-size: 12px;
  color: var(--s1-text-faint);
}

.metric-value {
  font-size: 16px;
  font-weight: 600;
  color: var(--s1-text);
}

.metric-value.verified {
  color: var(--s1-cyan-strong);
}

.eval-link {
  align-self: center;
  border: 1px solid var(--s1-border);
  border-radius: 6px;
  padding: 6px 14px;
  font-size: 12px;
  color: var(--s1-text-dim);
  text-decoration: none;
  white-space: nowrap;
}

.eval-link:hover {
  color: var(--s1-cyan-strong);
  border-color: var(--s1-cyan-dim);
}

.mono {
  font-family: ui-monospace, monospace;
}
</style>
