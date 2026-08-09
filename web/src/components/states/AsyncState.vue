<script setup lang="ts">
// v0.9.0：全站统一异步状态组件。每种状态必须回答三件事：
// 发生了什么（title）、哪些能力受影响（impact）、用户下一步做什么（nextAction）。
// loading 绝不编造影响/建议文案；error/offline/degraded 必须如实给出。
import { computed } from 'vue'
import {
  CircleClose,
  Connection,
  DocumentDelete,
  FolderOpened,
  Loading,
  Warning,
} from '@element-plus/icons-vue'
import type { Component } from 'vue'

export type AsyncStateKind = 'loading' | 'empty' | 'error' | 'offline' | 'degraded' | 'nodata'

const props = defineProps<{
  kind: AsyncStateKind
  title: string
  impact?: string
  nextAction?: string
  errorCode?: string
}>()

const ICONS: Record<AsyncStateKind, Component> = {
  loading: Loading,
  empty: FolderOpened,
  error: CircleClose,
  offline: Connection,
  degraded: Warning,
  nodata: DocumentDelete,
}

const icon = computed(() => ICONS[props.kind])
</script>

<template>
  <div class="async-state" :class="`is-${kind}`" role="status" :data-state="kind">
    <el-icon :size="30" class="state-icon" :class="{ spin: kind === 'loading' }">
      <component :is="icon" />
    </el-icon>
    <p class="state-title">{{ title }}</p>
    <p v-if="impact" class="state-line">
      <span class="line-label">受影响能力</span>{{ impact }}
    </p>
    <p v-if="nextAction" class="state-line">
      <span class="line-label">下一步</span>{{ nextAction }}
    </p>
    <code v-if="errorCode" class="state-code mono">{{ errorCode }}</code>
    <div v-if="$slots.action" class="state-action">
      <slot name="action" />
    </div>
  </div>
</template>

<style scoped>
.async-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--s1-space-2);
  padding: var(--s1-space-8) var(--s1-space-6);
  text-align: center;
  border: 1px dashed var(--s1-border);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-1);
  min-height: 160px;
}

.state-icon {
  color: var(--s1-text-faint);
}

.is-error .state-icon {
  color: var(--s1-error);
}

.is-offline .state-icon,
.is-degraded .state-icon {
  color: var(--s1-warning);
}

.is-loading .state-icon {
  color: var(--s1-cyan);
}

.spin {
  animation: async-state-spin 1.1s linear infinite;
}

@keyframes async-state-spin {
  to {
    transform: rotate(360deg);
  }
}

.state-title {
  margin: 0;
  font-size: var(--s1-font-lg);
  font-weight: 600;
  color: var(--s1-text);
}

.state-line {
  margin: 0;
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
  line-height: var(--s1-leading);
  max-width: 520px;
}

.line-label {
  display: inline-block;
  margin-right: 8px;
  color: var(--s1-text-faint);
}

.state-code {
  font-size: var(--s1-font-xs);
  color: var(--s1-warning);
  background: var(--s1-surface-2);
  border: 1px solid var(--s1-border);
  border-radius: 6px;
  padding: 2px 8px;
}

.state-action {
  margin-top: var(--s1-space-2);
}
</style>
