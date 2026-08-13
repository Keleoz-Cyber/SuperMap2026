<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ApiError,
  abandonDataset,
  confirmWarnings,
  fetchDataset,
  fetchInspection,
  fetchQuality,
  postMapping,
  validateDataset,
} from '../api/client'
import type {
  DatasetVersionRecord,
  FieldMappingPayload,
  InspectionResult,
  QualityReport,
} from '../api/types'
import DataIntakeWorkbench from '../components/upload/DataIntakeWorkbench.vue'
import PageNavigation from '../components/navigation/PageNavigation.vue'
import AsyncState from '../components/states/AsyncState.vue'

const route = useRoute()
const router = useRouter()

const caseId = computed(() => String(route.params.caseId))
const datasetId = computed(() => String(route.params.datasetId))

const dataset = ref<DatasetVersionRecord | null>(null)
const inspection = ref<InspectionResult | null>(null)
const report = ref<QualityReport | null>(null)
const loadError = ref<string | null>(null)
const actionError = ref<string | null>(null)

const submitting = ref(false)
const validating = ref(false)
const confirming = ref(false)
const conversion = ref<{ valid: number; invalid: number; total: number } | null>(null)

const workflowBusyLabel = computed(() => {
  if (submitting.value) return '正在应用字段映射并检查数值，请稍候'
  if (validating.value) return '正在执行数据质量检查，请勿关闭页面'
  if (confirming.value) return '正在保存质量确认并更新建模状态'
  return ''
})

const showAbandonDialog = ref(false)
const abandoning = ref(false)

const showValidated = computed(
  () =>
    dataset.value !== null &&
    dataset.value.status === 'validated' &&
    (isValidatedPreset.value || report.value === null),
)
const showAbandoned = computed(
  () => dataset.value !== null && dataset.value.status === 'abandoned',
)
const canAbandon = computed(
  () =>
    dataset.value !== null &&
    (dataset.value.status === 'uploaded' ||
      dataset.value.status === 'mapped' ||
      dataset.value.status === 'blocked'),
)

function describeError(e: unknown): string {
  if (e instanceof ApiError) return e.message
  return e instanceof Error ? e.message : String(e)
}

const datasetProfile = computed<Record<string, unknown>>(
  () => (dataset.value?.profile ?? {}) as Record<string, unknown>,
)
const datasetMapping = computed<Record<string, unknown>>(
  () => (datasetProfile.value.mapping ?? {}) as Record<string, unknown>,
)
const isValidatedPreset = computed(
  () =>
    dataset.value?.status === 'validated' &&
    datasetProfile.value.source_kind === 'builtin_preset',
)
const validatedSummary = computed(() => {
  const validRows = Number(datasetProfile.value.valid_row_count ?? datasetProfile.value.row_count ?? 0)
  const invalidRows = Number(datasetProfile.value.invalid_row_count ?? 0)
  return {
    validRows: Number.isFinite(validRows) ? validRows.toLocaleString('zh-CN') : '—',
    invalidRows: Number.isFinite(invalidRows) ? invalidRows.toLocaleString('zh-CN') : '—',
    valueName: String(datasetMapping.value.value_name ?? '建模属性'),
    valueUnit: String(datasetMapping.value.value_unit ?? '未登记'),
    coordinateKind:
      datasetMapping.value.coordinate_kind === 'local_linear'
        ? '局部线性米制坐标'
        : String(datasetMapping.value.coordinate_kind ?? '未登记'),
  }
})

async function loadQuality() {
  try {
    report.value = await fetchQuality(datasetId.value)
  } catch (e) {
    if (e instanceof ApiError && e.code === 'QUALITY_NOT_EVALUATED') {
      report.value = null
    } else {
      throw e
    }
  }
}

async function refreshDataset() {
  dataset.value = await fetchDataset(datasetId.value)
}

// 刷新/重开页面时一律以服务端状态重建向导（不依赖本地缓存）
onMounted(async () => {
  try {
    const ds = await fetchDataset(datasetId.value)
    dataset.value = ds
    const profile = ds.profile as Record<string, unknown>
    const validatedPreset =
      ds.status === 'validated' && profile.source_kind === 'builtin_preset'
    if (!validatedPreset) {
      inspection.value = await fetchInspection(datasetId.value)
    }
    if (ds.status === 'mapped' || ds.status === 'validated' || ds.status === 'blocked') {
      await loadQuality()
    }
  } catch (e) {
    loadError.value = describeError(e)
  }
})

async function onSheetChange(sheet: string) {
  actionError.value = null
  try {
    inspection.value = await fetchInspection(datasetId.value, sheet)
  } catch (e) {
    actionError.value = describeError(e)
  }
}

async function runValidate() {
  validating.value = true
  actionError.value = null
  try {
    report.value = await validateDataset(datasetId.value)
    await refreshDataset()
  } catch (e) {
    actionError.value = describeError(e)
  } finally {
    validating.value = false
  }
}

async function onMappingSubmit(mapping: FieldMappingPayload) {
  submitting.value = true
  actionError.value = null
  try {
    const updated = await postMapping(datasetId.value, mapping, inspection.value?.sheet ?? null)
    if (updated.status !== 'mapped' && updated.status !== 'validated') {
      throw new ApiError('MAPPING_NOT_APPLIED', `映射未生效（状态 ${updated.status}）`, 200)
    }
    dataset.value = updated
    const profile = updated.profile as Record<string, unknown>
    conversion.value = {
      valid: Number(profile.valid_row_count ?? 0),
      invalid: Number(profile.invalid_row_count ?? 0),
      total: Number(profile.row_count ?? 0),
    }
    report.value = null
    await runValidate()
  } catch (e) {
    actionError.value = describeError(e)
  } finally {
    submitting.value = false
  }
}

async function onConfirmWarnings() {
  if (!report.value) return
  confirming.value = true
  actionError.value = null
  try {
    const codes = report.value.issues
      .filter((issue) => issue.kind === 'warning')
      .map((issue) => issue.code)
      .sort()
    report.value = await confirmWarnings(datasetId.value, codes)
    await refreshDataset()
  } catch (e) {
    actionError.value = describeError(e)
  } finally {
    confirming.value = false
  }
}

async function onAbandon() {
  abandoning.value = true
  actionError.value = null
  try {
    await abandonDataset(datasetId.value)
    await refreshDataset()
    showAbandonDialog.value = false
  } catch (e) {
    actionError.value = describeError(e)
  } finally {
    abandoning.value = false
  }
}

function onStart() {
  void router.push(`/cases/${caseId.value}`)
}
</script>

<template>
  <div class="wizard-page product-page product-page--workflow">
    <PageNavigation :case-id="caseId" current-label="数据接入与准备" />
    <header class="wizard-header">
      <h1>数据接入与准备</h1>
      <p class="wizard-sub">
        完成字段识别、质量检查与建模确认；已完成的数据可直接返回案例继续工作。
      </p>
    </header>

    <AsyncState
      v-if="loadError"
      kind="error"
      title="数据集加载失败"
      :impact="loadError"
      next-action="返回案例工作台重新进入，或稍后重试"
    />
    <AsyncState v-else-if="!dataset" kind="loading" title="数据版本加载中" />

    <main v-else class="wizard-main">
      <div v-if="actionError" class="action-error" data-test="action-error">{{ actionError }}</div>
      <div
        v-if="workflowBusyLabel"
        class="workflow-busy"
        data-test="workflow-busy-status"
        role="status"
        aria-live="polite"
      >
        <span class="workflow-busy-spinner" aria-hidden="true" />
        <span>{{ workflowBusyLabel }}</span>
      </div>

      <div v-if="showValidated" data-test="wizard-step-validated">
        <section class="validated-summary">
          <div class="validated-copy">
            <span class="status-kicker">质量检查通过</span>
            <h2>数据已可用于建模</h2>
            <p>无需再次解析原始文件，可直接进入实验、空间结构分析和结果比较。</p>
          </div>
          <dl class="validated-metrics">
            <div>
              <dt>有效样本</dt>
              <dd>{{ validatedSummary.validRows }}</dd>
            </div>
            <div>
              <dt>无效样本</dt>
              <dd>{{ validatedSummary.invalidRows }}</dd>
            </div>
            <div>
              <dt>建模属性</dt>
              <dd>{{ validatedSummary.valueName }}</dd>
            </div>
            <div>
              <dt>单位</dt>
              <dd>{{ validatedSummary.valueUnit }}</dd>
            </div>
          </dl>
          <div class="validated-actions">
            <el-button type="primary" data-test="enter-workspace" @click="onStart">
              进入案例工作台
            </el-button>
          </div>
          <details class="technical-details" data-test="dataset-technical-details">
            <summary>技术详情</summary>
            <dl>
              <div><dt>坐标口径</dt><dd>{{ validatedSummary.coordinateKind }}</dd></div>
              <div><dt>案例标识</dt><dd class="mono">{{ caseId }}</dd></div>
              <div><dt>数据版本标识</dt><dd class="mono">{{ datasetId }}</dd></div>
            </dl>
          </details>
        </section>
      </div>

      <div v-else-if="showAbandoned" data-test="wizard-step-abandoned">
        <el-result
          icon="info"
          title="数据准备已放弃"
          sub-title="此数据版本已被放弃，请返回工作台上传新数据。"
        >
          <template #extra>
            <el-button type="primary" data-test="enter-workspace" @click="onStart">
              返回案例工作台
            </el-button>
          </template>
        </el-result>
      </div>

      <DataIntakeWorkbench
        v-else
        :dataset="dataset"
        :inspection="inspection"
        :report="report"
        :conversion="conversion"
        :submitting="submitting"
        :validating="validating"
        :confirming="confirming"
        @sheet-change="onSheetChange"
        @submit-mapping="onMappingSubmit"
        @validate="runValidate"
        @confirm-warnings="onConfirmWarnings"
        @start="onStart"
      />

      <div v-if="canAbandon" class="abandon-section">
        <el-button
          type="danger"
          plain
          data-test="abandon-preparation-btn"
          @click="showAbandonDialog = true"
        >
          放弃本次准备
        </el-button>
      </div>

      <el-dialog
        v-model="showAbandonDialog"
        title="放弃数据准备"
        width="440px"
        :close-on-click-modal="false"
        data-test="abandon-dialog"
      >
        <p class="abandon-warning">
          确定要放弃本次数据准备吗？此操作不可撤销，放弃后需重新上传数据。
        </p>
        <template #footer>
          <el-button @click="showAbandonDialog = false">取消</el-button>
          <el-button
            type="danger"
            :loading="abandoning"
            data-test="abandon-confirm-btn"
            @click="onAbandon"
          >
            确定放弃
          </el-button>
        </template>
      </el-dialog>
    </main>
  </div>
</template>

<style scoped>
.wizard-page {
  min-height: 100%;
  max-width: var(--s1-page-workflow);
  margin: 0 auto;
  padding: 28px 20px 48px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.wizard-header h1 {
  margin: 0;
  font-size: 20px;
}

.wizard-sub {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.mono {
  font-family: ui-monospace, monospace;
}

.wizard-main {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.workflow-busy {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border: 1px solid var(--s1-cyan-dim);
  border-radius: var(--s1-radius-sm);
  background: var(--s1-cyan-ghost);
  color: var(--s1-cyan-strong);
  font-size: var(--s1-font-sm);
  animation: workflow-busy-in var(--s1-motion-base) var(--s1-ease-out) both;
}

.workflow-busy-spinner {
  width: 14px;
  height: 14px;
  flex: none;
  border: 2px solid rgba(70, 194, 190, 0.24);
  border-top-color: var(--s1-cyan);
  border-radius: 50%;
  animation: workflow-busy-spin 0.8s linear infinite;
}

@keyframes workflow-busy-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes workflow-busy-spin {
  to { transform: rotate(360deg); }
}

.validated-summary {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(320px, 1fr);
  gap: 24px 36px;
  padding: 28px;
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-1);
}

.status-kicker {
  color: var(--s1-success);
  font-size: var(--s1-font-sm);
  font-weight: 600;
}

.validated-copy h2 {
  margin: 8px 0;
  font-size: 24px;
}

.validated-copy p {
  margin: 0;
  color: var(--s1-text-dim);
  line-height: var(--s1-leading);
}

.validated-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  margin: 0;
  background: var(--s1-border);
  border: 1px solid var(--s1-border);
}

.validated-metrics div {
  min-width: 0;
  padding: 14px 16px;
  background: var(--s1-surface-2);
}

.validated-metrics dt,
.technical-details dt {
  color: var(--s1-text-faint);
  font-size: var(--s1-font-xs);
}

.validated-metrics dd {
  margin: 5px 0 0;
  color: var(--s1-text);
  font-size: var(--s1-font-lg);
  font-weight: 600;
  overflow-wrap: anywhere;
}

.validated-actions,
.technical-details {
  grid-column: 1 / -1;
}

.technical-details {
  padding-top: 16px;
  border-top: 1px solid var(--s1-border);
  color: var(--s1-text-dim);
  font-size: var(--s1-font-sm);
}

.technical-details summary {
  width: fit-content;
  cursor: pointer;
  color: var(--s1-text-dim);
}

.technical-details dl {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin: 14px 0 0;
}

.technical-details dd {
  margin: 4px 0 0;
  overflow-wrap: anywhere;
}

.wizard-loading {
  min-height: 200px;
}

.action-error {
  border: 1px solid #a43d3d;
  background: rgba(164, 61, 61, 0.15);
  color: #ef9a9a;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
}

.abandon-section {
  margin-top: 8px;
}

.abandon-warning {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--gmp-text);
}

@media (max-width: 720px) {
  .validated-summary {
    grid-template-columns: 1fr;
    padding: 20px;
  }

  .technical-details dl {
    grid-template-columns: 1fr;
  }
}
</style>
