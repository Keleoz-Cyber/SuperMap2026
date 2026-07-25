<script setup lang="ts">
import { useRouter } from 'vue-router'

// 轻量页面导航：只负责有限的命名路由动作与可访问名称，
// 不是 AppShell，不决定页面布局；绝不使用 history.back()。
const props = defineProps<{
  home?: boolean
  experimentId?: string
  caseId?: string
  newExperiment?: boolean
}>()

const router = useRouter()

function goHome() {
  void router.push({ name: 'home' })
}

function goExperiment() {
  if (!props.experimentId) return
  void router.push({ name: 'experiment-detail', params: { experimentId: props.experimentId } })
}

function goNewExperiment() {
  if (!props.caseId) return
  void router.push({ name: 'experiment-create', params: { caseId: props.caseId } })
}
</script>

<template>
  <nav class="page-nav" aria-label="页面导航">
    <button v-if="experimentId" type="button" class="nav-btn" data-test="nav-experiment" @click="goExperiment">
      返回实验
    </button>
    <button v-if="home" type="button" class="nav-btn" data-test="nav-home" @click="goHome">
      返回首页
    </button>
    <button
      v-if="newExperiment && caseId"
      type="button"
      class="nav-btn accent"
      data-test="nav-new-experiment"
      @click="goNewExperiment"
    >
      新建实验
    </button>
  </nav>
</template>

<style scoped>
.page-nav {
  display: flex;
  align-items: center;
  gap: 10px;
}

.nav-btn {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text);
  border-radius: 8px;
  padding: 6px 14px;
  font-size: 12px;
  cursor: pointer;
}

.nav-btn:hover {
  border-color: var(--gmp-accent);
}

.nav-btn:focus-visible {
  outline: 2px solid var(--gmp-accent);
  outline-offset: 2px;
}

.nav-btn.accent {
  color: var(--gmp-accent);
  border-color: var(--gmp-accent);
}
</style>
