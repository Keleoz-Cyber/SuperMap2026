<script setup lang="ts">
import { computed } from 'vue'
import type { DatasetVersionRecord, InspectionResult } from '../../api/types'

const props = defineProps<{
  dataset: DatasetVersionRecord
  inspection: InspectionResult | null
}>()

const emit = defineEmits<{
  (e: 'sheet-change', sheet: string): void
}>()

const profile = computed(() => props.dataset.profile as Record<string, unknown>)
const filename = computed(() => String(profile.value.original_filename ?? '未知文件'))
const sizeBytes = computed(() => Number(profile.value.size_bytes ?? 0))
const sha256 = computed(() => String(profile.value.source_sha256 ?? ''))

const previewColumns = computed(() => props.inspection?.columns ?? [])
const previewRows = computed(() => (props.inspection?.preview_rows ?? []).slice(0, 8))

function onSheetChange(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  if (value) emit('sheet-change', value)
}
</script>

<template>
  <section class="wizard-step" data-test="step-file">
    <h3><span class="step-no">1</span> 源文件</h3>
    <div class="file-grid">
      <div class="file-item">
        <span class="label">原始文件名</span>
        <b>{{ filename }}</b>
      </div>
      <div class="file-item">
        <span class="label">大小</span>
        <b>{{ sizeBytes }} 字节</b>
      </div>
      <div class="file-item">
        <span class="label">SHA-256</span>
        <b class="mono">{{ sha256.slice(0, 12) }}…</b>
      </div>
      <div class="file-item" v-if="inspection">
        <span class="label">数据行</span>
        <b>{{ inspection.row_count }} / 上限 {{ inspection.limits.max_upload_rows }}</b>
      </div>
      <div class="file-item" v-if="inspection?.sheets?.length">
        <span class="label">工作表</span>
        <select
          class="gmp-select"
          data-test="sheet-select"
          :value="inspection.sheet ?? ''"
          @change="onSheetChange"
        >
          <option v-for="name in inspection.sheets" :key="name" :value="name">{{ name }}</option>
        </select>
      </div>
    </div>

    <table v-if="previewRows.length" class="preview-table">
      <thead>
        <tr>
          <th v-for="col in previewColumns" :key="col.name">
            {{ col.name }}
            <span class="col-type">{{ col.inferred_type }}</span>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, idx) in previewRows" :key="idx">
          <td v-for="col in previewColumns" :key="col.name">{{ row[col.name] }}</td>
        </tr>
      </tbody>
    </table>
    <p v-else class="step-hint">源预览加载中…</p>
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

.file-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 24px;
  margin-bottom: 14px;
}

.file-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 13px;
}

.file-item .label {
  color: var(--gmp-text-faint);
  font-size: 12px;
}

.mono {
  font-family: ui-monospace, monospace;
}

.preview-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.preview-table th,
.preview-table td {
  border: 1px solid var(--gmp-border);
  padding: 6px 8px;
  text-align: left;
}

.preview-table th {
  background: var(--gmp-bg-soft);
  color: var(--gmp-text-dim);
}

.col-type {
  margin-left: 6px;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.step-hint {
  color: var(--gmp-text-faint);
  font-size: 13px;
}

.gmp-select {
  background: var(--gmp-bg-soft);
  border: 1px solid var(--gmp-border);
  color: var(--gmp-text);
  border-radius: 6px;
  padding: 4px 8px;
}
</style>
