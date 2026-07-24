<script setup lang="ts">
import { ref } from 'vue'
import { ApiError, createExport, createPublication } from '../../api/client'
import type { ExportRecord, PublicationRecord } from '../../api/types'

const props = defineProps<{
  resultId: string
}>()

const exportRecord = ref<ExportRecord | null>(null)
const publication = ref<PublicationRecord | null>(null)
const busy = ref<'export' | 'publish' | null>(null)
const error = ref<string | null>(null)

async function doExport() {
  busy.value = 'export'
  error.value = null
  try {
    exportRecord.value = await createExport(props.resultId)
  } catch (e) {
    error.value = e instanceof ApiError ? `${e.code}：${e.message}` : String(e)
  } finally {
    busy.value = null
  }
}

async function doPublish() {
  busy.value = 'publish'
  error.value = null
  try {
    publication.value = await createPublication(props.resultId)
  } catch (e) {
    error.value = e instanceof ApiError ? `${e.code}：${e.message}` : String(e)
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <section class="panel" data-test="export-publication-panel">
    <h3>证据导出与发布</h3>
    <p v-if="error" class="panel-error" data-test="panel-error">{{ error }}</p>

    <div class="columns">
      <div class="column">
        <div class="column-head">
          <h4>证据导出</h4>
          <button class="gmp-btn" data-test="export-button" :disabled="busy !== null" @click="doExport">
            {{ busy === 'export' ? '导出中…' : '生成证据包' }}
          </button>
        </div>
        <template v-if="exportRecord">
          <p class="sha mono" data-test="export-sha">SHA-256 {{ exportRecord.package_sha256.slice(0, 16) }}…</p>
          <ul class="file-list">
            <li v-for="file in exportRecord.files" :key="file" data-test="export-file">{{ file }}</li>
          </ul>
        </template>
        <p v-else class="empty">尚未导出（包含清单、元数据、指标、质量报告、选择历史与完整网格）</p>
      </div>

      <div class="column">
        <div class="column-head">
          <h4>发布</h4>
          <button class="gmp-btn" data-test="publish-button" :disabled="busy !== null" @click="doPublish">
            {{ busy === 'publish' ? '登记中…' : '请求发布' }}
          </button>
        </div>
        <p class="pub-status">
          状态：
          <el-tag size="small" :type="publication?.status === 'manual_required' ? 'warning' : 'info'" data-test="publication-status">
            {{ publication?.status ?? '未请求' }}
          </el-tag>
        </p>
        <p v-if="publication" class="pub-instruction" data-test="publication-instruction">
          {{ publication.evidence.manual_instruction }}
        </p>
        <p class="pub-note">发布状态独立于建模与导出结果；程序化 iServer 发布不可用时一律记为 manual_required。</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.panel {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 16px 18px;
}

.panel h3 {
  margin: 0 0 12px;
  font-size: 15px;
}

.columns {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 18px;
}

.column-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.column-head h4 {
  margin: 0;
  font-size: 13px;
  color: var(--gmp-text-dim);
}

.sha {
  font-size: 11px;
  color: var(--gmp-text-faint);
  margin: 0 0 8px;
}

.mono {
  font-family: ui-monospace, monospace;
}

.file-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  font-family: ui-monospace, monospace;
  color: var(--gmp-text-dim);
}

.empty {
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.pub-status {
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 8px;
}

.pub-instruction {
  font-size: 12px;
  color: #e5c76b;
  border: 1px solid #9a7b2d;
  border-radius: 8px;
  padding: 8px 12px;
  margin: 0 0 8px;
}

.pub-note {
  font-size: 11px;
  color: var(--gmp-text-faint);
  margin: 0;
}

.panel-error {
  color: #ef9a9a;
  font-size: 12px;
}

.gmp-btn {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text);
  border-radius: 8px;
  padding: 6px 14px;
  font-size: 12px;
  cursor: pointer;
}

.gmp-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
