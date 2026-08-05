<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ApiError,
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
import FileStep from '../components/upload/FileStep.vue'
import MappingStep from '../components/upload/MappingStep.vue'
import QualityStep from '../components/upload/QualityStep.vue'
import PageNavigation from '../components/navigation/PageNavigation.vue'

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

function describeError(e: unknown): string {
  if (e instanceof ApiError) return `${e.code}：${e.message}`
  return e instanceof Error ? e.message : String(e)
}

async function loadQuality() {
  try {
    report.value = await fetchQuality(datasetId.value)
  } catch (e) {
    // 尚未校验（QUALITY_NOT_EVALUATED）属正常中间态，其余错误上浮
    if (e instanceof ApiError && e.code === 'QUALITY_NOT_EVALUATED') {
      report.value = null
    } else {
      throw e
    }
  }
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
    if (ds.status === 'validated' || ds.status === 'blocked') {
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
    // 不以 HTTP 200 推断成功：必须看到服务端状态真正落为 mapped
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
  } catch (e) {
    actionError.value = describeError(e)
  } finally {
    confirming.value = false
  }
}

function onStart() {
  // v0.7.0：上传/映射/质量流程完成后进入统一案例工作台；
  // 新建实验由工作台的显式命令进入
  void router.push(`/cases/${caseId.value}`)
}
</script>

<template>
  <div class="wizard-page">
    <PageNavigation home />
    <header class="wizard-header">
      <h1>数据准备向导</h1>
      <p class="wizard-sub">
        案例 <span class="mono">{{ caseId }}</span> · 数据集
        <span class="mono">{{ datasetId }}</span>
      </p>
    </header>

    <el-result v-if="loadError" icon="error" title="数据集加载失败" :sub-title="loadError" />
    <div v-else-if="!dataset" v-loading="true" class="wizard-loading" />

    <main v-else class="wizard-main">
      <div v-if="actionError" class="action-error" data-test="action-error">{{ actionError }}</div>

      <FileStep :dataset="dataset" :inspection="inspection" @sheet-change="onSheetChange" />
      <MappingStep
        :inspection="inspection"
        :submitting="submitting"
        :conversion="conversion"
        @submit="onMappingSubmit"
      />
      <QualityStep
        :report="report"
        :validating="validating"
        :confirming="confirming"
        @validate="runValidate"
        @confirm="onConfirmWarnings"
        @start="onStart"
      />
    </main>
  </div>
</template>

<style scoped>
.wizard-page {
  min-height: 100%;
  max-width: 980px;
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
</style>
