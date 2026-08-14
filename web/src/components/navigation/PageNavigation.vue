<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

const props = defineProps<{
  caseId?: string
  caseName?: string
  datasetId?: string
  experimentId?: string
  resultId?: string
  currentLabel?: string
}>()

const caseLabel = computed(() => props.caseName ?? '案例')
</script>

<template>
  <nav class="page-nav" aria-label="页面导航" data-test="page-navigation">
    <ol class="breadcrumb-list">
      <li class="crumb">
        <RouterLink to="/" data-test="crumb-home">首页</RouterLink>
      </li>
      <li v-if="caseId" class="crumb">
        <RouterLink :to="`/cases/${caseId}`" data-test="crumb-case">{{ caseLabel }}</RouterLink>
      </li>
      <li v-if="datasetId" class="crumb crumb-text" data-test="crumb-dataset">
        <span>数据版本</span>
      </li>
      <li v-if="experimentId" class="crumb">
        <RouterLink :to="`/experiments/${experimentId}`" data-test="crumb-experiment">建模实验</RouterLink>
      </li>
      <li v-if="resultId" class="crumb">
        <RouterLink :to="`/results/${resultId}`" data-test="crumb-result">成果</RouterLink>
      </li>
      <li v-if="currentLabel" class="crumb crumb-current" aria-current="page">
        <span>{{ currentLabel }}</span>
      </li>
    </ol>
  </nav>
</template>

<style scoped>
.page-nav {
  display: flex;
  align-items: center;
}

.breadcrumb-list {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  list-style: none;
  margin: 0;
  padding: 0;
}

.crumb {
  display: flex;
  align-items: center;
  font-size: var(--s1-font-sm);
}

.crumb a {
  color: var(--gmp-text-dim);
  text-decoration: none;
  border-radius: 6px;
  padding: 4px 8px;
  transition: color 0.15s;
}

.crumb a:hover {
  color: var(--gmp-accent);
}

.crumb a:focus-visible {
  outline: 2px solid var(--gmp-accent);
  outline-offset: 2px;
}

.crumb:not(:last-child)::after {
  content: '/';
  margin: 0 4px;
  color: var(--gmp-text-faint);
}

.crumb-text {
  color: var(--gmp-text-dim);
  padding: 4px 0;
}

.crumb-current {
  /* 当前页面包屑只是路径终点，不作为第二个页面标题（避免与下方 h1 重复抢眼） */
  color: var(--gmp-text-dim);
  font-weight: 500;
  padding: 4px 0;
}
</style>
