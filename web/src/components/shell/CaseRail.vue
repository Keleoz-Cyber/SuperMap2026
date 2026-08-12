<script setup lang="ts">
// v0.9.0：首页案例轨。卡片主体进入工作台；指挥舱预览由独立按钮切换，
// 避免用户必须寻找卡片底部的小字入口。
// 自定义数据入口固定在轨道底部（设计：顶部固定入口 + 项目列表入口）。
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { ArrowRight, MoreFilled, Plus, View } from '@element-plus/icons-vue'
import type { CaseSummary } from '../../api/types'
import { PLATFORM_DEMO_3D_DOWNLOAD_URL } from '../../api/client'
import { CASE_PRESENTATION, resolveCaseProfile } from '../../domain/casePresentation'
import { coordinateLabel } from '../../utils/modelingLabels'

const props = defineProps<{
  cases: CaseSummary[]
  selectedCaseId: string | null
}>()

const emit = defineEmits<{
  select: [caseId: string]
  trash: [caseId: string]
}>()

function kindOf(c: CaseSummary): 'builtin_legacy' | 'builtin_preset' | 'user_upload' {
  if (c.workspace_kind) return c.workspace_kind
  return c.source_kind === 'upload' ? 'user_upload' : 'builtin_legacy'
}

const officialCases = computed(() =>
  props.cases.filter((c) => kindOf(c) === 'builtin_preset' || kindOf(c) === 'builtin_legacy'),
)
const userCases = computed(() => props.cases.filter((c) => kindOf(c) === 'user_upload'))

function presentationOf(c: CaseSummary) {
  return CASE_PRESENTATION[resolveCaseProfile(c.provenance_summary)]
}

function badgeOf(c: CaseSummary): string {
  if (kindOf(c) === 'builtin_preset') {
    return String(c.provenance_summary?.badge ?? 'CSV 预置 · 官方成果')
  }
  if (kindOf(c) === 'user_upload') return c.featured_result ? '已有成果' : '建模中'
  return c.status
}

function unitOf(c: CaseSummary): string | null {
  const unit = c.provenance_summary?.value_unit
  return typeof unit === 'string' ? unit : null
}

// 局部坐标如实标注（display_anchor_only，非真实地理配准）
function coordinateOf(c: CaseSummary): string | null {
  const kind = c.provenance_summary?.coordinate_kind
  return typeof kind === 'string' ? coordinateLabel(kind) : null
}

function dataFormOf(c: CaseSummary): string | null {
  const form = c.provenance_summary?.data_form
  return typeof form === 'string' ? form : null
}
</script>

<template>
  <aside class="case-rail" data-test="case-rail" aria-label="案例列表">
    <div class="rail-section">
      <h3 class="rail-title">官方案例</h3>
      <div
        v-for="c in officialCases"
        :key="c.case_id"
        class="case-card rail-item"
        :class="{ selected: c.case_id === selectedCaseId }"
        :data-case-accent="presentationOf(c).accent"
      >
        <RouterLink
          :to="`/cases/${c.case_id}`"
          class="item-select"
          data-test="enter-case-workspace"
          :data-case-id="c.case_id"
          :aria-label="`进入案例 ${c.title}`"
        >
          <span class="item-head">
            <span class="accent-dot" aria-hidden="true" />
            <span class="item-title">{{ c.title }}</span>
          </span>
          <span class="item-meta">
            <span v-if="unitOf(c)" class="meta-chip">{{ unitOf(c) }}</span>
            <span v-if="dataFormOf(c)" class="meta-line">{{ dataFormOf(c) }}</span>
            <span v-if="coordinateOf(c)" class="meta-line">坐标 {{ coordinateOf(c) }}</span>
            <span class="meta-badge">{{ badgeOf(c) }}</span>
          </span>
        </RouterLink>
        <div class="item-actions" @click.stop>
          <button
            type="button"
            class="item-btn preview"
            data-test="case-rail-item"
            :data-case-id="c.case_id"
            :aria-pressed="c.case_id === selectedCaseId"
            @click="emit('select', c.case_id)"
          >
            <el-icon :size="12"><View /></el-icon>
            {{ c.case_id === selectedCaseId ? '正在预览' : '在首页预览' }}
          </button>
          <RouterLink
            v-if="c.official_result"
            :to="c.official_result.url"
            class="item-btn ghost"
            data-test="open-official-result"
          >
            查看官方成果
          </RouterLink>
        </div>
      </div>
    </div>

    <div v-if="userCases.length > 0" class="rail-section">
      <h3 class="rail-title">用户项目</h3>
      <div
        v-for="c in userCases"
        :key="c.case_id"
        class="case-card rail-item"
        :class="{ selected: c.case_id === selectedCaseId }"
        data-case-accent="cyan"
      >
        <RouterLink
          :to="`/cases/${c.case_id}`"
          class="item-select"
          data-test="enter-case-workspace"
          :data-case-id="c.case_id"
          :aria-label="`进入案例 ${c.title}`"
        >
          <span class="item-head">
            <span class="accent-dot" aria-hidden="true" />
            <span class="item-title">{{ c.title }}</span>
          </span>
          <span class="item-meta">
            <span class="meta-badge">{{ badgeOf(c) }}</span>
          </span>
        </RouterLink>
        <span class="card-overflow" @click.stop>
          <el-dropdown data-test="trash-case-btn" @command="emit('trash', c.case_id)">
            <el-icon
              :size="16"
              class="overflow-trigger"
              role="button"
              aria-label="案例操作菜单"
              tabindex="0"
              @keydown.enter.prevent="($event.target as HTMLElement).click()"
            ><MoreFilled /></el-icon>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="trash">移入回收站</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </span>
        <div class="item-actions" @click.stop>
          <button
            type="button"
            class="item-btn preview"
            data-test="case-rail-item"
            :data-case-id="c.case_id"
            :aria-pressed="c.case_id === selectedCaseId"
            @click="emit('select', c.case_id)"
          >
            <el-icon :size="12"><View /></el-icon>
            {{ c.case_id === selectedCaseId ? '正在预览' : '在首页预览' }}
          </button>
          <template v-if="c.featured_result">
            <RouterLink
              :to="c.featured_result.url"
              class="item-btn primary"
              data-test="open-featured-result"
            >
              查看体渲染成果
              <el-icon :size="12"><ArrowRight /></el-icon>
            </RouterLink>
            <RouterLink
              :to="`/cases/${c.case_id}/experiments/new`"
              class="item-btn ghost"
              data-test="new-experiment"
            >
              新建建模实验
            </RouterLink>
          </template>
        </div>
      </div>
    </div>

    <RouterLink to="/cases/new" class="case-card create-card" data-test="create-case-card">
      <el-icon :size="16"><Plus /></el-icon>
      <span>
        <b>导入数据 / 新建建模</b>
        <small>上传 CSV / XLSX 点数据，走同一套建模链</small>
      </span>
    </RouterLink>
    <a
      class="demo-download"
      data-test="download-demo-data"
      :href="PLATFORM_DEMO_3D_DOWNLOAD_URL"
      download
    >
      下载固定演示数据
    </a>
  </aside>
</template>

<style scoped>
.case-rail {
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-4);
  min-width: 0;
  overflow-y: auto;
}

.rail-section {
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-2);
}

.rail-title {
  margin: 0;
  font-size: var(--s1-font-xs);
  font-weight: 600;
  letter-spacing: 0.1em;
  color: var(--s1-text-faint);
}

.rail-item {
  scroll-margin-top: 72px;
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-1);
  padding: var(--s1-space-3);
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-2);
  cursor: pointer;
  transition:
    border-color var(--s1-motion-base) var(--s1-ease-out),
    background var(--s1-motion-base) var(--s1-ease-out);
}

.rail-item:hover {
  border-color: var(--s1-border-strong);
  background: var(--s1-surface-2);
}

.rail-item.selected {
  border-color: var(--s1-case-accent);
  background: var(--s1-case-accent-soft);
  box-shadow: inset 0 0 0 1px var(--s1-case-accent);
}

.item-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.accent-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--s1-case-accent);
  box-shadow: 0 0 8px var(--s1-case-accent);
  flex: none;
}

.item-title {
  font-size: var(--s1-font-md);
  font-weight: 600;
  color: var(--s1-text-strong);
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-overflow {
  display: flex;
  align-items: center;
}

.item-select {
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-2);
  min-width: 0;
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  text-decoration: none;
}

.item-select:focus-visible {
  outline: 2px solid var(--s1-case-accent);
  outline-offset: 3px;
}

.card-overflow :deep(.el-dropdown) {
  scroll-margin-top: 72px;
}

.overflow-trigger {
  color: var(--s1-text-faint);
}

.overflow-trigger:hover {
  color: var(--s1-cyan-strong);
}

.item-meta {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
}

.meta-chip {
  color: var(--s1-case-accent);
  font-weight: 600;
}

.meta-line {
  color: var(--s1-text-dim);
}

.meta-badge {
  color: var(--s1-text-faint);
}

.item-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.item-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--s1-font-xs);
  border-radius: 6px;
  padding: 4px 10px;
  text-decoration: none;
  border: 1px solid transparent;
  background: transparent;
  cursor: pointer;
  transition:
    color var(--s1-motion-fast) var(--s1-ease-out),
    border-color var(--s1-motion-fast) var(--s1-ease-out);
}

.item-btn.primary {
  color: var(--s1-case-accent);
  border-color: var(--s1-case-accent);
}

.item-btn.preview {
  color: var(--s1-case-accent);
  border-color: var(--s1-border);
}

.item-btn.preview:hover,
.item-btn.preview[aria-pressed='true'] {
  color: var(--s1-text-strong);
  border-color: var(--s1-case-accent);
  background: var(--s1-case-accent-soft);
}

.item-btn.primary:hover {
  background: var(--s1-case-accent-soft);
}

.item-btn.ghost {
  color: var(--s1-text-dim);
}

.item-btn.ghost:hover {
  color: var(--s1-cyan-strong);
}

.create-card {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px dashed var(--s1-cyan-dim);
  border-radius: var(--s1-radius-md);
  background: var(--s1-cyan-ghost);
  color: var(--s1-cyan-strong);
  padding: var(--s1-space-3);
  text-decoration: none;
  transition: border-color var(--s1-motion-base) var(--s1-ease-out);
}

.create-card:hover {
  border-color: var(--s1-cyan-strong);
}

.create-card span {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.create-card b {
  font-size: var(--s1-font-md);
}

.create-card small {
  font-size: var(--s1-font-xs);
  color: var(--s1-text-dim);
}

.demo-download {
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
  text-decoration: underline;
  text-underline-offset: 3px;
  align-self: center;
}

.demo-download:hover {
  color: var(--s1-cyan-strong);
}

/* 手机档：案例轨收敛为横向紧凑选择条（场景与发现优先，切换入口保留），
   新建/下载入口由全局头承担，避免长列表把三维顶出首屏 */
@media (max-width: 480px) {
  .case-rail {
    flex-direction: column;
    overflow-x: hidden;
    gap: var(--s1-space-2);
    padding-bottom: 2px;
  }

  .rail-section {
    flex-direction: row;
    gap: var(--s1-space-2);
    max-width: 100%;
    overflow-x: auto;
    scrollbar-width: none;
  }

  .rail-title {
    display: none;
  }

  .rail-item {
    min-width: 132px;
    padding: var(--s1-space-2) var(--s1-space-3);
  }

  .rail-item .item-meta,
  .rail-item .item-actions {
    display: none;
  }

  .create-card,
  .demo-download {
    display: none;
  }
}
</style>
