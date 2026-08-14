<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, compareCandidates, fetchComparisonCandidates, fetchResult } from '../api/client'
import type {
  CandidateCatalog,
  ComparisonCandidateSummary,
  MultiCandidateComparison,
} from '../api/types'
import { algorithmLabel, parameterLabel, parameterSummary } from '../utils/modelingLabels'
import PageContextHeader from '../components/navigation/PageContextHeader.vue'
import AsyncState from '../components/states/AsyncState.vue'
import MetricComparisonChart from '../components/comparison/MetricComparisonChart.vue'
import ParameterDiffTable from '../components/comparison/ParameterDiffTable.vue'

const route = useRoute()
const router = useRouter()
const datasetId = computed(() => String(route.params.datasetId ?? ''))
const queryCaseId = computed(() => {
  const q = route.query.case
  return typeof q === 'string' ? q : ''
})

const MIN_SELECTION = 2
const MAX_SELECTION = 4

const MISMATCH_LABELS: Record<string, string> = {
  validation_contract: '验证规则不同',
  grid_resolution: '成果网格规格不同',
  common_valid_count_mismatch: '公共有效样本数量不同',
  validation_holdout_fraction_mismatch: '验证集比例不同',
  split_fingerprint_mismatch: '验证分组不同',
  common_valid_fingerprint_mismatch: '公共有效样本范围不同',
  value_unit_mismatch: '属性单位不同',
  dataset_version_mismatch: '数据版本不同',
}

const loading = ref(true)
const loadError = ref<string | null>(null)
const catalog = ref<CandidateCatalog | null>(null)
const selectedIds = ref<Set<string>>(new Set())
const comparison = ref<MultiCandidateComparison | null>(null)
const comparing = ref(false)
const compareError = ref<string | null>(null)

const deepCompareReady = ref(false)
const deepCompareChecking = ref(false)
let deepCompareSequence = 0

interface CandidateRow extends ComparisonCandidateSummary {
  experiment_name: string
}

const rows = computed<CandidateRow[]>(() => {
  if (!catalog.value) return []
  return catalog.value.groups.flatMap((group) =>
    group.candidates.map((candidate) => ({
      ...candidate,
      experiment_name: group.experiment_name,
    })),
  )
})

const selectableRows = computed(() => rows.value.filter((row) => row.selectable))
const singleCandidate = computed(() => selectableRows.value.length === 1 ? selectableRows.value[0] : null)

const defaultCandidateIds = computed(() => {
  const selectedFingerprints = new Set<string>()
  const selected = [...selectableRows.value]
    .filter((row) => row.metrics.rmse !== null)
    .sort((a, b) => {
      const metricDelta = (a.metrics.rmse ?? Number.POSITIVE_INFINITY) - (b.metrics.rmse ?? Number.POSITIVE_INFINITY)
      return metricDelta || a.candidate_result_id.localeCompare(b.candidate_result_id)
    })
    .filter((row) => {
      if (selectedFingerprints.has(row.configuration_fingerprint)) return false
      selectedFingerprints.add(row.configuration_fingerprint)
      return true
    })
    .slice(0, 2)
  const ids = new Set(selected.map((row) => row.candidate_result_id))
  return rows.value.filter((row) => ids.has(row.candidate_result_id)).map((row) => row.candidate_result_id)
})

const selectedIdList = computed(() => Array.from(selectedIds.value))

const rankedCandidates = computed(() => {
  if (!comparison.value?.ranking) return []
  return comparison.value.ranking
    .map((id) => comparison.value?.candidates.find((candidate) => candidate.candidate_result_id === id))
    .filter((candidate): candidate is ComparisonCandidateSummary => candidate !== undefined)
})
const inspectionCandidates = computed(() =>
  comparison.value?.comparison_items?.length
    ? comparison.value.comparison_items
    : comparison.value?.candidates ?? [],
)

const recommendedCandidate = computed(() => rankedCandidates.value[0] ?? null)
const runnerUpCandidate = computed(() => rankedCandidates.value[1] ?? null)
const rmseDelta = computed(() => {
  const best = recommendedCandidate.value?.metrics.rmse
  const next = runnerUpCandidate.value?.metrics.rmse
  if (best === null || best === undefined || next === null || next === undefined) return null
  return next - best
})
const differingParameterLabels = computed(() => {
  if (rankedCandidates.value.length < 2) return []
  const keys = new Set(rankedCandidates.value.flatMap((candidate) => Object.keys(candidate.parameters)))
  return [...keys]
    .filter((key) => new Set(rankedCandidates.value.map((candidate) => JSON.stringify(candidate.parameters[key]))).size > 1)
    .map(parameterLabel)
})

const canCompare = computed(
  () =>
    selectedIdList.value.length >= MIN_SELECTION &&
    selectedIdList.value.length <= MAX_SELECTION,
)

const fingerprintGroups = computed(() => {
  const groups = new Map<string, string[]>()
  for (const row of rows.value) {
    const fp = row.configuration_fingerprint
    if (!groups.has(fp)) groups.set(fp, [])
    groups.get(fp)!.push(row.candidate_result_id)
  }
  return groups
})

function runPosition(row: CandidateRow): number {
  const ids = fingerprintGroups.value.get(row.configuration_fingerprint) ?? []
  return ids.indexOf(row.candidate_result_id) + 1
}

function isDuplicateGroup(row: CandidateRow): boolean {
  const ids = fingerprintGroups.value.get(row.configuration_fingerprint) ?? []
  return ids.length > 1
}

function isSameGroupDisabled(row: CandidateRow): boolean {
  if (!isDuplicateGroup(row)) return false
  const ids = fingerprintGroups.value.get(row.configuration_fingerprint) ?? []
  return ids.some((id) => id !== row.candidate_result_id && selectedIds.value.has(id))
}

function describeError(e: unknown): string {
  if (e instanceof ApiError) return `${e.code}：${e.message}`
  return e instanceof Error ? e.message : String(e)
}

function isCheckboxDisabled(row: CandidateRow): boolean {
  if (!row.selectable) return true
  if (
    !selectedIds.value.has(row.candidate_result_id) &&
    selectedIds.value.size >= MAX_SELECTION
  ) {
    return true
  }
  if (isSameGroupDisabled(row)) return true
  return false
}

function onCheckboxChange(row: CandidateRow, val: unknown) {
  toggleSelection(row.candidate_result_id, val === true)
}

function toggleSelection(id: string, checked: boolean) {
  const next = new Set(selectedIds.value)
  if (checked) {
    if (next.size >= MAX_SELECTION) return
    const row = rows.value.find((r) => r.candidate_result_id === id)
    if (row && isSameGroupDisabled(row)) return
    next.add(id)
  } else {
    next.delete(id)
  }
  selectedIds.value = next
  comparison.value = null
  compareError.value = null
  deepCompareReady.value = false
}

async function runComparison() {
  if (!canCompare.value) return
  comparing.value = true
  compareError.value = null
  comparison.value = null
  deepCompareReady.value = false
  try {
    comparison.value = await compareCandidates(selectedIdList.value)
    if (
      comparison.value.comparable &&
      comparison.value.ranking &&
      selectedIdList.value.length === 2
    ) {
      void checkDeepCompareCapability()
    }
  } catch (e) {
    compareError.value = describeError(e)
  } finally {
    comparing.value = false
  }
}

async function checkDeepCompareCapability() {
  const ids = [...selectedIdList.value]
  if (ids.length !== 2) {
    deepCompareReady.value = false
    return
  }
  const sequence = ++deepCompareSequence
  deepCompareChecking.value = true
  deepCompareReady.value = false
  try {
    const [meta1, meta2] = await Promise.all([fetchResult(ids[0]), fetchResult(ids[1])])
    if (sequence !== deepCompareSequence) return
    deepCompareReady.value =
      meta1.evaluation_summary?.enhanced_evidence_available === true &&
      meta2.evaluation_summary?.enhanced_evidence_available === true
  } catch {
    if (sequence !== deepCompareSequence) return
    deepCompareReady.value = false
  } finally {
    if (sequence === deepCompareSequence) deepCompareChecking.value = false
  }
}

const showDeepCompare = computed(
  () =>
    comparison.value?.comparable === true &&
    comparison.value?.ranking !== null &&
    selectedIdList.value.length === 2 &&
    deepCompareReady.value,
)

function gotoDeepCompare() {
  if (!showDeepCompare.value) return
  void router.push({
    name: 'model-evaluation',
    params: { resultId: selectedIdList.value[0] },
    query: { compareWith: selectedIdList.value[1] },
  })
}

function gotoResult(url: string) {
  void router.push(url)
}

function gotoGridExperiment() {
  void router.push({
    name: 'experiment-create',
    params: { caseId: queryCaseId.value || 'new' },
    query: { dataset: datasetId.value, mode: 'grid' },
  })
}

function gotoUnifiedValidationExperiment() {
  const draft = comparison.value?.unified_experiment_draft
  if (!draft) return
  const validation = draft.validation
  void router.push({
    name: 'experiment-create',
    params: { caseId: queryCaseId.value || 'new' },
    query: {
      dataset: draft.dataset_version_id,
      validation_method: String(validation.method ?? 'spatial_kfold'),
      validation_folds: String(validation.folds ?? 5),
      validation_seed: String(validation.seed ?? 20260723),
      holdout_fraction: String(validation.holdout_fraction ?? 0.2),
    },
  })
}

function getCandidateInfo(resultId: string): ComparisonCandidateSummary | undefined {
  return comparison.value?.candidates.find((c) => c.candidate_result_id === resultId)
}

function fmt(value: number | null, digits = 4): string {
  return value === null ? '-' : value.toFixed(digits)
}

function algoLabel(row: ComparisonCandidateSummary): string {
  return algorithmLabel(row.algorithm)
}

function paramSummary(row: ComparisonCandidateSummary): string {
  return parameterSummary(row.algorithm, row.parameters).join(' · ')
}

function mismatchLabel(field: string): string {
  const direct = MISMATCH_LABELS[field]
  if (direct) return direct
  if (field.startsWith('validation_')) return '验证规则不同'
  if (field.startsWith('grid_')) return '成果网格规格不同'
  if (field.startsWith('common_valid_')) return '公共有效样本范围不同'
  if (field.endsWith('_mismatch')) return '比较条件不同'
  return '候选成果的比较条件不同'
}

let catalogSequence = 0

async function loadCatalog() {
  const sequence = ++catalogSequence
  const targetDatasetId = datasetId.value
  loading.value = true
  loadError.value = null
  catalog.value = null
  selectedIds.value = new Set()
  comparison.value = null
  compareError.value = null
  deepCompareReady.value = false
  try {
    const result = await fetchComparisonCandidates(targetDatasetId)
    if (sequence !== catalogSequence || targetDatasetId !== datasetId.value) return
    catalog.value = result
    selectedIds.value = new Set(defaultCandidateIds.value)
  } catch (e) {
    if (sequence !== catalogSequence || targetDatasetId !== datasetId.value) return
    loadError.value = describeError(e)
  } finally {
    if (sequence === catalogSequence && targetDatasetId === datasetId.value) {
      loading.value = false
    }
  }
}

onMounted(loadCatalog)

watch(datasetId, (next, prev) => {
  if (next !== prev) void loadCatalog()
})
</script>

<template>
  <div class="comparison-page product-page" data-test="candidate-comparison-view">
    <PageContextHeader
      title="模型比较"
      subtitle="使用同一份数据和相同分组方式比较候选成果，避免把不能直接比较的指标排在一起。"
      :case-id="queryCaseId || undefined"
      :dataset-id="datasetId"
    >
      <template #meta>
        <details class="comparison-technical" data-test="comparison-technical-details">
          <summary>技术详情</summary>
          <span class="mono">数据版本标识：{{ datasetId }}</span>
        </details>
      </template>
    </PageContextHeader>

    <AsyncState
      v-if="loadError"
      kind="error"
      title="候选目录加载失败"
      :impact="loadError"
      next-action="返回案例工作台重新进入"
      data-test="load-error"
    />
    <AsyncState v-else-if="loading" kind="loading" title="候选目录加载中" data-test="page-loading" />

    <main v-else class="comparison-main">
      <section v-if="rows.length === 0" class="empty-state" data-test="empty-catalog">
        当前数据集暂无可比较的候选成果。
      </section>

      <template v-else>
        <section v-if="selectableRows.length === 1" class="single-candidate" data-test="single-candidate-state">
          <div>
            <span class="section-kicker">只有一个可验证候选</span>
            <h2>还不能形成有意义的模型比较</h2>
            <p v-if="singleCandidate" class="single-candidate__source">
              {{ singleCandidate.experiment_name }} · {{ algoLabel(singleCandidate) }}
            </p>
            <p>创建参数网格实验，生成至少一个不同配置的候选后再回来比较。</p>
          </div>
          <el-button type="primary" data-test="create-grid-experiment" @click="gotoGridExperiment">创建参数网格实验</el-button>
        </section>

        <section v-else class="catalog-section">
          <aside class="comparison-requirements" data-test="comparison-requirements">
            <strong>可比条件</strong>
            <span>同一数据版本</span>
            <span>相同验证规则</span>
            <span>相同公共有效样本</span>
            <p>系统会在排名前自动校验；条件不一致时保留各自成果，但不进行数值排名。</p>
          </aside>
          <div class="comparison-start" data-test="comparison-start-summary">
            <div>
              <span class="section-kicker">建议起点</span>
              <h2>先比较当前 RMSE 最低的两个不同配置</h2>
              <p>已为你选择两个候选；点击比较后，系统会确认两项成果是否使用同一份数据、相同分组和兼容网格。</p>
            </div>
            <span class="selection-info" data-test="selection-info">已选 {{ selectedIdList.length }} / {{ MAX_SELECTION }}</span>
          </div>
          <div class="catalog-actions">
            <span>也可以手动选择 2–4 个候选</span>
            <el-button
              type="primary"
              data-test="compare-btn"
              :disabled="!canCompare || comparing"
              :loading="comparing"
              @click="runComparison"
            >
              校验并比较
            </el-button>
          </div>

          <el-table
            :data="rows"
            size="small"
            border
            class="catalog-table"
            data-test="candidate-table"
          >
            <el-table-column label="选择" width="60" align="center">
              <template #default="{ row }">
                <el-checkbox
                  data-test="candidate-checkbox"
                  :aria-label="`选择候选 ${row.candidate_result_id}`"
                  :model-value="selectedIds.has(row.candidate_result_id)"
                  :disabled="isCheckboxDisabled(row)"
                  @change="onCheckboxChange(row, $event)"
                />
              </template>
            </el-table-column>
            <el-table-column prop="experiment_name" label="实验" width="140" />
            <el-table-column label="算法" width="160">
              <template #default="{ row }">
                <span>{{ algoLabel(row) }}</span>
                <div
                  v-if="isDuplicateGroup(row)"
                  class="dup-badge"
                  :data-test="`dup-badge-${row.candidate_result_id}`"
                >
                  相同配置，第 {{ runPosition(row) }} 次运行
                </div>
              </template>
            </el-table-column>
            <el-table-column label="参数" min-width="200">
              <template #default="{ row }">
                <span>{{ paramSummary(row) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="RMSE" width="90" align="right">
              <template #default="{ row }">{{ fmt(row.metrics.rmse) }}</template>
            </el-table-column>
            <el-table-column label="MAE" width="90" align="right">
              <template #default="{ row }">{{ fmt(row.metrics.mae) }}</template>
            </el-table-column>
            <el-table-column label="R²" width="90" align="right">
              <template #default="{ row }">{{ fmt(row.metrics.r2) }}</template>
            </el-table-column>
            <el-table-column label="Bias" width="90" align="right">
              <template #default="{ row }">{{ fmt(row.metrics.bias) }}</template>
            </el-table-column>
            <el-table-column label="成果" width="70" align="center">
              <template #default="{ row }">
                <el-button size="small" text @click="gotoResult(row.result_url)">查看</el-button>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="80" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.selectable" type="success" size="small">可选</el-tag>
                <el-tag v-else type="info" size="small">不可选</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <div v-if="compareError" class="action-error" role="alert" data-test="compare-error">{{ compareError }}</div>

        <section v-if="comparison" class="result-section">
          <div class="result-header">
            <h2>比较结果</h2>
            <el-button
              v-if="showDeepCompare"
              size="small"
              data-test="deep-compare-btn"
              @click="gotoDeepCompare"
            >
              查看详细差异
            </el-button>
            <span
              v-if="deepCompareChecking"
              class="deep-status"
              data-test="deep-compare-checking"
              aria-live="polite"
            >
              正在检查详细差异能力…
            </span>
          </div>

          <div class="inspection-result" data-test="comparison-inspection">
            <div class="inspection-head">
              <div>
                <span class="section-kicker">成果对照</span>
                <h3>并排查看模型与原始验证指标</h3>
              </div>
              <span>{{ inspectionCandidates.length }} 个成果</span>
            </div>
            <MetricComparisonChart
              :candidates="inspectionCandidates"
              :comparable="comparison.comparable"
            />
            <ParameterDiffTable :candidates="inspectionCandidates" />
            <div class="inspection-cards">
              <article v-for="candidate in inspectionCandidates" :key="candidate.candidate_result_id">
                <strong>{{ algoLabel(candidate) }}</strong>
                <span>RMSE {{ fmt(candidate.metrics.rmse) }} · R² {{ fmt(candidate.metrics.r2) }}</span>
                <el-button size="small" text data-test="inspection-result-link" @click="gotoResult(candidate.result_url)">
                  查看成果
                </el-button>
              </article>
            </div>
          </div>

          <div
            v-if="comparison.comparable && comparison.ranking"
            class="ranking-result"
            data-test="ranking-result"
          >
            <div class="comparison-summary" data-test="comparison-summary">
              <article>
                <span>推荐方案</span>
                <strong>{{ recommendedCandidate ? algoLabel(recommendedCandidate) : '—' }}</strong>
                <p>在本次可比候选中综合排名第一。</p>
              </article>
              <article>
                <span>RMSE 差异</span>
                <strong>{{ rmseDelta === null ? '—' : rmseDelta.toFixed(4) }}</strong>
                <p>相对第二名的误差优势，数值越大表示差异越明显。</p>
              </article>
              <article>
                <span>主要参数差异</span>
                <strong>{{ differingParameterLabels.length }} 项</strong>
                <p>{{ differingParameterLabels.slice(0, 3).join('、') || '参数配置一致' }}</p>
              </article>
            </div>
            <div class="ranking-scroll">
            <table class="ranking-table">
              <thead>
                <tr>
                  <th>排名</th>
                  <th>方案</th>
                  <th>算法</th>
                  <th>RMSE</th>
                  <th>MAE</th>
                  <th>R²</th>
                  <th>Bias</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(resultId, index) in comparison.ranking"
                  :key="resultId"
                  :data-test="`ranking-row-${index}`"
                >
                  <td>
                    <span class="rank-num">{{ index + 1 }}</span>
                    <el-tag v-if="index === 0" type="danger" size="small" class="best-badge">最佳</el-tag>
                  </td>
                  <td>
                    {{ getCandidateInfo(resultId) ? algorithmLabel(getCandidateInfo(resultId)!.algorithm) : '候选成果' }}
                    <details class="row-technical"><summary>技术详情</summary><span class="mono">{{ resultId }}</span></details>
                  </td>
                  <td>{{ getCandidateInfo(resultId) ? algorithmLabel(getCandidateInfo(resultId)!.algorithm) : '-' }}</td>
                  <td>{{ fmt(getCandidateInfo(resultId)?.metrics.rmse ?? null) }}</td>
                  <td>{{ fmt(getCandidateInfo(resultId)?.metrics.mae ?? null) }}</td>
                  <td>{{ fmt(getCandidateInfo(resultId)?.metrics.r2 ?? null) }}</td>
                  <td>{{ fmt(getCandidateInfo(resultId)?.metrics.bias ?? null) }}</td>
                </tr>
              </tbody>
            </table>
            </div>
          </div>

          <div
            v-else-if="!comparison.comparable"
            class="mismatch-result"
            data-test="mismatch-list"
          >
            <p class="mismatch-head">这些成果使用了不同的验证规则，可以查看差异，但不能据此判断谁最好。</p>
            <ul class="mismatch-fields">
              <li
                v-for="difference in comparison.differences"
                :key="difference.code"
              >
                {{ mismatchLabel(difference.code) }}：{{ difference.message }}
              </li>
            </ul>
            <p class="mismatch-guidance">
              需要统一排名时，可以用相同数据版本和验证规则创建一组新实验；现有成果不会被修改。
            </p>
            <el-button
              v-if="comparison.unified_experiment_draft"
              data-test="create-unified-validation"
              @click="gotoUnifiedValidationExperiment"
            >创建统一验证实验</el-button>
          </div>
        </section>
      </template>
    </main>
  </div>
</template>

<style scoped>
.comparison-page {
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
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.mono {
  font-family: ui-monospace, monospace;
}

.page-loading {
  min-height: 200px;
}

.empty-state {
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 24px;
  text-align: center;
  font-size: 13px;
  color: var(--gmp-text-faint);
}

.comparison-main {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.catalog-section {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.catalog-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.comparison-requirements {
  display: grid;
  grid-template-columns: auto repeat(3, auto) minmax(220px, 1fr);
  align-items: center;
  gap: 8px 14px;
  padding: 10px 12px;
  border: 1px solid var(--s1-border);
  border-left: 3px solid var(--s1-cyan-strong);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-2);
  color: var(--s1-text-dim);
  font-size: var(--s1-font-sm);
}

.comparison-requirements strong {
  color: var(--s1-text-strong);
}

.comparison-requirements span::before {
  content: '✓';
  margin-right: 5px;
  color: var(--s1-cyan-strong);
}

.comparison-requirements p {
  margin: 0;
  color: var(--s1-text-faint);
}

.selection-info {
  font-size: 13px;
  color: var(--gmp-text-dim);
}

.section-kicker {
  color: var(--s1-cyan-strong);
  font-size: var(--s1-font-xs);
  font-weight: 600;
}

.comparison-start,
.single-candidate {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s1-space-5);
}

.comparison-start h2,
.single-candidate h2 {
  margin: 5px 0;
  font-size: var(--s1-font-lg);
}

.comparison-start p,
.single-candidate p {
  margin: 0;
  color: var(--s1-text-dim);
  font-size: var(--s1-font-sm);
}

.single-candidate {
  padding: var(--s1-space-6) 0;
  border-block: 1px solid var(--s1-border);
}

.comparison-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border: 1px solid var(--s1-border);
  background: var(--s1-border);
  gap: 1px;
}

.inspection-result {
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-4);
  margin-bottom: var(--s1-space-4);
}

.inspection-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s1-space-3);
}

.inspection-head h3 {
  margin: 4px 0 0;
  color: var(--s1-text-strong);
  font-size: var(--s1-font-lg);
}

.inspection-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: var(--s1-space-3);
}

.inspection-cards article {
  display: grid;
  gap: 8px;
  padding: var(--s1-space-3);
  border: 1px solid var(--s1-border);
  background: var(--s1-surface-2);
}

.inspection-cards span {
  color: var(--s1-text-dim);
  font-size: var(--s1-font-sm);
}

.comparison-summary article {
  padding: var(--s1-space-4);
  background: var(--s1-surface-2);
}

.comparison-summary span,
.comparison-summary p {
  color: var(--s1-text-faint);
  font-size: var(--s1-font-xs);
}

.comparison-summary strong {
  display: block;
  margin: 6px 0;
  color: var(--s1-text-strong);
  font-size: var(--s1-font-lg);
}

.comparison-summary p {
  margin: 0;
  line-height: 1.45;
}

.row-technical {
  margin-top: 4px;
  color: var(--s1-text-faint);
  font-size: var(--s1-font-xs);
}

.dup-badge {
  font-size: 12px;
  color: var(--gmp-accent);
  margin-top: 2px;
}

.action-error {
  border: 1px solid #a43d3d;
  background: rgba(164, 61, 61, 0.15);
  color: #ef9a9a;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
}

.result-section {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.result-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.result-header h3 {
  margin: 0;
  font-size: 15px;
}

.deep-status {
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.ranking-scroll {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.ranking-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.ranking-table th,
.ranking-table td {
  border: 1px solid var(--gmp-border);
  padding: 6px 10px;
  text-align: left;
}

.ranking-table th {
  background: var(--gmp-bg-soft);
  color: var(--gmp-text-dim);
}

.rank-num {
  margin-right: 6px;
}

.best-badge {
  margin-left: 4px;
}

.mismatch-result {
  border: 1px solid #9a7b2d;
  background: rgba(154, 123, 45, 0.1);
  border-radius: 10px;
  padding: 12px 16px;
}

.mismatch-head {
  margin: 0 0 8px;
  font-size: 13px;
  color: #e5c76b;
}

.mismatch-fields {
  margin: 0;
  padding-left: 20px;
  font-size: 12px;
  color: #e5c76b;
}

.mismatch-guidance {
  margin: 10px 0 0;
  color: var(--s1-text-dim);
  font-size: var(--s1-font-sm);
  line-height: 1.5;
}

@media (max-width: 480px) {
  .comparison-page {
    padding: 16px 12px 32px;
  }

  .page-header h1 {
    font-size: 16px;
  }

  .catalog-section,
  .result-section {
    padding: 12px 14px;
  }

  .ranking-table {
    font-size: 12px;
  }

  .ranking-table th,
  .ranking-table td {
    padding: 4px 6px;
    white-space: nowrap;
  }

  .comparison-start,
  .single-candidate {
    align-items: flex-start;
    flex-direction: column;
  }

  .comparison-summary {
    grid-template-columns: 1fr;
  }

  .comparison-requirements {
    grid-template-columns: 1fr;
  }
}
</style>
