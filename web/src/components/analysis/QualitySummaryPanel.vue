<script setup lang="ts">
import { computed } from 'vue'
import type { AnalysisVariable, NumericSummary, QualitySummary } from '../../api/types'
import { formatNumber } from './analysisTypes'

// v0.8.0 第二批 Task 5：数据质量 + 基础统计摘要（右栏）。
// 所有统计数字带变量单位与样本数；null（未计算）显示占位符，绝不伪造 0。

const props = defineProps<{
  quality: QualitySummary
  statistics: NumericSummary | null
  variable: AnalysisVariable
}>()

const unit = computed(() => props.variable.unit ?? '')

function withUnit(value: number | null | undefined): string {
  const text = formatNumber(value)
  if (text === '—' || !unit.value) return text
  return `${text} ${unit.value}`
}

const boundsEntries = computed(() => {
  const bounds = props.quality.bounds
  if (!bounds) return []
  return Object.entries(bounds).map(([axis, pair]) => ({
    axis: axis.toUpperCase(),
    range: `${formatNumber(pair[0])} – ${formatNumber(pair[1])}`,
  }))
})

const QUANTILE_ROWS: { key: 'p05' | 'p25' | 'p50' | 'p75' | 'p95'; label: string }[] = [
  { key: 'p05', label: 'p05' },
  { key: 'p25', label: 'p25' },
  { key: 'p50', label: 'p50' },
  { key: 'p75', label: 'p75' },
  { key: 'p95', label: 'p95' },
]

const quantileRows = computed(() => {
  const quantiles = props.statistics?.quantiles ?? null
  return QUANTILE_ROWS.map((row) => ({
    label: row.label,
    value: quantiles ? withUnit(quantiles[row.key]) : '—',
  }))
})
</script>

<template>
  <section class="panel quality-summary" data-test="quality-summary-panel">
    <h3>数据质量与统计</h3>

    <dl class="metric-grid" data-test="quality-rows">
      <div class="metric">
        <dt>数据行</dt>
        <dd>{{ formatNumber(quality.row_count) }}</dd>
      </div>
      <div class="metric">
        <dt>有效行</dt>
        <dd>{{ formatNumber(quality.valid_count) }}</dd>
      </div>
      <div class="metric">
        <dt>无效/缺失行</dt>
        <dd>{{ formatNumber(quality.invalid_count) }}</dd>
      </div>
      <div class="metric">
        <dt>重复坐标</dt>
        <dd>{{ formatNumber(quality.duplicate_coordinate_count) }}</dd>
      </div>
    </dl>

    <div class="bounds" data-test="quality-bounds">
      <h4>坐标范围</h4>
      <p v-if="boundsEntries.length === 0" class="empty-note">坐标范围不可用（无有效样本）</p>
      <ul v-else>
        <li v-for="entry in boundsEntries" :key="entry.axis">
          {{ entry.axis }}：{{ entry.range }}
        </li>
      </ul>
    </div>

    <div class="numeric" data-test="numeric-summary">
      <template v-if="statistics">
        <h4>{{ variable.name }} 统计<span v-if="unit">（{{ unit }}）</span></h4>
        <p class="sample-count">样本数 {{ formatNumber(statistics.count) }}</p>
        <dl class="metric-grid">
          <div class="metric">
            <dt>最小值</dt>
            <dd>{{ withUnit(statistics.min) }}</dd>
          </div>
          <div class="metric">
            <dt>最大值</dt>
            <dd>{{ withUnit(statistics.max) }}</dd>
          </div>
          <div class="metric">
            <dt>均值</dt>
            <dd>{{ withUnit(statistics.mean) }}</dd>
          </div>
          <div class="metric">
            <dt>中位数</dt>
            <dd>{{ withUnit(statistics.median) }}</dd>
          </div>
          <div class="metric">
            <dt>标准差</dt>
            <dd>{{ withUnit(statistics.std) }}</dd>
          </div>
        </dl>
        <dl class="quantiles" data-test="numeric-quantiles">
          <div v-for="row in quantileRows" :key="row.label" class="quantile">
            <dt>{{ row.label }}</dt>
            <dd>{{ row.value }}</dd>
          </div>
        </dl>
      </template>
      <p v-else class="empty-note">基础统计不可用（无有限公共有效样本）</p>
    </div>
  </section>
</template>

<style scoped>
.panel {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

h3 {
  margin: 0;
  font-size: 15px;
}

h4 {
  margin: 0 0 6px;
  font-size: 13px;
  color: var(--gmp-text-dim);
}

.metric-grid {
  margin: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
  gap: 8px;
}

.metric dt {
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.metric dd {
  margin: 2px 0 0;
  font-size: 15px;
  font-variant-numeric: tabular-nums;
}

.bounds ul {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  color: var(--gmp-text-dim);
  font-variant-numeric: tabular-nums;
}

.sample-count {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.quantiles {
  margin: 10px 0 0;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.quantile dt {
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.quantile dd {
  margin: 2px 0 0;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.empty-note {
  margin: 0;
  font-size: 13px;
  color: var(--gmp-text-faint);
}
</style>
