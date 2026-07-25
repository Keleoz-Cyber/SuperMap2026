<script setup lang="ts">
import { computed, ref } from 'vue'

// 客户端只做 basename 去重与数量提示；文件集合是否合法由服务端权威判定。
const EXPECTED_DAT_COUNT = 22

const props = defineProps<{
  importing: boolean
}>()

const emit = defineEmits<{
  (e: 'import', files: File[]): void
}>()

// 两个入口各自保留选择结果，合并为一个待上传集合
const pickerFiles = ref<File[]>([])
const folderFiles = ref<File[]>([])

const files = computed(() => [...pickerFiles.value, ...folderFiles.value])

const duplicateNames = computed(() => {
  const seen = new Map<string, number>()
  for (const file of files.value) {
    seen.set(file.name, (seen.get(file.name) ?? 0) + 1)
  }
  return [...seen.entries()].filter(([, count]) => count > 1).map(([name]) => name)
})

const canSubmit = computed(
  () =>
    files.value.length >= EXPECTED_DAT_COUNT && duplicateNames.value.length === 0 && !props.importing,
)

function onPickerChange(event: Event) {
  const input = event.target as HTMLInputElement
  pickerFiles.value = Array.from(input.files ?? [])
}

function onFolderChange(event: Event) {
  const input = event.target as HTMLInputElement
  folderFiles.value = Array.from(input.files ?? [])
}

function submit() {
  if (!canSubmit.value) return
  emit('import', files.value)
}
</script>

<template>
  <section class="wizard-step" data-test="step-source">
    <h3><span class="step-no">1</span> 选择原始数据</h3>
    <p class="step-hint">
      选择包含 {{ EXPECTED_DAT_COUNT }} 个 DAT 的文件夹，或逐个选择 {{ EXPECTED_DAT_COUNT }} 个 DAT 文件。
      服务端将权威核验文件集合、逐文件哈希与派生合同。
    </p>

    <div class="picker-row">
      <label class="picker">
        <span class="picker-title">选择文件夹（Chromium）</span>
        <input type="file" webkitdirectory multiple data-test="micro-dat-folder" @change="onFolderChange" />
      </label>
      <label class="picker">
        <span class="picker-title">选择 {{ EXPECTED_DAT_COUNT }} 个 DAT</span>
        <input type="file" multiple accept=".dat" data-test="micro-dat-files" @change="onPickerChange" />
      </label>
    </div>

    <p class="file-count" data-test="micro-file-count">
      已选择 {{ files.length }} 个 DAT（需要 {{ EXPECTED_DAT_COUNT }} 个）
    </p>

    <div v-if="duplicateNames.length" class="dup-error" data-test="micro-dup-error">
      存在重复文件名（服务器将拒绝）：{{ duplicateNames.join('、') }}
    </div>

    <ul v-if="files.length" class="file-list" data-test="micro-file-list">
      <li v-for="(file, index) in files" :key="`${file.name}-${index}`">
        <span class="file-name">{{ file.name }}</span>
        <span class="file-size">{{ file.size }} B</span>
      </li>
    </ul>

    <div class="step-actions">
      <button class="gmp-btn primary" data-test="micro-import-submit" :disabled="!canSubmit" @click="submit">
        {{ importing ? '上传并派生中…' : '上传并由服务端派生' }}
      </button>
    </div>
  </section>
</template>

<style scoped>
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

.picker-row {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.picker {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: var(--gmp-text-dim);
}

.picker-title {
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.file-count {
  font-size: 13px;
  color: var(--gmp-text);
  margin: 0 0 10px;
}

.dup-error {
  border: 1px solid #a43d3d;
  background: rgba(164, 61, 61, 0.15);
  color: #ef9a9a;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
  margin-bottom: 10px;
}

.file-list {
  list-style: none;
  margin: 0 0 14px;
  padding: 0;
  max-height: 220px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.file-list li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  border: 1px solid var(--gmp-border);
  border-radius: 6px;
  padding: 5px 10px;
}

.file-name {
  font-family: ui-monospace, monospace;
  color: var(--gmp-text);
}

.file-size {
  color: var(--gmp-text-faint);
}

.step-actions {
  display: flex;
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

.gmp-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
