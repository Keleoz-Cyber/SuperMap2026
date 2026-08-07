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

const capabilityEntries = computed(() => {
  const caps = capabilities.value
  if (!caps) return []
  return (Object.entries(caps) as Array<[string, string | Record<string, string> | undefined]>)
    .filter(([key, value]) => key !== 'notes' && typeof value === 'string')
    .map(([key, value]) => ({ key, state: value as string }))
})
</script>

<template>
  <div class="analysis-page">
    <PageNavigation home :experiment-id="metadata?.experiment_id" />
    <header class="page-header">
      <h1>模型评估</h1>
      <p class="page-sub">
        成果 <span class="mono" data-test="selected-candidate-id">{{ selectedResultId || routeResultId }}</span>
        <template v-if="metadata"> · {{ metadata.dimension === '3d' ? '三维' : '二维' }}</template>
      </p>
      <button
        type="button"
        class="back-link"
        data-test="back-to-workbench"
        @click="gotoResultWorkbench"
      >
        返回成果工作台
      </button>
    </header>

    <el-result
      v-if="loadError"
      icon="error"
      title="评估加载失败"
      :sub-title="loadError"
      data-test="load-error"
    >
      <template #extra>
        <button type="button" class="back-link" data-test="error-back-to-workbench" @click="gotoResultWorkbench">
          返回成果工作台
        </button>
      </template>
    </el-result>
    <div v-else-if="phase.kind === 'loading'" v-loading="true" class="page-loading" data-test="page-loading" />

    <main v-else class="analysis-main">
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
          <span class="mono">{{ candidate.id }}</span>
        </button>
      </section>

      <section v-if="baseline" class="baseline-section" data-test="baseline-metrics">
        <h3>基线评估</h3>
        <div class="metrics-grid">
          <span data-test="baseline-rmse">RMSE {{ fmtMetric(baseline.rmse) }}</span>
          <span data-test="baseline-mae">MAE {{ fmtMetric(baseline.mae) }}</span>
          <span data-test="baseline-r2">R² {{ fmtR2(baseline.r2) }}</span>
          <span data-test="baseline-bias">Bias {{ fmtMetric(baseline.bias) }}</span>
          <span v-if="baseline.coverage !== null" data-test="baseline-coverage">
            覆盖率 {{ fmtMetric(baseline.coverage) }}
          </span>
          <span v-if="baseline.candidate_valid_count !== null" data-test="baseline-valid-count">
            有效节点 {{ baseline.candidate_valid_count }}
          </span>
          <span v-if="baseline.candidate_nodata_count !== null" data-test="baseline-nodata-count">
            NoData 节点 {{ baseline.candidate_nodata_count }}
          </span>
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
            <span data-test="summary-algorithm">算法 {{ professional?.algorithm }}</span>
            <span data-test="summary-confirmation">
              确认 {{ professional?.confirmation_id ?? '无（非 Kriging 确认流程）' }}
            </span>
            <span
              v-for="entry in capabilityEntries"
              :key="entry.key"
              :data-test="`capability-${entry.key.replaceAll('_', '-')}`"
            >
              {{ entry.key }}: {{ entry.state }}
            </span>
          </div>
          <div v-if="provenance" class="provenance" data-test="param-provenance">
            <span data-test="param-origin-validation">
              验证参数来源 {{ provenance.validation.origin }}（{{ provenance.validation.scope }}）
            </span>
            <span data-test="param-origin-final">
              最终参数来源 {{ provenance.final.origin }}（{{ provenance.final.scope }}）
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
  max-width: 1080px;
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
