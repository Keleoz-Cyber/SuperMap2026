<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { fetchCaseWorkspace } from '../api/client'
import type { CaseWorkspaceSummary } from '../api/types'

// v0.7.0 Task 5 路由占位：Task 6 在同一文件实现完整能力驱动工作台壳。
const route = useRoute()
const workspace = ref<CaseWorkspaceSummary | null>(null)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    workspace.value = await fetchCaseWorkspace(String(route.params.caseId))
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc)
  }
})
</script>

<template>
  <div class="case-workspace" data-test="case-workspace">
    <p v-if="error" data-test="workspace-error">{{ error }}</p>
    <h2 v-else-if="workspace" data-test="case-workspace-header">{{ workspace.title }}</h2>
    <p v-else>加载中…</p>
  </div>
</template>
