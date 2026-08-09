<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, compareCandidates, fetchComparisonCandidates, fetchResult } from '../api/client'
import type {
  CandidateCatalog,
  ComparisonCandidateSummary,
  MultiCandidateComparison,
} from '../api/types'
import { algorithmLabel, parameterSummary } from '../utils/modelingLabels'
import PageNavigation from '../components/navigation/PageNavigation.vue'
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

const selectedIdList = computed(() => Array.from(selectedIds.value))

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
  <div class="comparison-page" data-test="candidate-comparison-view">
    <PageNavigation :case-id="queryCaseId || undefined" :dataset-id="datasetId" current-label="模型对比" />
    <header class="page-header">
      <h1>模型对比</h1>
      <p class="page-sub">同一数据版本和验证方法下比较不同实验结果</p>
      <p class="page-sub">数据集 <span class="mono">{{ datasetId }}</span></p>
    </header>

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
        <section class="catalog-section">
          <div class="catalog-actions">
            <span class="selection-info" data-test="selection-info">
              已选 {{ selectedIdList.length }} / {{ MAX_SELECTION }}（至少 {{ MIN_SELECTION }} 个）
            </span>
            <el-button
              type="primary"
              data-test="compare-btn"
              :disabled="!canCompare || comparing"
              :loading="comparing"
              @click="runComparison"
            >
              开始对比
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

          <div
            v-if="comparison.comparable && comparison.ranking"
            class="ranking-result"
            data-test="ranking-result"
          >
            <MetricComparisonChart
              :candidates="comparison.candidates"
              :comparable="comparison.comparable"
            />
            <ParameterDiffTable :candidates="comparison.candidates" />
            <div class="ranking-scroll">
            <table class="ranking-table">
              <thead>
                <tr>
                  <th>排名</th>
                  <th>成果 ID</th>
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
                  <td class="mono">{{ resultId }}</td>
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
            <p class="mismatch-head">候选不兼容，无法排名。以下字段不一致：</p>
            <ul class="mismatch-fields">
              <li
                v-for="field in comparison.mismatches"
                :key="field"
                class="mono"
              >
                {{ field }}
              </li>
            </ul>
          </div>
        </section>
      </template>
    </main>
  </div>
</template>

<style scoped>
.comparison-page {
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

.selection-info {
  font-size: 13px;
  color: var(--gmp-text-dim);
}

.dup-badge {
  font-size: 11px;
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
    font-size: 11px;
  }

  .ranking-table th,
  .ranking-table td {
    padding: 4px 6px;
    white-space: nowrap;
  }
}
</style>
