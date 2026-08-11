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

const showAbandonDialog = ref(false)
const abandoning = ref(false)

const showValidated = computed(
  () =>
    dataset.value !== null &&
    dataset.value.status === 'validated' &&
    report.value === null,
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
  if (e instanceof ApiError) return `${e.code}：${e.message}`
  return e instanceof Error ? e.message : String(e)
}

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
    const [ds, insp] = await Promise.all([
      fetchDataset(datasetId.value),
      fetchInspection(datasetId.value),
    ])
    dataset.value = ds
    inspection.value = insp
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
        案例 <span class="mono">{{ caseId }}</span> · 数据集
        <span class="mono">{{ datasetId }}</span>
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

      <div v-if="showValidated" data-test="wizard-step-validated">
        <el-result
          icon="success"
          title="数据准备完成"
          sub-title="数据已通过质量校验，可以开始实验与空间结构分析。"
        >
          <template #extra>
            <el-button type="primary" data-test="enter-workspace" @click="onStart">
              进入案例工作台
            </el-button>
          </template>
        </el-result>
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
</style>
