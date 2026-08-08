<script setup lang="ts">
import type { AnalysisProvenance } from '../../api/types'

// v0.8.0 第二批 Task 5：导出与数据溯源——占位结构（导出逻辑属 Task 7，
// 此处仅渲染 provenance：source_sha256/dataset_version/generated_at/
// calculation_version + 禁用的导出命令）。溯源只含逻辑标识与哈希，绝不
// 出现原始文件路径。

defineProps<{
  provenance: AnalysisProvenance
  datasetId: string
  profile: string
}>()
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
      <el-button disabled data-test="export-command-json">导出 JSON</el-button>
      <el-button disabled data-test="export-command-csv">导出 CSV</el-button>
    </div>
    <p class="hint" data-test="export-placeholder-hint">
      导出功能将在后续批次就位；当前仅展示溯源信息，供复核统计口径与数据版本。
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

.hint {
  margin: 0;
  font-size: 12px;
  color: var(--gmp-text-faint);
}
</style>
