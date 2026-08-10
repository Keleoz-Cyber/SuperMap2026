<script setup lang="ts">
// v0.9.0 Task 6：成果网格证据带。七个标签页共享同一成果身份
// （result_id + grid_sha256 + result_analysis.v1），每个图表都标注
// 「成果网格」或「输入样本」来源，绝不混用两套统计口径。
// 组件只接收 DTO 不 fetch；数字与文案逐字来自后端响应。
import { computed } from 'vue'
import type {
  AnalysisSummaryResponse,
  ResidualEvidence,
  ResultAnalysisSummary,
  SliceAnalysisResponse,
} from '../../api/types'
import type { PresentationFinding } from '../../domain/findings'
import { formatNumber } from '../analysis/analysisTypes'
import type { RenderPaletteId, RenderScale } from '../rendering/renderTransferFunctions'
import SliceHeatmap from '../rendering/SliceHeatmap.vue'
import AsyncState from '../states/AsyncState.vue'
import FindingPanel from '../findings/FindingPanel.vue'
import QualityDonut from '../evidence/QualityDonut.vue'
import EChartBox from './EChartBox.vue'

const props = withDefaults(
  defineProps<{
    analysis: ResultAnalysisSummary | null
    currentSlice: SliceAnalysisResponse | null
    datasetSummary: AnalysisSummaryResponse | null
    datasetFindings?: PresentationFinding[]
    residuals?: ResidualEvidence | null
    resultId: string
    palette?: RenderPaletteId
    scale?: RenderScale
  }>(),
  { datasetFindings: () => [], residuals: null, palette: 'viridis', scale: 'linear' },
)

const emit = defineEmits<{
  (e: 'focus-component', componentId: number): void
  (e: 'focus-depth-bin', index: number): void
  (e: 'locate', finding: PresentationFinding): void
}>()

type EvidenceTab = 'composition' | 'depth' | 'components' | 'slice' | 'model' | 'input' | 'provenance'

const activeTab = defineModel<EvidenceTab>('activeTab', { default: 'composition' })

const TABS: Array<{ id: EvidenceTab; label: string; scope: string }> = [
  { id: 'composition', label: '成果组成', scope: '成果网格' },
  { id: 'depth', label: '深度趋势', scope: '成果网格' },
  { id: 'components', label: '组件比较', scope: '成果网格' },
  { id: 'slice', label: '当前切片', scope: '成果网格' },
  { id: 'model', label: '模型与残差', scope: '成果网格' },
  { id: 'input', label: '输入样本', scope: '输入样本' },
  { id: 'provenance', label: '溯源', scope: '成果网格' },
]

function percent(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return '—'
  return `${(ratio * 100).toFixed(1)}%`
}

const CHART_TEXT = { color: '#a7b8b0' }
const BUCKET_COLORS: Record<string, string> = { low: '#4d8de0', normal: '#8a9aa2', high: '#d9a84e' }
const BUCKET_LABELS: Record<string, string> = { low: '低值', normal: '正常', high: '高值' }

// ---------------------------------------------------------------------------
// 成果组成：环形图（可加总口径：体元节点占比）
// ---------------------------------------------------------------------------
const compositionOption = computed(() => {
  const analysis = props.analysis
  if (!analysis) return {}
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 体元节点（{d}%）' },
    legend: { bottom: 0, textStyle: CHART_TEXT, itemWidth: 12, itemHeight: 8 },
    series: [
      {
        type: 'pie',
        radius: ['42%', '68%'],
        center: ['50%', '44%'],
        label: { color: CHART_TEXT.color, formatter: '{b}\n{d}%' },
        data: analysis.composition.buckets.map((bucket) => ({
          name: BUCKET_LABELS[bucket.category] ?? bucket.category,
          value: bucket.count,
          itemStyle: { color: BUCKET_COLORS[bucket.category] ?? '#8a9aa2' },
        })),
      },
    ],
  }
})

// ---------------------------------------------------------------------------
// 深度趋势：层段高值占比柱 + 均值线（成果网格口径）
// ---------------------------------------------------------------------------
const depthApplicable = computed(
  () => props.analysis?.depth_profile.status === 'applicable' && (props.analysis?.depth_profile.bins.length ?? 0) > 0,
)

const depthOption = computed(() => {
  const analysis = props.analysis
  if (!analysis) return {}
  const bins = analysis.depth_profile.bins
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 48, right: 48, top: 28, bottom: 24 },
    xAxis: {
      type: 'category',
      data: bins.map((bin) => `${bin.z_lower}–${bin.z_upper} m`),
      axisLabel: { color: CHART_TEXT.color },
    },
    yAxis: [
      { type: 'value', name: '高值占比', axisLabel: { color: CHART_TEXT.color, formatter: (v: number) => `${(v * 100).toFixed(0)}%` } },
      { type: 'value', name: `均值（${analysis.variable.unit}）`, axisLabel: { color: CHART_TEXT.color } },
    ],
    series: [
      {
        name: '高值占比',
        type: 'bar',
        data: bins.map((bin) => bin.high_ratio),
        itemStyle: { color: '#d9a84e' },
      },
      {
        name: '均值',
        type: 'line',
        yAxisIndex: 1,
        data: bins.map((bin) => bin.mean),
        itemStyle: { color: '#64dab1' },
      },
    ],
  }
})

// ---------------------------------------------------------------------------
// 组件比较：网格支持量柱 + 峰值线（同一 components_preview 响应）
// ---------------------------------------------------------------------------
const componentsOption = computed(() => {
  const analysis = props.analysis
  if (!analysis) return {}
  const rows = analysis.components_preview.rows
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 56, right: 48, top: 28, bottom: 24 },
    xAxis: { type: 'category', data: rows.map((row) => row.label), axisLabel: { color: CHART_TEXT.color } },
    yAxis: [
      { type: 'value', name: '网格支持量', axisLabel: { color: CHART_TEXT.color } },
      { type: 'value', name: `峰值（${analysis.variable.unit}）`, axisLabel: { color: CHART_TEXT.color } },
    ],
    series: [
      { name: '网格支持量', type: 'bar', data: rows.map((row) => row.support_measure), itemStyle: { color: '#4d8de0' } },
      { name: '峰值', type: 'line', yAxisIndex: 1, data: rows.map((row) => row.value_max), itemStyle: { color: '#d9a84e' } },
    ],
  }
})

// ---------------------------------------------------------------------------
// 当前切片 / 模型 / 输入样本
// ---------------------------------------------------------------------------
const sliceStats = computed(() => props.currentSlice?.statistics ?? null)

const modelMetrics = computed(() => {
  const evidence = props.analysis?.model_evidence
  if (!evidence) return []
  const labels: Record<string, string> = { rmse: 'RMSE', mae: 'MAE', r2: 'R²', coverage: '覆盖率', bias: 'Bias' }
  return Object.entries(evidence.metrics)
    .filter(([key, value]) => key !== 'common_valid_count' && value !== null && Number.isFinite(value))
    .map(([key, value]) => ({ label: labels[key] ?? key, value: value as number }))
})

const inputQuality = computed(() => props.datasetSummary?.quality ?? null)
</script>

<template>
  <section class="grid-evidence" data-test="result-grid-evidence" aria-label="成果证据带">
    <header class="evidence-head">
      <div class="evidence-tabs" role="tablist">
        <button
          v-for="tab in TABS"
          :key="tab.id"
          type="button"
          role="tab"
          class="evidence-tab"
          :class="{ active: activeTab === tab.id }"
          :aria-selected="activeTab === tab.id ? 'true' : 'false'"
          :data-test="`ge-tab-${tab.id}`"
          @click="activeTab = tab.id"
        >
          {{ tab.label }}
        </button>
      </div>
      <span class="evidence-scope" data-test="ge-scope-badge">
        {{ TABS.find((t) => t.id === activeTab)?.scope }}
      </span>
    </header>

    <AsyncState
      v-if="!analysis"
      kind="nodata"
      title="暂无成果网格证据"
      impact="成果组成/深度/组件/切片统计不可用"
      next-action="成果物化并完成分析后自动展示"
      data-test="ge-empty"
    />

    <template v-else>
      <!-- 成果组成 -->
      <div v-if="activeTab === 'composition'" class="evidence-pane" data-test="ge-pane-composition">
        <p class="pane-note">低/正常/高值体元节点占比（完整成果网格 p25/p75 阈值，成果网格口径）</p>
        <EChartBox :option="compositionOption" data-test="ge-composition-chart" />
        <div class="bucket-strip">
          <span
            v-for="bucket in analysis.composition.buckets"
            :key="bucket.category"
            class="bucket-chip"
          >
            {{ BUCKET_LABELS[bucket.category] ?? bucket.category }}
            {{ bucket.count.toLocaleString() }}（{{ percent(bucket.ratio) }}）
          </span>
        </div>
      </div>

      <!-- 深度趋势 -->
      <div v-if="activeTab === 'depth'" class="evidence-pane" data-test="ge-pane-depth">
        <template v-if="depthApplicable">
          <p class="pane-note">Z 向等距层段的高值占比与均值（成果网格口径）</p>
          <EChartBox :option="depthOption" data-test="ge-depth-chart" />
          <table class="depth-table">
            <thead>
              <tr><th>层段（m）</th><th>有效体元</th><th>均值</th><th>高值占比</th><th /></tr>
            </thead>
            <tbody>
              <tr v-for="(bin, index) in analysis.depth_profile.bins" :key="index">
                <td>{{ bin.z_lower }}–{{ bin.z_upper }}</td>
                <td>{{ bin.valid_count.toLocaleString() }}</td>
                <td class="mono">{{ formatNumber(bin.mean) }}</td>
                <td class="mono">{{ percent(bin.high_ratio) }}</td>
                <td>
                  <button
                    type="button"
                    class="link-button"
                    :data-test="`ge-depth-bin-${index}`"
                    @click="emit('focus-depth-bin', index)"
                  >
                    定位切片
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </template>
        <p v-else class="pane-note">深度分层不适用（二维成果无 Z 向层段）</p>
      </div>

      <!-- 组件比较 -->
      <div v-if="activeTab === 'components'" class="evidence-pane" data-test="ge-pane-components">
        <template v-if="analysis.components_preview.rows.length > 0">
          <p class="pane-note">
            高值连通区
            {{ analysis.components_preview.rows[0].support_unit === 'volume_coordinate_unit3' ? '网格支持体积估计' : '网格支持面积估计' }}
            与峰值比较（同一响应，组件 ID 与三维标注一致）
          </p>
          <EChartBox :option="componentsOption" data-test="ge-components-chart" />
          <div class="bucket-strip">
            <button
              v-for="row in analysis.components_preview.rows"
              :key="row.component_id"
              type="button"
              class="bucket-chip as-button"
              :data-test="`ge-component-${row.component_id}`"
              @click="emit('focus-component', row.component_id)"
            >
              {{ row.label }} · 峰值 {{ formatNumber(row.value_max) }} · 支持量
              {{ formatNumber(row.support_measure) }}
            </button>
          </div>
        </template>
        <p v-else class="pane-note">当前阈值下无高值连通区</p>
      </div>

      <!-- 当前切片 -->
      <div v-if="activeTab === 'slice'" class="evidence-pane" data-test="ge-pane-slice">
        <p v-if="!currentSlice" class="pane-note">进入切片模式后显示当前切片证据</p>
        <template v-else>
          <p class="pane-note">
            {{ currentSlice.slice.fixed_axis.toUpperCase() }} =
            {{ formatNumber(currentSlice.slice.coordinate) }} · 有效
            {{ sliceStats?.valid_count ?? 0 }} / NoData {{ sliceStats?.nodata_count ?? 0 }} ·
            均值 {{ formatNumber(sliceStats?.mean) }}
            <template v-if="sliceStats?.thresholds">
              · 低 {{ percent(sliceStats.low_ratio) }} / 正常
              {{ percent(sliceStats.normal_ratio) }} / 高 {{ percent(sliceStats.high_ratio) }}
            </template>
          </p>
          <div class="slice-heatmap" data-test="ge-slice-heatmap">
            <SliceHeatmap :analysis="currentSlice" :palette="palette" :scale="scale" />
          </div>
        </template>
      </div>

      <!-- 模型与残差 -->
      <div v-if="activeTab === 'model'" class="evidence-pane" data-test="ge-pane-model">
        <p class="pane-note">
          算法 {{ analysis.model_evidence.algorithm }} · 交叉验证公共有效点
          {{ analysis.model_evidence.common_valid_count?.toLocaleString() ?? '—' }}（成果网格口径）
        </p>
        <div v-if="modelMetrics.length > 0" class="metric-strip">
          <div v-for="metric in modelMetrics" :key="metric.label" class="metric-cell">
            <span class="metric-label">{{ metric.label }}</span>
            <span class="metric-value mono">{{ formatNumber(metric.value) }}</span>
          </div>
        </div>
        <p v-if="!residuals || residuals.returned === 0" class="pane-note">暂无残差证据</p>
        <p v-else class="pane-note">残差证据 {{ residuals.returned }} 点（输入样本交叉验证口径）</p>
      </div>

      <!-- 输入样本 -->
      <div v-if="activeTab === 'input'" class="evidence-pane" data-test="ge-pane-input">
        <p class="pane-note">
          输入样本（插值前散点）质量与分布证据，与成果网格统计严格区分
        </p>
        <template v-if="inputQuality">
          <p class="pane-note">
            有效 {{ (inputQuality?.valid_count ?? 0).toLocaleString() }} / 共
            {{ (inputQuality?.row_count ?? 0).toLocaleString() }} 行，无效
            {{ (inputQuality?.invalid_count ?? 0).toLocaleString() }}，重复坐标
            {{ (inputQuality?.duplicate_coordinate_count ?? 0).toLocaleString() }}
          </p>
          <div class="input-quality">
            <QualityDonut
              :valid="inputQuality?.valid_count ?? 0"
              :invalid="inputQuality?.invalid_count ?? 0"
              :total="inputQuality?.row_count ?? 0"
            />
          </div>
        </template>
        <p v-else class="pane-note">输入样本质量报告不可用</p>
        <FindingPanel
          v-if="datasetFindings.length > 0"
          :findings="datasetFindings"
          @locate="emit('locate', $event)"
        />
      </div>

      <!-- 溯源 -->
      <div v-if="activeTab === 'provenance'" class="evidence-pane" data-test="ge-pane-provenance">
        <dl class="provenance-list">
          <div><dt>成果</dt><dd class="mono">{{ analysis.identity.result_id }}</dd></div>
          <div><dt>网格 SHA-256</dt><dd class="mono">{{ analysis.provenance.grid_sha256.slice(0, 16) }}…</dd></div>
          <div><dt>计算版本</dt><dd class="mono">{{ analysis.provenance.calculation_version }}</dd></div>
          <div><dt>阈值方法</dt><dd class="mono">{{ analysis.provenance.threshold_method }}</dd></div>
          <div><dt>连通规则</dt><dd class="mono">{{ analysis.components_preview.connectivity_rule }}</dd></div>
          <div><dt>坐标类型</dt><dd>{{ analysis.identity.coordinate_type }}（局部线性，非地理配准）</dd></div>
        </dl>
      </div>
    </template>
  </section>
</template>

<style scoped>
.grid-evidence {
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-1);
  min-width: 0;
}

.evidence-head {
  display: flex;
  align-items: center;
  gap: var(--s1-space-3);
  padding: var(--s1-space-2) var(--s1-space-3);
  border-bottom: 1px solid var(--s1-border-soft);
}

.evidence-tabs {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  flex: 1;
}

.evidence-tab {
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  padding: 4px 12px;
  cursor: pointer;
}

.evidence-tab:hover {
  color: var(--s1-cyan-strong);
}

.evidence-tab.active {
  color: var(--s1-cyan-strong);
  background: var(--s1-cyan-ghost);
  border-color: var(--s1-cyan-dim);
}

.evidence-scope {
  font-size: var(--s1-font-xs);
  color: var(--s1-cyan-strong);
  border: 1px solid var(--s1-cyan-dim);
  border-radius: 4px;
  padding: 2px 8px;
  white-space: nowrap;
}

.evidence-pane {
  padding: var(--s1-space-3);
  min-height: 120px;
}

.pane-note {
  margin: 0 0 var(--s1-space-2);
  font-size: var(--s1-font-sm);
  color: var(--s1-text-faint);
  line-height: var(--s1-leading);
}

.bucket-strip {
  display: flex;
  gap: var(--s1-space-2);
  flex-wrap: wrap;
}

.bucket-chip {
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
  border: 1px solid var(--s1-border-soft);
  border-radius: 6px;
  padding: 4px 10px;
}

.bucket-chip.as-button {
  background: transparent;
  cursor: pointer;
  color: var(--s1-text);
}

.bucket-chip.as-button:hover {
  border-color: var(--s1-cyan-dim);
  color: var(--s1-cyan-strong);
}

.depth-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: var(--s1-space-2);
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
}

.depth-table th,
.depth-table td {
  text-align: left;
  padding: 4px 8px;
  border-bottom: 1px solid var(--s1-border-soft);
}

.link-button {
  border: 1px solid var(--s1-cyan-dim);
  background: var(--s1-cyan-ghost);
  color: var(--s1-cyan-strong);
  border-radius: 6px;
  padding: 2px 10px;
  font-size: var(--s1-font-xs);
  cursor: pointer;
}

.slice-heatmap {
  border: 1px solid var(--s1-border-soft);
  border-radius: var(--s1-radius-sm);
  overflow: hidden;
}

.metric-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: var(--s1-space-2);
  margin-bottom: var(--s1-space-2);
}

.metric-cell {
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

.input-quality {
  max-width: 260px;
}

.provenance-list {
  margin: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--s1-space-2);
}

.provenance-list div {
  border: 1px solid var(--s1-border-soft);
  border-radius: var(--s1-radius-sm);
  padding: 6px 10px;
}

.provenance-list dt {
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
}

.provenance-list dd {
  margin: 2px 0 0;
  font-size: var(--s1-font-sm);
  color: var(--s1-text);
  word-break: break-all;
}

.mono {
  font-family: ui-monospace, monospace;
}
</style>
