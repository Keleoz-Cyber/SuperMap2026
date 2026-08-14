<script setup lang="ts">
// v0.9.0：全局应用头。纯展示组件——不 fetch 页面数据、不创建路由实例；
// 导航一律使用命名路由，服务状态与案例上下文由 AppShell/壳上下文传入。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { Delete, MoreFilled, Setting, Upload } from '@element-plus/icons-vue'
import { WEB_VERSION } from '../../version'

const props = defineProps<{
  serviceState: 'unknown' | 'online' | 'offline'
  serviceVersion: string | null
}>()

// 大屏时钟：真实本地时间
const now = ref(new Date())
let clockTimer: number | undefined

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

const clockText = computed(() => {
  const d = now.value
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ` +
    `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`
})

onMounted(() => {
  clockTimer = window.setInterval(() => {
    now.value = new Date()
  }, 1000)
})
onBeforeUnmount(() => {
  if (clockTimer !== undefined) window.clearInterval(clockTimer)
})

const emit = defineEmits<{ (event: 'open-ai-settings'): void }>()

void props
</script>

<template>
  <header class="app-header">
    <div class="header-left">
      <span class="version mono" data-test="shell-version">v{{ serviceVersion ?? WEB_VERSION }}</span>
      <nav class="product-nav" aria-label="产品主导航">
        <RouterLink
          :to="{ name: 'home' }"
          class="product-link action ghost"
          data-test="shell-home-link"
        >
          首页
        </RouterLink>
      </nav>
      <span class="hero-clock mono" aria-hidden="true">{{ clockText }}</span>
      <span
        class="service-pill"
        :class="serviceState"
        data-test="shell-service-status"
        role="status"
      >
        <span class="dot" :class="serviceState === 'online' ? 'ok' : serviceState === 'offline' ? 'bad' : 'pending'"></span>
        {{ serviceState === 'online' ? '服务在线' : serviceState === 'offline' ? '服务离线' : '服务检测中' }}
      </span>
    </div>

    <div class="platform-hero" data-test="shell-platform-title" aria-hidden="true">
      <span class="hero-line"></span>
      <span class="hero-title">地质属性三维建模与智能分析平台</span>
      <span class="hero-line right"></span>
    </div>

    <div class="header-right">
      <button type="button" class="action ghost" data-test="shell-ai-settings" @click="emit('open-ai-settings')">
        <el-icon :size="15"><Setting /></el-icon>
        <span class="ai-settings-label">AI 设置</span>
      </button>
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
        <button type="button" data-test="shell-mobile-ai-settings" @click="emit('open-ai-settings')">
          <el-icon :size="15"><Setting /></el-icon>
          AI 服务设置
        </button>
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
  gap: var(--s1-space-3);
  padding: 0 var(--s1-space-6);
  height: 60px;
  background: linear-gradient(180deg, rgba(9, 20, 44, 0.92), rgba(7, 15, 34, 0.78));
  backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(74, 182, 232, 0.22);
  box-shadow: 0 1px 18px rgba(30, 110, 220, 0.14);
}

/* 全局主标题：相对整个头部绝对居中，两侧渐变流线 */
.platform-hero {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 26px;
  pointer-events: none;
}

.hero-line {
  flex: none;
  width: clamp(48px, 10vw, 160px);
  height: 2px;
  background: linear-gradient(90deg, transparent, rgba(70, 190, 255, 0.75));
  position: relative;
}

.hero-line::after {
  content: '';
  position: absolute;
  right: 0;
  top: -2px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #8fdcff;
  box-shadow: 0 0 10px rgba(70, 200, 255, 0.9);
}

.hero-line.right {
  transform: scaleX(-1);
}

.hero-title {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.22em;
  text-indent: 0.22em;
  white-space: nowrap;
  background: linear-gradient(180deg, #f0faff 15%, #79ccff 85%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  text-shadow: 0 0 22px rgba(70, 190, 255, 0.4);
}

.hero-clock {
  color: #9fd8ff;
  font-size: 12px;
  letter-spacing: 0.08em;
  white-space: nowrap;
}

/* 窄屏收敛：先收时钟和流线，再收标题档，最后整体隐藏 */
@media (max-width: 1400px) {
  .hero-clock,
  .hero-line {
    display: none;
  }

  .hero-title {
    font-size: 19px;
  }
}

@media (max-width: 1150px) {
  .platform-hero {
    display: none;
  }
}

.header-left,
.header-right {
  display: flex;
  align-items: center;
  gap: var(--s1-space-3);
  min-width: 0;
}

/* 左列信息层级：版本号弱化垫底，时钟与状态留出呼吸间距 */
.header-left .version {
  margin-right: 2px;
}

.header-left .hero-clock {
  margin-left: var(--s1-space-2);
}

.product-nav {
  display: flex;
  align-items: center;
  gap: 2px;
}

.product-link {
  color: var(--s1-text-dim);
  text-decoration: none;
  font-size: var(--s1-font-md);
  padding: 6px 14px;
  border-radius: var(--s1-radius-sm);
  white-space: nowrap;
}

/* 首页入口采用与右侧操作一致的幽灵按钮样式 */
.product-link.action.ghost {
  color: var(--s1-text-dim);
}

.product-link.action.ghost:hover {
  color: var(--s1-cyan-strong);
  background: transparent;
}

.product-link:hover,
.product-link.router-link-active {
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
  background: rgba(74, 182, 232, 0.22);
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
.mobile-menu-panel button,
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

.mobile-menu-panel button { border: 0; background: transparent; text-align: left; cursor: pointer; }

.mobile-menu-panel a:hover {
  color: var(--s1-cyan-strong);
  background: var(--s1-cyan-ghost);
}

.mobile-service {
  color: var(--s1-text-dim);
  border-bottom: 1px solid var(--s1-border-soft);
}

@media (max-width: 1200px) {
  .ai-settings-label {
    display: none;
  }

  [data-test="shell-ai-settings"] {
    padding-inline: 8px;
  }
}

@media (max-width: 900px) {
  .app-header {
    padding: 0 var(--s1-space-3);
    gap: var(--s1-space-2);
  }

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
  .product-link {
    padding-inline: 8px;
  }
}
</style>
