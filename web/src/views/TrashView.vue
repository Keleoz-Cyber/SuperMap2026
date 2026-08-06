<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError, fetchTrashCases, purgeCase, restoreCase } from '../api/client'
import type { TrashCaseSummary } from '../api/types'
import CasePurgeDialog from '../components/cases/CasePurgeDialog.vue'
import PageNavigation from '../components/navigation/PageNavigation.vue'

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
    <PageNavigation home />
    <header class="page-header">
      <h1>回收站</h1>
      <p class="page-sub">已移入回收站的案例可恢复或永久删除。永久删除不可恢复。</p>
    </header>

    <div v-if="actionError" class="action-error" data-test="action-error">{{ actionError }}</div>

    <el-result
      v-if="loadError"
      icon="error"
      title="回收站加载失败"
      :sub-title="loadError"
    />

    <el-table
      v-else
      v-loading="loading"
      :data="trashCases"
      data-test="trash-list"
      stripe
      style="width: 100%"
    >
      <el-table-column prop="name" label="案例名称" min-width="160" />
      <el-table-column label="移入时间" width="180">
        <template #default="{ row }">
          {{ (row.trashed_at || '').slice(0, 19).replace('T', ' ') }}
        </template>
      </el-table-column>
      <el-table-column label="数据集" width="90" align="center">
        <template #default="{ row }">{{ row.counts?.datasets ?? 0 }}</template>
      </el-table-column>
      <el-table-column label="实验" width="90" align="center">
        <template #default="{ row }">{{ row.counts?.experiments ?? 0 }}</template>
      </el-table-column>
      <el-table-column label="成果" width="90" align="center">
        <template #default="{ row }">{{ row.counts?.results ?? 0 }}</template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <div class="row-actions" data-test="trash-row">
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
        </template>
      </el-table-column>
      <template #empty>
        <span>回收站为空</span>
      </template>
    </el-table>

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
</style>
