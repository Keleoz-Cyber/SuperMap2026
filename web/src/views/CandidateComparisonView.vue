<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, compareCandidates, fetchComparisonCandidates } from '../api/client'
import type {
  CandidateCatalog,
  ComparisonCandidateSummary,
  MultiCandidateComparison,
} from '../api/types'
import PageNavigation from '../components/navigation/PageNavigation.vue'

const route = useRoute()
const router = useRouter()
const datasetId = computed(() => String(route.params.datasetId ?? ''))

const MIN_SELECTION = 2
const MAX_SELECTION = 4

const loading = ref(true)
const loadError = ref<string | null>(null)
const catalog = ref<CandidateCatalog | null>(null)
const selectedIds = ref<Set<string>>(new Set())
const comparison = ref<MultiCandidateComparison | null>(null)
const comparing = ref(false)
const compareError = ref<string | null>(null)

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

const canDeepCompare = computed(() => selectedIdList.value.length === 2)

function describeError(e: unknown): string {
  if (e instanceof ApiError) return `${e.code}：${e.message}`
  return e instanceof Error ? e.message : String(e)
}

function isCheckboxDisabled(candidate: ComparisonCandidateSummary): boolean {
  if (!candidate.selectable) return true
  if (
    !selectedIds.value.has(candidate.candidate_result_id) &&
    selectedIds.value.size >= MAX_SELECTION
  ) {
    return true
  }
  return false
}

function onCheckboxChange(row: CandidateRow, val: unknown) {
  toggleSelection(row.candidate_result_id, val === true)
}

function toggleSelection(id: string, checked: boolean) {
  const next = new Set(selectedIds.value)
  if (checked) {
    if (next.size >= MAX_SELECTION) return
    next.add(id)
  } else {
    next.delete(id)
  }
  selectedIds.value = next
  comparison.value = null
  compareError.value = null
}

async function runComparison() {
  if (!canCompare.value) return
  comparing.value = true
  compareError.value = null
  comparison.value = null
  try {
    comparison.value = await compareCandidates(selectedIdList.value)
  } catch (e) {
    compareError.value = describeError(e)
  } finally {
    comparing.value = false
  }
}

function gotoDeepCompare() {
  if (!canDeepCompare.value) return
  void router.push({
    name: 'professional-analysis',
    params: { resultId: selectedIdList.value[0] },
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

function formatParamNumber(value: number): string {
  return Number.isFinite(value) ? String(Number(value.toPrecision(12))) : String(value)
}

function formatParamValue(value: unknown): string {
  if (value === null || value === undefined) return 'null'
  if (typeof value === 'number') return formatParamNumber(value)
  if (typeof value === 'boolean') return String(value)
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return `[${value.map((item) => formatParamValue(item)).join(',')}]`
  if (typeof value === 'object') {
    const entries = Object.keys(value as Record<string, unknown>)
      .sort()
      .map((key) => `${key}:${formatParamValue((value as Record<string, unknown>)[key])}`)
    return `{${entries.join(',')}}`
  }
  return String(value)
}

function paramsPreview(parameters: Record<string, unknown>): string {
  return Object.keys(parameters)
    .sort()
    .map((key) => `${key}=${formatParamValue(parameters[key])}`)
    .join(' ')
}

onMounted(async () => {
  try {
    catalog.value = await fetchComparisonCandidates(datasetId.value)
  } catch (e) {
    loadError.value = describeError(e)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="comparison-page" data-test="candidate-comparison-view">
    <PageNavigation home />
    <header class="page-header">
      <h1>同一数据版本 / 同一验证合同候选比较</h1>
      <p class="page-sub">数据集 <span class="mono">{{ datasetId }}</span></p>
    </header>

    <el-result
      v-if="loadError"
      icon="error"
      title="候选目录加载失败"
      :sub-title="loadError"
      data-test="load-error"
    />
    <div v-else-if="loading" v-loading="true" class="page-loading" data-test="page-loading" />

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
              比较候选
            </el-button>
            <el-button
              data-test="deep-compare-btn"
              :disabled="!canDeepCompare"
              @click="gotoDeepCompare"
            >
              深度比较
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
                  :model-value="selectedIds.has(row.candidate_result_id)"
                  :disabled="isCheckboxDisabled(row)"
                  @change="onCheckboxChange(row, $event)"
                />
              </template>
            </el-table-column>
            <el-table-column prop="experiment_name" label="实验" width="140" />
            <el-table-column label="算法" width="140">
              <template #default="{ row }">
                <span class="mono">{{ row.algorithm }}</span>
              </template>
            </el-table-column>
            <el-table-column label="参数" min-width="200">
              <template #default="{ row }">
                <span class="mono">{{ paramsPreview(row.parameters) }}</span>
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

        <div v-if="compareError" class="action-error" data-test="compare-error">{{ compareError }}</div>

        <section v-if="comparison" class="result-section">
          <h3>比较结果</h3>

          <div
            v-if="comparison.comparable && comparison.ranking"
            class="ranking-result"
            data-test="ranking-result"
          >
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
                  <td class="mono">{{ getCandidateInfo(resultId)?.algorithm ?? '-' }}</td>
                  <td>{{ fmt(getCandidateInfo(resultId)?.metrics.rmse ?? null) }}</td>
                  <td>{{ fmt(getCandidateInfo(resultId)?.metrics.mae ?? null) }}</td>
                  <td>{{ fmt(getCandidateInfo(resultId)?.metrics.r2 ?? null) }}</td>
                  <td>{{ fmt(getCandidateInfo(resultId)?.metrics.bias ?? null) }}</td>
                </tr>
              </tbody>
            </table>
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

.result-section h3 {
  margin: 0;
  font-size: 15px;
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
</style>
