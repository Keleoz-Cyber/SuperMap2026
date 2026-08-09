<script setup lang="ts">
// v0.9.0：质量组成摘要。环图仅用于有效/无效部分-整体关系；
// 问题按阻断/警告分级，空间范围如实展示；绝不把任何占比命名为地质体积。
import { computed } from 'vue'
import type { QualityReport } from '../../api/types'

const props = defineProps<{
  report: QualityReport | null
}>()

const composition = computed(() => {
  if (!props.report) return null
  const { valid_row_count: valid, invalid_row_count: invalid, row_count: rows } = props.report
  if (![valid, invalid, rows].every((v) => Number.isFinite(v)) || rows <= 0) return null
  return { valid, invalid, rows, ratio: valid / rows }
})

const donutDash = computed(() => {
  if (!composition.value) return '0 100'
  const pct = composition.value.ratio * 100
  return `${pct} ${100 - pct}`
})

const blockers = computed(() => props.report?.issues.filter((i) => i.kind === 'blocker') ?? [])
const warnings = computed(() => props.report?.issues.filter((i) => i.kind === 'warning') ?? [])

const ranges = computed(() => {
  const r = props.report?.statistics?.ranges
  if (!r) return null
  const entries = Object.entries(r).filter(
    (entry): entry is [string, [number, number]] => Array.isArray(entry[1]) && entry[1] !== null,
  )
  return entries.length > 0 ? entries : null
})

function fmt(v: number): string {
  return Math.abs(v) >= 1000 ? v.toFixed(0) : String(Math.round(v * 1000) / 1000)
}
</script>

<template>
  <section class="quality-composition" data-test="quality-composition">
    <h4 class="qc-title">质量摘要</h4>
    <p v-if="!report" class="qc-empty">尚未生成质量报告：完成字段映射后自动校验。</p>
    <template v-else>
      <div class="qc-grid">
        <div class="qc-donut" data-test="quality-donut">
          <svg v-if="composition" viewBox="0 0 42 42" class="donut" role="img" aria-label="有效数据占比">
            <circle class="track" cx="21" cy="21" r="15.9155" />
            <circle class="valid" cx="21" cy="21" r="15.9155" :stroke-dasharray="donutDash" />
            <text x="21" y="23.5" class="donut-text">{{ Math.round(composition.ratio * 100) }}%</text>
          </svg>
          <div v-if="composition" class="donut-legend">
            <span><i class="swatch valid" />有效 {{ composition.valid }}</span>
            <span><i class="swatch invalid" />无效 {{ composition.invalid }}</span>
            <span class="total">共 {{ composition.rows }} 行</span>
          </div>
        </div>

        <div class="qc-issues">
          <p class="issue-counts">
            <span class="count blocker" data-test="quality-blocker-count">阻断 {{ blockers.length }}</span>
            <span class="count warning" data-test="quality-warning-count">警告 {{ warnings.length }}</span>
          </p>
          <ul v-if="blockers.length || warnings.length" class="issue-list">
            <li
              v-for="issue in [...blockers, ...warnings]"
              :key="issue.code"
              :class="issue.kind"
            >
              <code>{{ issue.code }}</code> {{ issue.message }}
            </li>
          </ul>
          <p v-else class="qc-clean">无阻断项与警告项</p>
        </div>

        <div v-if="ranges" class="qc-ranges">
          <p v-for="[axis, range] in ranges" :key="axis">
            {{ axis.toUpperCase() }} ∈ [{{ fmt(range[0]) }}, {{ fmt(range[1]) }}]
          </p>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.quality-composition {
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-1);
  padding: var(--s1-space-3) var(--s1-space-4);
}

.qc-title {
  margin: 0 0 var(--s1-space-2);
  font-size: var(--s1-font-sm);
  font-weight: 600;
  color: var(--s1-text-dim);
  letter-spacing: 0.05em;
}

.qc-empty {
  margin: 0;
  font-size: var(--s1-font-sm);
  color: var(--s1-text-faint);
}

.qc-grid {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: var(--s1-space-4);
  align-items: start;
}

.qc-donut {
  display: flex;
  align-items: center;
  gap: var(--s1-space-3);
}

.donut {
  width: 64px;
  height: 64px;
}

.track {
  fill: none;
  stroke: var(--s1-surface-3);
  stroke-width: 5;
}

.valid {
  fill: none;
  stroke: var(--s1-cyan);
  stroke-width: 5;
  stroke-linecap: round;
  transform: rotate(-90deg);
  transform-origin: center;
}

.donut-text {
  fill: var(--s1-text-strong);
  font-size: 11px;
  font-weight: 700;
  text-anchor: middle;
}

.donut-legend {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: var(--s1-font-xs);
  color: var(--s1-text-dim);
}

.swatch {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 2px;
  margin-right: 5px;
}

.swatch.valid {
  background: var(--s1-cyan);
}

.swatch.invalid {
  background: var(--s1-surface-3);
}

.total {
  color: var(--s1-text-faint);
}

.issue-counts {
  margin: 0 0 6px;
  display: flex;
  gap: 10px;
}

.count {
  font-size: var(--s1-font-xs);
  border-radius: 999px;
  padding: 2px 10px;
  border: 1px solid var(--s1-border);
}

.count.blocker {
  color: var(--s1-error);
  border-color: rgba(224, 104, 94, 0.45);
}

.count.warning {
  color: var(--s1-warning);
  border-color: rgba(217, 168, 78, 0.45);
}

.issue-list {
  margin: 0;
  padding: 0 0 0 16px;
  font-size: var(--s1-font-xs);
  line-height: 1.7;
  max-height: 120px;
  overflow-y: auto;
}

.issue-list li.blocker {
  color: var(--s1-error);
}

.issue-list li.warning {
  color: var(--s1-warning);
}

.issue-list code {
  font-size: 10px;
  opacity: 0.85;
}

.qc-clean {
  margin: 0;
  font-size: var(--s1-font-xs);
  color: var(--s1-success);
}

.qc-ranges {
  font-size: var(--s1-font-xs);
  color: var(--s1-text-dim);
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.qc-ranges p {
  margin: 2px 0;
}

@media (max-width: 720px) {
  .qc-grid {
    grid-template-columns: 1fr;
  }

  .qc-ranges {
    text-align: left;
  }
}
</style>
