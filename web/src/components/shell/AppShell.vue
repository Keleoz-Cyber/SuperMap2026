<script setup lang="ts">
// v0.9.0：持久应用壳。拥有跳转链接、全局头和主内容区；
// 服务状态只做轻量健康检查，不加载任何页面业务数据。
import { onMounted, ref } from 'vue'
import { fetchHealth } from '../../api/client'
import AppHeader from './AppHeader.vue'

const serviceState = ref<'unknown' | 'online' | 'offline'>('unknown')
const serviceVersion = ref<string | null>(null)

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
  <div class="app-shell">
    <a class="skip-link" href="#main-content">跳转到主内容</a>
    <AppHeader :service-state="serviceState" :service-version="serviceVersion" />
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
</style>
