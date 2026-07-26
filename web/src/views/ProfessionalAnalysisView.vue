<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
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
  ResultMetadata,
} from '../api/types'
import FoldInspector from '../components/professional/FoldInspector.vue'
import UncertaintyPanel from '../components/professional/UncertaintyPanel.vue'
import AnomalyPanel from '../components/professional/AnomalyPanel.vue'
import CandidateComparison from '../components/professional/CandidateComparison.vue'
import PageNavigation from '../components/navigation/PageNavigation.vue'

// 统一专业分析台：视图状态只保存选中候选 ID 与显示选项（§13.2），
// 所有证据都来自 API；任何开关只改变请求与渲染，绝不修改正式选择或结果指标。
const route = useRoute()
const routeResultId = computed(() => String(route.params.resultId ?? ''))

// 分析页状态机（判别联合）：加载 → 就绪 / legacy / 泄漏阻断 / 失败
type AnalysisPhase =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready' }
  | { kind: 'legacy'; reason: string }
  | { kind: 'leaked' }

const metadata = ref<ResultMetadata | null>(null)
const experiment = ref<ExperimentRecord | null>(null)
const candidates = ref<CandidateRecord[]>([])
const selectedResultId = ref<string>('')
const phase = ref<AnalysisPhase>({ kind: 'loading' })

const professional = ref<ProfessionalResultEvidence | null>(null)
const folds = ref<FoldEvidence | null>(null)
const residuals = ref<ResidualEvidence | null>(null)

function describeError(e: unknown): string {
  if (e instanceof ApiError) return `${e.code}：${e.message}`
  return e instanceof Error ? e.message : String(e)
}

// 只有成功候选进入切换器与比较面板（后端对非成功候选一律 409）
const candidateOptions = computed(() =>
  candidates.value.filter((candidate) => candidate.status === 'succeeded'),
)

const loadError = computed(() => (phase.value.kind === 'error' ? phase.value.message : null))
const legacy = computed(() => (phase.value.kind === 'legacy' ? phase.value : null))

// 切换候选：所有面板以同一新 result ID 重新请求（单候选联动）
async function loadCandidate(resultId: string) {
  selectedResultId.value = resultId
  phase.value = { kind: 'loading' }
  professional.value = null
  folds.value = null
  residuals.value = null
  try {
    const evidence = await fetchProfessionalResult(resultId)
    if (selectedResultId.value !== resultId) return // 竞态防护：旧候选响应一律丢弃
    professional.value = evidence
    if (!evidence.available) {
      // legacy 候选：明确披露原因，绝不伪造能力或指标
      phase.value = { kind: 'legacy', reason: evidence.reason ?? 'LEGACY_RESULT_NOT_COMPUTED' }
      return
    }
    const [foldEvidence, residualEvidence] = await Promise.all([
      fetchResultFolds(resultId),
      fetchResultResiduals(resultId),
    ])
    if (selectedResultId.value !== resultId) return
    folds.value = foldEvidence
    residuals.value = residualEvidence
    if (foldEvidence.leakage_detected) {
      // 泄漏失败阻断整个分析视图（失败态），面板一律不渲染
      phase.value = { kind: 'leaked' }
      return
    }
    phase.value = { kind: 'ready' }
  } catch (e) {
    if (selectedResultId.value !== resultId) return
    phase.value = { kind: 'error', message: describeError(e) }
  }
}

function selectCandidate(resultId: string) {
  if (resultId === selectedResultId.value) return
  void loadCandidate(resultId)
}

const provenance = computed(() => professional.value?.parameter_provenance ?? null)
const capabilities = computed(() => professional.value?.capabilities ?? null)

const capabilityEntries = computed(() => {
  const caps = capabilities.value
  if (!caps) return []
  return (Object.entries(caps) as Array<[string, string | Record<string, string> | undefined]>)
    .filter(([key, value]) => key !== 'notes' && typeof value === 'string')
    .map(([key, value]) => ({ key, state: value as string }))
})

onMounted(async () => {
  try {
    const meta = await fetchResult(routeResultId.value)
    metadata.value = meta
    const exp = await fetchExperiment(meta.experiment_id)
    experiment.value = exp
    try {
      const body = await fetchCandidates(exp.id)
      candidates.value = body.candidates
    } catch {
      candidates.value = [] // 候选列表失败不阻断当前成果的分析
    }
    await loadCandidate(routeResultId.value)
  } catch (e) {
    phase.value = { kind: 'error', message: describeError(e) }
  }
})
</script>

<template>
  <div class="analysis-page">
    <PageNavigation home :experiment-id="metadata?.experiment_id" />
    <header class="page-header">
      <h1>专业分析台</h1>
      <p class="page-sub">
        成果 <span class="mono" data-test="selected-candidate-id">{{ selectedResultId || routeResultId }}</span>
        <template v-if="metadata"> · {{ metadata.dimension === '3d' ? '三维' : '二维' }}</template>
      </p>
    </header>

    <el-result
      v-if="loadError"
      icon="error"
      title="专业证据加载失败"
      :sub-title="loadError"
      data-test="load-error"
    />
    <div v-else-if="phase.kind === 'loading'" v-loading="true" class="page-loading" data-test="page-loading" />

    <div v-else-if="legacy" class="legacy-blocked" data-test="legacy-unavailable">
      该成果没有专业证据（{{ legacy.reason }}）：只有 v0.6 专业建模流程产生的候选才提供
      折分、不确定性与比较证据；可返回成果工作台查看常规场与切片。
    </div>

    <div v-else-if="phase.kind === 'leaked'" class="leakage-blocked" data-test="leakage-blocked">
      折分泄漏检查失败：训练/验证空间组存在重叠，验证证据不可信。分析视图已阻断，
      请回到实验检查数据与验证配置后重新运行。
    </div>

    <main v-else class="analysis-main">
      <section class="candidate-switcher" data-test="candidate-switcher">
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
      <CandidateComparison :candidates="candidateOptions" :first-result-id="selectedResultId" />
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

.page-loading {
  min-height: 200px;
}

.legacy-blocked,
.leakage-blocked {
  border-radius: 10px;
  padding: 14px 16px;
  font-size: 13px;
  line-height: 1.6;
}

.legacy-blocked {
  border: 1px solid #9a7b2d;
  background: rgba(154, 123, 45, 0.12);
  color: #e5c76b;
}

.leakage-blocked {
  border: 1px solid #a43d3d;
  background: rgba(164, 61, 61, 0.12);
  color: #ef9a9a;
}

.analysis-main {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.candidate-switcher,
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

.summary-section h3 {
  margin: 0;
  font-size: 15px;
}

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
