<script setup lang="ts">
import { ref } from 'vue'
import { Download } from '@element-plus/icons-vue'
import { ApiError, downloadAnalysisExport } from '../../api/client'
import type { AnalysisExportFormat, AnalysisProvenance } from '../../api/types'

// v0.8.0 第二批 Task 7：导出与数据溯源——JSON/CSV 真实导出接线。
// 两条命令（图标+文字）调用 downloadAnalysisExport，以 URL.createObjectURL
// + a[download] 触发浏览器保存，revokeObjectURL 清理；进行中 loading 且
// 双命令禁用（防重复触发），失败反馈 ApiError code+message。状态文案与
// 下载文件名保留当前 dataset/profile 身份。溯源渲染不变：只含逻辑标识
// 与哈希，绝不出现原始文件路径。设计 §2 的「可打印报告导出」在本批以
// JSON/CSV 摘要兑现，不引入第三种格式。

const props = defineProps<{
  provenance: AnalysisProvenance
  datasetId: string
  profile: string
}>()

const pendingFormat = ref<AnalysisExportFormat | null>(null)
const statusText = ref<string | null>(null)
const errorText = ref<string | null>(null)

async function runExport(format: AnalysisExportFormat) {
  if (pendingFormat.value !== null) return
  pendingFormat.value = format
  errorText.value = null
  statusText.value = `正在导出 ${format.toUpperCase()} 摘要（数据集 ${props.datasetId} · profile ${props.profile}）…`
  try {
    const { blob, filename } = await downloadAnalysisExport(props.datasetId, format)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.click()
    URL.revokeObjectURL(url)
    statusText.value = `已导出 ${filename}（数据集 ${props.datasetId} · profile ${props.profile}）`
  } catch (e) {
    statusText.value = null
    errorText.value =
      e instanceof ApiError
        ? `导出失败（${e.code}）：${e.message}`
        : `导出失败：${e instanceof Error ? e.message : String(e)}`
  } finally {
    pendingFormat.value = null
  }
}
</script>

<template>
  <section class="panel export-panel" data-test="analysis-export-panel">
    <h3>导出与数据溯源</h3>
    <dl class="provenance" data-test="export-provenance">
      <div class="prov-row">
        <dt>数据集</dt>
        <dd class="mono">{{ datasetId }}</dd>
      </div>
      <div class="prov-row">
        <dt>分析 profile</dt>
        <dd class="mono">{{ profile }}</dd>
      </div>
      <div class="prov-row">
        <dt>源数据 SHA-256</dt>
        <dd class="mono">{{ provenance.source_sha256.slice(0, 16) }}…</dd>
      </div>
      <div class="prov-row">
        <dt>数据版本</dt>
        <dd>v{{ provenance.dataset_version }}</dd>
      </div>
      <div class="prov-row">
        <dt>生成时间</dt>
        <dd class="mono">{{ provenance.generated_at }}</dd>
      </div>
      <div class="prov-row">
        <dt>计算版本</dt>
        <dd class="mono">{{ provenance.calculation_version }}</dd>
      </div>
    </dl>
    <div class="export-actions">
      <el-button
        type="primary"
        plain
        :icon="Download"
        :loading="pendingFormat === 'json'"
        :disabled="pendingFormat !== null"
        data-test="export-command-json"
        @click="runExport('json')"
      >
        导出 JSON
      </el-button>
      <el-button
        plain
        :icon="Download"
        :loading="pendingFormat === 'csv'"
        :disabled="pendingFormat !== null"
        data-test="export-command-csv"
        @click="runExport('csv')"
      >
        导出 CSV
      </el-button>
    </div>
    <el-alert
      v-if="errorText"
      type="error"
      :title="errorText"
      show-icon
      :closable="false"
      data-test="export-error"
      role="alert"
    />
    <p v-if="statusText" class="status" data-test="export-status">{{ statusText }}</p>
    <p class="hint" data-test="export-hint">
      导出为只读分析摘要（JSON 全量 / CSV 统计·分布·剖面表格），随附数据集与计算版本溯源；
      设计 §2 的可打印报告在本批以 JSON/CSV 摘要兑现，绝不包含原始文件路径。
    </p>
  </section>
</template>

<style scoped>
.panel {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

h3 {
  margin: 0;
  font-size: 15px;
}

.provenance {
  margin: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px 16px;
}

.prov-row dt {
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.prov-row dd {
  margin: 2px 0 0;
  font-size: 13px;
}

.mono {
  font-family: ui-monospace, monospace;
}

.export-actions {
  display: flex;
  gap: 10px;
}

.status {
  margin: 0;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.hint {
  margin: 0;
  font-size: 12px;
  color: var(--gmp-text-faint);
}
</style>
