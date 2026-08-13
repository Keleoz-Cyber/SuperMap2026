<script setup lang="ts">
// v0.9.0：持久应用壳。拥有跳转链接、全局头和主内容区；
// 服务状态只做轻量健康检查，不加载任何页面业务数据。
// 所有路由共用同一个全局头，避免成果页再维护第二套导航。
import { computed, inject, onMounted, provide, ref } from 'vue'
import { routeLocationKey, type RouteLocationNormalizedLoaded } from 'vue-router'
import { fetchHealth } from '../../api/client'
import AppHeader from './AppHeader.vue'
import AIServiceSettingsDialog from '../settings/AIServiceSettingsDialog.vue'
import { openAISettingsKey } from '../settings/aiSettingsContext'

const serviceState = ref<'unknown' | 'online' | 'offline'>('unknown')
const serviceVersion = ref<string | null>(null)
// 生产环境始终由 Router 提供路由；显式后备值让组件级测试和静态预览
// 仍可独立挂载，不会因为缺少注入而在渲染阶段崩溃。
const route = inject(
  routeLocationKey,
  { name: null } as unknown as RouteLocationNormalizedLoaded,
)
const immersive = computed(() => route.name === 'result-workbench')
const commandCenterRoute = computed(() => route.name === 'home')
const aiSettingsOpen = ref(false)

function openAISettings() { aiSettingsOpen.value = true }
provide(openAISettingsKey, openAISettings)

onMounted(async () => {
  try {
    const health = await fetchHealth()
    serviceState.value = health.status === 'ok' ? 'online' : 'offline'
    serviceVersion.value = health.version ?? null
  } catch {
    serviceState.value = 'offline'
  }
})
</script>

<template>
  <div class="app-shell" :class="{ immersive, 'command-center-route': commandCenterRoute }">
    <a class="skip-link" href="#main-content">跳转到主内容</a>
    <AppHeader
      :service-state="serviceState"
      :service-version="serviceVersion"
      data-test="app-global-header"
      @open-ai-settings="openAISettings"
    />
    <AIServiceSettingsDialog v-model="aiSettingsOpen" />
    <main id="main-content" class="app-main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

.app-main {
  flex: 1;
  min-width: 0;
  /* 关键：保持块级布局。列向 flex 会让带 margin:auto 居中的页面按
     min-content 撑宽（stretch 被 auto 边距禁用），造成移动端横向溢出 */
  display: block;
}

/* 首页本身就是一屏指挥舱：桌面与横向笔记本使用确定的视口高度，
   让三维舞台、关键发现与底部证据坞共同参与同一套网格分配。
   各列已有自己的 overflow-y，内容较多时只滚动局部，不再把证据坞
   推到第二屏。平板和手机仍保持自然文档流。 */
@media (min-width: 961px) {
  .app-shell.command-center-route {
    height: 100dvh;
    overflow: hidden;
  }

  .app-shell.command-center-route .app-main {
    min-height: 0;
    overflow: hidden;
  }
}

/* 成果页只有在桌面宽度和可用高度都足够时才锁成一屏工作台。
   1280×720 / 1366×768 虽然属于桌面宽度，但应保留文档流滚动，
   否则顶栏、三维舞台和证据坞会共同挤压可用高度。 */
@media (min-width: 1200px) and (min-height: 820px) {
  .app-shell.immersive {
    height: 100dvh;
    overflow: hidden;
  }

  .app-shell.immersive .app-main {
    min-height: 0;
    overflow: hidden;
  }
}
</style>
