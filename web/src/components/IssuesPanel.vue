<script setup lang="ts">
import { computed, ref } from 'vue'
import type { FailedResult, IssueEntry } from '../api/types'

const props = defineProps<{
  issues: IssueEntry[]
  failedResults: FailedResult[]
}>()

const PREVIEW_COUNT = 6
const expanded = ref(false)

const visibleIssues = computed(() =>
  expanded.value ? props.issues : props.issues.slice(0, PREVIEW_COUNT),
)

function severityType(s: string): 'danger' | 'warning' | 'info' {
  if (s === 'error') return 'danger'
  if (s === 'warning') return 'warning'
  return 'info'
}

function severityLabel(s: string): string {
  if (s === 'error') return '错误'
  if (s === 'warning') return '警告'
  return '提示'
}
</script>

<template>
  <div class="issues-panel">
    <template v-if="failedResults.length">
      <div class="sub-title">失败结果（{{ failedResults.length }}）</div>
      <div v-for="f in failedResults" :key="f.dataset" class="failed-card">
        <div class="failed-head">
          <span class="mono break-all">{{ f.dataset }}</span>
          <el-tag size="small" type="danger" effect="plain">
            {{ f.status }} / {{ f.result_category }}
          </el-tag>
        </div>
        <div v-if="f.error_evidence" class="failed-evidence mono">{{ f.error_evidence }}</div>
      </div>
    </template>

    <div class="sub-title">已知问题与边界（{{ issues.length }}）</div>
    <div
      v-for="(issue, i) in visibleIssues"
      :key="issue.code ?? issue.issue_id ?? i"
      class="issue-item"
      :class="`sev-${issue.severity}`"
    >
      <div class="issue-head">
        <el-tag size="small" :type="severityType(issue.severity)" effect="dark">
          {{ severityLabel(issue.severity) }}
        </el-tag>
        <span class="mono issue-code">{{ issue.code ?? issue.issue_id }}</span>
        <el-tag v-if="issue.blocking" size="small" type="danger" effect="plain">阻塞</el-tag>
      </div>
      <div class="issue-message">{{ issue.message ?? issue.description }}</div>
      <div v-if="issue.scope" class="issue-scope">范围：{{ issue.scope }}</div>
      <el-collapse v-if="issue.evidence || issue.current_handling" class="issue-more">
        <el-collapse-item title="证据与当前处理">
          <p v-if="issue.evidence"><b>证据：</b>{{ issue.evidence }}</p>
          <p v-if="issue.current_handling"><b>当前处理：</b>{{ issue.current_handling }}</p>
        </el-collapse-item>
      </el-collapse>
    </div>
    <el-button
      v-if="issues.length > PREVIEW_COUNT"
      text
      type="primary"
      size="small"
      @click="expanded = !expanded"
    >
      {{ expanded ? '收起' : `展开全部（${issues.length}）` }}
    </el-button>
  </div>
</template>

<style scoped>
.failed-card {
  background: rgba(224, 92, 92, 0.06);
  border: 1px solid rgba(224, 92, 92, 0.35);
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 8px;
}

.failed-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
}

.failed-evidence {
  margin-top: 6px;
  color: var(--gmp-text-dim);
  line-height: 1.5;
  word-break: break-all;
}

.issue-item {
  border-left: 3px solid var(--gmp-border);
  background: var(--gmp-card);
  border-radius: 0 8px 8px 0;
  padding: 8px 10px;
  margin-bottom: 8px;
}

.issue-item.sev-error {
  border-left-color: var(--gmp-red);
}

.issue-item.sev-warning {
  border-left-color: var(--gmp-gold);
}

.issue-item.sev-info {
  border-left-color: var(--gmp-accent);
}

.issue-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.issue-code {
  color: var(--gmp-text-dim);
  font-size: 11px;
}

.issue-message {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.6;
}

.issue-scope {
  margin-top: 4px;
  font-size: 11px;
  color: var(--gmp-text-faint);
}

.issue-more {
  margin-top: 6px;
  --el-collapse-header-bg-color: transparent;
  --el-collapse-content-bg-color: transparent;
  --el-collapse-border-color: var(--gmp-border-soft);
  --el-collapse-header-text-color: var(--gmp-text-dim);
  --el-collapse-header-height: 30px;
  font-size: 12px;
}

.issue-more :deep(.el-collapse-item__wrap) {
  border-bottom: none;
}

.issue-more :deep(.el-collapse-item__header) {
  border-top: none;
  font-size: 12px;
}

.issue-more p {
  margin: 4px 0;
  color: var(--gmp-text-dim);
  line-height: 1.6;
  font-size: 12px;
}

.issue-more b {
  color: var(--gmp-text);
}
</style>
