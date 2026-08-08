<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError, fetchTrashCases, purgeCase, restoreCase } from '../api/client'
import type { TrashCaseSummary } from '../api/types'
import CasePurgeDialog from '../components/cases/CasePurgeDialog.vue'
import PageNavigation from '../components/navigation/PageNavigation.vue'
import { formatDateTime } from '../utils/datetime'

const trashCases = ref<TrashCaseSummary[]>([])
const loading = ref(true)
const loadError = ref<string | null>(null)
const actionError = ref<string | null>(null)

const purgeVisible = ref(false)
const purgeTarget = ref<TrashCaseSummary | null>(null)

function describeError(e: unknown): string {
  if (e instanceof ApiError) return `${e.code}：${e.message}`
  return e instanceof Error ? e.message : String(e)
}

async function load() {
  loading.value = true
  loadError.value = null
  try {
    const resp = await fetchTrashCases()
    trashCases.value = resp.cases
  } catch (e) {
    loadError.value = describeError(e)
  } finally {
    loading.value = false
  }
}

async function handleRestore(caseId: string) {
  actionError.value = null
  try {
    await restoreCase(caseId)
    await load()
  } catch (e) {
    actionError.value = describeError(e)
  }
}

function openPurge(entry: TrashCaseSummary) {
  purgeTarget.value = entry
  purgeVisible.value = true
}

async function handlePurgeConfirm(name: string) {
  if (!purgeTarget.value) return
  actionError.value = null
  try {
    await purgeCase(purgeTarget.value.case_id, name)
    purgeVisible.value = false
    purgeTarget.value = null
    await load()
  } catch (e) {
    actionError.value = describeError(e)
  }
}

function handlePurgeClose() {
  purgeTarget.value = null
}

onMounted(load)
</script>

<template>
  <div class="trash-page">
    <PageNavigation current-label="回收站" />
    <header class="page-header">
      <h1>回收站</h1>
      <p class="page-sub">已移入回收站的案例可恢复或永久删除。永久删除不可恢复。</p>
    </header>

    <div v-if="actionError" class="action-error" role="alert" data-test="action-error">{{ actionError }}</div>

    <el-result
      v-if="loadError"
      icon="error"
      title="回收站加载失败"
      :sub-title="loadError"
      role="alert"
    />

    <div v-else v-loading="loading" data-test="trash-list" class="trash-table-wrap">
    <table class="trash-table">
      <thead>
        <tr>
          <th>案例名称</th>
          <th>移入时间</th>
          <th class="col-num">数据集</th>
          <th class="col-num">实验</th>
          <th class="col-num">成果</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in trashCases" :key="row.case_id" data-test="trash-row">
          <td>{{ row.name }}</td>
          <td>{{ formatDateTime(row.trashed_at || '') }}</td>
          <td class="col-num">{{ row.counts?.datasets ?? 0 }}</td>
          <td class="col-num">{{ row.counts?.experiments ?? 0 }}</td>
          <td class="col-num">{{ row.counts?.results ?? 0 }}</td>
          <td>
            <div class="row-actions">
              <el-button
                size="small"
                type="primary"
                plain
                :disabled="!row.can_restore"
                data-test="restore-case"
                @click="handleRestore(row.case_id)"
              >
                恢复
              </el-button>
              <el-button
                size="small"
                type="danger"
                plain
                :disabled="!row.can_purge"
                data-test="purge-case-open"
                @click="openPurge(row)"
              >
                永久删除
              </el-button>
            </div>
          </td>
        </tr>
        <tr v-if="trashCases.length === 0">
          <td colspan="6" class="empty-cell">回收站为空</td>
        </tr>
      </tbody>
    </table>
    </div>

    <CasePurgeDialog
      v-model:visible="purgeVisible"
      :case-name="purgeTarget?.name ?? ''"
      @confirm="handlePurgeConfirm"
      @close="handlePurgeClose"
    />
  </div>
</template>

<style scoped>
.trash-page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 28px;
  box-sizing: border-box;
  overflow-x: hidden;
}

.page-header {
  margin-bottom: 20px;
}

.page-header h1 {
  margin: 0 0 6px;
  font-size: 22px;
}

.page-sub {
  margin: 0;
  font-size: 13px;
  color: var(--gmp-text-dim);
}

.action-error {
  margin-bottom: 16px;
  padding: 10px 14px;
  border-radius: 8px;
  background: var(--el-color-danger-light-9);
  border: 1px solid var(--el-color-danger-light-5);
  color: var(--el-color-danger);
  font-size: 13px;
}

.row-actions {
  display: flex;
  gap: 8px;
}

.trash-table-wrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.trash-table {
  width: 100%;
  min-width: 560px;
  border-collapse: collapse;
  font-size: 13px;
}

.trash-table th,
.trash-table td {
  border: 1px solid var(--gmp-border);
  padding: 8px 12px;
  text-align: left;
}

.trash-table th {
  background: var(--gmp-bg-soft);
  color: var(--gmp-text-dim);
  font-weight: 600;
}

.trash-table .col-num {
  text-align: center;
}

.trash-table .empty-cell {
  text-align: center;
  color: var(--gmp-text-faint);
  padding: 24px;
}

@media (max-width: 480px) {
  .trash-page {
    padding: 16px 12px;
  }

  .trash-table {
    font-size: 12px;
  }

  .trash-table th,
  .trash-table td {
    padding: 6px 8px;
    white-space: nowrap;
  }

  .row-actions {
    flex-direction: column;
    gap: 4px;
  }
}
</style>
