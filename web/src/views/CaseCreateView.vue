<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError, createCase, uploadDataset } from '../api/client'
import PageNavigation from '../components/navigation/PageNavigation.vue'

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
    error.value = e instanceof ApiError ? `${e.code}：${e.message}` : e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="create-page">
    <header class="create-header">
      <h1>新建建模案例</h1>
      <p>数据接入与准备：上传 CSV / XLSX 点数据，完成字段映射与质量校验后即可开始建模实验。</p>
    </header>

    <div class="create-form">
      <label class="field">
        <span>案例名称</span>
        <input
          v-model="name"
          class="gmp-input"
          data-test="case-name"
          placeholder="如：××矿区电阻率建模"
          maxlength="256"
        />
      </label>

      <label class="field">
        <span>数据文件（CSV / XLSX，≤ 50 MiB、≤ 50 万行）</span>
        <input
          class="gmp-file"
          data-test="case-file"
          type="file"
          accept=".csv,.xlsx"
          @change="onFileChange"
        />
      </label>

      <div v-if="error" class="create-error" data-test="create-error">{{ error }}</div>

      <div class="create-actions">
        <button class="gmp-btn primary" data-test="case-submit" :disabled="!canSubmit" @click="submit">
          {{ busy ? '创建并上传中…' : '创建并进入数据准备' }}
        </button>
        <PageNavigation current-label="新建案例" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.create-page {
  min-height: 100%;
  max-width: 720px;
  margin: 0 auto;
  padding: 40px 20px;
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.create-header h1 {
  margin: 0 0 8px;
  font-size: 22px;
}

.create-header p {
  margin: 0;
  color: var(--gmp-text-dim);
  font-size: 13px;
}

.create-form {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
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

.gmp-file {
  color: var(--gmp-text);
  font-size: 13px;
}

.create-error {
  border: 1px solid #a43d3d;
  background: rgba(164, 61, 61, 0.15);
  color: #ef9a9a;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
}

.create-actions {
  display: flex;
  gap: 12px;
}

.gmp-btn {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text);
  border-radius: 8px;
  padding: 10px 20px;
  font-size: 14px;
  cursor: pointer;
}

.gmp-btn.primary {
  background: var(--gmp-accent);
  border-color: var(--gmp-accent);
  color: #0b0f14;
  font-weight: 600;
}

.gmp-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
