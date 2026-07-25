<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ApiError,
  confirmWarnings,
  fetchCaseDatasets,
  fetchDataset,
  fetchMicroseismicDerivation,
  importMicroseismic,
  validateDataset,
} from '../api/client'
import type {
  DatasetVersionRecord,
  MicroseismicDerivation,
  MicroseismicImportProfile,
  MicroseismicImportResponse,
  MicroseismicMapping,
  QualityReport,
} from '../api/types'
import SourceFilesStep from '../components/microseismic/SourceFilesStep.vue'
import DerivationSummary from '../components/microseismic/DerivationSummary.vue'
import PageNavigation from '../components/navigation/PageNavigation.vue'

const route = useRoute()
const router = useRouter()

const caseId = computed(() => String(route.params.caseId))

const step = ref<1 | 2 | 3 | 4>(1)
const loading = ref(true)
const loadError = ref<string | null>(null)

const importing = ref(false)
const importResult = ref<MicroseismicImportResponse | null>(null)
const importError = ref<{ code: string; message: string; details: Record<string, unknown> } | null>(null)

const datasetId = ref<string | null>(null)
const mapping = ref<MicroseismicMapping | null>(null)
const derivation = ref<MicroseismicDerivation | null>(null)

const quality = ref<QualityReport | null>(null)
const validating = ref(false)
const confirming = ref(false)
const actionError = ref<string | null>(null)

function describeError(e: unknown): string {
  if (e instanceof ApiError) return `${e.code}：${e.message}`
  return e instanceof Error ? e.message : String(e)
}

// 刷新/重开页面时以服务端状态恢复：路由 dataset 参数优先，
// 其次案例下已存在的微震导入数据集；两者都没有才回到文件选择。
onMounted(async () => {
  try {
    const datasetQuery = route.query.dataset ? String(route.query.dataset) : null
    let record: DatasetVersionRecord | null = null
    if (datasetQuery) {
      record = await fetchDataset(datasetQuery)
    } else {
      const listing = await fetchCaseDatasets(caseId.value)
      record =
        listing.datasets.find(
          (d) => (d.profile as { source_kind?: unknown }).source_kind === 'microseismic_dat_bundle',
        ) ?? null
    }
    if (record) {
      const evidence = await fetchMicroseismicDerivation(record.id)
      derivation.value = evidence
      datasetId.value = record.id
      mapping.value = (record.profile as unknown as Partial<MicroseismicImportProfile>).mapping ?? null
      step.value = 3
    }
  } catch (e) {
    loadError.value = describeError(e)
  } finally {
    loading.value = false
  }
})

async function onImport(files: File[]) {
  importing.value = true
  importError.value = null
  importResult.value = null
  try {
    const result = await importMicroseismic(caseId.value, files)
    // 成功不以 HTTP 201 为准：必须取回完整派生证据才进入核验步骤
    const evidence = await fetchMicroseismicDerivation(result.id)
    importResult.value = result
    derivation.value = evidence
    datasetId.value = result.id
    mapping.value = result.profile.mapping
    step.value = 2
  } catch (e) {
    // 服务端阻断（如派生合同/黄金门禁失败）：只展示公开诊断，不提供继续入口
    importError.value =
      e instanceof ApiError
        ? { code: e.code, message: e.message, details: e.details }
        : { code: 'IMPORT_FAILED', message: describeError(e), details: {} }
    step.value = 2
  } finally {
    importing.value = false
  }
}

const failedChecks = computed<Array<{ name: string; evidence: unknown }>>(() => {
  const raw = importError.value?.details.failed_checks
  return Array.isArray(raw) ? (raw as Array<{ name: string; evidence: unknown }>) : []
})

const missingFiles = computed(() => stringList(importError.value?.details.missing))
const unknownFiles = computed(() => stringList(importError.value?.details.unknown))

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function backToSelect() {
  importError.value = null
  importResult.value = null
  step.value = 1
}

async function continueToModeling() {
  step.value = 4
  if (!quality.value) await runValidate()
}

async function runValidate() {
  if (!datasetId.value) return
  validating.value = true
  actionError.value = null
  try {
    quality.value = await validateDataset(datasetId.value)
  } catch (e) {
    actionError.value = describeError(e)
  } finally {
    validating.value = false
  }
}

const blockers = computed(() => quality.value?.issues.filter((i) => i.kind === 'blocker') ?? [])
const warnings = computed(() => quality.value?.issues.filter((i) => i.kind === 'warning') ?? [])

// 质量就绪的唯一判定：passed，或 warnings 且已被用户显式确认
const qualityReady = computed(
  () =>
    quality.value !== null &&
    (quality.value.status === 'passed' || (quality.value.status === 'warnings' && quality.value.confirmed)),
)

const banner = computed(() => {
  const report = quality.value
  if (!report) return null
  if (report.status === 'blocked') return { kind: 'bad', text: '质量校验未通过：存在阻断项，建模入口已禁用' }
  if (report.status === 'warnings' && !report.confirmed)
    return { kind: 'warn', text: '存在警告：须逐条知悉并整体确认后才能继续' }
  if (report.status === 'warnings') return { kind: 'ok', text: '警告已确认，可以进入建模' }
  return { kind: 'ok', text: '质量校验通过' }
})

async function onConfirmWarnings() {
  if (!quality.value || !datasetId.value) return
  confirming.value = true
  actionError.value = null
  try {
    const codes = quality.value.issues
      .filter((issue) => issue.kind === 'warning')
      .map((issue) => issue.code)
      .sort()
    quality.value = await confirmWarnings(datasetId.value, codes)
  } catch (e) {
    actionError.value = describeError(e)
  } finally {
    confirming.value = false
  }
}

function enterModeling() {
  if (!qualityReady.value || !datasetId.value) return
  void router.push({
    path: `/cases/${caseId.value}/experiments/new`,
    query: { dataset: datasetId.value },
  })
}
</script>

<template>
  <div class="import-page">
    <PageNavigation home />
    <header class="import-header">
      <h1>微震 DAT 导入向导</h1>
      <p class="import-sub">
        案例 <span class="mono">{{ caseId }}</span>
        <template v-if="datasetId"> · 数据集 <span class="mono">{{ datasetId }}</span></template>
      </p>
    </header>

    <el-result v-if="loadError" icon="error" title="微震案例加载失败" :sub-title="loadError" />
    <div v-else-if="loading" v-loading="true" class="import-loading" />

    <main v-else class="import-main">
      <SourceFilesStep v-if="step === 1" :importing="importing" @import="onImport" />

      <section v-else-if="step === 2" class="wizard-step" data-test="step-verify">
        <h3><span class="step-no">2</span> 原始数据核验</h3>

        <template v-if="importResult">
          <p class="step-hint">
            服务端已原子完成导入与派生；以下为登记的文件身份（文件名 / 测点 / 测线 / 记录数 / 哈希）。
          </p>
          <ul class="manifest" data-test="source-manifest">
            <li v-for="entry in importResult.profile.source_files" :key="entry.file_name">
              <span class="mono file-name">{{ entry.file_name }}</span>
              <span class="dim">{{ entry.point_id }} · {{ entry.line_id }}</span>
              <span class="dim">{{ entry.source_record_count }} 行</span>
              <span class="mono dim">sha256 {{ entry.sha256.slice(0, 12) }}…</span>
            </li>
          </ul>
          <p class="verify-counts">
            共 {{ importResult.profile.source_files.length }} 个文件 · 源记录
            {{ importResult.profile.layer_counts.source_records }} · 有限记录
            {{ importResult.profile.layer_counts.finite_records }}
          </p>
          <div class="step-actions">
            <button
              class="gmp-btn primary"
              data-test="micro-continue-derivation"
              :disabled="!derivation"
              @click="step = 3"
            >
              查看派生结果
            </button>
          </div>
        </template>

        <template v-else-if="importError">
          <div class="import-error" data-test="import-error">
            <p class="error-head">{{ importError.code }}：{{ importError.message }}</p>
            <ul v-if="failedChecks.length" class="issue-list blockers" data-test="failed-checks">
              <li v-for="check in failedChecks" :key="check.name">
                <b class="mono">{{ check.name }}</b>
                <span>{{ check.evidence }}</span>
              </li>
            </ul>
            <p v-if="missingFiles.length" class="error-detail" data-test="missing-files">
              缺失文件：{{ missingFiles.join('、') }}
            </p>
            <p v-if="unknownFiles.length" class="error-detail" data-test="unknown-files">
              未登记文件：{{ unknownFiles.join('、') }}
            </p>
            <p class="step-hint">服务端已阻断本次导入，不存在可绕过的继续入口；请修正文件集合后重试。</p>
          </div>
          <div class="step-actions">
            <button class="gmp-btn" data-test="micro-back-select" @click="backToSelect">重新选择文件</button>
          </div>
        </template>
      </section>

      <section v-else-if="step === 3 && derivation && mapping" class="wizard-step" data-test="step-derivation">
        <h3><span class="step-no">3</span> 派生结果确认</h3>
        <DerivationSummary :derivation="derivation" :mapping="mapping" />
        <div class="step-actions">
          <button class="gmp-btn primary" data-test="micro-continue-modeling" @click="continueToModeling">
            确认并进入质量校验
          </button>
        </div>
      </section>

      <section v-else-if="step === 4" class="wizard-step" data-test="step-modeling">
        <h3><span class="step-no">4</span> 质量校验与建模入口</h3>
        <p class="step-hint">进入调参实验室前，先对标准化建模节点执行平台既有质量校验。</p>

        <div v-if="validating" class="quality-loading">质量校验中…</div>
        <template v-else>
          <div v-if="actionError" class="action-error" data-test="action-error">
            <span>{{ actionError }}</span>
            <button class="gmp-btn" data-test="run-validate-retry" @click="runValidate">重试</button>
          </div>

          <template v-if="quality">
            <div class="quality-banner" :class="banner?.kind" data-test="quality-banner">{{ banner?.text }}</div>

            <div class="quality-stats">
              <span>总行 {{ quality.row_count }}</span>
              <span>有效 {{ quality.valid_row_count }}</span>
              <span>数值失败 {{ quality.invalid_row_count }}</span>
              <span>唯一点位 {{ quality.statistics.unique_coordinate_count }}</span>
              <span>重复 {{ quality.statistics.duplicate_count }}</span>
              <span>冲突 {{ quality.statistics.conflict_count }}</span>
            </div>

            <ul v-if="blockers.length" class="issue-list blockers" data-test="blocker-list">
              <li v-for="issue in blockers" :key="issue.code">
                <b>{{ issue.code }}</b>
                <span>{{ issue.message }}</span>
              </li>
            </ul>

            <ul v-if="warnings.length" class="issue-list warnings" data-test="warning-list">
              <li v-for="issue in warnings" :key="issue.code">
                <b>{{ issue.code }}</b>
                <span>{{ issue.message }}</span>
              </li>
            </ul>

            <div class="step-actions">
              <button
                v-if="quality.status === 'warnings' && !quality.confirmed"
                class="gmp-btn warn"
                data-test="confirm-warnings"
                :disabled="confirming"
                @click="onConfirmWarnings"
              >
                {{ confirming ? '确认中…' : `确认全部 ${warnings.length} 条警告` }}
              </button>
              <button class="gmp-btn" data-test="run-validate-again" :disabled="validating" @click="runValidate">
                重新校验
              </button>
              <button
                v-if="quality.status !== 'blocked'"
                class="gmp-btn primary"
                data-test="enter-modeling"
                :disabled="!qualityReady"
                @click="enterModeling"
              >
                进入建模
              </button>
            </div>
          </template>
        </template>
      </section>
    </main>
  </div>
</template>

<style scoped>
.import-page {
  min-height: 100%;
  max-width: 980px;
  margin: 0 auto;
  padding: 28px 20px 48px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.import-header h1 {
  margin: 0;
  font-size: 20px;
}

.import-sub {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.mono {
  font-family: ui-monospace, monospace;
}

.dim {
  color: var(--gmp-text-faint);
  font-size: 12px;
}

.import-main {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.import-loading {
  min-height: 200px;
}

.wizard-step {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 18px 20px;
}

.wizard-step h3 {
  margin: 0 0 14px;
  font-size: 15px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-no {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--gmp-accent);
  color: #0b0f14;
  font-size: 12px;
  font-weight: 700;
}

.step-hint {
  color: var(--gmp-text-faint);
  font-size: 13px;
  margin: 0 0 14px;
  line-height: 1.6;
}

.step-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 14px;
}

.manifest {
  list-style: none;
  margin: 0 0 12px;
  padding: 0;
  max-height: 260px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.manifest li {
  display: flex;
  gap: 14px;
  align-items: baseline;
  font-size: 13px;
  border: 1px solid var(--gmp-border);
  border-radius: 6px;
  padding: 6px 10px;
}

.file-name {
  color: var(--gmp-text);
  min-width: 72px;
}

.verify-counts {
  font-size: 13px;
  color: var(--gmp-text);
  margin: 0;
}

.import-error {
  border: 1px solid #a43d3d;
  background: rgba(164, 61, 61, 0.12);
  border-radius: 10px;
  padding: 14px 16px;
}

.error-head {
  margin: 0 0 10px;
  color: #ef9a9a;
  font-size: 14px;
  font-weight: 600;
}

.error-detail {
  margin: 6px 0;
  font-size: 13px;
  color: #ef9a9a;
}

.issue-list {
  list-style: none;
  margin: 0 0 12px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.issue-list li {
  display: flex;
  gap: 10px;
  align-items: baseline;
  font-size: 13px;
  border: 1px solid var(--gmp-border);
  border-radius: 8px;
  padding: 8px 12px;
}

.issue-list.blockers li {
  border-color: #a43d3d;
}

.issue-list.blockers b {
  color: #ef9a9a;
}

.issue-list.warnings b {
  color: #e5c76b;
}

.quality-loading {
  color: var(--gmp-text-dim);
  font-size: 13px;
}

.quality-banner {
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
  margin-bottom: 12px;
  border: 1px solid var(--gmp-border);
}

.quality-banner.ok {
  border-color: #2e7d4f;
  background: rgba(46, 125, 79, 0.15);
  color: #7fd6a4;
}

.quality-banner.warn {
  border-color: #9a7b2d;
  background: rgba(154, 123, 45, 0.15);
  color: #e5c76b;
}

.quality-banner.bad {
  border-color: #a43d3d;
  background: rgba(164, 61, 61, 0.15);
  color: #ef9a9a;
}

.quality-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  font-size: 12px;
  color: var(--gmp-text-dim);
  margin-bottom: 12px;
}

.action-error {
  border: 1px solid #a43d3d;
  background: rgba(164, 61, 61, 0.15);
  color: #ef9a9a;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.gmp-btn {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text);
  border-radius: 8px;
  padding: 8px 18px;
  font-size: 13px;
  cursor: pointer;
}

.gmp-btn.primary {
  background: var(--gmp-accent);
  border-color: var(--gmp-accent);
  color: #0b0f14;
  font-weight: 600;
}

.gmp-btn.warn {
  border-color: #9a7b2d;
  color: #e5c76b;
}

.gmp-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
