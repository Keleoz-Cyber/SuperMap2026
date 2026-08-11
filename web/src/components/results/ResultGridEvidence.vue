<script setup lang="ts">
// v0.9.0 V6 Task 3/4：成果证据窗（四个一级标签）。
//   综合分析 = 成果组成 + 深度趋势；切片与异常 = 当前切片 + 连通区；
//   模型证据 = 模型指标 + 残差；数据溯源 = 输入样本 + 成果/资产身份 + 导出。
// 七类证据全部保留，只归组；每个面板标注「成果网格」或「输入样本」口径；
// 组件只接收 DTO 不 fetch；ECharts 统一 dispose。
import { computed } from 'vue'
import type {
  AnalysisSummaryResponse,
  ResidualEvidence,
  ResultAnalysisSummary,
  SliceAnalysisResponse,
} from '../../api/types'
import type { PresentationFinding } from '../../domain/findings'
import { formatNumber } from '../analysis/analysisTypes'
import type { AnalysisSelection } from '../analysis/analysisTypes'
import { comparisonCandidatesOf, distributionBinsOf, profileAxesOf } from '../analysis/analysisTypes'
import type { RenderPaletteId, RenderScale } from '../rendering/renderTransferFunctions'
import SliceHeatmap from '../rendering/SliceHeatmap.vue'
import AsyncState from '../states/AsyncState.vue'
import FindingPanel from '../findings/FindingPanel.vue'
import QualityDonut from '../evidence/QualityDonut.vue'
import ModelMetricBars from '../evidence/ModelMetricBars.vue'
import AxisTrendChart from '../evidence/AxisTrendChart.vue'
import DistributionPanel from '../analysis/DistributionPanel.vue'
import ResidualEvidenceChart from '../evidence/ResidualEvidence.vue'
import EChartBox from './EChartBox.vue'
import { buildComponentOption, buildDepthTrendOption } from './resultChartOptions'

// 渲染资产身份（数据溯源展示；由 NativeVolumePanel 真实事件外发）
export interface RenderAssetIdentity {
  assetId: string
  renderer: string
  status: string
  gridSha256: string
  netcdfSha256: string | null
  geolocationStatus: string
}

const props = withDefaults(
  defineProps<{
    analysis: ResultAnalysisSummary | null
    currentSlice: SliceAnalysisResponse | null
    datasetSummary: AnalysisSummaryResponse | null
    datasetFindings?: PresentationFinding[]
    residuals?: ResidualEvidence | null
    resultId: string
    datasetId?: string | null
    assetIdentity?: RenderAssetIdentity | null
    palette?: RenderPaletteId
    scale?: RenderScale
  }>(),
  {
    datasetFindings: () => [],
    residuals: null,
    datasetId: null,
    assetIdentity: null,
    palette: 'viridis',
    scale: 'linear',
  },
)

const emit = defineEmits<{
  (e: 'focus-component', componentId: number): void
  (e: 'focus-depth-bin', index: number): void
  (e: 'locate', finding: PresentationFinding): void
  (e: 'select', selection: AnalysisSelection): void
  (e: 'select-result', resultId: string): void
}>()

export type EvidenceTab = 'overview' | 'slices' | 'model' | 'provenance'

const activeTab = defineModel<EvidenceTab>('activeTab', { default: 'overview' })

const TABS: Array<{ id: EvidenceTab; label: string; scope: string }> = [
  { id: 'overview', label: '综合分析', scope: '成果网格' },
  { id: 'slices', label: '切片与异常', scope: '成果网格' },
  { id: 'model', label: '模型证据', scope: '成果网格' },
  { id: 'provenance', label: '数据溯源', scope: '输入样本/成果身份' },
]

function percent(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return '—'
  return `${(ratio * 100).toFixed(1)}%`
}

const CHART_TEXT = { color: '#a7b8b0' }
const BUCKET_COLORS: Record<string, string> = { low: '#4d8de0', normal: '#8a9aa2', high: '#d9a84e' }
const BUCKET_LABELS: Record<string, string> = { low: '低值', normal: '正常', high: '高值' }

// 成果组成：环形图（可加总口径：体元节点占比）
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

// 深度趋势：层段高值占比柱 + 均值线
const depthApplicable = computed(
  () => props.analysis?.depth_profile.status === 'applicable' && (props.analysis?.depth_profile.bins.length ?? 0) > 0,
)

const depthOption = computed(() => {
  const analysis = props.analysis
  if (!analysis) return {}
  return buildDepthTrendOption(analysis.depth_profile.bins, analysis.variable.unit)
})

// 组件比较：网格支持量柱 + 峰值线
const componentsOption = computed(() => {
  const analysis = props.analysis
  if (!analysis) return {}
  return buildComponentOption(analysis.components_preview.rows, analysis.variable.unit)
})

const sliceStats = computed(() => props.currentSlice?.statistics ?? null)

const modelMetrics = computed(() => {
  const evidence = props.analysis?.model_evidence
  if (!evidence) return []
  const labels: Record<string, string> = { rmse: 'RMSE', mae: 'MAE', r2: 'R²', coverage: '覆盖率', bias: 'Bias' }
  return Object.entries(evidence.metrics)
    .filter(([key, value]) => key !== 'common_valid_count' && value !== null && Number.isFinite(value))
    .map(([key, value]) => ({ label: labels[key] ?? key, value: value as number }))
})

// 输入样本模块（数据集级，明确标注为插值前散点证据）
const inputQuality = computed(() => props.datasetSummary?.quality ?? null)

function moduleOf(id: string) {
  return props.datasetSummary?.modules.find((m) => m.module_id === id) ?? null
}

const inputDistribution = computed(() => {
  const m = moduleOf('distribution')
  return m !== null && m.status === 'ok' && distributionBinsOf(m).length > 0 ? m : null
})

const inputTrendAxes = computed(() => {
  const m = moduleOf('profile_slices')
  if (!m || m.status !== 'ok') return []
  return profileAxesOf(m).filter((a) => a.bins.length > 0)
})

const inputModelCandidates = computed(() => comparisonCandidatesOf(moduleOf('model_comparison')))
const hasResiduals = computed(() => (props.residuals?.returned ?? 0) > 0)
</script>

<template>
  <section class="grid-evidence" data-test="result-grid-evidence" aria-label="成果证据窗">
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
      v-if="!analysis && activeTab !== 'provenance'"
      kind="nodata"
      title="暂无成果网格证据"
      impact="成果组成/深度/组件/切片统计不可用"
      next-action="成果物化并完成分析后自动展示"
      data-test="ge-empty"
    />

    <!-- 数据溯源：资产身份/导出/输入样本不依赖成果分析（分析缺失时仍可用） -->
    <div
      v-if="activeTab === 'provenance'"
      key="provenance"
      class="evidence-pane grouped layout-provenance"
      :class="{ 'no-asset': !assetIdentity }"
      data-test="ge-pane-provenance"
    >
      <section class="evidence-cell input-summary-card" data-test="ge-input-summary">
        <h4 class="cell-title">输入样本 <span class="scope-tag">输入样本</span></h4>
        <template v-if="inputQuality">
          <div class="input-quality-summary">
            <p class="pane-note">
              有效 {{ (inputQuality?.valid_count ?? 0).toLocaleString() }} / 共
              {{ (inputQuality?.row_count ?? 0).toLocaleString() }} 行<br />
              无效 {{ (inputQuality?.invalid_count ?? 0).toLocaleString() }} · 重复坐标
              {{ (inputQuality?.duplicate_coordinate_count ?? 0).toLocaleString() }}
            </p>
            <div class="input-quality">
              <QualityDonut
                :valid="inputQuality?.valid_count ?? 0"
                :invalid="inputQuality?.invalid_count ?? 0"
                :total="inputQuality?.row_count ?? 0"
              />
            </div>
          </div>
        </template>
        <p v-else class="pane-note">输入样本质量报告不可用</p>
        <details
          v-if="datasetFindings.length > 0 || inputDistribution || inputTrendAxes.length > 0"
          class="input-details"
          data-test="ge-input-details"
        >
          <summary>查看输入样本详细分析</summary>
          <div class="input-details-body">
            <FindingPanel
              v-if="datasetFindings.length > 0"
              :findings="datasetFindings"
              @locate="emit('locate', $event)"
            />
            <DistributionPanel
              v-if="inputDistribution && datasetSummary"
              :module="inputDistribution"
              :variable="datasetSummary.variable"
              :profile="datasetSummary.analysis_profile"
            />
            <AxisTrendChart
              v-if="inputTrendAxes.length > 0 && datasetId"
              :axes="inputTrendAxes"
              :unit="datasetSummary?.variable.unit ?? null"
              :dataset-id="datasetId"
              :result-id="resultId"
              @select="emit('select', $event)"
            />
          </div>
        </details>
      </section>
      <section v-if="analysis" class="evidence-cell result-identity-card">
        <h4 class="cell-title">成果身份 <span class="scope-tag">成果网格</span></h4>
        <dl class="provenance-list">
          <div><dt>成果</dt><dd class="mono">{{ analysis.identity.result_id }}</dd></div>
          <div><dt>网格 SHA-256</dt><dd class="mono">{{ analysis.provenance.grid_sha256.slice(0, 16) }}…</dd></div>
          <div><dt>计算版本</dt><dd class="mono">{{ analysis.provenance.calculation_version }}</dd></div>
          <div><dt>阈值方法</dt><dd class="mono">{{ analysis.provenance.threshold_method }}</dd></div>
          <div><dt>连通规则</dt><dd class="mono">{{ analysis.components_preview.connectivity_rule }}</dd></div>
          <div><dt>坐标类型</dt><dd>{{ analysis.identity.coordinate_type }}（局部线性，非地理配准）</dd></div>
        </dl>
      </section>
      <section v-if="assetIdentity" class="evidence-cell asset-identity-card" data-test="ge-asset-identity">
        <h4 class="cell-title">渲染资产 <span class="scope-tag">成果网格</span></h4>
        <dl class="provenance-list">
          <div><dt>资产</dt><dd class="mono">{{ assetIdentity.assetId }}</dd></div>
          <div><dt>渲染器/状态</dt><dd class="mono">{{ assetIdentity.renderer }} / {{ assetIdentity.status }}</dd></div>
          <div><dt>网格 SHA-256</dt><dd class="mono">{{ assetIdentity.gridSha256.slice(0, 16) }}…</dd></div>
          <div v-if="assetIdentity.netcdfSha256">
            <dt>NetCDF SHA-256</dt>
            <dd class="mono">{{ assetIdentity.netcdfSha256.slice(0, 16) }}…</dd>
          </div>
          <div><dt>坐标契约</dt><dd>{{ assetIdentity.geolocationStatus }}</dd></div>
        </dl>
      </section>
      <section class="evidence-cell export-card">
        <h4 class="cell-title">导出与发布</h4>
        <slot name="provenance-actions" />
      </section>
    </div>

    <template v-else-if="analysis">
      <!-- 综合分析：成果组成 + 深度趋势 -->
      <div
        v-if="activeTab === 'overview'"
        key="overview"
        class="evidence-pane grouped layout-overview"
        data-test="ge-pane-overview"
      >
        <section class="evidence-cell">
          <h4 class="cell-title">成果组成 <span class="scope-tag">成果网格</span></h4>
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
        </section>
        <section class="evidence-cell">
          <h4 class="cell-title">深度趋势 <span class="scope-tag">成果网格</span></h4>
          <template v-if="depthApplicable">
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
        </section>
      </div>

      <!-- 切片与异常：当前切片 + 高值连通区 -->
      <div
        v-if="activeTab === 'slices'"
        key="slices"
        class="evidence-pane grouped layout-slices"
        :class="{ 'no-current-slice': !currentSlice }"
        data-test="ge-pane-slices"
      >
        <section class="evidence-cell">
          <h4 class="cell-title">当前切片 <span class="scope-tag">成果网格</span></h4>
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
        </section>
        <section class="evidence-cell">
          <h4 class="cell-title">高值连通区 <span class="scope-tag">成果网格</span></h4>
          <template v-if="analysis.components_preview.rows.length > 0">
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
                {{ row.label }} · 峰值 {{ formatNumber(row.value_max) }} ·
                {{ row.support_unit === 'volume_coordinate_unit3' ? '网格支持体积估计' : '网格支持面积估计' }}
                {{ formatNumber(row.support_measure) }}
              </button>
            </div>
          </template>
          <p v-else class="pane-note">当前阈值下无高值连通区</p>
        </section>
      </div>

      <!-- 模型证据：候选指标 + 残差 -->
      <div
        v-if="activeTab === 'model'"
        key="model"
        class="evidence-pane grouped layout-model"
        data-test="ge-pane-model"
      >
        <section class="evidence-cell">
          <h4 class="cell-title">模型指标 <span class="scope-tag">成果网格</span></h4>
          <p class="pane-note">
            算法 {{ analysis.model_evidence.algorithm }} · 交叉验证公共有效点
            {{ analysis.model_evidence.common_valid_count?.toLocaleString() ?? '—' }}
          </p>
          <div v-if="modelMetrics.length > 0" class="metric-strip">
            <div v-for="metric in modelMetrics" :key="metric.label" class="metric-cell">
              <span class="metric-label">{{ metric.label }}</span>
              <span class="metric-value mono">{{ formatNumber(metric.value) }}</span>
            </div>
          </div>
          <ModelMetricBars
            v-if="inputModelCandidates.length > 0"
            :candidates="inputModelCandidates"
            :unit="datasetSummary?.variable.unit ?? null"
            @select="emit('select-result', $event)"
          />
        </section>
        <section class="evidence-cell">
          <h4 class="cell-title">残差 <span class="scope-tag">输入样本</span></h4>
          <p v-if="!hasResiduals" class="pane-note">暂无残差证据</p>
          <ResidualEvidenceChart
            v-else
            :evidence="residuals ?? null"
            :unit="datasetSummary?.variable.unit ?? null"
          />
        </section>
      </div>

    </template>
  </section>
</template>

<style scoped>
.grid-evidence {
  border-top: 1px solid var(--s1-border);
  background: var(--s1-surface-1);
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.evidence-head {
  display: flex;
  align-items: center;
  gap: var(--s1-space-3);
  padding: var(--s1-space-1, 4px) var(--s1-space-3);
  border-bottom: 1px solid var(--s1-border-soft);
  flex: none;
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
  padding: var(--s1-space-2) var(--s1-space-3);
  overflow: auto;
  min-height: 0;
  flex: 1;
  overscroll-behavior: contain;
}

.evidence-pane.grouped {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: var(--s1-space-3);
  align-items: start;
  align-content: start;
  grid-auto-rows: min-content;
}

.evidence-cell {
  min-width: 0;
  border: 1px solid var(--s1-border-soft);
  border-radius: var(--s1-radius-md);
  background: linear-gradient(145deg, rgba(83, 215, 184, 0.035), rgba(5, 18, 14, 0.2));
  padding: var(--s1-space-2) var(--s1-space-3);
  overflow: hidden;
}

.layout-overview > :first-child {
  grid-column: span 4;
}

.layout-overview > :last-child {
  grid-column: span 8;
}

.layout-slices > :first-child {
  grid-column: span 5;
}

.layout-slices > :last-child {
  grid-column: span 7;
}

.layout-slices.no-current-slice > :first-child {
  grid-column: span 3;
}

.layout-slices.no-current-slice > :last-child {
  grid-column: span 9;
}

.layout-model > .evidence-cell {
  grid-column: span 6;
}

.layout-provenance .input-summary-card {
  grid-column: span 3;
}

.layout-provenance .result-identity-card {
  grid-column: span 3;
}

.layout-provenance .asset-identity-card {
  grid-column: span 3;
}

.layout-provenance .export-card {
  grid-column: span 3;
}

.layout-provenance.no-asset .export-card {
  grid-column: span 6;
}

.cell-title {
  margin: 0 0 6px;
  font-size: var(--s1-font-xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--s1-text-dim);
  display: flex;
  align-items: center;
  gap: 8px;
}

.scope-tag {
  font-size: var(--s1-font-xs);
  color: var(--s1-cyan-strong);
  border: 1px solid var(--s1-cyan-dim);
  border-radius: 4px;
  padding: 0 5px;
  font-weight: 400;
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
  padding: 3px 10px;
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
  padding: 3px 8px;
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
  grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
  gap: var(--s1-space-2);
  margin-bottom: var(--s1-space-2);
}

.metric-cell {
  border: 1px solid var(--s1-border-soft);
  border-radius: var(--s1-radius-sm);
  padding: 5px 10px;
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
  width: min(180px, 46%);
  flex: none;
}

.input-quality-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s1-space-2);
}

.input-quality-summary .pane-note {
  margin: 0;
}

.input-details {
  margin-top: var(--s1-space-2);
  border-top: 1px solid var(--s1-border-soft);
  padding-top: var(--s1-space-2);
}

.input-details summary {
  color: var(--s1-cyan-strong);
  font-size: var(--s1-font-sm);
  cursor: pointer;
  user-select: none;
}

.input-details-body {
  display: grid;
  gap: var(--s1-space-3);
  margin-top: var(--s1-space-3);
}

.provenance-list {
  margin: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--s1-space-2);
}

.provenance-list div {
  border: 1px solid var(--s1-border-soft);
  border-radius: var(--s1-radius-sm);
  padding: 5px 10px;
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

.layout-overview :deep(.echart-box),
.layout-slices :deep(.echart-box) {
  height: 160px;
}

@media (max-width: 1199px) {
  .evidence-pane.grouped {
    grid-template-columns: 1fr;
  }

  .evidence-pane.grouped > .evidence-cell {
    grid-column: 1;
  }
}
</style>
