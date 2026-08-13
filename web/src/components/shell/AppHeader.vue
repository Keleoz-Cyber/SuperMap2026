<script setup lang="ts">
// v0.9.0：全局应用头。纯展示组件——不 fetch 页面数据、不创建路由实例；
// 导航一律使用命名路由，服务状态与案例上下文由 AppShell/壳上下文传入。
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { Delete, MoreFilled, Upload } from '@element-plus/icons-vue'
import { WEB_VERSION } from '../../version'

const props = defineProps<{
  serviceState: 'unknown' | 'online' | 'offline'
  serviceVersion: string | null
  routeName?: string | null
  routePath?: string
  routeFocus?: unknown
}>()

const isCasesActive = computed(() => {
  if (props.routeName === 'home') return props.routeFocus === 'cases'
  return /^(\/cases|\/datasets|\/experiments|\/results)/.test(props.routePath ?? '')
})
const isHomeActive = computed(() => props.routeName === 'home' && !isCasesActive.value)

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
      <nav class="product-nav" aria-label="产品主导航">
        <RouterLink
          :to="{ name: 'home' }"
          class="product-link"
          :class="{ 'is-active': isHomeActive }"
          active-class=""
          data-test="shell-home-link"
        >
          首页
        </RouterLink>
        <RouterLink
          :to="{ name: 'home', query: { focus: 'cases' } }"
          class="product-link"
          :class="{ 'is-active': isCasesActive }"
          active-class=""
          data-test="shell-nav-cases"
        >
          案例
        </RouterLink>
        <RouterLink :to="{ name: 'case-create' }" class="product-link" data-test="shell-nav-ingest">
          数据接入
        </RouterLink>
      </nav>
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
      <RouterLink :to="{ name: 'trash' }" class="action ghost" data-test="shell-trash-link">
        <el-icon :size="15"><Delete /></el-icon>
        回收站
      </RouterLink>
    </div>
    <details class="mobile-menu" data-test="shell-mobile-menu">
      <summary aria-label="打开全局菜单">
        <el-icon :size="18"><MoreFilled /></el-icon>
      </summary>
      <nav class="mobile-menu-panel" aria-label="移动端全局菜单">
        <span class="mobile-service" role="status">
          <span class="dot" :class="serviceState === 'online' ? 'ok' : serviceState === 'offline' ? 'bad' : 'pending'"></span>
          {{ serviceState === 'online' ? '服务在线' : serviceState === 'offline' ? '服务离线' : '服务检测中' }}
          · v{{ serviceVersion ?? WEB_VERSION }}
        </span>
        <RouterLink :to="{ name: 'case-create' }">
          <el-icon :size="15"><Upload /></el-icon>
          导入数据
        </RouterLink>
        <RouterLink :to="{ name: 'trash' }">
          <el-icon :size="15"><Delete /></el-icon>
          回收站
        </RouterLink>
      </nav>
    </details>
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

.product-nav {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: var(--s1-space-3);
}

.product-link {
  color: var(--s1-text-dim);
  text-decoration: none;
  font-size: var(--s1-font-md);
  padding: 7px 11px;
  border-radius: var(--s1-radius-sm);
  white-space: nowrap;
}

.product-link:hover,
.product-link.is-active {
  color: var(--s1-cyan-strong);
  background: var(--s1-cyan-ghost);
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

.mobile-menu {
  display: none;
  position: relative;
}

.mobile-menu summary {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-sm);
  color: var(--s1-text);
  cursor: pointer;
  list-style: none;
}

.mobile-menu summary::-webkit-details-marker {
  display: none;
}

.mobile-menu summary:focus-visible {
  outline: 2px solid var(--s1-cyan-strong);
  outline-offset: 2px;
}

.mobile-menu-panel {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 1200;
  display: grid;
  min-width: 210px;
  padding: var(--s1-space-2);
  border: 1px solid var(--s1-border-strong);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-2);
  box-shadow: var(--s1-elevation-3);
}

.mobile-menu-panel a,
.mobile-service {
  display: flex;
  align-items: center;
  gap: var(--s1-space-2);
  padding: 10px 12px;
  color: var(--s1-text);
  text-decoration: none;
  border-radius: var(--s1-radius-sm);
  font-size: var(--s1-font-md);
}

.mobile-menu-panel a:hover {
  color: var(--s1-cyan-strong);
  background: var(--s1-cyan-ghost);
}

.mobile-service {
  color: var(--s1-text-dim);
  border-bottom: 1px solid var(--s1-border-soft);
}

@media (max-width: 900px) {
  .app-header {
    padding: 0 var(--s1-space-3);
    gap: var(--s1-space-2);
  }

  .brand-text small,
  .version {
    display: none;
  }

  .product-link {
    padding-inline: 7px;
  }
}

@media (max-width: 640px) {
  .app-header {
    position: sticky;
    padding: 0 var(--s1-space-2);
    gap: var(--s1-space-2);
  }

  .brand-text strong {
    font-size: var(--s1-font-md);
  }

  .product-nav {
    overflow-x: auto;
    scrollbar-width: none;
    margin-left: 0;
    gap: 0;
  }

  .product-link {
    font-size: var(--s1-font-sm);
  }

  .header-right {
    display: none;
  }

  .mobile-menu {
    display: block;
  }
}

@media (max-width: 420px) {
  .brand-text {
    display: none;
  }

  .product-link {
    padding-inline: 8px;
  }
}
</style>
