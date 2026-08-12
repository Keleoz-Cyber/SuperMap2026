<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { ApiError, uploadDataset } from '../api/client'
import type { DatasetVersionRecord } from '../api/types'
import PageContextHeader from '../components/navigation/PageContextHeader.vue'
import DatasetIntakeStart from '../components/upload/DatasetIntakeStart.vue'

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
  if (e instanceof ApiError) return e.message
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
  <div class="upload-page product-page product-page--form">
    <PageContextHeader
      title="新增数据版本"
      subtitle="保留既有版本和成果，为当前案例接入一份新的点数据。"
      :case-id="caseId"
      current-label="数据接入"
    >
      <template #actions>
        <el-button :icon="ArrowLeft" title="返回案例工作台" @click="router.push(`/cases/${caseId}`)">
          返回案例工作台
        </el-button>
      </template>
    </PageContextHeader>

    <DatasetIntakeStart
      mode="version" :file="file" input-test="dataset-file" :busy="busy" :can-submit="canSubmit"
      :error="error" error-test="upload-error" submit-test="dataset-submit"
      @file-change="onFileChange" @submit="submit"
    />
  </div>
</template>

<style scoped>
.upload-page {
  min-height: 100%;
  padding: var(--s1-space-4) var(--s1-space-6) var(--s1-space-8);
  max-width: var(--s1-page-workflow);
  margin: 0 auto;
}
</style>
