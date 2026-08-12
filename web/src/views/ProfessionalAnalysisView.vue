<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ApiError,
  fetchCandidates,
  fetchExperiment,
  fetchProfessionalResult,
  fetchResult,
  fetchResultFolds,
  fetchResultResiduals,
} from '../api/client'
import type {
  CandidateRecord,
  ExperimentRecord,
  FoldEvidence,
  ProfessionalResultEvidence,
  ResidualEvidence,
  ResultEvaluationSummary,
  ResultMetadata,
} from '../api/types'
import FoldInspector from '../components/professional/FoldInspector.vue'
import UncertaintyPanel from '../components/professional/UncertaintyPanel.vue'
import AnomalyPanel from '../components/professional/AnomalyPanel.vue'
import CandidateComparison from '../components/professional/CandidateComparison.vue'
import PageNavigation from '../components/navigation/PageNavigation.vue'
import { algorithmLabel } from '../utils/modelingLabels'

const route = useRoute()
const router = useRouter()
const routeResultId = computed(() => String(route.params.resultId ?? ''))
const compareWithQuery = computed(() => {
  const q = route.query.compareWith
  return typeof q === 'string' ? q : ''
})

type AnalysisPhase =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready' }

const metadata = ref<ResultMetadata | null>(null)
const experiment = ref<ExperimentRecord | null>(null)
const candidates = ref<CandidateRecord[]>([])
const selectedResultId = ref<string>('')
const phase = ref<AnalysisPhase>({ kind: 'loading' })
const leakageDetected = ref(false)

const professional = ref<ProfessionalResultEvidence | null>(null)
const folds = ref<FoldEvidence | null>(null)
const residuals = ref<ResidualEvidence | null>(null)

function describeError(e: unknown): string {
  if (e instanceof ApiError) return `${e.code}：${e.message}`
  return e instanceof Error ? e.message : String(e)
}

const candidateOptions = computed(() =>
  candidates.value.filter((candidate) => candidate.status === 'succeeded'),
)

const loadError = computed(() => (phase.value.kind === 'error' ? phase.value.message : null))

const baseline = computed<ResultEvaluationSummary | null>(
  () => metadata.value?.evaluation_summary ?? null,
)

const enhancedAvailable = computed(
  () => metadata.value?.evaluation_summary?.enhanced_evidence_available === true,
)

const showEnhanced = computed(
  () =>
    enhancedAvailable.value &&
    !leakageDetected.value &&
    professional.value?.available === true,
)

const evaluationConclusion = computed(() => {
  if (leakageDetected.value) {
    return {
      title: '基线指标可读，但增强证据已被泄漏检查阻断',
      body: '训练与验证空间组存在重叠，逐折、残差和不确定性证据不应继续用于决策。',
      tone: 'warning',
    }
  }
  if (showEnhanced.value) {
    return {
      title: '增强评估证据可用',
      body: '基线指标、逐折验证、残差与不确定性证据已登记，且未检测到空间折分泄漏。',
      tone: 'success',
    }
  }
  return {
    title: '基线指标已生成',
    body: '可查看总体误差、拟合度与覆盖率；逐折与残差证据未生成，当前结论仅限基线评估。',
    tone: 'info',
  }
})

function gotoComparison() {
  const datasetId = metadata.value?.dataset_version_id
  if (!datasetId) return
  void router.push({
    name: 'candidate-comparison',
    params: { datasetId },
    query: { case: experiment.value?.case_id ?? undefined },
  })
}

function printEvaluation() {
  window.print()
}

function fmtMetric(value: number | null, digits = 4): string {
  return value === null ? '-' : value.toFixed(digits)
}

function fmtR2(value: number | null): string {
  return value === null ? '不可计算' : value.toFixed(4)
}

let loadSequence = 0

async function loadCandidate(resultId: string) {
  const sequence = ++loadSequence
  const targetId = resultId
  selectedResultId.value = targetId
  phase.value = { kind: 'loading' }
  leakageDetected.value = false
  professional.value = null
  folds.value = null
  residuals.value = null

  const current = () => sequence === loadSequence && selectedResultId.value === targetId

  try {
    const meta = await fetchResult(targetId)
    if (!current()) return
    metadata.value = meta

    if (!meta.evaluation_summary) {
      phase.value = {
        kind: 'error',
        message: 'EVALUATION_UNAVAILABLE：该成果未携带基线评估摘要',
      }
      return
    }

    const exp = await fetchExperiment(meta.experiment_id)
    if (!current()) return
    experiment.value = exp

    try {
      const body = await fetchCandidates(exp.id)
      if (!current()) return
      candidates.value = body.candidates
    } catch {
      if (!current()) return
      candidates.value = []
    }

    if (!meta.evaluation_summary.enhanced_evidence_available) {
      if (!current()) return
      phase.value = { kind: 'ready' }
      return
    }

    const evidence = await fetchProfessionalResult(targetId)
    if (!current()) return
    professional.value = evidence

    if (!evidence.available) {
      if (!current()) return
      phase.value = { kind: 'ready' }
      return
    }

    const [foldEvidence, residualEvidence] = await Promise.all([
      fetchResultFolds(targetId),
      fetchResultResiduals(targetId),
    ])
    if (!current()) return
    folds.value = foldEvidence
    residuals.value = residualEvidence

    if (foldEvidence.leakage_detected) {
      leakageDetected.value = true
      phase.value = { kind: 'ready' }
      return
    }

    phase.value = { kind: 'ready' }
  } catch (e) {
    if (!current()) return
    phase.value = { kind: 'error', message: describeError(e) }
  }
}

function selectCandidate(resultId: string) {
  if (resultId === selectedResultId.value) return
  void loadCandidate(resultId)
}

function gotoResultWorkbench() {
  void router.push({
    name: 'result-workbench',
    params: { resultId: selectedResultId.value || routeResultId.value },
  })
}

const routeIdentity = computed(
  () => `${routeResultId.value}\u0000${compareWithQuery.value}`,
)

watch(
  routeIdentity,
  () => {
    void loadCandidate(routeResultId.value)
  },
  { immediate: true },
)

const provenance = computed(() => professional.value?.parameter_provenance ?? null)
const capabilities = computed(() => professional.value?.capabilities ?? null)

const CAPABILITY_LABELS: Record<string, string> = {
  algorithm: '评估算法',
  empirical_variogram: '经验变异函数',
  model_anisotropy: '空间各向异性',
  empirical_error_scale: '经验误差尺度',
  native_kriging_std: '克里金标准差',
  anomaly_extraction: '异常区域提取',
  candidate_comparison: '候选成果比较',
}

const CAPABILITY_STATE_LABELS: Record<string, string> = {
  supported: '可用',
  not_applicable: '不适用',
  unavailable: '未生成',
  unsupported: '不可用',
}

const capabilityEntries = computed(() => {
  const caps = capabilities.value
  if (!caps) return []
  return (Object.entries(caps) as Array<[string, string | Record<string, string> | undefined]>)
    .filter(([key, value]) => key !== 'notes' && typeof value === 'string')
    .map(([key, value]) => ({
      key,
      state: value as string,
      label: CAPABILITY_LABELS[key] ?? '其他能力',
      stateLabel: CAPABILITY_STATE_LABELS[value as string] ?? '状态未知',
    }))
})

const ORIGIN_LABELS: Record<string, string> = {
  automatic_candidate: '交叉验证候选',
  fold_training_subsets: '各折训练数据',
  final_full_data_fit: '全量有效数据拟合',
}

function originLabel(value: string): string {
  return ORIGIN_LABELS[value] ?? '已登记计算流程'
}
</script>

<template>
  <div class="analysis-page product-page">
    <PageNavigation
      :case-id="experiment?.case_id"
      :experiment-id="metadata?.experiment_id"
      :result-id="selectedResultId || routeResultId"
      current-label="模型评估"
    />
    <header class="page-header">
      <h1>模型评估</h1>
      <p class="page-sub">
        <template v-if="metadata">{{ metadata.dimension === '3d' ? '三维' : '二维' }}成果 · 只读评估</template>
      </p>
      <details class="page-technical">
        <summary>技术详情</summary>
        <span class="mono" data-test="selected-candidate-id">成果 {{ selectedResultId || routeResultId }}</span>
      </details>
    </header>

    <el-result
      v-if="loadError"
      icon="error"
      title="评估加载失败"
      :sub-title="loadError"
      data-test="load-error"
      role="alert"
    >
      <template #extra>
        <button type="button" class="back-link" data-test="error-back-to-workbench" @click="gotoResultWorkbench">
          返回成果工作台
        </button>
      </template>
    </el-result>
    <div v-else-if="phase.kind === 'loading'" v-loading="true" class="page-loading" data-test="page-loading" />

    <main v-else class="analysis-main">
      <section
        class="evaluation-conclusion"
        :data-tone="evaluationConclusion.tone"
        data-test="evaluation-conclusion"
      >
        <div>
          <span class="section-kicker">评估结论</span>
          <h2>{{ evaluationConclusion.title }}</h2>
          <p>{{ evaluationConclusion.body }}</p>
        </div>
        <div class="evaluation-actions" data-test="evaluation-next-actions">
          <button type="button" class="gmp-btn primary" data-test="back-to-workbench" @click="gotoResultWorkbench">返回三维成果</button>
          <button type="button" class="gmp-btn" data-test="evaluation-compare" @click="gotoComparison">比较候选</button>
          <button type="button" class="gmp-btn" data-test="evaluation-export" @click="printEvaluation">导出 / 打印</button>
        </div>
      </section>

      <section v-if="candidateOptions.length > 1" class="candidate-switcher" data-test="candidate-switcher">
        <span class="switcher-label">候选（同一实验，仅成功候选）：</span>
        <button
          v-for="candidate in candidateOptions"
          :key="candidate.id"
          class="candidate-option"
          :class="{ active: candidate.id === selectedResultId }"
          :data-test="`candidate-option-${candidate.id}`"
          @click="selectCandidate(candidate.id)"
        >
          <span>候选 {{ candidateOptions.indexOf(candidate) + 1 }}</span>
          <small>RMSE {{ fmtMetric(candidate.metrics.rmse ?? null) }}</small>
        </button>
      </section>

      <section v-if="baseline" class="baseline-section" data-test="baseline-metrics">
        <h2>总体指标</h2>
        <div class="metrics-grid">
          <article data-test="baseline-rmse"><span>RMSE</span><strong>{{ fmtMetric(baseline.rmse) }}</strong><p>RMSE 反映典型误差尺度，适合在同一验证口径下比较候选。</p></article>
          <article data-test="baseline-mae"><span>MAE</span><strong>{{ fmtMetric(baseline.mae) }}</strong><p>MAE 表示平均绝对偏差，对少量极端误差相对不敏感。</p></article>
          <article data-test="baseline-r2"><span>R²</span><strong>{{ fmtR2(baseline.r2) }}</strong><p>{{ baseline.r2 === null ? 'R² 当前不可计算，不能据此评价解释度。' : 'R² 描述验证值变化被模型解释的比例，不等同于空间真实性。' }}</p></article>
          <article data-test="baseline-bias"><span>Bias</span><strong>{{ fmtMetric(baseline.bias) }}</strong><p>Bias 用于判断整体高估或低估方向，接近零不代表局部无误差。</p></article>
          <article v-if="baseline.coverage !== null" data-test="baseline-coverage"><span>覆盖率</span><strong>{{ fmtMetric(baseline.coverage) }}</strong><p>验证公共集上获得有限预测的比例。</p></article>
          <article v-if="baseline.candidate_valid_count !== null" data-test="baseline-valid-count"><span>有效节点</span><strong>{{ baseline.candidate_valid_count }}</strong><p>本候选参与总体指标计算的有效预测数量。</p></article>
          <article v-if="baseline.candidate_nodata_count !== null" data-test="baseline-nodata-count"><span>NoData 节点</span><strong>{{ baseline.candidate_nodata_count }}</strong><p>未形成有限预测的验证节点，需要结合覆盖率阅读。</p></article>
        </div>
      </section>

      <div v-if="leakageDetected" class="leakage-blocked" data-test="leakage-blocked">
        折分泄漏检查失败：训练/验证空间组存在重叠，增强证据不可信。
        基线评估仍可参考，请回到实验检查数据与验证配置后重新运行。
      </div>

      <div
        v-if="!showEnhanced && !leakageDetected"
        class="baseline-only-note"
        data-test="baseline-only-note"
      >
        基础评估可用；本结果未生成增强证据
      </div>

      <template v-if="showEnhanced">
        <section class="summary-section" data-test="professional-summary">
          <h3>结构诊断摘要</h3>
          <div class="summary-grid">
            <span data-test="summary-algorithm">算法 {{ professional ? algorithmLabel(professional.algorithm) : '-' }}</span>
            <span data-test="summary-confirmation">
              {{ professional?.confirmation_id ? '已采用空间结构建议' : '无需空间结构确认' }}
            </span>
            <span
              v-for="entry in capabilityEntries"
              :key="entry.key"
              :data-test="`capability-${entry.key.replaceAll('_', '-')}`"
            >
              {{ entry.label }}：{{ entry.stateLabel }}
            </span>
          </div>
          <details class="professional-technical" data-test="professional-technical-details">
            <summary>技术详情</summary>
            <p class="mono">algorithm: {{ professional?.algorithm }}</p>
            <p class="mono">confirmation_id: {{ professional?.confirmation_id ?? 'null' }}</p>
            <p v-for="entry in capabilityEntries" :key="`technical-${entry.key}`" class="mono">
              {{ entry.key }}: {{ entry.state }}
            </p>
            <template v-if="provenance">
              <p class="mono">validation.origin: {{ provenance.validation.origin }}</p>
              <p class="mono">validation.scope: {{ provenance.validation.scope }}</p>
              <p class="mono">final.origin: {{ provenance.final.origin }}</p>
              <p class="mono">final.scope: {{ provenance.final.scope }}</p>
            </template>
          </details>
          <div v-if="provenance" class="provenance" data-test="param-provenance">
            <span data-test="param-origin-validation">
              验证参数来源：{{ originLabel(provenance.validation.origin) }}
            </span>
            <span data-test="param-origin-final">
              最终参数来源：{{ originLabel(provenance.final.origin) }}
            </span>
            <span v-if="provenance.final.variogram" data-test="param-variogram">
              最终变异函数 {{ provenance.final.variogram.model }}
            </span>
          </div>
        </section>

        <FoldInspector v-if="folds" :folds="folds" :residuals="residuals" />
        <UncertaintyPanel :result-id="selectedResultId" :capabilities="capabilities" />
        <AnomalyPanel :result-id="selectedResultId" :capabilities="capabilities" />
      </template>

      <CandidateComparison
        v-if="showEnhanced || compareWithQuery"
        :candidates="candidateOptions"
        :first-result-id="selectedResultId"
        :initial-second-result-id="compareWithQuery || undefined"
      />
    </main>
  </div>
</template>

<style scoped>
.analysis-page {
  min-height: 100%;
  max-width: var(--s1-page-standard);
  margin: 0 auto;
  padding: 28px 20px 48px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header h1 {
  margin: 0;
  font-size: 20px;
}

.page-sub {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.page-technical {
  margin-top: 6px;
  color: var(--gmp-text-faint);
  font-size: 12px;
}

.page-technical summary {
  cursor: pointer;
}

.mono {
  font-family: ui-monospace, monospace;
}

.back-link {
  margin-top: 8px;
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text);
  border-radius: 8px;
  padding: 6px 14px;
  font-size: 12px;
  cursor: pointer;
  align-self: flex-start;
}

.back-link:hover {
  border-color: var(--gmp-accent);
}

.page-loading {
  min-height: 200px;
}

.leakage-blocked {
  border: 1px solid #a43d3d;
  background: rgba(164, 61, 61, 0.12);
  color: #ef9a9a;
  border-radius: 10px;
  padding: 14px 16px;
  font-size: 13px;
  line-height: 1.6;
}

.baseline-only-note {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text-dim);
  border-radius: 10px;
  padding: 12px 16px;
  font-size: 13px;
}

.analysis-main {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.evaluation-conclusion {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--s1-space-6);
  padding: var(--s1-space-5) 0;
  border-block: 1px solid var(--s1-border);
}

.section-kicker {
  color: var(--s1-cyan-strong);
  font-size: var(--s1-font-xs);
  font-weight: 600;
}

.evaluation-conclusion h2 {
  margin: 6px 0;
  font-size: var(--s1-font-xl);
}

.evaluation-conclusion p {
  margin: 0;
  color: var(--s1-text-dim);
  line-height: var(--s1-leading);
}

.evaluation-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s1-space-2);
  flex: 0 0 auto;
}

.candidate-switcher,
.baseline-section,
.summary-section {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.candidate-switcher {
  flex-direction: row;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.switcher-label {
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.candidate-option {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text-dim);
  border-radius: 8px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
}

.candidate-option.active {
  background: var(--gmp-accent);
  border-color: var(--gmp-accent);
  color: #0b0f14;
  font-weight: 600;
}

.baseline-section h3,
.summary-section h3 {
  margin: 0;
  font-size: 15px;
}

.metrics-grid,
.summary-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.baseline-section .metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  background: var(--s1-border);
  border: 1px solid var(--s1-border);
}

.baseline-section .metrics-grid article {
  min-width: 0;
  padding: var(--s1-space-4);
  background: var(--s1-surface-2);
}

.baseline-section .metrics-grid article > span {
  color: var(--s1-text-faint);
}

.baseline-section .metrics-grid strong {
  display: block;
  margin: 6px 0;
  color: var(--s1-text-strong);
  font-size: var(--s1-font-xl);
}

.baseline-section .metrics-grid p {
  margin: 0;
  color: var(--s1-text-dim);
  line-height: 1.5;
}

@media (max-width: 760px) {
  .evaluation-conclusion {
    align-items: flex-start;
    flex-direction: column;
  }

  .baseline-section .metrics-grid {
    grid-template-columns: 1fr 1fr;
  }
}

@media print {
  .page-nav,
  .evaluation-actions,
  .candidate-switcher {
    display: none !important;
  }
}

.provenance {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  font-size: 12px;
  color: var(--gmp-text-faint);
  border-top: 1px dashed var(--gmp-border);
  padding-top: 10px;
}
</style>
