<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError, createCase, uploadDataset } from '../api/client'
import PageNavigation from '../components/navigation/PageNavigation.vue'
import DatasetIntakeStart from '../components/upload/DatasetIntakeStart.vue'

const router = useRouter()

const name = ref('')
const file = ref<File | null>(null)
const busy = ref(false)
const error = ref<string | null>(null)

const canSubmit = computed(
  () => name.value.trim().length > 0 && file.value !== null && !busy.value,
)

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  file.value = input.files?.[0] ?? null
}

async function submit() {
  if (!canSubmit.value) return
  busy.value = true
  error.value = null
  try {
    if (!file.value) return
    const created = await createCase(name.value.trim(), 'generic')
    const uploaded = await uploadDataset(created.id, file.value)
    // 上传成功以服务端返回的数据集记录为准（含状态与校验和）
    if (!uploaded.id || uploaded.status !== 'uploaded') {
      throw new ApiError('UPLOAD_NOT_ACCEPTED', '上传未被服务端接受', 200)
    }
    void router.push(`/cases/${created.id}/datasets/${uploaded.id}/prepare`)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="create-page product-page product-page--workflow">
    <DatasetIntakeStart
      mode="create" :file="file" input-test="case-file" :busy="busy" :can-submit="canSubmit"
      :error="error" error-test="create-error" submit-test="case-submit"
      @file-change="onFileChange" @submit="submit"
    >
      <template #before-file>
        <label class="field">
          <span>案例名称</span>
          <input v-model="name" class="gmp-input" data-test="case-name" placeholder="如：北区电阻率三维建模" maxlength="256" autocomplete="off" />
        </label>
      </template>
      <template #secondary-action>
        <PageNavigation current-label="新建案例" />
      </template>
    </DatasetIntakeStart>
  </div>
</template>

<style scoped>
.create-page {
  min-height: 100%;
  max-width: var(--s1-page-workflow);
  margin: 0 auto;
  padding: 40px 20px;
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 13px;
  color: var(--gmp-text-dim);
}

.gmp-input {
  background: var(--gmp-bg-soft);
  border: 1px solid var(--gmp-border);
  color: var(--gmp-text);
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 14px;
}

</style>
