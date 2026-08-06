<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { ApiError, uploadDataset } from '../api/client'
import type { DatasetVersionRecord } from '../api/types'

const route = useRoute()
const router = useRouter()
const caseId = computed(() => String(route.params.caseId))

const file = ref<File | null>(null)
const busy = ref(false)
const error = ref<string | null>(null)

const canSubmit = computed(() => file.value !== null && !busy.value)

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  file.value = input.files?.[0] ?? null
}

function describeError(e: unknown): string {
  if (e instanceof ApiError) return `${e.code}：${e.message}`
  return e instanceof Error ? e.message : String(e)
}

async function submit() {
  if (!canSubmit.value || !file.value) return
  busy.value = true
  error.value = null
  try {
    const uploaded: DatasetVersionRecord = await uploadDataset(caseId.value, file.value)
    if (!uploaded.id || uploaded.status !== 'uploaded') {
      throw new ApiError('UPLOAD_NOT_ACCEPTED', '上传未被服务端接受', 200)
    }
    void router.push(`/cases/${caseId.value}/datasets/${uploaded.id}/prepare`)
  } catch (e) {
    error.value = describeError(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="upload-page">
    <header class="upload-header">
      <el-button :icon="ArrowLeft" circle title="返回案例工作台" @click="router.push(`/cases/${caseId}`)" />
      <div class="header-title">
        <h1>上传数据到案例</h1>
        <p class="header-sub">
          案例 <span class="mono">{{ caseId }}</span> · 上传 CSV / XLSX 点数据继续数据准备
        </p>
      </div>
    </header>

    <div class="upload-form">
      <label class="field">
        <span>数据文件（CSV / XLSX，≤ 50 MiB、≤ 50 万行）</span>
        <input
          class="gmp-file"
          data-test="dataset-file"
          type="file"
          accept=".csv,.xlsx"
          @change="onFileChange"
        />
      </label>

      <div v-if="error" class="upload-error" data-test="upload-error">{{ error }}</div>

      <div class="upload-actions">
        <el-button
          type="primary"
          data-test="dataset-submit"
          :loading="busy"
          :disabled="!canSubmit"
          @click="submit"
        >
          {{ busy ? '上传中…' : '上传并进入数据准备' }}
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.upload-page {
  min-height: 100vh;
  background: #0f141c;
  color: #d5dde8;
  padding: 16px 24px 40px;
  max-width: 720px;
  margin: 0 auto;
}
.upload-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.header-title h1 {
  margin: 0;
  font-size: 20px;
}
.header-sub {
  margin: 6px 0 0;
  color: #93a1b3;
  font-size: 13px;
}
.mono {
  font-family: ui-monospace, monospace;
}
.upload-form {
  background: #151c26;
  border: 1px solid #263142;
  border-radius: 8px;
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 13px;
  color: #93a1b3;
}
.gmp-file {
  color: #d5dde8;
  font-size: 13px;
}
.upload-error {
  border: 1px solid #a43d3d;
  background: rgba(164, 61, 61, 0.15);
  color: #ef9a9a;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
}
.upload-actions {
  display: flex;
  gap: 12px;
}
</style>
