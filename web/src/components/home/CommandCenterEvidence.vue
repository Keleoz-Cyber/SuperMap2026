<script setup lang="ts">
// v0.9.0：指挥舱底部证据带。质量组成环图（仅部分-整体口径）、模型指标、
// 异常支持占比与溯源摘要的紧凑组合；数据由 HomeView 传入，本组件不 fetch。
import { computed } from 'vue'
import type { AnalysisSummaryResponse } from '../../api/types'
import { comparisonCandidatesOf, formatNumber, spatialAnomalyOf } from '../analysis/analysisTypes'
import { algorithmLabel } from '../../utils/modelingLabels'

const props = defineProps<{
  summary: AnalysisSummaryResponse | null
  loading: boolean
}>()

// ---- 质量组成环图（有效/无效，唯一允许的部分-整体环图口径） ----
const quality = computed(() => {
  const q = props.summary?.quality
  const valid = q?.valid_count
  const invalid = q?.invalid_count
  if (typeof valid !== 'number' || !Number.isFinite(valid)) return null
  if (typeof invalid !== 'number' || !Number.isFinite(invalid)) return null
  const total = valid + invalid
  if (total <= 0) return null
  return { valid, invalid, total, ratio: valid / total }
})

const donutDash = computed(() => {
  if (!quality.value) return '0 100'
  const pct = quality.value.ratio * 100
  return `${pct} ${100 - pct}`
})

// ---- 模型指标（公共有效集口径，仅展示有限 RMSE） ----
const candidates = computed(() => {
  const module = props.summary?.modules.find((m) => m.module_id === 'model_comparison')
  if (!module || module.status !== 'ok') return []
  return comparisonCandidatesOf(module)
})

const rmseMax = computed(() => {
  const values = candidates.value
    .map((c) => c.metrics.rmse)
    .filter((v): v is number => typeof v === 'number' && Number.isFinite(v))
  return values.length > 0 ? Math.max(...values) : 0
})

// ---- 异常支持占比（探索性口径） ----
const anomaly = computed(() => {
  const module = props.summary?.modules.find((m) => m.module_id === 'spatial_anomaly')
  if (!module || module.status !== 'ok') return null
  return spatialAnomalyOf(module)
})

const provenance = computed(() => props.summary?.provenance ?? null)
const variable = computed(() => props.summary?.variable ?? null)
</script>

<template>
  <section class="evidence-band" data-test="home-evidence-dock" aria-label="证据摘要">
    <div class="evidence-cell">
      <h4 class="cell-title">质量组成</h4>
      <div v-if="quality" class="donut-wrap">
        <svg viewBox="0 0 42 42" class="donut" role="img" :aria-label="`有效数据占比 ${(quality.ratio * 100).toFixed(1)}%`">
          <circle class="donut-track" cx="21" cy="21" r="15.9155" />
          <circle class="donut-valid" cx="21" cy="21" r="15.9155" :stroke-dasharray="donutDash" />
          <text x="21" y="23.5" class="donut-text">{{ Math.round(quality.ratio * 100) }}%</text>
        </svg>
        <div class="donut-legend">
          <span><i class="swatch valid" />有效 {{ quality.valid }}</span>
          <span><i class="swatch invalid" />无效 {{ quality.invalid }}</span>
        </div>
      </div>
      <p v-else class="cell-empty">{{ loading ? '加载中…' : '暂无质量数据' }}</p>
    </div>

    <div class="evidence-cell">
      <h4 class="cell-title">模型指标（RMSE）</h4>
      <div v-if="candidates.length > 0" class="metric-bars">
        <div v-for="c in candidates.slice(0, 4)" :key="c.result_id" class="metric-row">
          <span class="metric-name" :class="{ formal: c.formal_selection }">{{ algorithmLabel(c.algorithm) }}</span>
          <span class="metric-track">
            <span
              class="metric-fill"
              :class="{ formal: c.formal_selection }"
              :style="{ width: rmseMax > 0 && c.metrics.rmse !== undefined ? `${(c.metrics.rmse / rmseMax) * 100}%` : '0%' }"
            />
          </span>
          <span class="metric-value mono">{{ formatNumber(c.metrics.rmse) }}</span>
        </div>
      </div>
      <p v-else class="cell-empty">{{ loading ? '加载中…' : '暂无候选指标' }}</p>
    </div>

    <div class="evidence-cell">
      <h4 class="cell-title">异常支持占比<span class="cell-tag">探索性</span></h4>
      <div v-if="anomaly && (anomaly.highVolumeRatio !== null || anomaly.lowVolumeRatio !== null)" class="anomaly-wrap">
        <div class="anomaly-bar">
          <span
            class="anomaly-high"
            :style="{ width: `${((anomaly.highVolumeRatio ?? 0) * 100).toFixed(1)}%` }"
          />
          <span
            class="anomaly-low"
            :style="{ width: `${((anomaly.lowVolumeRatio ?? 0) * 100).toFixed(1)}%` }"
          />
        </div>
        <div class="anomaly-legend">
          <span><i class="swatch high" />高值 {{ anomaly.highVolumeRatio !== null ? `${(anomaly.highVolumeRatio * 100).toFixed(1)}%` : '—' }}</span>
          <span><i class="swatch low" />低值 {{ anomaly.lowVolumeRatio !== null ? `${(anomaly.lowVolumeRatio * 100).toFixed(1)}%` : '—' }}</span>
        </div>
        <p class="cell-note">分位阈值的探索性网格支持占比</p>
      </div>
      <p v-else class="cell-empty">{{ loading ? '加载中…' : '暂无异常分析' }}</p>
    </div>

    <div class="evidence-cell">
      <h4 class="cell-title">溯源</h4>
      <div v-if="provenance" class="provenance">
        <p><span>变量</span>{{ variable?.name ?? '—' }}<template v-if="variable?.unit">（{{ variable.unit }}）</template></p>
        <p><span>源哈希</span><code class="mono">{{ provenance.source_sha256.slice(0, 8) }}</code></p>
        <p><span>数据版本</span>v{{ provenance.dataset_version }} · {{ provenance.calculation_version }}</p>
      </div>
      <p v-else class="cell-empty">{{ loading ? '加载中…' : '暂无溯源信息' }}</p>
    </div>
  </section>
</template>

<style scoped>
.evidence-band {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s1-space-3);
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-1);
  padding: var(--s1-space-3) var(--s1-space-4);
}

.evidence-cell {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-2);
}

.cell-title {
  margin: 0;
  font-size: var(--s1-font-sm);
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--s1-text-dim);
  display: flex;
  align-items: center;
  gap: 6px;
}

.cell-tag {
  font-size: var(--s1-font-sm);
  color: var(--s1-warning);
  border: 1px solid rgba(217, 168, 78, 0.4);
  border-radius: 999px;
  padding: 0 6px;
  font-weight: 400;
}

.cell-empty {
  margin: 0;
  font-size: var(--s1-font-sm);
  color: var(--s1-text-faint);
}

.donut-wrap {
  display: flex;
  align-items: center;
  gap: var(--s1-space-3);
}

.donut {
  width: 56px;
  height: 56px;
}

.donut-track {
  fill: none;
  stroke: var(--s1-surface-3);
  stroke-width: 5;
}

.donut-valid {
  fill: none;
  stroke: var(--s1-cyan);
  stroke-width: 5;
  stroke-linecap: round;
  transform: rotate(-90deg);
  transform-origin: center;
  transition: stroke-dasharray var(--s1-motion-panel) var(--s1-ease-out);
}

.donut-text {
  fill: var(--s1-text-strong);
  font-size: 12px;
  font-weight: 700;
  text-anchor: middle;
  font-variant-numeric: tabular-nums;
}

.donut-legend,
.anomaly-legend {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: var(--s1-font-sm);
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

.swatch.high {
  background: var(--s1-gold);
}

.swatch.low {
  background: var(--s1-cyan-dim);
}

.metric-bars {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.metric-row {
  display: grid;
  grid-template-columns: 96px 1fr 56px;
  align-items: center;
  gap: 8px;
  font-size: var(--s1-font-sm);
}

.metric-name {
  color: var(--s1-text-dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.metric-name.formal {
  color: var(--s1-gold);
  font-weight: 600;
}

.metric-track {
  height: 6px;
  border-radius: 3px;
  background: var(--s1-surface-3);
  overflow: hidden;
}

.metric-fill {
  display: block;
  height: 100%;
  border-radius: 3px;
  background: var(--s1-cyan-dim);
  transition: width var(--s1-motion-panel) var(--s1-ease-out);
}

.metric-fill.formal {
  background: var(--s1-gold);
}

.metric-value {
  text-align: right;
  color: var(--s1-text);
}

.anomaly-wrap {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.anomaly-bar {
  display: flex;
  height: 8px;
  border-radius: 4px;
  background: var(--s1-surface-3);
  overflow: hidden;
}

.anomaly-high {
  background: var(--s1-gold);
  transition: width var(--s1-motion-panel) var(--s1-ease-out);
}

.anomaly-low {
  background: var(--s1-cyan-dim);
  transition: width var(--s1-motion-panel) var(--s1-ease-out);
}

.cell-note {
  margin: 0;
  font-size: var(--s1-font-sm);
  color: var(--s1-text-faint);
}

.provenance {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: var(--s1-font-sm);
  color: var(--s1-text);
}

.provenance p {
  margin: 0;
}

.provenance span {
  display: inline-block;
  width: 52px;
  color: var(--s1-text-faint);
}

@media (max-width: 900px) {
  .evidence-band {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 480px) {
  .evidence-band {
    grid-template-columns: 1fr;
  }
}
</style>
