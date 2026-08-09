<script setup lang="ts">
// v0.9.0：全局应用头。纯展示组件——不 fetch 页面数据、不创建路由实例；
// 导航一律使用命名路由，服务状态与案例上下文由 AppShell/壳上下文传入。
import { RouterLink } from 'vue-router'
import { Delete, DataAnalysis, Upload } from '@element-plus/icons-vue'
import { WEB_VERSION } from '../../version'
import { useShellContext } from '../../stores/shellContext'

const props = defineProps<{
  serviceState: 'unknown' | 'online' | 'offline'
  serviceVersion: string | null
}>()

const context = useShellContext()

void props
</script>

<template>
  <header class="app-header">
    <div class="header-left">
      <RouterLink :to="{ name: 'home' }" class="brand" data-test="shell-brand">
        <span class="brand-mark" aria-hidden="true">G</span>
        <span class="brand-text">
          <strong>GeoModelingPlatform</strong>
          <small>深地属性建模综合指挥舱</small>
        </span>
      </RouterLink>
      <RouterLink :to="{ name: 'home' }" class="home-link" data-test="shell-home-link">
        首页
      </RouterLink>
      <div v-if="context.caseTitle" class="case-context" data-test="shell-case-context">
        <span class="ctx-sep" aria-hidden="true">/</span>
        <span class="ctx-title">{{ context.caseTitle }}</span>
        <span v-if="context.stageLabel" class="ctx-stage">{{ context.stageLabel }}</span>
      </div>
    </div>

    <div class="header-right">
      <span
        class="service-pill"
        :class="serviceState"
        data-test="shell-service-status"
        role="status"
      >
        <span class="dot" :class="serviceState === 'online' ? 'ok' : serviceState === 'offline' ? 'bad' : 'pending'"></span>
        {{ serviceState === 'online' ? '服务在线' : serviceState === 'offline' ? '服务离线' : '服务检测中' }}
      </span>
      <span class="version mono" data-test="shell-version">v{{ serviceVersion ?? WEB_VERSION }}</span>
      <RouterLink
        :to="{ name: 'case-create' }"
        class="action primary"
        data-test="global-create-case"
      >
        <el-icon :size="15"><Upload /></el-icon>
        导入数据 / 新建建模
      </RouterLink>
      <RouterLink
        :to="{ name: 'presentation' }"
        class="action ghost"
        data-test="presentation-mode-entry"
        aria-label="进入答辩模式"
      >
        <el-icon :size="15"><DataAnalysis /></el-icon>
        答辩模式
      </RouterLink>
      <RouterLink :to="{ name: 'trash' }" class="action ghost" data-test="shell-trash-link">
        <el-icon :size="15"><Delete /></el-icon>
        回收站
      </RouterLink>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  position: sticky;
  top: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s1-space-4);
  padding: 0 var(--s1-space-6);
  height: 52px;
  background: var(--s1-surface-glass);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--s1-border-soft);
}

.header-left,
.header-right {
  display: flex;
  align-items: center;
  gap: var(--s1-space-3);
  min-width: 0;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
  color: var(--s1-text-strong);
}

.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  font-weight: 700;
  font-size: 15px;
  color: #06110f;
  background: linear-gradient(135deg, var(--s1-cyan-strong), var(--s1-cyan));
  box-shadow: 0 0 12px rgba(70, 194, 190, 0.35);
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.15;
}

.brand-text strong {
  font-size: var(--s1-font-lg);
  letter-spacing: 0.02em;
}

.brand-text small {
  font-size: var(--s1-font-xs);
  color: var(--s1-text-dim);
  letter-spacing: 0.08em;
}

.home-link {
  color: var(--s1-text-dim);
  text-decoration: none;
  font-size: var(--s1-font-md);
  padding: 4px 8px;
  border-radius: 6px;
}

.home-link:hover {
  color: var(--s1-cyan-strong);
}

.case-context {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  font-size: var(--s1-font-md);
  color: var(--s1-text-dim);
}

.ctx-title {
  color: var(--s1-case-accent);
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 220px;
}

.ctx-stage {
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
  border: 1px solid var(--s1-border);
  border-radius: 999px;
  padding: 1px 8px;
}

.service-pill {
  display: inline-flex;
  align-items: center;
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
  border: 1px solid var(--s1-border);
  border-radius: 999px;
  padding: 3px 10px;
}

.version {
  color: var(--s1-text-faint);
}

.action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--s1-font-md);
  border-radius: var(--s1-radius-sm);
  padding: 6px 12px;
  text-decoration: none;
  cursor: pointer;
  border: 1px solid transparent;
  transition:
    border-color var(--s1-motion-fast) var(--s1-ease-out),
    color var(--s1-motion-fast) var(--s1-ease-out),
    background var(--s1-motion-fast) var(--s1-ease-out);
}

.action.primary {
  background: var(--s1-cyan-ghost);
  border-color: var(--s1-cyan-dim);
  color: var(--s1-cyan-strong);
}

.action.primary:hover {
  background: rgba(70, 194, 190, 0.22);
}

.action.ghost {
  background: transparent;
  border-color: var(--s1-border);
  color: var(--s1-text-dim);
}

.action.ghost:hover:not(:disabled) {
  color: var(--s1-cyan-strong);
  border-color: var(--s1-cyan-dim);
}

.action.ghost:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

@media (max-width: 900px) {
  .app-header {
    padding: 0 var(--s1-space-3);
    gap: var(--s1-space-2);
  }

  .brand-text small,
  .home-link,
  .version {
    display: none;
  }

  .ctx-stage {
    display: none;
  }
}

@media (max-width: 640px) {
  .app-header {
    padding: 0 var(--s1-space-2);
    gap: var(--s1-space-2);
  }

  .brand-text strong {
    font-size: var(--s1-font-md);
  }

  /* 手机档：服务状态收敛为圆点，次级入口让位给主动作，避免横向溢出 */
  .service-pill {
    font-size: 0;
    padding: 6px;
    gap: 0;
  }

  .header-right .action.ghost {
    display: none;
  }

  .action.primary {
    padding: 6px 10px;
    font-size: var(--s1-font-sm);
  }
}
</style>
