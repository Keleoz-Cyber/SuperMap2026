<script setup lang="ts">
// v0.9.0 V6 Task 3：成果专用顶栏（52px 紧凑横向结构）。
// 品牌 + 五段阶段导航 + 当前案例选择 + 导出分析报告唯一主动作。
// 无上下文入口显示明确 disabled 状态，不构造假 ID；服务状态/版本/回收站/
// 答辩模式不得挤占成果页主导航。
import { RouterLink } from 'vue-router'

export interface V6NavEntry {
  key: string
  label: string
  to: { name: string; params?: Record<string, string> } | null
  active?: boolean
}

const props = withDefaults(defineProps<{
  currentCaseId: string | null
  caseTitle: string | null
  caseOptions: Array<{ id: string; name: string }>
  nav: V6NavEntry[]
  exporting?: boolean
  exportReady?: boolean
}>(), { exporting: false, exportReady: true })

const emit = defineEmits<{
  (e: 'select-case', caseId: string): void
  (e: 'export-report'): void
}>()

void props

function onCaseChange(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  if (value) emit('select-case', value)
}
</script>

<template>
  <header class="v6-topbar" data-test="v6-result-topbar">
    <RouterLink :to="{ name: 'home' }" class="brand" data-test="v6-brand">
      <span class="brand-mark">G</span>
      <span class="brand-text">
        <strong>GeoModelingPlatform</strong>
        <small>深地属性建模平台</small>
      </span>
    </RouterLink>

    <nav class="stage-nav" aria-label="阶段导航">
      <template v-for="entry in nav" :key="entry.key">
        <RouterLink
          v-if="entry.to"
          :to="entry.to"
          class="stage-link"
          :class="{ active: entry.active }"
          :data-test="`v6-nav-${entry.key}`"
        >
          {{ entry.label }}
        </RouterLink>
        <span
          v-else
          class="stage-link disabled"
          :data-test="`v6-nav-${entry.key}`"
          :title="`${entry.label}缺少上下文`"
        >
          {{ entry.label }}
        </span>
      </template>
    </nav>

    <div class="topbar-right">
      <select
        class="case-select"
        data-test="v6-case-select"
        aria-label="当前案例"
        :value="currentCaseId ?? ''"
        @change="onCaseChange"
      >
        <option v-for="option in caseOptions" :key="option.id" :value="option.id">
          {{ option.name }}
        </option>
      </select>
      <button
        type="button"
        class="export-action"
        data-test="v6-export-report"
        :disabled="exporting || exportReady === false"
        @click="emit('export-report')"
      >
        {{ exporting ? '正在导出…' : '导出分析报告' }}
      </button>
    </div>
  </header>
</template>

<style scoped>
.v6-topbar {
  height: 52px;
  flex: none;
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 0 18px;
  border-bottom: 1px solid var(--s1-border);
  background: var(--s1-surface-1);
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
  color: var(--s1-text);
  flex: none;
}

.brand-mark {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  background: var(--s1-cyan-strong);
  color: #0b0f14;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.15;
}

.brand-text strong {
  font-size: 14px;
}

.brand-text small {
  font-size: 12px;
  color: var(--s1-text-faint);
}

.stage-nav {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
  min-width: 0;
}

.stage-link {
  font-size: 14px;
  color: var(--s1-text-dim);
  text-decoration: none;
  padding: 5px 12px;
  border-radius: 6px;
  white-space: nowrap;
}

.stage-link:hover {
  color: var(--s1-cyan-strong);
}

.stage-link.active {
  color: var(--s1-cyan-strong);
  background: var(--s1-cyan-ghost);
  font-weight: 600;
}

.stage-link.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: none;
}

.case-select {
  border: 1px solid var(--s1-border);
  background: var(--s1-bg-soft);
  color: var(--s1-text);
  border-radius: 6px;
  padding: 5px 10px;
  font-size: 12px;
  max-width: 180px;
}

.export-action {
  border: 1px solid var(--s1-cyan-strong);
  background: var(--s1-cyan-strong);
  color: #0b0f14;
  border-radius: 6px;
  padding: 6px 16px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

.export-action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
