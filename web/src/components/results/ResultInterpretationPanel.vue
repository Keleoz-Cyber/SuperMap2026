<script setup lang="ts">
// v0.9.0 Task 6：规则研判面板（成果级）。四个真实信息模块 + 后端结构化发现：
//   成果概览 / 异常区域 / 当前切片 / 模型与不确定性。
// 全部数字与文案只来自 ResultAnalysisSummary 与权威 SliceAnalysisResponse；
// 前端绝不重算阈值、连通区排序或结论 prose；不支持的数据一律类型化空态。
// 面板只发射聚焦事件（组件/深度层段），相机与高亮由父级经协议落地。
import { computed } from 'vue'
import type {
  ResultAnalysisSummary,
  ResultComponentPreview,
  SliceAnalysisResponse,
} from '../../api/types'
import { formatNumber } from '../analysis/analysisTypes'
import AsyncState from '../states/AsyncState.vue'
import { algorithmLabel, propertyLabel, unitLabel } from '../../utils/modelingLabels'

const props = withDefaults(
  defineProps<{
    analysis: ResultAnalysisSummary | null
    currentSlice: SliceAnalysisResponse | null
    focusedComponentId: number | null
    loading?: boolean
    error?: string | null
  }>(),
  { loading: false, error: null },
)

const emit = defineEmits<{
  (e: 'focus-component', componentId: number): void
  (e: 'focus-depth-bin', index: number): void
}>()

const CONFIDENCE_LABELS: Record<string, string> = { high: '较强', medium: '一般', low: '有限' }
const METRIC_LABELS: Record<string, string> = {
  rmse: 'RMSE',
  mae: 'MAE',
  r2: 'R²',
  coverage: '覆盖率',
  bias: 'Bias',
}
const DOMAIN_CONFIDENCE_LABELS: Record<string, string> = {
  rule_supported: '可直接参考',
  exploratory: '建议复核',
}

const domain = computed(() => props.analysis?.domain_interpretation ?? null)

function percent(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return '—'
  return `${(ratio * 100).toFixed(1)}%`
}

function supportUnitLabel(unit: ResultComponentPreview['support_unit']): string {
  return unit === 'volume_coordinate_unit3'
    ? '模型覆盖范围估计（三维网格）'
    : '模型覆盖范围估计（平面网格）'
}

// 成果组成桶：保持后端返回顺序与数值，只补显示标签
const BUCKET_LABELS: Record<string, string> = { low: '低值', normal: '正常', high: '高值' }
const buckets = computed(() => props.analysis?.composition.buckets ?? [])
const fullGridHighRatio = computed(
  () => buckets.value.find((b) => b.category === 'high')?.ratio ?? null,
)

// 高值集中层段：后端 depth_profile 中 high_ratio 最大的层段（纯展示选择，不重算阈值）
const dominantBin = computed(() => {
  const profile = props.analysis?.depth_profile
  if (!profile || profile.status !== 'applicable' || profile.bins.length === 0) return null
  let best = 0
  profile.bins.forEach((bin, i) => {
    if (bin.high_ratio > profile.bins[best].high_ratio) best = i
  })
  return { index: best, bin: profile.bins[best] }
})

const modelMetrics = computed(() => {
  const evidence = props.analysis?.model_evidence
  if (!evidence) return []
  return Object.entries(evidence.metrics)
    .filter(([key, value]) => key in METRIC_LABELS && value !== null && Number.isFinite(value))
    .map(([key, value]) => ({ label: METRIC_LABELS[key], value: value as number }))
})

function productFindingCopy(text: string): string {
  return text
    .replaceAll('网格支持体积估计非真实地质体积', '这里只表示模型覆盖大小，不是真实地质体积')
    .replaceAll('网格支持面积估计非真实地质面积', '这里只表示模型覆盖大小，不是真实地质面积')
    .replaceAll('网格支持体积估计', '模型覆盖范围估计')
    .replaceAll('网格支持面积估计', '模型覆盖范围估计')
    .replaceAll('volume_coordinate_unit3', '网格坐标单位³')
    .replaceAll('area_coordinate_unit2', '网格坐标单位²')
}

// 不确定性状态：直接引用后端 uncertainty_availability 发现的陈述，不自行生成结论
const uncertaintyStatement = computed(() => {
  const finding = props.analysis?.findings.find((f) => f.kind === 'uncertainty_availability')
  return finding?.statement ?? '无不确定性证据'
})

// 当前切片：权威响应的组成 + 与完整场高值占比差值（仅展示算术，阈值仍来自后端）
const sliceStats = computed(() => props.currentSlice?.statistics ?? null)
const sliceHighDelta = computed(() => {
  const stats = sliceStats.value
  const full = fullGridHighRatio.value
  if (!stats || stats.high_ratio === null || full === null) return null
  return stats.high_ratio - full
})

function formatDelta(delta: number | null): string {
  if (delta === null || !Number.isFinite(delta)) return '—'
  const points = delta * 100
  return `${points >= 0 ? '+' : ''}${points.toFixed(1)} 个百分点`
}

function onFindingLocate(finding: NonNullable<ResultAnalysisSummary['findings']>[number]) {
  const target = finding.spatial_target
  if (!target) return
  if (target.kind === 'component' && target.component_id !== null) {
    emit('focus-component', target.component_id)
  } else if (target.kind === 'depth_bin' && target.depth_bin_index !== null) {
    emit('focus-depth-bin', target.depth_bin_index)
  }
}

function findingTitle(finding: NonNullable<ResultAnalysisSummary['findings']>[number]): string {
  if (finding.kind === 'formal_model') {
    return `正式模型：${algorithmLabel(props.analysis?.model_evidence.algorithm ?? '')}`
  }
  if (finding.kind === 'uncertainty_availability') return '不确定性证据'
  return finding.title
}

function findingStatement(finding: NonNullable<ResultAnalysisSummary['findings']>[number]): string {
  if (finding.kind !== 'formal_model') return productFindingCopy(finding.statement)
  const metrics = props.analysis?.model_evidence.metrics ?? {}
  const parts = [
    props.analysis?.model_evidence.common_valid_count !== null
      ? `公共有效点 ${props.analysis?.model_evidence.common_valid_count?.toLocaleString() ?? '—'}`
      : null,
    metrics.rmse !== null && Number.isFinite(metrics.rmse) ? `RMSE ${formatNumber(metrics.rmse)}` : null,
    metrics.mae !== null && Number.isFinite(metrics.mae) ? `MAE ${formatNumber(metrics.mae)}` : null,
    metrics.r2 !== null && Number.isFinite(metrics.r2) ? `R² ${formatNumber(metrics.r2)}` : null,
  ].filter(Boolean)
  return parts.join(' · ')
}
</script>

<template>
  <section
    class="interpretation"
    :class="domain ? `domain-${domain.profile}` : ''"
    data-test="result-interpretation"
    :aria-label="domain?.panel_label ?? '规则研判'"
  >
    <AsyncState
      v-if="loading"
      kind="loading"
      title="成果分析加载中"
      data-test="interpretation-loading"
    />
    <AsyncState
      v-else-if="error"
      kind="error"
      title="成果分析不可用"
      :impact="error"
      next-action="确认成果已物化后重试"
      data-test="interpretation-error"
    />
    <AsyncState
      v-else-if="!analysis"
      kind="nodata"
      title="暂无成果分析"
      impact="规则研判与三维异常标注不可用"
      next-action="成果物化成功后自动生成"
      data-test="interpretation-empty"
    />

    <template v-else>
      <section
        v-if="domain"
        class="domain-overview"
        data-test="domain-overview"
        :data-status="domain.status"
      >
        <div class="domain-kicker">
          <span>{{ domain.narrative_label }}</span>
          <span class="domain-status">{{ domain.status === 'not_applicable' ? '仅看数值' : '建议复核' }}</span>
        </div>
        <h3>{{ domain.panel_label }}</h3>
        <p>{{ domain.overview }}</p>
        <div v-if="domain.global_limitations.length" class="domain-boundary">
          <strong>注意</strong>
          <span>{{ domain.global_limitations.join('；') }}</span>
        </div>
      </section>

      <section v-if="domain?.cards.length" class="domain-cards" data-test="domain-cards">
        <details
          v-for="(card, index) in domain.cards"
          :key="card.id"
          class="domain-card"
          :class="[`direction-${card.direction}`, { focused: card.component_id === focusedComponentId }]"
          :open="index === 0 || card.component_id === focusedComponentId"
          :data-test="`domain-card-${card.direction}-${card.component_id}`"
        >
          <summary>
            <span class="direction-dot" aria-hidden="true"></span>
            <span class="domain-card-heading">
              <strong>{{ card.title }}</strong>
              <small>{{ card.summary }}</small>
            </span>
            <span class="domain-confidence">{{ DOMAIN_CONFIDENCE_LABELS[card.confidence] }}</span>
          </summary>
          <div class="domain-card-body">
            <p class="domain-narrative">
              {{ card.possible_interpretations.join('；') }}。{{ card.potential_impacts.join('；') }}。
            </p>
            <p class="domain-action"><strong>建议：</strong>{{ card.recommended_actions.join('；') }}</p>
            <p class="card-limitations"><strong>注意：</strong>{{ card.limitations.join('；') }}</p>
            <details class="card-values">
              <summary>查看数值</summary>
              <p>{{ card.evidence.join(' · ') }}</p>
            </details>
            <button
              type="button"
              class="domain-locate"
              :data-test="`domain-locate-${card.component_id}`"
              @click="emit('focus-component', card.component_id)"
            >
              定位三维
            </button>
          </div>
        </details>
      </section>

      <details
        class="technical-evidence"
        :open="domain?.status === 'not_applicable'"
        data-test="technical-evidence"
      >
        <summary>
          <span>计算说明</span>
          <small>查看阈值、区域划分、切片和模型指标</small>
        </summary>
        <div class="technical-evidence-body">
      <!-- 结构化发现：后端受控模板文案 + 空间定位 -->
      <section class="block technical-block" data-test="interpretation-findings">
        <h3 class="block-title">关键发现</h3>
        <article
          v-for="finding in analysis.findings"
          :key="finding.id"
          class="finding"
          :data-test="`finding-${finding.id}`"
        >
          <header class="finding-head">
            <span class="finding-title">{{ findingTitle(finding) }}</span>
            <span class="confidence" :data-confidence="finding.confidence">
              数据支持 {{ CONFIDENCE_LABELS[finding.confidence] ?? finding.confidence }}
            </span>
          </header>
          <p class="finding-statement">{{ findingStatement(finding) }}</p>
          <ul v-if="finding.limitations.length > 0" class="finding-limits">
            <li v-for="limit in finding.limitations" :key="limit">{{ productFindingCopy(limit) }}</li>
          </ul>
          <button
            v-if="finding.spatial_target && finding.spatial_target.kind !== 'grid'"
            type="button"
            class="locate-button"
            :data-test="`finding-locate-${finding.id}`"
            @click="onFindingLocate(finding)"
          >
            定位
          </button>
        </article>
      </section>

      <!-- 成果概览：完整场组成 / 阈值 / 高值层段（成果网格口径） -->
      <section class="block" data-test="interpretation-overview">
        <h3 class="block-title">成果概览 <span class="scope-badge">成果网格</span></h3>
        <p class="scope-note">
          {{ propertyLabel(analysis.variable.name) }}（{{ unitLabel(analysis.variable.unit) }}）·
          有效体元 {{ analysis.grid.valid_count.toLocaleString() }}，NoData
          {{ analysis.grid.nodata_count.toLocaleString() }}
        </p>
        <div class="bucket-row" data-test="overview-composition">
          <div v-for="bucket in buckets" :key="bucket.category" class="bucket" :data-category="bucket.category">
            <span class="bucket-label">{{ BUCKET_LABELS[bucket.category] ?? bucket.category }}</span>
            <span class="bucket-value mono">{{ percent(bucket.ratio) }}</span>
            <span class="bucket-count">{{ bucket.count.toLocaleString() }} 体元节点</span>
          </div>
        </div>
        <p class="scope-note">
          阈值：低值 &lt; {{ formatNumber(analysis.thresholds.low) }}，高值 ≥
          {{ formatNumber(analysis.thresholds.high) }}（完整网格 p25/p75）
        </p>
        <p v-if="dominantBin" class="scope-note">
          高值集中层段 {{ dominantBin.bin.z_lower }}–{{ dominantBin.bin.z_upper }} m（高值占比
          {{ percent(dominantBin.bin.high_ratio) }}）
        </p>
        <p v-else class="scope-note">深度分层不适用（{{ analysis.identity.dimension === '2d' ? '二维成果' : '无层段' }}）</p>
      </section>

      <!-- 异常区域：A/B/C 连通区（后端排序与标签） -->
      <section class="block" data-test="interpretation-components">
        <h3 class="block-title">
          异常区域
          <span class="scope-note inline">
            阈值 ≥ {{ formatNumber(analysis.components_preview.threshold) }} ·
            共 {{ analysis.components_preview.total }} 个，显示
            {{ analysis.components_preview.returned }} 个
          </span>
        </h3>
        <p v-if="analysis.components_preview.rows.length === 0" class="scope-note">
          当前阈值下无高值连通区
        </p>
        <button
          v-for="row in analysis.components_preview.rows"
          :key="row.component_id"
          type="button"
          class="component-row"
          :class="{ focused: row.component_id === focusedComponentId }"
          :data-test="`component-${row.component_id}`"
          @click="emit('focus-component', row.component_id)"
        >
          <span class="component-label">{{ row.label }}</span>
          <span class="component-body">
            <span class="component-line">
              峰值 {{ formatNumber(row.value_max) }} · {{ supportUnitLabel(row.support_unit) }}
              {{ formatNumber(row.support_measure) }}
              <em v-if="row.touches_grid_boundary" class="boundary-badge">接触边界</em>
            </span>
            <span class="component-sub">
              中心 ({{ row.centroid.map((c) => formatNumber(c)).join(', ') }})
              <template v-if="row.kriging_std_mean !== null && row.kriging_std_mean !== undefined">
                · Kriging 标准差 {{ formatNumber(row.kriging_std_mean) }}
              </template>
            </span>
          </span>
        </button>
      </section>

      <!-- 当前切片：权威剖面统计（共享完整网格阈值） -->
      <section class="block" data-test="interpretation-slice">
        <h3 class="block-title">当前切片</h3>
        <p v-if="!currentSlice" class="scope-note" data-test="slice-empty">
          进入切片模式后显示当前切片统计
        </p>
        <template v-else>
          <p class="scope-note">
            {{ currentSlice.slice.fixed_axis.toUpperCase() }} =
            {{ formatNumber(currentSlice.slice.coordinate) }} · 有效
            {{ sliceStats?.valid_count ?? 0 }} / NoData {{ sliceStats?.nodata_count ?? 0 }} ·
            均值 {{ formatNumber(sliceStats?.mean) }}
          </p>
          <template v-if="sliceStats && sliceStats.thresholds">
            <p class="scope-note">低值和高值按完整模型的 p25/p75 划分</p>
            <div class="bucket-row compact">
              <div class="bucket" data-category="low">
                <span class="bucket-label">低值</span>
                <span class="bucket-value mono">{{ percent(sliceStats.low_ratio) }}</span>
              </div>
              <div class="bucket" data-category="normal">
                <span class="bucket-label">正常</span>
                <span class="bucket-value mono">{{ percent(sliceStats.normal_ratio) }}</span>
              </div>
              <div class="bucket" data-category="high">
                <span class="bucket-label">高值</span>
                <span class="bucket-value mono">{{ percent(sliceStats.high_ratio) }}</span>
              </div>
            </div>
            <p class="scope-note">这个切片的高值占比较完整模型相差：{{ formatDelta(sliceHighDelta) }}</p>
          </template>
          <p v-else class="scope-note">未提供完整网格阈值，切片组成不可用</p>
        </template>
      </section>

      <!-- 模型与不确定性 -->
      <section class="block" data-test="interpretation-model">
        <h3 class="block-title">模型表现</h3>
        <p class="scope-note">算法 {{ algorithmLabel(analysis.model_evidence.algorithm) }}</p>
        <div v-if="modelMetrics.length > 0" class="metric-row">
          <div v-for="metric in modelMetrics" :key="metric.label" class="metric">
            <span class="metric-label">{{ metric.label }}</span>
            <span class="metric-value mono">{{ formatNumber(metric.value) }}</span>
          </div>
        </div>
        <p v-if="analysis.model_evidence.common_valid_count !== null" class="scope-note">
          共同参与比较的点 {{ analysis.model_evidence.common_valid_count.toLocaleString() }}
        </p>
        <p class="scope-note">
          <template v-if="analysis.model_evidence.formal_selection_id">
            当前使用的正式模型
          </template>
          <template v-else>未选择正式模型</template>
        </p>
        <p class="scope-note">{{ uncertaintyStatement }}</p>
      </section>
        </div>
      </details>
    </template>
  </section>
</template>

<style scoped>
.interpretation {
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-3);
  min-width: 0;
}

.domain-overview {
  position: relative;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--domain-accent, var(--s1-cyan-strong)) 55%, transparent);
  border-radius: 14px;
  padding: 14px;
  background:
    radial-gradient(circle at 100% 0, color-mix(in srgb, var(--domain-accent, var(--s1-cyan-strong)) 18%, transparent), transparent 48%),
    var(--s1-surface-1);
}

.domain-resistivity { --domain-accent: #e8b84b; --domain-low: #4d8de0; }
.domain-microseismic_velocity { --domain-accent: #9d87ff; --domain-low: #54d5d0; }
.domain-gas_content { --domain-accent: #ef8a4c; --domain-low: #54d6a8; }
.domain-generic_3d { --domain-accent: var(--s1-cyan-strong); --domain-low: var(--s1-cyan-strong); }

.domain-kicker {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  color: var(--domain-accent);
  font-size: var(--s1-font-xs);
  letter-spacing: 0.08em;
}

.domain-status {
  border: 1px solid color-mix(in srgb, var(--domain-accent) 45%, transparent);
  border-radius: 999px;
  padding: 1px 7px;
  letter-spacing: 0;
}

.domain-overview h3 {
  margin: 8px 0 4px;
  font-size: 20px;
  color: var(--s1-text);
}

.domain-overview > p {
  margin: 0;
  color: var(--s1-text-dim);
  font-size: var(--s1-font-sm);
  line-height: 1.65;
}

.domain-boundary {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--s1-border-soft);
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
  line-height: 1.55;
}

.domain-boundary strong { color: var(--domain-accent); }
.domain-cards { display: grid; gap: 8px; }

.domain-card {
  border: 1px solid var(--s1-border-soft);
  border-left: 3px solid var(--domain-accent);
  border-radius: 10px;
  background: color-mix(in srgb, var(--s1-surface-1) 94%, var(--domain-accent) 6%);
  overflow: hidden;
}

.domain-card.direction-low { border-left-color: var(--domain-low); }
.domain-card.focused {
  box-shadow: 0 0 0 1px var(--domain-accent), 0 0 22px color-mix(in srgb, var(--domain-accent) 16%, transparent);
}

.domain-card summary {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr) auto;
  gap: 9px;
  align-items: start;
  cursor: pointer;
  padding: 11px 12px;
  list-style: none;
}

.domain-card summary::-webkit-details-marker { display: none; }
.direction-dot {
  width: 8px;
  height: 8px;
  margin-top: 5px;
  border-radius: 50%;
  background: var(--domain-accent);
  box-shadow: 0 0 10px var(--domain-accent);
}
.direction-low .direction-dot { background: var(--domain-low); box-shadow: 0 0 10px var(--domain-low); }
.domain-card-heading { display: grid; gap: 3px; min-width: 0; }
.domain-card-heading strong { color: var(--s1-text); font-size: var(--s1-font-sm); }
.domain-card-heading small { color: var(--s1-text-faint); font-size: var(--s1-font-xs); line-height: 1.45; }
.domain-confidence { color: var(--domain-accent); font-size: var(--s1-font-xs); white-space: nowrap; }
.domain-card-body { display: grid; gap: 8px; padding: 0 12px 12px 31px; }
.domain-narrative,
.domain-action,
.card-limitations,
.card-values p {
  margin: 0;
  font-size: var(--s1-font-xs);
  line-height: 1.65;
}
.domain-narrative { color: var(--s1-text-dim); }
.domain-action {
  padding: 8px;
  margin-left: -8px;
  border-radius: 7px;
  background: color-mix(in srgb, var(--domain-accent) 9%, transparent);
  color: var(--s1-text);
}
.domain-action strong { color: var(--domain-accent); }
.card-limitations { color: var(--s1-text-faint); }
.card-limitations strong { color: var(--s1-warning); }
.card-values { color: var(--s1-text-faint); font-size: var(--s1-font-xs); }
.card-values summary { color: var(--domain-accent); }
.card-values p { margin-top: 6px; color: var(--s1-text-faint); }
.card-limitations {
  padding-top: 7px;
  border-top: 1px dashed var(--s1-border-soft);
  color: var(--s1-text-faint);
  font-size: var(--s1-font-xs);
  line-height: 1.5;
}
.domain-locate {
  justify-self: start;
  border: 1px solid color-mix(in srgb, var(--domain-accent) 55%, transparent);
  border-radius: 7px;
  background: color-mix(in srgb, var(--domain-accent) 10%, transparent);
  color: var(--domain-accent);
  padding: 5px 12px;
  cursor: pointer;
}
.technical-block { opacity: 0.82; }

.technical-evidence {
  border: 1px solid color-mix(in srgb, var(--s1-border) 82%, transparent);
  border-radius: var(--s1-radius-md);
  background: color-mix(in srgb, var(--s1-surface-2) 76%, transparent);
}

.technical-evidence > summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s1-space-2);
  padding: 10px 12px;
  color: var(--s1-text);
  cursor: pointer;
  list-style: none;
}

.technical-evidence > summary::-webkit-details-marker { display: none; }

.technical-evidence > summary::after {
  content: '展开';
  color: var(--s1-accent);
  font-size: var(--s1-font-xs);
}

.technical-evidence[open] > summary::after { content: '收起'; }

.technical-evidence > summary small {
  margin-left: auto;
  color: var(--s1-text-dim);
  font-size: var(--s1-font-xs);
}

.technical-evidence-body {
  display: grid;
  gap: var(--s1-space-3);
  padding: 0 8px 8px;
}

.block {
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-1);
  padding: var(--s1-space-3);
}

.block-title {
  margin: 0 0 var(--s1-space-2);
  font-size: var(--s1-font-xs);
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--s1-text-dim);
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}

.scope-badge {
  font-size: var(--s1-font-xs);
  color: var(--s1-cyan-strong);
  border: 1px solid var(--s1-cyan-dim);
  border-radius: 4px;
  padding: 0 6px;
  letter-spacing: 0;
}

.scope-note {
  margin: 4px 0 0;
  font-size: var(--s1-font-sm);
  color: var(--s1-text-faint);
  line-height: var(--s1-leading);
}

.scope-note.inline {
  margin: 0;
  font-weight: 400;
  letter-spacing: 0;
  text-transform: none;
}

.finding {
  border: 1px solid var(--s1-border-soft);
  border-radius: var(--s1-radius-sm);
  padding: 8px 10px;
  margin-bottom: 8px;
}

.finding:last-child {
  margin-bottom: 0;
}

.finding-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.finding-title {
  font-size: var(--s1-font-sm);
  font-weight: 600;
  color: var(--s1-text);
}

.confidence {
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
  white-space: nowrap;
}

.confidence[data-confidence='high'] {
  color: var(--s1-cyan-strong);
}

.finding-statement {
  margin: 4px 0 0;
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
  line-height: var(--s1-leading);
}

.finding-limits {
  margin: 4px 0 0;
  padding-left: 16px;
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
}

.locate-button {
  margin-top: 6px;
  border: 1px solid var(--s1-cyan-dim);
  background: var(--s1-cyan-ghost);
  color: var(--s1-cyan-strong);
  border-radius: 6px;
  padding: 2px 10px;
  font-size: var(--s1-font-xs);
  cursor: pointer;
}

.bucket-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--s1-space-2);
  margin-top: var(--s1-space-2);
}

.bucket-row.compact {
  margin-top: var(--s1-space-2);
}

.bucket {
  border: 1px solid var(--s1-border-soft);
  border-radius: var(--s1-radius-sm);
  padding: 6px 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.bucket-label {
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
}

.bucket[data-category='high'] .bucket-value {
  color: var(--s1-gold);
}

.bucket-value {
  font-size: var(--s1-font-lg);
  font-weight: 600;
  color: var(--s1-text);
}

.bucket-count {
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
}

.component-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  width: 100%;
  text-align: left;
  border: 1px solid var(--s1-border-soft);
  background: transparent;
  border-radius: var(--s1-radius-sm);
  padding: 8px 10px;
  margin-bottom: 6px;
  cursor: pointer;
  color: var(--s1-text);
}

.component-row:last-child {
  margin-bottom: 0;
}

.component-row:hover {
  border-color: var(--s1-cyan-dim);
  background: var(--s1-cyan-ghost);
}

.component-row.focused {
  border-color: var(--s1-gold);
  background: rgba(217, 168, 78, 0.08);
}

.component-label {
  flex: none;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--s1-gold);
  color: #0b0f14;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--s1-font-sm);
}

.component-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.component-line {
  font-size: var(--s1-font-sm);
  color: var(--s1-text);
  line-height: var(--s1-leading);
}

.component-sub {
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
}

.boundary-badge {
  font-style: normal;
  font-size: var(--s1-font-xs);
  color: var(--s1-warning);
  border: 1px solid rgba(217, 168, 78, 0.4);
  border-radius: 4px;
  padding: 0 4px;
  margin-left: 4px;
}

.metric-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--s1-space-2);
  margin-top: var(--s1-space-2);
}

.metric {
  border: 1px solid var(--s1-border-soft);
  border-radius: var(--s1-radius-sm);
  padding: 6px 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
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

.mono {
  font-family: ui-monospace, monospace;
}
</style>
