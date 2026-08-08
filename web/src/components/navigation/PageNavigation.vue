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
  <nav class="page-nav" aria-label="页面导航">
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
        <RouterLink :to="`/experiments/${experimentId}`" data-test="crumb-experiment">实验</RouterLink>
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
  font-size: 13px;
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
  color: var(--gmp-text);
  font-weight: 600;
  padding: 4px 0;
}
</style>
