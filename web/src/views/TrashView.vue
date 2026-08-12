<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError, fetchTrashCases, purgeCase, restoreCase } from '../api/client'
import type { TrashCaseSummary } from '../api/types'
import CasePurgeDialog from '../components/cases/CasePurgeDialog.vue'
import PageNavigation from '../components/navigation/PageNavigation.vue'
import AsyncState from '../components/states/AsyncState.vue'
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
  <div class="trash-page product-page">
    <PageNavigation current-label="回收站" />
    <header class="page-header">
      <h1>回收站</h1>
      <p class="page-sub">已移入回收站的案例可恢复或永久删除。永久删除不可恢复。</p>
    </header>

    <div v-if="actionError" class="action-error" role="alert" data-test="action-error">{{ actionError }}</div>

    <AsyncState
      v-if="loadError"
      kind="error"
      title="回收站加载失败"
      :impact="loadError"
      next-action="返回首页或稍后重试"
    />

    <div v-else-if="loading" v-loading="true" class="trash-loading" data-test="trash-loading" />

    <section v-else-if="trashCases.length === 0" class="trash-empty" data-test="trash-empty">
      <span class="empty-mark" aria-hidden="true">0</span>
      <div>
        <p class="empty-kicker">回收站已清空</p>
        <h2>没有待处理的案例</h2>
        <p>已删除的案例会暂存在这里。在此之前，可以返回案例总览或创建新的建模案例。</p>
      </div>
      <div class="empty-actions">
        <router-link class="gmp-btn primary" to="/" data-test="trash-empty-home">返回首页</router-link>
        <router-link class="gmp-btn" to="/cases/new" data-test="trash-empty-create">新建案例</router-link>
      </div>
    </section>

    <div v-else data-test="trash-list" class="trash-list">
      <div class="trash-table-wrap">
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
              <td><strong>{{ row.name }}</strong></td>
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
          </tbody>
        </table>
      </div>

      <div class="trash-mobile-list" aria-label="已删除案例">
        <article v-for="row in trashCases" :key="row.case_id" class="trash-mobile-item" data-test="trash-mobile-item">
          <div class="mobile-item-head">
            <div>
              <h2>{{ row.name }}</h2>
              <p>{{ formatDateTime(row.trashed_at || '') }} 移入</p>
            </div>
            <span>{{ (row.counts?.datasets ?? 0) + (row.counts?.experiments ?? 0) + (row.counts?.results ?? 0) }} 项关联内容</span>
          </div>
          <dl class="mobile-counts">
            <div><dt>数据集</dt><dd>{{ row.counts?.datasets ?? 0 }}</dd></div>
            <div><dt>实验</dt><dd>{{ row.counts?.experiments ?? 0 }}</dd></div>
            <div><dt>成果</dt><dd>{{ row.counts?.results ?? 0 }}</dd></div>
          </dl>
          <div class="mobile-actions">
            <el-button type="primary" plain :disabled="!row.can_restore" data-test="restore-case-mobile" @click="handleRestore(row.case_id)">恢复</el-button>
            <el-button type="danger" plain :disabled="!row.can_purge" data-test="purge-case-open-mobile" @click="openPurge(row)">永久删除</el-button>
          </div>
        </article>
      </div>
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
  max-width: var(--s1-page-standard);
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
  font-size: 14px;
  color: var(--gmp-text-dim);
}

.trash-loading {
  min-height: 260px;
}

.trash-empty {
  min-height: min(52vh, 460px);
  display: grid;
  grid-template-columns: auto minmax(0, 560px) auto;
  align-items: center;
  justify-content: center;
  gap: var(--s1-space-6);
  border-block: 1px solid var(--s1-border);
}

.empty-mark {
  display: grid;
  place-items: center;
  width: 72px;
  aspect-ratio: 1;
  border: 1px solid var(--s1-border-strong);
  color: var(--s1-text-faint);
  font-size: 28px;
  font-variant-numeric: tabular-nums;
}

.empty-kicker {
  margin: 0 0 4px;
  color: var(--s1-cyan-strong);
  font-size: var(--s1-font-xs);
  font-weight: 600;
}

.trash-empty h2 {
  margin: 0 0 8px;
  font-size: var(--s1-font-2xl);
}

.trash-empty p:last-child {
  margin: 0;
  color: var(--s1-text-dim);
  line-height: var(--s1-leading);
}

.empty-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s1-space-2);
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

.trash-mobile-list {
  display: none;
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

@media (max-width: 480px) {
  .trash-page {
    padding: 16px 12px;
  }

  .page-header {
    margin-bottom: 16px;
  }

  .trash-empty {
    min-height: 56vh;
    grid-template-columns: 1fr;
    align-content: center;
    justify-items: start;
    gap: var(--s1-space-4);
  }

  .empty-mark {
    width: 56px;
    font-size: 22px;
  }

  .empty-actions,
  .empty-actions .gmp-btn {
    width: 100%;
  }

  .empty-actions .gmp-btn {
    justify-content: center;
  }

  .trash-table-wrap {
    display: none;
  }

  .trash-mobile-list {
    display: grid;
    gap: 12px;
  }

  .trash-mobile-item {
    min-width: 0;
    padding: 16px;
    border: 1px solid var(--s1-border);
    background: var(--s1-surface-2);
  }

  .mobile-item-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }

  .mobile-item-head h2,
  .mobile-item-head p {
    margin: 0;
  }

  .mobile-item-head h2 {
    font-size: 16px;
  }

  .mobile-item-head p,
  .mobile-item-head > span {
    color: var(--s1-text-faint);
    font-size: 12px;
  }

  .mobile-item-head > span {
    flex: 0 0 auto;
  }

  .mobile-counts {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    margin: 16px 0;
    border-block: 1px solid var(--s1-border);
  }

  .mobile-counts div {
    padding: 10px 0;
    text-align: center;
  }

  .mobile-counts dt {
    color: var(--s1-text-faint);
    font-size: 12px;
  }

  .mobile-counts dd {
    margin: 4px 0 0;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }

  .mobile-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }

  .mobile-actions :deep(.el-button) {
    width: 100%;
    margin: 0;
  }
}
</style>
